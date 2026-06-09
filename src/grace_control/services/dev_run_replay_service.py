# ############################################################################
# AI_HEADER: dev_run_replay_service
# ROLE: Dev-only service to rerun failed pipeline stages from saved worktrees.
# ############################################################################

# START_MODULE_CONTRACT
# purpose: Enable developers to replay T0/T1/T2/verifier/reviewer stages of
#          an existing PacketRun, saving output to the run's replays/ directory.
# inputs: run_id (str), stage (str) / override params.
# returns: Dict containing status, summary, and path to replay artifacts.
# side_effects: Runs acceptance commands, updates database, writes to run_dir/replays/.
# emitted_logs: None.
# error_behavior: Raises custom exceptions on configuration or missing asset errors.
# END_MODULE_CONTRACT

# START_MODULE_MAP
# mapping:
#   - class: DevReplayException
#   - class: DevRunReplayService
# END_MODULE_MAP

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

from grace_control.config import settings as _settings_mod
from grace_control.core.contracts import (
    AcceptanceReport,
    FinalVerdict,
    StageStatus,
    VerifierReport,
    build_packet_contract,
)
from grace_control.core.evidence_verifier import run_evidence_verifier
from grace_control.core.reviewer_gate import run_reviewer_gate
from grace_control.db import get_db
from grace_control.db.schema import Packet, PacketRun


class DevReplayException(Exception):
    def __init__(self, code: str, message: str, extra: dict | None = None):
        super().__init__(message)
        self.code = code
        self.message = message
        self.extra = extra or {}


class DevRunReplayService:
    def __init__(self) -> None:
        pass

    def _check_enabled(self) -> None:
        if not _settings_mod.settings.dev_tools_enabled:
            raise DevReplayException("DEV_TOOLS_DISABLED", "Dev tools are disabled in settings")

    def _load_run_and_packet(self, run_id: str) -> tuple[PacketRun, Packet]:
        self._check_enabled()
        with get_db() as db:
            run = db.query(PacketRun).filter_by(id=run_id).first()
            if not run:
                raise DevReplayException("RUN_NOT_FOUND", f"Packet run {run_id} not found")
            packet = db.query(Packet).filter_by(id=run.packet_id).first()
            if not packet:
                raise DevReplayException("PACKET_NOT_FOUND", f"Packet {run.packet_id} not found")
            return run, packet

    def _resolve_paths(self, run: PacketRun) -> tuple[Path, Path, dict]:
        res_json = run.result_json or {}
        dev_rep = res_json.get("dev_replay")
        if not dev_rep:
            raise DevReplayException("RUN_NOT_REPLAYABLE", f"Run {run.id} does not contain dev_replay metadata")

        wt_path = Path(dev_rep.get("worktree_path", ""))
        run_dir = Path(dev_rep.get("run_dir", ""))

        if not wt_path or not wt_path.exists():
            patch_file = run_dir / "agent.patch" if run_dir else None
            patch_path_str = str(patch_file) if patch_file and patch_file.exists() else None
            extra = {"patch_path": patch_path_str} if patch_path_str else {}
            raise DevReplayException(
                "WORKTREE_MISSING",
                "Worktree directory was cleaned or does not exist",
                extra=extra
            )

        if not run_dir or not run_dir.exists():
            raise DevReplayException("RUN_DIR_MISSING", "Run directory does not exist")

        return wt_path, run_dir, dev_rep

    def replay_acceptance(self, run_id: str, stage: str, worktree_path_override: str | None = None) -> dict:
        self._check_enabled()
        run, packet = self._load_run_and_packet(run_id)
        wt_path, run_dir, dev_rep = self._resolve_paths(run)

        if worktree_path_override:
            wt_path = Path(worktree_path_override)
            if not wt_path.exists():
                raise DevReplayException("WORKTREE_MISSING", f"Override worktree does not exist: {wt_path}")

        # Rebuild packet contract
        pkt_contract = build_packet_contract(packet.to_dict() if hasattr(packet, "to_dict") else {
            "id": packet.id,
            "title": packet.title,
            "acceptance_profile": packet.acceptance_profile,
            "spec_json": packet.spec_json or {}
        })

        timestamp = datetime.now(UTC).strftime("%Y%m%d%H%M%S")
        replay_dir = run_dir / "replays" / f"{timestamp}-{stage}"
        replay_dir.mkdir(parents=True, exist_ok=True)

        from grace_control.core.acceptance_pipeline import run_acceptance_stage_replay
        base_ref = dev_rep.get("base_ref")
        base_sha = dev_rep.get("base_sha")

        try:
            report = run_acceptance_stage_replay(
                packet=pkt_contract,
                legacy_result=res_json_legacy_result(run),
                project_root=Path(_settings_mod.settings.target_repo_root or "."),
                worktree_path=wt_path,
                branch_name=dev_rep.get("branch_name", ""),
                run_dir=replay_dir,
                stage=stage,
                base_ref=base_ref,
                base_sha=base_sha
            )
        except ValueError as e:
            if "UNSUPPORTED_REPLAY_STAGE" in str(e):
                raise DevReplayException("UNSUPPORTED_REPLAY_STAGE", f"Unsupported stage: {stage}") from e
            raise

        # Determine overall status and summary
        if isinstance(report, AcceptanceReport):
            passed = report.is_accepted
            summary = report.summary
            blocking = report.scope_violations + report.evidence_issues
            stage_results = [s.to_dict() if hasattr(s, "to_dict") else s for s in report.stages]
        else:
            passed = report.status == StageStatus.PASSED
            summary = report.summary
            blocking = report.blocking_issues
            stage_results = [report.to_dict() if hasattr(report, "to_dict") else report]

        replay_entry = {
            "timestamp": datetime.now(UTC).isoformat() + "Z",
            "type": "acceptance",
            "stage": stage,
            "passed": passed,
            "summary": summary,
            "replay_dir": str(replay_dir),
            "stages": stage_results,
        }

        # Persist replay log entry to result_json without changing packet state
        self._append_replay_log(run.id, replay_entry)

        # Write acceptance report to replay dir
        if isinstance(report, AcceptanceReport):
            report_path = replay_dir / "acceptance_report.json"
            report_path.write_text(json.dumps(report.to_dict(), indent=2, default=str))

        return {
            "run_id": run.id,
            "packet_id": packet.id,
            "stage": stage,
            "status": "passed" if passed else "failed",
            "summary": summary,
            "blocking_issues": blocking,
            "replay_dir": str(replay_dir),
            "stages": stage_results,
        }

    async def rerun_verifier(self, run_id: str, worktree_path_override: str | None = None) -> dict:
        self._check_enabled()
        run, packet = self._load_run_and_packet(run_id)
        wt_path, run_dir, dev_rep = self._resolve_paths(run)

        if worktree_path_override:
            wt_path = Path(worktree_path_override)
            if not wt_path.exists():
                raise DevReplayException("WORKTREE_MISSING", f"Override worktree does not exist: {wt_path}")

        # Try loading acceptance report
        res_json = run.result_json or {}
        accept_dict = res_json.get("acceptance_report")
        if not accept_dict or "error" in accept_dict:
            raise DevReplayException("ACCEPTANCE_REPORT_MISSING", "Original run did not produce a valid acceptance report")

        # Reconstitute AcceptanceReport object
        from grace_control.core.acceptance_pipeline import AcceptanceReport as AR
        from grace_control.core.acceptance_pipeline import CommandResult as CR
        from grace_control.core.acceptance_pipeline import StageName as SN
        from grace_control.core.acceptance_pipeline import StageResult as SR
        from grace_control.core.acceptance_pipeline import StageStatus as SS
        stages = []
        for s in accept_dict.get("stages", []):
            cmds = [CR(command=c.get("command",""), cwd=c.get("cwd",""), exit_code=c.get("exit_code",0),
                       stdout=c.get("stdout",""), stderr=c.get("stderr",""), timed_out=c.get("timed_out",False))
                    for c in s.get("commands", [])]
            stages.append(SR(
                name=SN(s.get("name")),
                status=SS(s.get("status")),
                summary=s.get("summary", ""),
                commands=cmds,
                blocking_issues=s.get("blocking_issues", []),
                warnings=s.get("warnings", []),
                skipped_reason=s.get("skipped_reason"),
            ))

        accept_report = AR(
            packet_id=accept_dict.get("packet_id", packet.id),
            final_verdict=FinalVerdict(accept_dict.get("final_verdict", "rework_required")),
            profile=packet.acceptance_profile,
            stages=stages,
            scope_violations=accept_dict.get("scope_violations", []),
            evidence_issues=accept_dict.get("evidence_issues", []),
            summary=accept_dict.get("summary", ""),
        )

        # Build packet contract
        pkt_contract = build_packet_contract(packet.to_dict() if hasattr(packet, "to_dict") else {
            "id": packet.id,
            "title": packet.title,
            "acceptance_profile": packet.acceptance_profile,
            "spec_json": packet.spec_json or {}
        })

        timestamp = datetime.now(UTC).strftime("%Y%m%d%H%M%S")
        replay_dir = run_dir / "replays" / f"{timestamp}-verifier"
        replay_dir.mkdir(parents=True, exist_ok=True)

        changed_files = dev_rep.get("changed_files", [])
        art = [str(p.relative_to(run_dir)) for p in run_dir.rglob("*") if p.is_file()] if run_dir.exists() else []

        evr = await run_evidence_verifier(
            packet=pkt_contract,
            acceptance_report=accept_report,
            worktree_path=wt_path,
            run_dir=run_dir,
            changed_files=changed_files,
            artifacts=art
        )

        replay_entry = {
            "timestamp": datetime.now(UTC).isoformat() + "Z",
            "type": "verifier",
            "passed": evr.verdict.value not in ("rework_required", "escalate_to_architect"),
            "verdict": evr.verdict.value,
            "summary": evr.summary,
            "replay_dir": str(replay_dir),
            "report": evr.model_dump() if hasattr(evr, "model_dump") else evr
        }

        self._append_replay_log(run.id, replay_entry)

        # Write verifier report to replay dir
        report_path = replay_dir / "verifier_report.json"
        report_path.write_text(json.dumps(evr.model_dump() if hasattr(evr, "model_dump") else evr, indent=2, default=str))

        return {
            "run_id": run.id,
            "packet_id": packet.id,
            "verdict": evr.verdict.value,
            "summary": evr.summary,
            "blocking_issues": evr.blocking_issues,
            "replay_dir": str(replay_dir),
        }

    async def rerun_reviewer(self, run_id: str, worktree_path_override: str | None = None, force_rerun_verifier: bool = False) -> dict:
        self._check_enabled()
        run, packet = self._load_run_and_packet(run_id)
        wt_path, run_dir, dev_rep = self._resolve_paths(run)

        if worktree_path_override:
            wt_path = Path(worktree_path_override)
            if not wt_path.exists():
                raise DevReplayException("WORKTREE_MISSING", f"Override worktree does not exist: {wt_path}")

        res_json = run.result_json or {}
        accept_dict = res_json.get("acceptance_report")
        if not accept_dict or "error" in accept_dict:
            raise DevReplayException("ACCEPTANCE_REPORT_MISSING", "Original run did not produce a valid acceptance report")

        # Load or Rerun verifier report
        verifier_report_dict = res_json.get("evidence_verifier_report")
        if not verifier_report_dict or force_rerun_verifier:
            # Rerun verifier automatically to get report
            await self.rerun_verifier(run_id, worktree_path_override=worktree_path_override)
            with get_db() as db:
                run = db.query(PacketRun).filter_by(id=run_id).first()
                res_json = run.result_json or {}
                verifier_report_dict = res_json.get("evidence_verifier_report")

        if not verifier_report_dict:
            raise DevReplayException("VERIFIER_REPORT_MISSING", "Verifier report is missing")

        # Reconstitute AcceptanceReport
        from grace_control.core.acceptance_pipeline import AcceptanceReport as AR
        from grace_control.core.acceptance_pipeline import CommandResult as CR
        from grace_control.core.acceptance_pipeline import StageName as SN
        from grace_control.core.acceptance_pipeline import StageResult as SR
        from grace_control.core.acceptance_pipeline import StageStatus as SS
        stages = []
        for s in accept_dict.get("stages", []):
            cmds = [CR(command=c.get("command",""), cwd=c.get("cwd",""), exit_code=c.get("exit_code",0),
                       stdout=c.get("stdout",""), stderr=c.get("stderr",""), timed_out=c.get("timed_out",False))
                    for c in s.get("commands", [])]
            stages.append(SR(
                name=SN(s.get("name")),
                status=SS(s.get("status")),
                summary=s.get("summary", ""),
                commands=cmds,
                blocking_issues=s.get("blocking_issues", []),
                warnings=s.get("warnings", []),
                skipped_reason=s.get("skipped_reason"),
            ))

        accept_report = AR(
            packet_id=accept_dict.get("packet_id", packet.id),
            final_verdict=FinalVerdict(accept_dict.get("final_verdict", "rework_required")),
            profile=packet.acceptance_profile,
            stages=stages,
            scope_violations=accept_dict.get("scope_violations", []),
            evidence_issues=accept_dict.get("evidence_issues", []),
            summary=accept_dict.get("summary", ""),
        )

        # Reconstitute VerifierReport
        evr = VerifierReport(
            packet_id=verifier_report_dict.get("packet_id", packet.id),
            verdict=pkt_verdict_helper(verifier_report_dict.get("verdict", "rework_required")),
            requirement_results=verifier_report_dict.get("requirement_results", []),
            test_verdict=verifier_report_dict.get("test_verdict", "not_run"),
            commands_run=verifier_report_dict.get("commands_run", []),
            evidence_paths=verifier_report_dict.get("evidence_paths", []),
            blocking_issues=verifier_report_dict.get("blocking_issues", []),
        )

        # Build packet contract
        pkt_contract = build_packet_contract(packet.to_dict() if hasattr(packet, "to_dict") else {
            "id": packet.id,
            "title": packet.title,
            "acceptance_profile": packet.acceptance_profile,
            "spec_json": packet.spec_json or {}
        })

        timestamp = datetime.now(UTC).strftime("%Y%m%d%H%M%S")
        replay_dir = run_dir / "replays" / f"{timestamp}-reviewer"
        replay_dir.mkdir(parents=True, exist_ok=True)

        changed_files = dev_rep.get("changed_files", [])
        art = [str(p.relative_to(run_dir)) for p in run_dir.rglob("*") if p.is_file()] if run_dir.exists() else []

        rvr = await run_reviewer_gate(
            packet=pkt_contract,
            acceptance_report=accept_report,
            evidence_verifier_report=evr,
            worktree_path=wt_path,
            run_dir=run_dir,
            changed_files=changed_files,
            artifacts=art
        )

        replay_entry = {
            "timestamp": datetime.now(UTC).isoformat() + "Z",
            "type": "reviewer",
            "passed": rvr.verdict.value not in ("rework_required", "escalate_to_architect"),
            "verdict": rvr.verdict.value,
            "summary": rvr.reasons[0] if rvr.reasons else "Reviewer complete",
            "replay_dir": str(replay_dir),
            "report": rvr.model_dump() if hasattr(rvr, "model_dump") else rvr
        }

        self._append_replay_log(run.id, replay_entry)

        # Write reviewer report to replay dir
        report_path = replay_dir / "reviewer_report.json"
        report_path.write_text(json.dumps(rvr.model_dump() if hasattr(rvr, "model_dump") else rvr, indent=2, default=str))

        return {
            "run_id": run.id,
            "packet_id": packet.id,
            "verdict": rvr.verdict.value,
            "summary": rvr.reasons[0] if rvr.reasons else "Reviewer complete",
            "blocking_issues": rvr.reasons,
            "replay_dir": str(replay_dir),
        }

    def _append_replay_log(self, run_id: str, entry: dict) -> None:
        with get_db() as db:
            run = db.query(PacketRun).filter_by(id=run_id).first()
            if run:
                res_json = dict(run.result_json) if run.result_json else {}
                replays = list(res_json.get("dev_replays", []))
                replays.append(entry)
                res_json["dev_replays"] = replays
                run.result_json = res_json
                db.commit()


def res_json_legacy_result(run: PacketRun) -> dict:
    res_json = run.result_json or {}
    return res_json.get("legacy_result", {})


def pkt_verdict_helper(val: str):
    from grace_control.core.contracts import PacketVerdict
    try:
        return PacketVerdict(val)
    except ValueError:
        return PacketVerdict.REWORK_REQUIRED
