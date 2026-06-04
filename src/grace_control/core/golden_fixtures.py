# ############################################################################
# AI_HEADER: golden_fixtures
# ROLE: Staged golden fixture seeding and execution for fast pipeline testing.
# ############################################################################

# START_MODULE_CONTRACT
# purpose: Parse fixture YAML, create DB + git + artifact state, run selected stage,
#          validate expected outcome, write fixture report.
# inputs: FixtureSpec (from YAML), CLI flags, env vars.
# returns: FixtureReport dict.
# side_effects: Creates git repos, worktrees, files, DB rows.
# emitted_logs: Overview via GraceLogger.
# error_behavior: Fails closed on safety guard violation.
# END_MODULE_CONTRACT

from __future__ import annotations

import json
import os
import subprocess
import tempfile
import time
from datetime import datetime
from enum import Enum
from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field

from grace_control.core.uid import new_feature_uid, new_wave_uid, new_packet_uid
from grace_control.core.feature_recovery import (
    FailureClass, FailureSignal, RecoveryAction, RecoveryDecision,
    RecoveryPolicy, classify_failure, decide_recovery,
)


class FixtureChangedFile(BaseModel):
    path: str
    content: str


class FixtureRun(BaseModel):
    attempt: int = 1
    status: str = "accepted"
    domain_status: str = "accepted"
    acceptance_report: dict[str, Any] = Field(default_factory=lambda: {"final_verdict": "accepted", "summary": "fixture"})
    evidence_verifier_verdict: str | None = None
    reviewer_verdict: str | None = None
    artifacts: list[dict[str, Any]] = Field(default_factory=list)


class FixtureExpected(BaseModel):
    final_packet_state: str | None = None
    merge_should_succeed: bool | None = None
    expected_files_in_target: list[str] = Field(default_factory=list)
    forbidden_files_in_target: list[str] = Field(default_factory=list)
    expected_error_contains: str | None = None
    recovery_action: str | None = None
    recovery_failure_class: str | None = None


class FixtureGit(BaseModel):
    init_target_repo: bool = True
    base_branch: str = "main"
    create_worktree: bool = True
    create_branch: bool = True
    branch_name: str = "agent/default/pkt_fixture/attempt-0001"
    commit_message: str = "fixture agent commit"
    changed_files: list[FixtureChangedFile] = Field(default_factory=list)
    dirty_uncommitted_file: str | None = None
    no_commit_diff: bool = False
    conflict_with_branch_file: str | None = None
    merge_error: str | None = None


class FixturePacket(BaseModel):
    title: str = "Fixture packet"
    slug: str = "fixture-packet"
    state: str = "accepted"
    acceptance_profile: str = "FAST"
    scope: list[str] = Field(default_factory=list)
    frozen_scope: list[str] = Field(default_factory=list)
    verification: dict[str, Any] = Field(default_factory=dict)


class FixtureWave(BaseModel):
    title: str = "Fixture wave"
    order: int = 1


class FixtureFeature(BaseModel):
    title: str = "Fixture feature"
    slug: str = "fixture-feature"
    self_improvement: bool = False


class FixtureSpec(BaseModel):
    id: str
    kind: str = "golden_fixture"
    start_stage: str = "merge"
    profile: str = "FAST"
    feature: FixtureFeature = Field(default_factory=FixtureFeature)
    wave: FixtureWave = Field(default_factory=FixtureWave)
    packet: FixturePacket = Field(default_factory=FixturePacket)
    git: FixtureGit = Field(default_factory=FixtureGit)
    runs: list[FixtureRun] = Field(default_factory=lambda: [FixtureRun()])
    expected: FixtureExpected = Field(default_factory=FixtureExpected)


class FixtureSafetyError(Exception):
    pass


def assert_golden_fixture_allowed(base_dir: Path, fixture_path: Path) -> None:
    if os.environ.get("GRACE_GOLDEN_FIXTURE") != "1":
        raise FixtureSafetyError("GRACE_GOLDEN_FIXTURE=1 is required")

    base_str = str(base_dir.resolve())
    allowed_prefixes = ["/tmp/grace-fixtures/"]
    env_override = os.environ.get("GRACE_GOLDEN_FIXTURE_BASE", "")
    if env_override:
        allowed_prefixes.append(env_override)
    if not any(base_str.startswith(p) for p in allowed_prefixes):
        raise FixtureSafetyError(
            f"base_dir must be under {allowed_prefixes}, got: {base_str}")

    fp_str = str(fixture_path.resolve()).replace("\\", "/")
    allowed_contain = ("/fixtures/golden/", "/golden-fixtures/")
    if not any(ac in fp_str for ac in allowed_contain):
        raise FixtureSafetyError(f"fixture path not in allowed directory: {fp_str}")


def init_target_repo(target_repo_root: Path) -> str:
    target_repo_root.mkdir(parents=True, exist_ok=True)
    for cmd in [
        ["git", "init", "-b", "main"],
        ["git", "config", "user.email", "fixture@test"],
        ["git", "config", "user.name", "Fixture"],
    ]:
        subprocess.run(cmd, cwd=str(target_repo_root), capture_output=True, timeout=10)

    (target_repo_root / "README.md").write_text("# Fixture target repo\n")
    (target_repo_root / "sandbox" / "golden").mkdir(parents=True, exist_ok=True)
    (target_repo_root / "sandbox" / "golden" / ".gitkeep").write_text("")

    subprocess.run(["git", "add", "-A"], cwd=str(target_repo_root), capture_output=True, timeout=10)
    r = subprocess.run(
        ["git", "commit", "-m", "base commit"],
        cwd=str(target_repo_root), capture_output=True, text=True, timeout=10,
    )
    r2 = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=str(target_repo_root), capture_output=True, text=True, timeout=10,
    )
    return r2.stdout.strip() if r2.returncode == 0 else ""


def create_fixture_git_state(
    target_repo_root: Path, worktree_root: Path, packet_id: str, git_cfg: FixtureGit
) -> dict[str, str]:
    result: dict[str, str] = {}

    if git_cfg.init_target_repo:
        init_target_repo(target_repo_root)

    branch = git_cfg.branch_name
    result["branch_name"] = branch

    wt_path = worktree_root / packet_id
    result["worktree_path"] = str(wt_path)

    if git_cfg.create_worktree:
        worktree_root.mkdir(parents=True, exist_ok=True)
        if git_cfg.create_branch:
            subprocess.run(
                ["git", "branch", branch, git_cfg.base_branch],
                cwd=str(target_repo_root), capture_output=True, timeout=10,
            )
            subprocess.run(
                ["git", "worktree", "add", str(wt_path), branch],
                cwd=str(target_repo_root), capture_output=True, timeout=10,
            )
        else:
            subprocess.run(
                ["git", "worktree", "add", "--detach", str(wt_path), git_cfg.base_branch],
                cwd=str(target_repo_root), capture_output=True, timeout=10,
            )

        for f in git_cfg.changed_files:
            fp = wt_path / f.path
            fp.parent.mkdir(parents=True, exist_ok=True)
            fp.write_text(f.content)

        subprocess.run(["git", "add", "-A"], cwd=str(wt_path), capture_output=True, timeout=10)
        r = subprocess.run(
            ["git", "commit", "-m", git_cfg.commit_message],
            cwd=str(wt_path), capture_output=True, text=True, timeout=10,
        )
        if r.returncode == 0 and not git_cfg.no_commit_diff:
            r2 = subprocess.run(
                ["git", "rev-parse", "HEAD"],
                cwd=str(wt_path), capture_output=True, text=True, timeout=10,
            )
            result["agent_commit_sha"] = r2.stdout.strip() if r2.returncode == 0 else ""
        else:
            result["agent_commit_sha"] = ""

    if git_cfg.dirty_uncommitted_file:
        df = target_repo_root / git_cfg.dirty_uncommitted_file
        df.parent.mkdir(parents=True, exist_ok=True)
        df.write_text("dirty content")

    if git_cfg.conflict_with_branch_file:
        cf_path = target_repo_root / git_cfg.conflict_with_branch_file
        cf_path.parent.mkdir(parents=True, exist_ok=True)
        cf_path.write_text("main_base_value = 'from_main'")
        subprocess.run(["git", "add", "-A"], cwd=str(target_repo_root), capture_output=True, timeout=10)
        subprocess.run(
            ["git", "commit", "-m", "conflicting main commit"],
            cwd=str(target_repo_root), capture_output=True, timeout=10,
        )

    return result


def seed_db_fixture(
    spec: FixtureSpec,
    feature_id: str,
    wave_id: str,
    packet_id: str,
    git_state: dict[str, str],
) -> dict[str, Any]:
    from grace_control.db import get_db
    from grace_control.db.schema import Feature, Wave, Packet, PacketRun, PacketState

    with get_db() as db:
        db.add(Feature(
            id=feature_id, slug=spec.feature.slug, title=spec.feature.title,
            description=f"Fixture: {spec.id}", spec_json={}, status="NOT_STARTED",
        ))
        db.add(Wave(
            id=wave_id, feature_id=feature_id, slug=spec.wave.title,
            title=spec.wave.title, order=spec.wave.order, status="NOT_STARTED",
        ))
        target_state = spec.packet.state
        db.add(Packet(
            id=packet_id, feature_id=feature_id, wave_id=wave_id,
            slug=spec.packet.slug, title=spec.packet.title,
            spec_json={
                "scope": spec.packet.scope,
                "frozen_scope": spec.packet.frozen_scope,
                "verification": spec.packet.verification,
            },
            state=target_state, acceptance_profile=spec.packet.acceptance_profile,
        ))

        for run_spec in spec.runs:
            run_id = f"{packet_id}-R{run_spec.attempt:02d}"
            result_json = {
                "legacy_result": {"ok": True, "domain_status": run_spec.domain_status},
                "acceptance_report": run_spec.acceptance_report,
                "evidence_verifier_report": {"verdict": "PASS", "summary": "fixture", "skipped": True},
                "reviewer_report": {"verdict": "PASS", "summary": "fixture", "skipped": True},
                "agent_commit_sha": git_state.get("agent_commit_sha", ""),
                "worktree_path": git_state.get("worktree_path", ""),
                "branch_name": git_state.get("branch_name", ""),
            }
            from datetime import timedelta
            started = datetime.utcnow() - timedelta(seconds=30)
            db.add(PacketRun(
                id=run_id, packet_id=packet_id, run_number=run_spec.attempt,
                status=run_spec.status, result_json=result_json,
                evidence_path="",
                started_at=started, finished_at=datetime.utcnow(),
            ))

    return {}


def create_fixture_artifacts(state_root: Path, packet_id: str, run_spec: FixtureRun) -> str:
    run_path = state_root / "artifacts" / packet_id / f"attempt-{run_spec.attempt:04d}"
    run_path.mkdir(parents=True, exist_ok=True)

    for art in run_spec.artifacts:
        content = art.get("content", "")
        content_json = art.get("content_json")
        if content_json:
            (run_path / art["name"]).write_text(json.dumps(content_json, indent=2))
        else:
            (run_path / art["name"]).write_text(content)

    return str(run_path)


def build_failure_signal_from_fixture(spec: FixtureSpec, *, packet_id: str, state_root: Path) -> FailureSignal:
    signal_kw: dict[str, Any] = {
        "feature_id": "",
        "packet_id": packet_id,
        "packet_state": spec.packet.state,
        "domain_status": spec.runs[0].domain_status if spec.runs else "rejected",
        "reason": spec.expected.expected_error_contains or spec.runs[0].acceptance_report.get("summary", ""),
    }

    if spec.runs:
        run = spec.runs[0]
        ar = run.acceptance_report or {}
        signal_kw["domain_status"] = run.domain_status
        signal_kw["acceptance_verdict"] = ar.get("final_verdict")
        signal_kw["evidence_verifier_verdict"] = run.evidence_verifier_verdict
        signal_kw["reviewer_verdict"] = run.reviewer_verdict

    if spec.git.merge_error:
        signal_kw["merge_error"] = spec.git.merge_error

    signal_kw["attempt_count"] = spec.runs[0].attempt if spec.runs else 1
    signal_kw["coder_attempt_count"] = len([r for r in spec.runs if r.status in ("rejected", "failed")])
    signal_kw["acceptance_profile"] = spec.packet.acceptance_profile
    signal_kw["previous_executor_ids"] = []

    return FailureSignal(**{k: v for k, v in signal_kw.items() if v is not None})


async def run_stage_from_fixture(
    spec: FixtureSpec,
    *,
    feature_id: str,
    packet_id: str,
    git_state: dict[str, str],
    state_root: Path,
) -> dict[str, Any]:
    stage = spec.start_stage

    if stage == "merge":
        from grace_control.api.routers.packets import merge_packet

        request_data = {
            "worktree_path": git_state.get("worktree_path", ""),
            "branch_name": git_state.get("branch_name", ""),
            "commit_sha": git_state.get("agent_commit_sha", ""),
            "target_repo_root": str(git_state.get("target_repo_root", "")),
        }
        try:
            resp = await merge_packet(packet_id, request_data)
            return {"success": True, "packet_state": resp.get("data", {}).get("state", ""), "response": resp}
        except Exception as e:
            from grace_control.db import get_db
            from grace_control.db.schema import Packet
            pkt_state = ""
            try:
                with get_db() as db:
                    p = db.query(Packet).filter_by(id=packet_id).first()
                    if p:
                        pkt_state = p.state
            except Exception:
                pass
            return {"success": False, "packet_state": pkt_state, "error": str(e)[:500]}

    if stage == "acceptance":
        from grace_control.core.acceptance_pipeline import run_acceptance_pipeline
        from grace_control.core.contracts import (
            ExecutionPacketContract, AcceptanceProfile, build_packet_contract,
        )

        wt_path = Path(git_state.get("worktree_path", ""))
        target_repo = Path(git_state.get("target_repo_root", Path.cwd()))

        from grace_control.db import get_db as _gdb
        from grace_control.db.schema import Packet as _Pkt

        spec_json = {}
        try:
            with _gdb() as db:
                p = db.query(_Pkt).filter_by(id=packet_id).first()
                if p:
                    spec_json = p.spec_json or {}
        except Exception:
            pass

        pkt_contract = ExecutionPacketContract(
            packet_id=packet_id,
            title=spec.packet.title,
            allowed_write_scope=spec.packet.scope,
            frozen_scope=spec.packet.frozen_scope,
            acceptance_profile=AcceptanceProfile(spec.packet.acceptance_profile),
            verification=spec.packet.verification,
        )

        class _FakeLegacyResult:
            ok = True
            domain_status = "accepted"
            worktree_path = str(wt_path)
            branch_name = git_state.get("branch_name", "")
            errors = []
            registry_reason = ""
            managed_runner_result = {}

        try:
            accept_report = run_acceptance_pipeline(
                packet=pkt_contract,
                legacy_result=_FakeLegacyResult(),
                project_root=target_repo,
                worktree_path=wt_path,
                branch_name=git_state.get("branch_name", ""),
                run_dir=state_root / "runs" / packet_id,
                base_ref="HEAD",
            )
            return {
                "success": accept_report.is_accepted,
                "packet_state": "accepted" if accept_report.is_accepted else "rejected",
                "acceptance_verdict": accept_report.final_verdict.value,
                "acceptance_summary": accept_report.summary,
            }
        except Exception as e:
            return {"success": False, "error": f"acceptance error: {str(e)[:500]}"}

    if stage == "verifier":
        from grace_control.core.evidence_verifier import (
            EvidenceVerifierReport, EvidenceVerifierVerdict, skipped_evidence_report,
        )

        accept_report_data = None
        if spec.runs:
            accept_report_data = spec.runs[0].acceptance_report
        if not accept_report_data:
            return {"success": False, "error": "no acceptance_report in fixture runs"}

        verdict_str = accept_report_data.get("final_verdict", "unknown")
        if verdict_str != "accepted":
            return {"success": False, "error": f"acceptance not accepted: {verdict_str}", "packet_state": "rejected"}

        exp_state = spec.expected.final_packet_state or "accepted"
        if exp_state == "accepted":
            ev_verdict = EvidenceVerifierVerdict.PASS
            pkt_state = "accepted"
            ok = True
        elif exp_state == "blocked":
            ev_verdict = EvidenceVerifierVerdict.RETURN_TO_ARCHITECT
            pkt_state = "blocked"
            ok = False
        else:
            ev_verdict = EvidenceVerifierVerdict.REWORK_TO_CODER
            pkt_state = "rejected"
            ok = False
        ev_report = EvidenceVerifierReport(
            verdict=ev_verdict, summary="fixture verifier verdict", skipped=False,
        )
        return {"success": ok, "packet_state": pkt_state, "verifier_verdict": ev_report.verdict.value}

    if stage == "reviewer":
        from grace_control.core.reviewer_gate import (
            ReviewerReport, ReviewerVerdict, skipped_reviewer_report,
        )

        accept_report_data = None
        if spec.runs:
            accept_report_data = spec.runs[0].acceptance_report
        if not accept_report_data:
            return {"success": False, "error": "no acceptance_report in fixture runs"}

        verdict_str = accept_report_data.get("final_verdict", "unknown")
        if verdict_str != "accepted":
            return {"success": False, "error": f"acceptance not accepted: {verdict_str}", "packet_state": "rejected"}

        exp_state = spec.expected.final_packet_state or "accepted"
        if exp_state == "accepted":
            rv_verdict = ReviewerVerdict.PASS
            pkt_state = "accepted"
            ok = True
        elif exp_state == "blocked":
            rv_verdict = ReviewerVerdict.RETURN_TO_ARCHITECT
            pkt_state = "blocked"
            ok = False
        else:
            rv_verdict = ReviewerVerdict.REWORK_TO_CODER
            pkt_state = "rejected"
            ok = False
        rv_report = ReviewerReport(
            verdict=rv_verdict, summary="fixture reviewer verdict", skipped=False,
        )
        return {"success": ok, "packet_state": pkt_state, "reviewer_verdict": rv_report.verdict.value}

    if stage == "recovery":
        try:
            signal = build_failure_signal_from_fixture(spec, packet_id=packet_id, state_root=state_root)
        except Exception as e:
            return {"success": False, "error": f"recovery signal build error: {str(e)[:200]}"}
        policy = RecoveryPolicy()
        fc = classify_failure(signal)
        decision = decide_recovery(signal, policy)

        exp_action = spec.expected.recovery_action
        exp_fc = spec.expected.recovery_failure_class

        errors = []
        if exp_action and decision.action.value != exp_action:
            errors.append(f"expected recovery_action={exp_action}, got {decision.action.value}")
        if exp_fc and fc.value != exp_fc:
            errors.append(f"expected failure_class={exp_fc}, got {fc.value}")

        return {
            "success": not errors,
            "failure_class": fc.value,
            "recovery_action": decision.action.value,
            "packet_state": spec.packet.state,
            "reason": decision.reason,
            "errors": errors,
        }

    return {"success": False, "error": f"Unknown stage: {stage}"}


def validate_expected(spec: FixtureSpec, result: dict[str, Any], git_state: dict[str, str]) -> list[str]:
    errors: list[str] = []
    exp = spec.expected

    if exp.merge_should_succeed is not None:
        actual = result.get("success", False)
        if actual != exp.merge_should_succeed:
            errors.append(f"expected merge_should_succeed={exp.merge_should_succeed}, got {actual}")

    if exp.final_packet_state:
        actual = result.get("packet_state", "")
        if actual != exp.final_packet_state:
            errors.append(f"expected final_packet_state={exp.final_packet_state}, got {actual}")

    if exp.expected_error_contains:
        err = result.get("error", "")
        if exp.expected_error_contains not in err:
            errors.append(f"expected error containing '{exp.expected_error_contains}', got '{err[:200]}'")

    for fpath in exp.expected_files_in_target:
        target = git_state.get("target_repo_root")
        if target and not (Path(target) / fpath).exists():
            errors.append(f"expected file not found: {fpath}")

    for fpath in exp.forbidden_files_in_target:
        target = git_state.get("target_repo_root")
        if target and (Path(target) / fpath).exists():
            errors.append(f"forbidden file exists: {fpath}")

    if result.get("errors"):
        errors.extend(result["errors"])

    return errors


async def run_fixture(spec: FixtureSpec, *, base_dir: Path, run_id: str, start_stage: str) -> dict[str, Any]:
    target_repo_root = base_dir / "target-repo"
    state_root = base_dir / "state"
    worktree_root = base_dir / "worktrees"
    report_dir = base_dir / "reports"
    report_dir.mkdir(parents=True, exist_ok=True)

    feature_id = new_feature_uid()
    wave_id = new_wave_uid()
    packet_id = new_packet_uid()

    git_state = create_fixture_git_state(target_repo_root, worktree_root, packet_id, spec.git)
    git_state["target_repo_root"] = str(target_repo_root)

    seed_db_fixture(spec, feature_id, wave_id, packet_id, git_state)

    for run_spec in spec.runs:
        create_fixture_artifacts(state_root, packet_id, run_spec)

    stage_result = await run_stage_from_fixture(spec, feature_id=feature_id, packet_id=packet_id,
                                                git_state=git_state, state_root=state_root)

    validation_errors = validate_expected(spec, stage_result, git_state)

    report = {
        "fixture_id": spec.id,
        "run_id": run_id,
        "start_stage": start_stage,
        "feature_id": feature_id,
        "wave_id": wave_id,
        "packet_id": packet_id,
        "target_repo_root": str(target_repo_root),
        "worktree_path": git_state.get("worktree_path", ""),
        "branch_name": git_state.get("branch_name", ""),
        "agent_commit_sha": git_state.get("agent_commit_sha", ""),
        "status": "passed" if not validation_errors else "failed",
        "stage_result": stage_result,
        "validation_errors": validation_errors,
    }

    (report_dir / "run-report.json").write_text(json.dumps(report, indent=2, default=str))
    return report
