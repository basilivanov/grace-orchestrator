# ############################################################################
# AI_HEADER: packet_executor
# ROLE: Bridge between DB packets and legacy run_e2e_packet. STATELESS.
#       W6 of source/codex/tz-api-first-cleanup-waves-w0-w11.md: git
#       subprocess calls extracted into WorktreeInspector and
#       AgentCommitService — the executor orchestrates only.
# ############################################################################

# START_MODULE_CONTRACT
# purpose: Materialize DB packet → markdown → call legacy runner → return structured result.
# inputs: packet_id, worker_id, project_root, state_root, worktree_root.
# returns: ExecutionResult (accepted, reason, evidence_path, duration_ms, domain_status).
# side_effects: Creates PacketRun record. Does NOT change packet state.
# emitted_logs: log_event for execution lifecycle.
# error_behavior: Raises on DB/runtime failures. Does not mask exceptions.
# END_MODULE_CONTRACT

# START_MODULE_MAP
# mapping:
#   - class: ExecutionResult
#   - class: PacketExecutionAdapter
# END_MODULE_MAP

from __future__ import annotations

import os
import time
from datetime import datetime, timezone
from pathlib import Path

import yaml
from pydantic import BaseModel

from grace_control.core.structured_logger import GraceLogger
from grace_control.agent.backend import ExecutionBackend
from grace_control.core.evidence_verifier import (
    EvidenceVerifierVerdict,
    run_evidence_verifier,
    skipped_evidence_report,
)
from grace_control.core.reviewer_gate import (
    ReviewerVerdict,
    run_reviewer_gate,
    skipped_reviewer_report,
)
from grace_control.db import get_db
from grace_control.db.schema import Packet, PacketRun
from grace_control.services.agent_commit_service import AgentCommitService
from grace_control.services.worktree_inspector import WorktreeInspector

_log = GraceLogger("adapter")

# Legacy helpers — were in grace_control.agent.legacy_backend before W8.
# Inlined here because they're trivial and only packet_executor uses them.
_LEGACY_BRANCH_FORMAT = "agent/default/{packet_id}/{attempt_slug}"


def _legacy_branch_name(packet_id: str, attempt_slug: str) -> str:
    return _LEGACY_BRANCH_FORMAT.format(packet_id=packet_id, attempt_slug=attempt_slug)


def _legacy_prepare_worktree(project_root: Path, packet_id: str, attempt_slug: str) -> tuple[Path, str]:
    import shutil
    import subprocess
    wt_path = Path(project_root) / f"{packet_id}-{attempt_slug}"
    branch = _legacy_branch_name(packet_id, attempt_slug)
    try:
        subprocess.run(
            ["git", "-C", str(project_root), "worktree", "prune"],
            capture_output=True, timeout=10,
        )
        if wt_path.exists():
            subprocess.run(
                ["git", "-C", str(project_root), "worktree", "remove", str(wt_path), "--force"],
                capture_output=True, timeout=10,
            )
            shutil.rmtree(wt_path, ignore_errors=True)
        subprocess.run(
            ["git", "-C", str(project_root), "branch", "-D", branch],
            capture_output=True, timeout=10,
        )
    except Exception as e:
        _log.warn("legacy_prepare_worktree_failed", packet_id=packet_id, error=str(e)[:200])
    return wt_path, branch


# START_BLOCK_MODELS
class ExecutionResult(BaseModel):
    """Structured result returned by adapter. Worker uses this for release."""
    accepted: bool
    reason: str | None = None
    evidence_path: str = ""
    duration_ms: int = 0
    domain_status: str = ""
    worktree_path: str = ""
    branch_name: str = ""
    acceptance_report_path: str = ""
    acceptance_verdict: str = ""
    acceptance_summary: str = ""
    commit_sha: str = ""
# END_BLOCK_MODELS


#START_BLOCK_ADAPTER
class PacketExecutionAdapter:
    """
    Bridge between DB packets and legacy run_e2e_packet.

    STATELESS: does NOT call mark_running, mark_accepted, mark_rejected, mark_failed.
    State ownership belongs to API endpoints (claim/release).
    """

    # START_FUNCTION_CONTRACT
    # name: __init__
    # purpose: Initialize adapter with filesystem paths + git-helper services.
    # inputs: project_root, state_root, worktree_root, backend (optional).
    # returns: None.
    # side_effects: None.
    # emitted_logs: None.
    # error_behavior: None.
    # END_FUNCTION_CONTRACT
    def __init__(self, project_root: Path, state_root: Path, worktree_root: Path,
                 backend: "ExecutionBackend | None" = None):
        self.project_root = Path(project_root)
        self.state_root = Path(state_root)
        self.worktree_root = Path(worktree_root)
        if backend is None:
            from grace_control.agent import select_backend
            self._backend: ExecutionBackend = select_backend()
        else:
            self._backend = backend
        from grace_control.services.packet_materializer import PacketMaterializer
        from grace_control.services.evidence_service import EvidenceService
        self._materializer = PacketMaterializer()
        self._evidence = EvidenceService(db_factory=get_db)
        self._inspector = WorktreeInspector()
        self._committer = AgentCommitService()

    # START_FUNCTION_CONTRACT
    # name: execute
    # purpose: Execute a packet: load DB → materialize → call legacy runner →
    #          inspect worktree → save evidence → return result.
    # inputs: packet_id (str), worker_id (str).
    # returns: ExecutionResult.
    # side_effects: Creates PacketRun, writes evidence, may create git commit.
    # emitted_logs: adapter_execute_start, adapter_execute_done, adapter_execute_failed.
    # error_behavior: Raises on packet not found / runtime failure.
    # END_FUNCTION_CONTRACT
    async def execute(self, packet_id: str, worker_id: str) -> ExecutionResult:
        start_time = time.time()
        _log.info("adapter_execute_start", packet_id=packet_id, worker_id=worker_id)

        state_root = self.state_root
        state_root.mkdir(parents=True, exist_ok=True)
        from grace_control.db import init_db as _init_db
        _init_db()
        worktree_root = self.worktree_root
        worktree_root.mkdir(parents=True, exist_ok=True)

        with get_db() as db:
            packet = db.query(Packet).filter_by(id=packet_id).first()
            if not packet:
                raise ValueError(f"Packet {packet_id} not found")

            run_number = packet.attempt_count
            run_id = f"{packet_id}-R{run_number:02d}"

            attempt_slug = f"attempt-{run_number:04d}"
            _legacy_prepare_worktree(self.project_root, packet_id, attempt_slug)

            existing_run = db.query(PacketRun).filter_by(id=run_id).first()
            if existing_run:
                _log.debug("run_already_exists", packet_id=packet_id, run_id=run_id)
                existing_run.status = "running"
                existing_run.started_at = datetime.now(timezone.utc)
            else:
                db.add(PacketRun(
                    id=run_id, packet_id=packet_id, run_number=run_number,
                    worker_id=worker_id, status="running",
                    started_at=datetime.now(timezone.utc),
                ))

            packet_data = {
                "id": packet.id, "feature_id": packet.feature_id,
                "wave_id": packet.wave_id, "slug": packet.slug,
                "title": packet.title, "description": packet.description,
                "spec_json": packet.spec_json, "state": packet.state,
                "acceptance_profile": packet.acceptance_profile,
                "attempt_count": packet.attempt_count,
                "max_attempts": packet.max_attempts,
            }

        agent_commit_sha = ""

        from grace_control.core.complexity_router import route_packet
        from grace_control.core.executor_selector import select_executor
        tier = route_packet(packet_data.get("acceptance_profile", "NORMAL"), packet_data.get("spec_json"))
        spec_json = packet_data.get("spec_json") or {}
        recovery = spec_json.get("recovery", {}) if isinstance(spec_json, dict) else {}
        requested_executor_id = recovery.get("requested_executor_id")
        if isinstance(spec_json, dict) and requested_executor_id:
            from grace_control.core.executor_selector import load_profiles
            profiles = load_profiles()
            executors = profiles.get("codex", {}).get("executors", [])
            matching = [e for e in executors if e.get("executor_id") == requested_executor_id]
            executor = matching[0] if matching else select_executor("coder", attempt=packet_data.get("attempt_count", 1) + 1)
        else:
            executor = select_executor("coder", attempt=packet_data.get("attempt_count", 1) + 1)
        packet_data["_executor"] = executor
        packet_data["_tier"] = tier.value

        try:
            packet_path = self._materializer.materialize(packet_data, state_root)
            _log.debug("packet_materialized", packet_id=packet_id, path=str(packet_path))

            from grace_control.core.contracts import build_packet_contract
            pkt_contract = build_packet_contract(packet_data)

            from grace_control.config.settings import settings
            base_ref = os.environ.get("GRACE_BASE_REF", settings.base_branch)
            base_sha = self._inspector.base_sha(self.project_root, base_ref)

            result = await self._call_legacy_runner(
                packet_path, state_root, worktree_root,
                allowed_scope=pkt_contract.allowed_write_scope,
                frozen_scope=pkt_contract.frozen_scope,
                packet_contract=pkt_contract,
                attempt=run_number,
                base_ref=base_ref)
            _log.debug("legacy_runner_completed", packet_id=packet_id,
                ok=result.ok, domain=result.domain_status,
                errors=result.errors[:3], blocker=getattr(result, 'registry_reason', '')[:200])

            if result.ok and not result.worktree_path:
                _log.warn("worktree_missing_after_run", packet_id=packet_id)
                return self._finish_early_rejected_run(
                    run_id=run_id, reason="Worktree was cleaned before acceptance could verify",
                    duration_ms=int((time.time() - start_time) * 1000),
                    executor_id=executor.get("executor_id", ""))

            agent_commit_sha = ""
            if result.worktree_path:
                wt = Path(result.worktree_path)
                if not wt.exists():
                    _log.warn("worktree_cleaned_before_accept", packet_id=packet_id)
                    return self._finish_early_rejected_run(
                        run_id=run_id,
                        reason=f"Worktree cleaned before acceptance: {result.worktree_path}",
                        duration_ms=int((time.time() - start_time) * 1000),
                        executor_id=executor.get("executor_id", ""))

                if not self._inspector.is_git_worktree(wt):
                    _log.debug("worktree_not_git_wt_skipping_commit_verification", packet_id=packet_id, worktree=str(wt))
                else:
                    try:
                        if not self._inspector.has_changes(wt, pkt_contract.allowed_write_scope):
                            _log.warn("no_changes_produced", packet_id=packet_id)
                            return self._finish_early_rejected_run(
                                run_id=run_id, reason="Agent produced no changes",
                                duration_ms=int((time.time() - start_time) * 1000),
                                executor_id=executor.get("executor_id", ""))
                        agent_commit_sha = self._committer.commit(
                            wt, packet_id, packet_data['attempt_count'])
                        if not agent_commit_sha:
                            return self._finish_early_rejected_run(
                                run_id=run_id, reason="Agent commit returned no SHA",
                                duration_ms=int((time.time() - start_time) * 1000),
                                executor_id=executor.get("executor_id", ""))
                    except Exception as e:
                        _log.warn("agent_commit_failed", packet_id=packet_id, error=str(e)[:200])
                        return self._finish_early_rejected_run(
                            run_id=run_id, reason=f"Agent commit exception: {str(e)[:200]}",
                            duration_ms=int((time.time() - start_time) * 1000),
                            executor_id=executor.get("executor_id", ""))

            try:
                from grace_control.core.acceptance_pipeline import run_acceptance_pipeline
                wt_path = Path(result.worktree_path) if result.worktree_path else self.project_root
                run_dir = state_root / "packets" / packet_id / "runs" / f"R{run_number:02d}"

                from grace_control.core.scope_guard import get_changed_files as _get_changed_files
                changed_files: list[str] = []
                try:
                    changed_files = _get_changed_files(wt_path, base_ref=base_sha or base_ref)
                except Exception:
                    changed_files = []

                accept_report = run_acceptance_pipeline(
                    packet=pkt_contract, legacy_result=result,
                    project_root=self.project_root, worktree_path=wt_path,
                    branch_name=result.branch_name or "", run_dir=run_dir,
                    base_ref=base_ref, base_sha=base_sha)
                _log.info("acceptance_completed", packet_id=packet_id,
                    verdict=accept_report.final_verdict.value,
                    is_accepted=accept_report.is_accepted)

                ev_dir = run_dir
                accept_report_path = self._evidence.save_acceptance_report(packet_id, run_number, accept_report, state_root)

                try:
                    safe_legacy_dict = result.to_dict()
                except Exception:
                    safe_legacy_dict = {"ok": result.ok, "domain_status": result.domain_status}

                if not accept_report.is_accepted:
                    from grace_control.core.recovery_rules import evaluate_ladder
                    route = evaluate_ladder(packet_data.get("attempt_count", 1))
                    if route.skip_verifier:
                        ev_report = skipped_evidence_report("odd attempt skips verifier per ladder")
                        rv_report = skipped_reviewer_report("deterministic acceptance failed")
                    else:
                        ev_report = await run_evidence_verifier(
                            packet=pkt_contract, acceptance_report=accept_report,
                            worktree_path=wt_path, run_dir=run_dir,
                            changed_files=changed_files, artifacts=artifacts)
                        rv_report = skipped_reviewer_report("deterministic acceptance failed")

                    execution_result = self._build_execution_result_from_acceptance(
                        legacy_execution_result=None, acceptance_report=accept_report,
                        acceptance_report_path=accept_report_path,
                        worktree_path=result.worktree_path or "",
                        branch_name=result.branch_name or "",
                        duration_ms=int((time.time() - start_time) * 1000))
                    self._evidence.update_run_result(
                        run_id=run_id, status="rejected",
                        legacy_result=safe_legacy_dict,
                        acceptance_report=accept_report,
                        evidence_verifier_report=ev_report,
                        reviewer_report=rv_report,
                        evidence_path=execution_result.evidence_path,
                        duration_ms=execution_result.duration_ms,
                        executor_id=executor.get("executor_id", ""))
                    _log.info("adapter_execute_done", packet_id=packet_id,
                        accepted=False, duration_ms=execution_result.duration_ms)
                    return execution_result
            except Exception as e:
                _log.error("acceptance_pipeline_error", packet_id=packet_id, error=str(e)[:200])
                return self._build_blocked_result(run_id, executor, start_time, e)

            # ── Self-evolution guard ──
            spec_json = packet_data.get("spec_json") or {}
            if isinstance(spec_json, dict) and spec_json.get("origin") == "self_evolution":
                _log.info("self_evolution_guard_check", packet_id=packet_id)
                from grace_control.core.self_evolution_guard import SelfEvolutionGuard
                guard = SelfEvolutionGuard()
                changed = self._inspector.collect_changed_files(wt_path)
                guard_result = guard.check(changed, session_id=spec_json.get("session_id", ""))
                if not guard_result.passed:
                    _log.warn("self_evolution_guard_blocked", packet_id=packet_id, errors=guard_result.errors)
                    ev_report = skipped_evidence_report("self-evolution guard blocked")
                    rv_report = skipped_reviewer_report("self-evolution guard blocked")
                    execution_result = ExecutionResult(
                        accepted=False, domain_status="rejected",
                        reason="; ".join(guard_result.errors),
                        evidence_path="",
                        duration_ms=int((time.time() - start_time) * 1000))
                    self._evidence.update_run_result(
                        run_id=run_id, status="rejected",
                        legacy_result=safe_legacy_dict,
                        acceptance_report=accept_report,
                        evidence_verifier_report=ev_report,
                        reviewer_report=rv_report,
                        evidence_path=execution_result.evidence_path,
                        duration_ms=execution_result.duration_ms,
                        executor_id=executor.get("executor_id", ""))
                    return execution_result
                _log.info("self_evolution_guard_passed", packet_id=packet_id)

            artifacts: list[str] = []
            if run_dir.exists():
                try:
                    artifacts = [str(p.relative_to(run_dir)) for p in run_dir.rglob("*") if p.is_file()]
                except Exception:
                    artifacts = []

            return await self._route_after_acceptance(
                start_time=start_time, run_id=run_id, packet_id=packet_id,
                executor=executor, packet_data=packet_data, result=result,
                pkt_contract=pkt_contract, accept_report=accept_report,
                accept_report_path=accept_report_path, safe_legacy_dict=safe_legacy_dict,
                wt_path=wt_path, run_dir=run_dir, changed_files=changed_files,
                artifacts=artifacts, agent_commit_sha=agent_commit_sha,
                state_root=state_root, run_number=run_number)

        except Exception:
            _log.error("adapter_execute_failed", packet_id=packet_id)
            with get_db() as db:
                existing = db.query(PacketRun).filter_by(id=run_id).first()
                if existing:
                    existing.status = "failed"
                    existing.finished_at = datetime.now(timezone.utc)
                    existing.duration_ms = int((time.time() - start_time) * 1000)
            raise

    # START_FUNCTION_CONTRACT
    # name: _route_after_acceptance
    # purpose: After acceptance, route through FAST/NORMAL/STRICT profiles and
    #          finalize the run. Pulled out of execute() to keep it under 300
    #          lines.
    # inputs: start_time, run_id, packet_id, executor, packet_data, result,
    #         pkt_contract, accept_report, accept_report_path, safe_legacy_dict,
    #         wt_path, run_dir, changed_files, artifacts, agent_commit_sha,
    #         state_root, run_number.
    # returns: ExecutionResult.
    # side_effects: Writes PacketRun rows.
    # emitted_logs: adapter_execute_done, unexpected_reviewer_verdict.
    # error_behavior: Re-raises unexpected reviewer verdicts.
    # END_FUNCTION_CONTRACT
    async def _route_after_acceptance(
        self, *, start_time, run_id, packet_id, executor, packet_data, result,
        pkt_contract, accept_report, accept_report_path, safe_legacy_dict,
        wt_path, run_dir, changed_files, artifacts, agent_commit_sha,
        state_root, run_number,
    ) -> ExecutionResult:
        from grace_control.core.contracts import AcceptanceProfile
        profile = pkt_contract.acceptance_profile
        executor_id = executor.get("executor_id", "")
        evidence_path = self._evidence.evidence_path(packet_id, run_number, state_root)

        def _make_result(*, accepted, domain_status, reason=None, commit=agent_commit_sha, ep=""):
            return ExecutionResult(
                accepted=accepted, reason=reason, domain_status=domain_status,
                worktree_path=result.worktree_path or "",
                branch_name=result.branch_name or "",
                acceptance_report_path=accept_report_path,
                acceptance_verdict=accept_report.final_verdict.value,
                acceptance_summary=accept_report.summary,
                duration_ms=int((time.time() - start_time) * 1000),
                commit_sha=commit, evidence_path=ep,
            )

        if profile == AcceptanceProfile.FAST:
            er = _make_result(accepted=True, domain_status=accept_report.final_verdict.value, ep=evidence_path)
            self._evidence.save_agent_log(packet_id, run_number, result, state_root)
            self._persist(run_id, "accepted", safe_legacy_dict, accept_report,
                skipped_evidence_report("FAST profile skips evidence verifier"),
                skipped_reviewer_report("FAST profile skips reviewer"),
                er, executor_id, evidence_path, commit_sha=agent_commit_sha)
            _log.info("adapter_execute_done", packet_id=packet_id, accepted=True, duration_ms=er.duration_ms)
            return er

        ev_report = await run_evidence_verifier(
            packet=pkt_contract, acceptance_report=accept_report,
            worktree_path=wt_path, run_dir=run_dir,
            changed_files=changed_files, artifacts=artifacts)
        _log.info("evidence_verifier_completed", packet_id=packet_id,
            verdict=ev_report.verdict.value, skipped=ev_report.skipped)

        if ev_report.verdict == EvidenceVerifierVerdict.REWORK_TO_CODER:
            return self._reject_with_reviewer("rejected", ev_report.summary, run_id, executor_id,
                safe_legacy_dict, accept_report, ev_report,
                skipped_reviewer_report("evidence verifier did not pass"),
                start_time, packet_id, accept_report_path, result)
        if ev_report.verdict == EvidenceVerifierVerdict.RETURN_TO_ARCHITECT:
            return self._reject_with_reviewer("blocked", ev_report.summary, run_id, executor_id,
                safe_legacy_dict, accept_report, ev_report,
                skipped_reviewer_report("evidence verifier returned to architect"),
                start_time, packet_id, accept_report_path, result)

        if profile == AcceptanceProfile.NORMAL:
            er = _make_result(accepted=True, domain_status=accept_report.final_verdict.value, ep=evidence_path)
            self._evidence.save_agent_log(packet_id, run_number, result, state_root)
            self._persist(run_id, "accepted", safe_legacy_dict, accept_report, ev_report,
                skipped_reviewer_report("NORMAL profile skips reviewer by default"),
                er, executor_id, evidence_path, commit_sha=agent_commit_sha)
            _log.info("adapter_execute_done", packet_id=packet_id, accepted=True, duration_ms=er.duration_ms)
            return er

        reviewer_report = await run_reviewer_gate(
            packet=pkt_contract, acceptance_report=accept_report,
            evidence_verifier_report=ev_report, worktree_path=wt_path,
            run_dir=run_dir, changed_files=changed_files, artifacts=artifacts)
        _log.info("reviewer_gate_completed", packet_id=packet_id,
            verdict=reviewer_report.verdict.value, skipped=reviewer_report.skipped)

        if reviewer_report.verdict == ReviewerVerdict.PASS:
            er = _make_result(accepted=True, domain_status=accept_report.final_verdict.value, ep=evidence_path)
            self._evidence.save_agent_log(packet_id, run_number, result, state_root)
            self._persist(run_id, "accepted", safe_legacy_dict, accept_report, ev_report,
                reviewer_report, er, executor_id, evidence_path, commit_sha=agent_commit_sha)
            _log.info("adapter_execute_done", packet_id=packet_id, accepted=True, duration_ms=er.duration_ms)
            return er
        if reviewer_report.verdict == ReviewerVerdict.REWORK_TO_CODER:
            return self._reject_with_reviewer("rejected", reviewer_report.summary, run_id, executor_id,
                safe_legacy_dict, accept_report, ev_report, reviewer_report,
                start_time, packet_id, accept_report_path, result)
        if reviewer_report.verdict == ReviewerVerdict.RETURN_TO_ARCHITECT:
            return self._reject_with_reviewer("blocked", reviewer_report.summary, run_id, executor_id,
                safe_legacy_dict, accept_report, ev_report, reviewer_report,
                start_time, packet_id, accept_report_path, result)

        _log.error("unexpected_reviewer_verdict", packet_id=packet_id, verdict=reviewer_report.verdict.value)
        raise RuntimeError(f"Unexpected reviewer verdict: {reviewer_report.verdict.value}")

    # START_FUNCTION_CONTRACT
    # name: _reject_with_reviewer
    # purpose: Build a rejected/blocked ExecutionResult, persist it, and log done.
    # inputs: status ("rejected" | "blocked"), summary, run_id, executor_id,
    #         safe_legacy_dict, accept_report, ev_report, rv_report, start_time,
    #         packet_id, accept_report_path, result.
    # returns: ExecutionResult.
    # side_effects: Writes PacketRun row.
    # emitted_logs: adapter_execute_done.
    # error_behavior: Never raises.
    # END_FUNCTION_CONTRACT
    def _reject_with_reviewer(
        self, status, summary, run_id, executor_id,
        safe_legacy_dict, accept_report, ev_report, rv_report,
        start_time, packet_id, accept_report_path, result,
    ) -> ExecutionResult:
        domain = "rejected" if status == "rejected" else "blocked"
        er = ExecutionResult(
            accepted=False, reason=summary, domain_status=domain,
            worktree_path=result.worktree_path or "",
            branch_name=result.branch_name or "",
            acceptance_report_path=accept_report_path,
            acceptance_verdict=accept_report.final_verdict.value,
            acceptance_summary=accept_report.summary,
            duration_ms=int((time.time() - start_time) * 1000),
        )
        self._evidence.update_run_result(
            run_id=run_id, status=status,
            legacy_result=safe_legacy_dict, acceptance_report=accept_report,
            evidence_verifier_report=ev_report, reviewer_report=rv_report,
            evidence_path=er.evidence_path, duration_ms=er.duration_ms,
            executor_id=executor_id)
        _log.info("adapter_execute_done", packet_id=packet_id,
            accepted=False, duration_ms=er.duration_ms)
        return er

    # START_FUNCTION_CONTRACT
    # name: _persist
    # purpose: Persist an accepted ExecutionResult to PacketRun. Thin wrapper
    #          around update_run_result for the happy path.
    # inputs: run_id, status, safe_legacy_dict, accept_report, ev_report,
    #         rv_report, er (ExecutionResult), executor_id, evidence_path,
    #         commit_sha.
    # returns: None.
    # side_effects: Writes PacketRun row.
    # emitted_logs: None.
    # error_behavior: Never raises (caller decides).
    # END_FUNCTION_CONTRACT
    def _persist(
        self, run_id, status, safe_legacy_dict, accept_report, ev_report,
        rv_report, er, executor_id, evidence_path, commit_sha,
    ) -> None:
        self._evidence.update_run_result(
            run_id=run_id, status=status,
            legacy_result=safe_legacy_dict, acceptance_report=accept_report,
            evidence_verifier_report=ev_report, reviewer_report=rv_report,
            evidence_path=evidence_path, duration_ms=er.duration_ms,
            executor_id=executor_id, commit_sha=commit_sha)

    # START_FUNCTION_CONTRACT
    # name: _build_blocked_result
    # purpose: Build + persist a blocked ExecutionResult on acceptance-pipeline error.
    # inputs: run_id, executor, start_time, error.
    # returns: ExecutionResult(accepted=False, domain_status="blocked", ...).
    # side_effects: Writes PacketRun row.
    # emitted_logs: None (caller logs acceptance_pipeline_error).
    # error_behavior: Never raises; persistence failure is silently ignored.
    # END_FUNCTION_CONTRACT
    def _build_blocked_result(self, run_id, executor, start_time, error) -> ExecutionResult:
        reason = f"Acceptance pipeline error: {str(error)[:200]}"
        ev_report = skipped_evidence_report("deterministic acceptance failed")
        rv_report = skipped_reviewer_report("deterministic acceptance failed")
        er = ExecutionResult(
            accepted=False, domain_status="blocked", reason=reason,
            evidence_path="", duration_ms=int((time.time() - start_time) * 1000),
            acceptance_verdict="blocked", acceptance_summary=str(error)[:200])
        try:
            self._evidence.update_run_result(
                run_id=run_id, status="blocked",
                legacy_result={"error": reason},
                acceptance_report=None,
                evidence_verifier_report=ev_report, reviewer_report=rv_report,
                evidence_path="", duration_ms=er.duration_ms,
                executor_id=executor.get("executor_id", ""))
        except Exception:
            pass
        return er

    # START_FUNCTION_CONTRACT
    # name: _call_legacy_runner
    # purpose: Prepare packet registry + worktree, then delegate execution to
    #          the injected ExecutionBackend. Adapter no longer imports
    #          prefect_grace directly.
    # inputs: packet_path, state_root, worktree_root, allowed_scope,
    #         frozen_scope, packet_contract, attempt, base_ref.
    # returns: ExecutionResult.
    # side_effects: Writes packet_registry.yaml, prunes stale worktrees.
    # emitted_logs: legacy_runner_done (via backend).
    # error_behavior: Never raises; failures encoded in ExecutionResult.accepted=False.
    # END_FUNCTION_CONTRACT
    async def _call_legacy_runner(self, packet_path: Path, state_root: Path, worktree_root: Path,
                                   allowed_scope: list[str] | None = None,
                                   frozen_scope: list[str] | None = None,
                                   packet_contract=None,
                                   attempt: int = 1,
                                   base_ref: str = "HEAD") -> "ExecutionResult":
        from grace_control.agent.backend import ExecutionRequest
        packet_id = packet_path.parent.name
        os.environ.setdefault("GRACE_ALLOW_SANDBOX_BYPASS", "true")

        effective_allowed = packet_contract.allowed_write_scope if packet_contract else allowed_scope
        effective_frozen = packet_contract.frozen_scope if packet_contract else frozen_scope

        reg_dir = state_root / "state"
        reg_dir.mkdir(parents=True, exist_ok=True)
        reg_file = reg_dir / "packet_registry.yaml"
        try:
            existing = {}
            if reg_file.exists():
                existing = yaml.safe_load(reg_file.read_text()) or {}
            existing[packet_id] = {
                "packet_id": packet_id, "feature_id": packet_id[:15],
                "wave_id": "W01", "status": "ready", "phase": "PHASE-TEST",
                "packet_path": str(packet_path),
                "allowed_write_scope": effective_allowed or [],
                "frozen_scope": effective_frozen or [], "depends_on": [],
            }
            reg_file.write_text(yaml.dump(existing, default_flow_style=False))
        except Exception:
            pass

        attempt_slug = f"attempt-{attempt:04d}"
        _legacy_prepare_worktree(self.project_root, packet_id, attempt_slug)

        from grace_control.config.settings import settings
        timeout = int(os.environ.get("GRACE_AGENT_TIMEOUT", str(settings.agent_timeout_seconds)))
        request = ExecutionRequest(
            packet_id=packet_id,
            spec={"attempt_count": attempt, "base_ref": base_ref,
                  "allowed_write_scope": effective_allowed or [],
                  "frozen_scope": effective_frozen or []},
            worktree_path=worktree_root / f"{packet_id}-{attempt_slug}",
            branch_name=_legacy_branch_name(packet_id, attempt_slug),
            scope_paths=list(effective_allowed or []),
            executor={"executor_id": "legacy", "model": "prefect"},
            timeout_s=timeout, session_dir=state_root,
        )
        return await self._backend.run(request)

    # START_FUNCTION_CONTRACT
    # name: _build_execution_result_from_acceptance
    # purpose: Build ExecutionResult from acceptance report + legacy result.
    # inputs: legacy_execution_result, acceptance_report, acceptance_report_path,
    #         worktree_path, branch_name, duration_ms.
    # returns: ExecutionResult.
    # side_effects: None.
    # emitted_logs: None.
    # error_behavior: Never raises.
    # END_FUNCTION_CONTRACT
    def _build_execution_result_from_acceptance(
        self, legacy_execution_result=None, acceptance_report=None,
        acceptance_report_path: str = "", worktree_path: str = "",
        branch_name: str = "", duration_ms: int = 0,
    ) -> ExecutionResult:
        accepted = acceptance_report.is_accepted
        return ExecutionResult(
            accepted=accepted, reason=None if accepted else acceptance_report.summary,
            domain_status=acceptance_report.final_verdict.value,
            worktree_path=worktree_path, branch_name=branch_name,
            evidence_path=acceptance_report_path if not accepted else "",
            acceptance_report_path=acceptance_report_path,
            acceptance_verdict=acceptance_report.final_verdict.value,
            acceptance_summary=acceptance_report.summary, duration_ms=duration_ms,
        )

    # START_FUNCTION_CONTRACT
    # name: _finish_early_rejected_run
    # purpose: Update PacketRun on early git/worktree failures before acceptance.
    # inputs: run_id, reason, duration_ms, executor_id, legacy_result.
    # returns: ExecutionResult with accepted=False.
    # side_effects: Writes PacketRun.status=rejected with result_json.
    # emitted_logs: None.
    # error_behavior: Never raises.
    # END_FUNCTION_CONTRACT
    def _finish_early_rejected_run(
        self, *, run_id: str, reason: str, duration_ms: int,
        executor_id: str = "", legacy_result: dict | None = None,
    ) -> ExecutionResult:
        result = ExecutionResult(
            accepted=False, domain_status="rejected", reason=reason,
            evidence_path="", duration_ms=duration_ms, commit_sha="")
        lr = legacy_result or {"error": "pre-acceptance failure", "reason": reason}
        try:
            self._evidence.update_run_result(
                run_id=run_id, status="rejected", legacy_result=lr,
                acceptance_report=None,
                evidence_verifier_report=skipped_evidence_report(reason),
                reviewer_report=skipped_reviewer_report(reason),
                evidence_path="", duration_ms=duration_ms,
                executor_id=executor_id)
        except Exception:
            pass
        return result
#END_BLOCK_ADAPTER
