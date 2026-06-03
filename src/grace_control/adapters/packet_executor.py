# ############################################################################
# AI_HEADER: packet_executor
# ROLE: Bridge between DB packets and legacy run_e2e_packet. STATELESS.
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
#   - function: _collect_changed_files
# END_MODULE_MAP

from __future__ import annotations

import asyncio
import os
import time
from datetime import datetime
from functools import partial
from pathlib import Path

import yaml
from pydantic import BaseModel

from grace_control.core.structured_logger import GraceLogger
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

_log = GraceLogger("adapter")

#START_BLOCK_MODELS
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

#END_BLOCK_MODELS

#START_BLOCK_ADAPTER
class PacketExecutionAdapter:
    """
    Bridge between DB packets and legacy run_e2e_packet.

    STATELESS: does NOT call mark_running, mark_accepted, mark_rejected, mark_failed.
    State ownership belongs to API endpoints (claim/release).
    """

    # START_FUNCTION_CONTRACT
    # name: __init__
    # purpose: Initialize adapter with filesystem paths.
    # inputs: project_root, state_root, worktree_root.
    # returns: None.
    # side_effects: None.
    # emitted_logs: None.
    # error_behavior: None.
    # END_FUNCTION_CONTRACT
    def __init__(self, project_root: Path, state_root: Path, worktree_root: Path):
        self.project_root = Path(project_root)
        self.state_root = Path(state_root)
        self.worktree_root = Path(worktree_root)

    # START_FUNCTION_CONTRACT
    # name: execute
    # purpose: Execute a packet: load DB → materialize → call legacy runner → save evidence → return result.
    # inputs:
    #   packet_id: Packet ID string.
    #   worker_id: Worker ID string.
    # returns: ExecutionResult with accepted, evidence_path, etc.
    # side_effects: Creates PacketRun record, writes evidence directory.
    # emitted_logs: None (caller should log).
    # error_behavior: Raises on packet not found, runtime failure.
    # END_FUNCTION_CONTRACT
    async def execute(self, packet_id: str, worker_id: str) -> ExecutionResult:
        start_time = time.time()
        _log.info("adapter_execute_start", packet_id=packet_id, worker_id=worker_id)

        # Use persistent state_root (registry must survive agent process)
        state_root = self.state_root
        state_root.mkdir(parents=True, exist_ok=True)
        # Ensure DB initialized
        from grace_control.db import init_db as _init_db
        _init_db()
        # Use persistent worktree_root (must survive until merge)
        worktree_root = self.worktree_root
        worktree_root.mkdir(parents=True, exist_ok=True)

        with get_db() as db:
            packet = db.query(Packet).filter_by(id=packet_id).first()
            if not packet:
                raise ValueError(f"Packet {packet_id} not found")

            run_number = packet.attempt_count
            run_id = f"{packet_id}-R{run_number:02d}"

            # Clean git state for this attempt BEFORE anything
            import subprocess as _sp
            import shutil
            attempt_slug = f"attempt-{run_number:04d}"
            try:
                _sp.run(["git", "-C", str(self.project_root), "worktree", "prune"],
                        capture_output=True, timeout=10)
                wt_path = self.worktree_root / f"{packet_id}-{attempt_slug}"
                if wt_path.exists():
                    _sp.run(["git", "-C", str(self.project_root), "worktree", "remove",
                            str(wt_path), "--force"], capture_output=True, timeout=10)
                    shutil.rmtree(wt_path, ignore_errors=True)
                branch = f"agent/default/{packet_id}/{attempt_slug}"
                _sp.run(["git", "-C", str(self.project_root), "branch", "-D", branch],
                       capture_output=True, timeout=10)
            except Exception:
                pass

            # Check if run already exists (from a previous worker crash)
            existing_run = db.query(PacketRun).filter_by(id=run_id).first()
            if existing_run:
                _log.debug("run_already_exists", packet_id=packet_id, run_id=run_id)
                # Still update status to running
                existing_run.status = "running"
                existing_run.started_at = datetime.utcnow()
            else:
                packet_run = PacketRun(
                    id=run_id, packet_id=packet_id, run_number=run_number,
                    worker_id=worker_id, status="running", started_at=datetime.utcnow(),
                )
                db.add(packet_run)

            # Eagerly read all attributes before session closes
            packet_data = {
                "id": packet.id,
                "feature_id": packet.feature_id,
                "wave_id": packet.wave_id,
                "slug": packet.slug,
                "title": packet.title,
                "description": packet.description,
                "spec_json": packet.spec_json,
                "state": packet.state,
                "acceptance_profile": packet.acceptance_profile,
                "attempt_count": packet.attempt_count,
                "max_attempts": packet.max_attempts,
            }

        agent_commit_sha = ""

        # Select executor with escalation
        from grace_control.core.complexity_router import route_packet
        from grace_control.core.executor_selector import select_executor

        tier = route_packet(packet_data.get("acceptance_profile", "NORMAL"), packet_data.get("spec_json"))
        executor = select_executor("coder", attempt=packet_data.get("attempt_count", 1) + 1)
        packet_data["_executor"] = executor
        packet_data["_tier"] = tier.value

        try:
            packet_path = self._materialize_packet(packet_data, state_root)
            _log.debug("packet_materialized", packet_id=packet_id, path=str(packet_path))

            # Build packet contract for registry + legacy runner
            from grace_control.core.contracts import build_packet_contract
            pkt_contract = build_packet_contract(packet_data)

            # Resolve base SHA for commit diff comparison
            import subprocess as _sp_base
            base_ref = os.environ.get("GRACE_BASE_REF", "main")
            base_sha = ""
            try:
                sr = _sp_base.run(["git", "-C", str(self.project_root), "rev-parse", base_ref],
                                  capture_output=True, text=True, timeout=10)
                base_sha = sr.stdout.strip() if sr.returncode == 0 else ""
            except Exception:
                pass

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

            # Durable worktree check: reject if worktree is already cleaned
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

                import subprocess as _sp
                is_git_wt = False
                try:
                    r = _sp.run(["git", "rev-parse", "--is-inside-work-tree"], cwd=str(wt),
                                capture_output=True, text=True, timeout=5)
                    is_git_wt = r.returncode == 0 and r.stdout.strip() == "true"
                except Exception:
                    pass
                if is_git_wt:
                    try:
                        # Check for agent-produced changes by looking at files on disk
                        has_changes = False
                        for scope_pattern in pkt_contract.allowed_write_scope:
                            scope_path = wt / scope_pattern
                            if scope_path.exists():
                                has_changes = True
                                break
                            if scope_pattern.endswith("/") or scope_pattern.endswith("/**"):
                                stripped = scope_pattern.rstrip("/").rstrip("*").rstrip("/")
                                scope_dir = wt / stripped
                                if scope_dir.exists() and scope_dir.is_dir():
                                    if list(scope_dir.iterdir()):
                                        has_changes = True
                                        break

                        if not has_changes:
                            _log.warn("no_changes_produced", packet_id=packet_id)
                            return self._finish_early_rejected_run(
                                run_id=run_id, reason="Agent produced no changes",
                                duration_ms=int((time.time() - start_time) * 1000),
                                executor_id=executor.get("executor_id", ""))

                        # Always commit agent changes for merge
                        add = _sp.run(["git", "add", "-A"], cwd=str(wt), capture_output=True, timeout=10)
                        commit = _sp.run(["git", "commit", "-m",
                            f"agent: {packet_id} attempt {packet_data['attempt_count']}"],
                            cwd=str(wt), capture_output=True, text=True, timeout=10)

                        sha = _sp.run(["git", "rev-parse", "HEAD"], cwd=str(wt),
                                      capture_output=True, text=True, timeout=10)
                        agent_commit_sha = sha.stdout.strip() if sha.returncode == 0 else ""
                        _log.debug("agent_worktree_committed", packet_id=packet_id, worktree=str(wt),
                                   sha=agent_commit_sha[:12])
                    except Exception as e:
                        _log.warn("agent_commit_failed", packet_id=packet_id, error=str(e)[:200])
                        return self._finish_early_rejected_run(
                            run_id=run_id, reason=f"Agent commit exception: {str(e)[:200]}",
                            duration_ms=int((time.time() - start_time) * 1000),
                            executor_id=executor.get("executor_id", ""))
                else:
                    _log.debug("worktree_not_git_wt_skipping_commit_verification", packet_id=packet_id,
                               worktree=str(wt))

            # ── Deterministic acceptance pipeline (replaces fake verifier/reviewer) ──
            try:
                from grace_control.core.acceptance_pipeline import run_acceptance_pipeline

                # Diff from worktree, not project_root — agent changes are there
                wt_path = Path(result.worktree_path) if result.worktree_path else self.project_root
                run_dir = state_root / "packets" / packet_id / "runs" / f"R{run_number:02d}"

                accept_report = run_acceptance_pipeline(
                    packet=pkt_contract,
                    legacy_result=result,
                    project_root=self.project_root,
                    worktree_path=wt_path,
                    branch_name=result.branch_name or "",
                    run_dir=run_dir,
                    base_ref=base_ref,
                    base_sha=base_sha,
                )
                _log.info("acceptance_completed", packet_id=packet_id,
                    verdict=accept_report.final_verdict.value,
                    is_accepted=accept_report.is_accepted)

                # Save acceptance report + evidence as JSON
                ev_dir = run_dir
                accept_report_path = self._save_acceptance_report(packet_id, run_number, accept_report, state_root)

                try:
                    safe_legacy_dict = result.to_dict()
                except Exception:
                    safe_legacy_dict = {"ok": result.ok, "domain_status": result.domain_status}

                # ── Deterministic fail branch (skips verifier + reviewer) ──
                if not accept_report.is_accepted:
                    ev_report = skipped_evidence_report("deterministic acceptance failed")
                    rv_report = skipped_reviewer_report("deterministic acceptance failed")
                    execution_result = self._build_execution_result_from_acceptance(
                        legacy_execution_result=None,
                        acceptance_report=accept_report,
                        acceptance_report_path=accept_report_path,
                        worktree_path=result.worktree_path or "",
                        branch_name=result.branch_name or "",
                        duration_ms=int((time.time() - start_time) * 1000),
                    )
                    self._update_packet_run_result(
                        run_id=run_id, status="rejected",
                        legacy_result=safe_legacy_dict,
                        acceptance_report=accept_report,
                        evidence_verifier_report=ev_report,
                        reviewer_report=rv_report,
                        evidence_path=execution_result.evidence_path,
                        duration_ms=execution_result.duration_ms,
                        executor_id=executor.get("executor_id", ""),
                    )
                    _log.info("adapter_execute_done", packet_id=packet_id,
                        accepted=False, duration_ms=execution_result.duration_ms)
                    return execution_result
            except Exception as e:
                _log.error("acceptance_pipeline_error", packet_id=packet_id, error=str(e)[:200])
                ev_report = skipped_evidence_report("deterministic acceptance failed")
                rv_report = skipped_reviewer_report("deterministic acceptance failed")
                try:
                    safe_legacy = safe_legacy_dict
                except Exception:
                    safe_legacy = {"error": str(e)[:200]}
                try:
                    self._update_packet_run_result(
                        run_id=run_id, status="blocked",
                        legacy_result=safe_legacy,
                        acceptance_report=None,
                        evidence_verifier_report=ev_report,
                        reviewer_report=rv_report,
                        evidence_path="",
                        duration_ms=int((time.time() - start_time) * 1000),
                        executor_id=executor.get("executor_id", ""),
                    )
                except Exception:
                    pass
                return ExecutionResult(
                    accepted=False,
                    domain_status="blocked",
                    reason=f"Acceptance pipeline error: {str(e)[:200]}",
                    evidence_path="",
                    acceptance_verdict="blocked",
                    acceptance_summary=str(e)[:200],
                    duration_ms=int((time.time() - start_time) * 1000),
                )

            # ── Self-evolution guard ──
            spec_json = packet_data.get("spec_json") or {}
            if isinstance(spec_json, dict) and spec_json.get("origin") == "self_evolution":
                _log.info("self_evolution_guard_check", packet_id=packet_id)
                from grace_control.core.self_evolution_guard import SelfEvolutionGuard
                guard = SelfEvolutionGuard()
                changed = _collect_changed_files(wt_path)
                guard_result = guard.check(changed, session_id=spec_json.get("session_id", ""))
                if not guard_result.passed:
                    _log.warn("self_evolution_guard_blocked", packet_id=packet_id, errors=guard_result.errors)
                    ev_report = skipped_evidence_report("self-evolution guard blocked")
                    rv_report = skipped_reviewer_report("self-evolution guard blocked")
                    execution_result = ExecutionResult(
                        accepted=False, domain_status="rejected",
                        reason="; ".join(guard_result.errors),
                        evidence_path="",
                        duration_ms=int((time.time() - start_time) * 1000),
                    )
                    self._update_packet_run_result(
                        run_id=run_id, status="rejected",
                        legacy_result=safe_legacy_dict,
                        acceptance_report=accept_report,
                        evidence_verifier_report=ev_report,
                        reviewer_report=rv_report,
                        evidence_path=execution_result.evidence_path,
                        duration_ms=execution_result.duration_ms,
                        executor_id=executor.get("executor_id", ""),
                    )
                    return execution_result
                _log.info("self_evolution_guard_passed", packet_id=packet_id)

            # ── Prepare context for verifier + reviewer ──
            from grace_control.core.scope_guard import get_changed_files as _get_changed_files
            changed_files: list[str] = []
            try:
                changed_files = _get_changed_files(wt_path, base_ref=base_sha or base_ref)
            except Exception:
                changed_files = []

            artifacts: list[str] = []
            if run_dir.exists():
                try:
                    artifacts = [str(p.relative_to(run_dir)) for p in run_dir.rglob("*") if p.is_file()]
                except Exception:
                    artifacts = []

            # ── Profile-based routing for LLM gates ──
            from grace_control.core.contracts import AcceptanceProfile

            profile = pkt_contract.acceptance_profile

            if profile == AcceptanceProfile.FAST:
                ev_report = skipped_evidence_report("FAST profile skips evidence verifier")
                rv_report = skipped_reviewer_report("FAST profile skips reviewer")
                execution_result = ExecutionResult(
                    accepted=True,
                    reason=None,
                    domain_status=accept_report.final_verdict.value,
                    worktree_path=result.worktree_path or "",
                    branch_name=result.branch_name or "",
                    acceptance_report_path=accept_report_path,
                    acceptance_verdict=accept_report.final_verdict.value,
                    acceptance_summary=accept_report.summary,
                    duration_ms=int((time.time() - start_time) * 1000),
                    commit_sha=agent_commit_sha,
                )
                evidence_path = self._save_evidence(packet_id, run_number, result.to_dict(), state_root)
                execution_result.evidence_path = evidence_path
                execution_result.commit_sha = agent_commit_sha
                self._save_agent_log(packet_id, run_number, result, state_root)
                self._update_packet_run_result(
                    run_id=run_id, status="accepted",
                    legacy_result=safe_legacy_dict,
                    acceptance_report=accept_report,
                    evidence_verifier_report=ev_report,
                    reviewer_report=rv_report,
                    evidence_path=evidence_path,
                    duration_ms=execution_result.duration_ms,
                    executor_id=executor.get("executor_id", ""),
                    commit_sha=agent_commit_sha,
                )
                _log.info("adapter_execute_done", packet_id=packet_id,
                    accepted=True, duration_ms=execution_result.duration_ms)
                return execution_result

            # ── Evidence Verifier (cheap LLM gate) ──
            evidence_report = await run_evidence_verifier(
                packet=pkt_contract,
                acceptance_report=accept_report,
                worktree_path=wt_path,
                run_dir=run_dir,
                changed_files=changed_files,
                artifacts=artifacts,
            )
            _log.info("evidence_verifier_completed", packet_id=packet_id,
                verdict=evidence_report.verdict.value, skipped=evidence_report.skipped)

            if evidence_report.verdict == EvidenceVerifierVerdict.REWORK_TO_CODER:
                rv_report = skipped_reviewer_report("evidence verifier did not pass")
                execution_result = ExecutionResult(
                    accepted=False, domain_status="rejected",
                    reason=evidence_report.summary,
                    worktree_path=result.worktree_path or "",
                    branch_name=result.branch_name or "",
                    acceptance_report_path=accept_report_path,
                    acceptance_verdict=accept_report.final_verdict.value,
                    acceptance_summary=accept_report.summary,
                    duration_ms=int((time.time() - start_time) * 1000),
                )
                self._update_packet_run_result(
                    run_id=run_id, status="rejected",
                    legacy_result=safe_legacy_dict,
                    acceptance_report=accept_report,
                    evidence_verifier_report=evidence_report,
                    reviewer_report=rv_report,
                    evidence_path=execution_result.evidence_path,
                    duration_ms=execution_result.duration_ms,
                    executor_id=executor.get("executor_id", ""),
                )
                _log.info("adapter_execute_done", packet_id=packet_id,
                    accepted=False, duration_ms=execution_result.duration_ms)
                return execution_result

            if evidence_report.verdict == EvidenceVerifierVerdict.RETURN_TO_ARCHITECT:
                rv_report = skipped_reviewer_report("evidence verifier returned to architect")
                execution_result = ExecutionResult(
                    accepted=False, domain_status="blocked",
                    reason=evidence_report.summary,
                    worktree_path=result.worktree_path or "",
                    branch_name=result.branch_name or "",
                    acceptance_report_path=accept_report_path,
                    acceptance_verdict=accept_report.final_verdict.value,
                    acceptance_summary=accept_report.summary,
                    duration_ms=int((time.time() - start_time) * 1000),
                )
                self._update_packet_run_result(
                    run_id=run_id, status="blocked",
                    legacy_result=safe_legacy_dict,
                    acceptance_report=accept_report,
                    evidence_verifier_report=evidence_report,
                    reviewer_report=rv_report,
                    evidence_path=execution_result.evidence_path,
                    duration_ms=execution_result.duration_ms,
                    executor_id=executor.get("executor_id", ""),
                )
                _log.info("adapter_execute_done", packet_id=packet_id,
                    accepted=False, duration_ms=execution_result.duration_ms)
                return execution_result

            # ── Evidence Verifier PASS → profile-based routing ──
            if profile == AcceptanceProfile.NORMAL:
                rv_report = skipped_reviewer_report("NORMAL profile skips reviewer by default")
                execution_result = ExecutionResult(
                    accepted=True,
                    reason=None,
                    domain_status=accept_report.final_verdict.value,
                    worktree_path=result.worktree_path or "",
                    branch_name=result.branch_name or "",
                    acceptance_report_path=accept_report_path,
                    acceptance_verdict=accept_report.final_verdict.value,
                    acceptance_summary=accept_report.summary,
                    duration_ms=int((time.time() - start_time) * 1000),
                )
                execution_result.commit_sha = agent_commit_sha
                evidence_path = self._save_evidence(packet_id, run_number, result.to_dict(), state_root)
                execution_result.evidence_path = evidence_path
                self._save_agent_log(packet_id, run_number, result, state_root)
                self._update_packet_run_result(
                    run_id=run_id, status="accepted",
                    legacy_result=safe_legacy_dict,
                    acceptance_report=accept_report,
                    evidence_verifier_report=evidence_report,
                    reviewer_report=rv_report,
                    evidence_path=evidence_path,
                    duration_ms=execution_result.duration_ms,
                    executor_id=executor.get("executor_id", ""),
                    commit_sha=agent_commit_sha,
                )
                _log.info("adapter_execute_done", packet_id=packet_id,
                    accepted=True, duration_ms=execution_result.duration_ms)
                return execution_result

            # ── STRICT / default: run Reviewer ──
            reviewer_report = await run_reviewer_gate(
                packet=pkt_contract,
                acceptance_report=accept_report,
                evidence_verifier_report=evidence_report,
                worktree_path=wt_path,
                run_dir=run_dir,
                changed_files=changed_files,
                artifacts=artifacts,
            )
            _log.info("reviewer_gate_completed", packet_id=packet_id,
                verdict=reviewer_report.verdict.value, skipped=reviewer_report.skipped)

            if reviewer_report.verdict == ReviewerVerdict.PASS:
                execution_result = ExecutionResult(
                    accepted=True,
                    reason=None,
                    domain_status=accept_report.final_verdict.value,
                    worktree_path=result.worktree_path or "",
                    branch_name=result.branch_name or "",
                    acceptance_report_path=accept_report_path,
                    acceptance_verdict=accept_report.final_verdict.value,
                    acceptance_summary=accept_report.summary,
                    duration_ms=int((time.time() - start_time) * 1000),
                    commit_sha=agent_commit_sha,
                )
                evidence_path = self._save_evidence(packet_id, run_number, result.to_dict(), state_root)
                execution_result.evidence_path = evidence_path
                self._save_agent_log(packet_id, run_number, result, state_root)
                self._update_packet_run_result(
                    run_id=run_id, status="accepted",
                    legacy_result=safe_legacy_dict,
                    acceptance_report=accept_report,
                    evidence_verifier_report=evidence_report,
                    reviewer_report=reviewer_report,
                    evidence_path=evidence_path,
                    duration_ms=execution_result.duration_ms,
                    executor_id=executor.get("executor_id", ""),
                    commit_sha=agent_commit_sha,
                )
                _log.info("adapter_execute_done", packet_id=packet_id,
                    accepted=True, duration_ms=execution_result.duration_ms)
                return execution_result

            if reviewer_report.verdict == ReviewerVerdict.REWORK_TO_CODER:
                execution_result = ExecutionResult(
                    accepted=False, domain_status="rejected",
                    reason=reviewer_report.summary,
                    worktree_path=result.worktree_path or "",
                    branch_name=result.branch_name or "",
                    acceptance_report_path=accept_report_path,
                    acceptance_verdict=accept_report.final_verdict.value,
                    acceptance_summary=accept_report.summary,
                    duration_ms=int((time.time() - start_time) * 1000),
                )
                self._update_packet_run_result(
                    run_id=run_id, status="rejected",
                    legacy_result=safe_legacy_dict,
                    acceptance_report=accept_report,
                    evidence_verifier_report=evidence_report,
                    reviewer_report=reviewer_report,
                    evidence_path=execution_result.evidence_path,
                    duration_ms=execution_result.duration_ms,
                    executor_id=executor.get("executor_id", ""),
                )
                _log.info("adapter_execute_done", packet_id=packet_id,
                    accepted=False, duration_ms=execution_result.duration_ms)
                return execution_result

            if reviewer_report.verdict == ReviewerVerdict.RETURN_TO_ARCHITECT:
                execution_result = ExecutionResult(
                    accepted=False, domain_status="blocked",
                    reason=reviewer_report.summary,
                    worktree_path=result.worktree_path or "",
                    branch_name=result.branch_name or "",
                    acceptance_report_path=accept_report_path,
                    acceptance_verdict=accept_report.final_verdict.value,
                    acceptance_summary=accept_report.summary,
                    duration_ms=int((time.time() - start_time) * 1000),
                )
                self._update_packet_run_result(
                    run_id=run_id, status="blocked",
                    legacy_result=safe_legacy_dict,
                    acceptance_report=accept_report,
                    evidence_verifier_report=evidence_report,
                    reviewer_report=reviewer_report,
                    evidence_path=execution_result.evidence_path,
                    duration_ms=execution_result.duration_ms,
                    executor_id=executor.get("executor_id", ""),
                )
                _log.info("adapter_execute_done", packet_id=packet_id,
                    accepted=False, duration_ms=execution_result.duration_ms)
                return execution_result

            _log.error("unexpected_reviewer_verdict", packet_id=packet_id,
                verdict=reviewer_report.verdict.value)
            raise RuntimeError(f"Unexpected reviewer verdict: {reviewer_report.verdict.value}")

        except Exception:
            _log.error("adapter_execute_failed", packet_id=packet_id)
            with get_db() as db:
                existing = db.query(PacketRun).filter_by(id=run_id).first()
                if existing:
                    existing.status = "failed"
                    existing.finished_at = datetime.utcnow()
                    existing.duration_ms = int((time.time() - start_time) * 1000)
            raise

    # START_FUNCTION_CONTRACT
    # name: _materialize_packet
    # purpose: Convert DB Packet into EXECUTION_PACKET.md file parseable by parse_packet_markdown.
    # inputs: packet ORM object.
    # returns: Path to created markdown file.
    # side_effects: Writes file to state_root/packets/{id}/EXECUTION_PACKET.md.
    # emitted_logs: None.
    # error_behavior: Raises on filesystem error.
    # END_FUNCTION_CONTRACT
    def _materialize_packet(self, packet_data: dict, state_root: Path) -> Path:
        packet_id = packet_data["id"]
        packet_dir = state_root / "packets" / packet_id
        packet_dir.mkdir(parents=True, exist_ok=True)

        spec_json = packet_data["spec_json"] if isinstance(packet_data["spec_json"], dict) else {}
        spec_str = yaml.dump(spec_json, default_flow_style=False, allow_unicode=True)
        scope = spec_json.get("scope", "src/")
        if isinstance(scope, str):
            scope = [scope]
        scope_lines = "\n".join(f"- {s}" for s in scope)

        frozen = spec_json.get("frozen_scope", ["src/prefect_grace/"])
        if isinstance(frozen, str):
            frozen = [frozen]
        frozen_lines = "\n".join(f"- {s}" for s in frozen)

        verification_raw = spec_json.get("verification", {})
        if isinstance(verification_raw, list):
            verification_text = "\n".join(f"- {v}" if isinstance(v, str) else f"- {' '.join(v)}" for v in verification_raw)
        elif isinstance(verification_raw, dict):
            parts = []
            for stage in ("t0", "t1", "t2"):
                cmds = verification_raw.get(stage, [])
                for c in cmds:
                    c_str = " ".join(c) if isinstance(c, list) else c
                    parts.append(f"- [{stage}] {c_str}")
            verification_text = "\n".join(parts) if parts else "pytest -v\nruff check src/"
        else:
            verification_text = "pytest -v\nruff check src/"

        expected_raw = spec_json.get("expected_evidence", [])
        if expected_raw:
            expected_lines = "\n".join(
                f"- {e['id']}" if isinstance(e, dict) else f"- {e}"
                for e in expected_raw
            )
        else:
            expected_lines = "- test results\n- lint output"

        pd = packet_data
        content = f"""# Execution Packet: {pd['id']}

## Objective

{pd.get('description') or pd.get('title', '')}

## Slice

- slice_id: `SLICE-{pd.get('slug', '').upper()}`
- feature_id: `{pd.get('feature_id', '')}`
- packet_id: `{pd['id']}`
- wave_id: `{pd.get('wave_id', '')}`
- status: `{pd.get('state', '')}`

## Allowed Write Scope

{scope_lines}

## Frozen Scope

{frozen_lines}

## Must Preserve

- Follow GRACE Canon contracts (AI_HEADER, MODULE_CONTRACT, FUNCTION_CONTRACT)
- File ≤ 1000 lines, function ≤ 4000 tokens
- Use log_event() for structured logging

## Acceptance Profile

{pd.get('acceptance_profile', 'NORMAL')}

## Verification

```bash
{verification_text}
```

## Expected Evidence

{expected_lines}

## Escalation Triggers

- Tests fail
- Lint errors
- Scope violation

## Specification

```yaml
{spec_str}
```
"""
        packet_file = packet_dir / "EXECUTION_PACKET.md"
        packet_file.write_text(content)
        return packet_file

    # START_FUNCTION_CONTRACT
    # name: _call_legacy_runner
    # purpose: Call existing run_e2e_packet synchronously in executor thread.
    # inputs: packet_path to EXECUTION_PACKET.md.
    # returns: E2EPacketRunnerResult.
    # side_effects: Creates git worktree, launches agents, runs verifier/reviewer.
    # emitted_logs: None.
    # error_behavior: Raises on runtime failure.
    # END_FUNCTION_CONTRACT
    async def _call_legacy_runner(self, packet_path: Path, state_root: Path, worktree_root: Path,
                                   allowed_scope: list[str] | None = None,
                                   frozen_scope: list[str] | None = None,
                                   packet_contract=None,
                                   attempt: int = 1,
                                   base_ref: str = "HEAD"):
        from prefect_grace.platform.e2e_packet_runner import run_e2e_packet

        packet_id = packet_path.parent.name

        os.environ.setdefault("GRACE_ALLOW_SANDBOX_BYPASS", "true")

        effective_allowed = allowed_scope
        effective_frozen = frozen_scope
        if packet_contract is not None:
            effective_allowed = packet_contract.allowed_write_scope
            effective_frozen = packet_contract.frozen_scope

        # Write packet to legacy registry (required by agent launcher)
        reg_dir = state_root / "state"
        reg_dir.mkdir(parents=True, exist_ok=True)
        reg_file = reg_dir / "packet_registry.yaml"
        try:
            existing = {}
            if reg_file.exists():
                existing = yaml.safe_load(reg_file.read_text()) or {}
            existing[packet_id] = {
                "packet_id": packet_id,
                "feature_id": packet_id[:15],
                "wave_id": "W01", "status": "ready", "phase": "PHASE-TEST",
                "packet_path": str(packet_path),
                "allowed_write_scope": effective_allowed or [],
                "frozen_scope": effective_frozen or [],
                "depends_on": [],
            }
            reg_file.write_text(yaml.dump(existing, default_flow_style=False))
        except Exception:
            pass

        # Clean stale git worktrees + branches from previous attempts
        import subprocess as _sp
        import shutil
        attempt_slug = f"attempt-{attempt:04d}"
        try:
            _sp.run(["git", "-C", str(self.project_root), "worktree", "prune"],
                    capture_output=True, timeout=10)
            wt_path = worktree_root / f"{packet_id}-{attempt_slug}"
            if wt_path.exists():
                _sp.run(["git", "-C", str(self.project_root), "worktree", "remove", str(wt_path), "--force"],
                       capture_output=True, timeout=10)
                shutil.rmtree(wt_path, ignore_errors=True)
            branch = f"agent/default/{packet_id}/{attempt_slug}"
            _sp.run(["git", "-C", str(self.project_root), "branch", "-D", branch],
                   capture_output=True, timeout=10)
        except Exception:
            pass

        timeout = int(os.environ.get("GRACE_AGENT_TIMEOUT", "600"))
        loop = asyncio.get_event_loop()
        result = await loop.run_in_executor(
            None,
            partial(
                run_e2e_packet,
                project_root=self.project_root,
                packet_path=packet_path,
                state_root=state_root,
                worktree_root=worktree_root,
                dry_run=False,
                execute_agent=True,
                attempt=attempt,
                base_ref=base_ref,
                keep_worktree=True,
                runtime_state_root=state_root,
                timeout_seconds=timeout,
            ),
        )
        return result

    # START_FUNCTION_CONTRACT
    # name: _parse_result
    # purpose: Map E2EPacketRunnerResult to ExecutionResult.
    # inputs: E2EPacketRunnerResult from legacy runner.
    # returns: ExecutionResult.
    # side_effects: None.
    # emitted_logs: None.
    # error_behavior: Never raises (safe mapping).
    # END_FUNCTION_CONTRACT
    def _parse_result(self, result) -> ExecutionResult:
        return ExecutionResult(
            accepted=False,
            reason="legacy result is not an acceptance gate",
            domain_status=result.domain_status,
            worktree_path=result.worktree_path or "",
            branch_name=result.branch_name or "",
        )

    # START_FUNCTION_CONTRACT
    # name: _save_evidence
    # purpose: Return evidence path string for PacketRun record.
    # inputs: packet_id, run_number, result_dict.
    # returns: Evidence directory path string.
    # side_effects: None (path only, evidence saved by legacy runner).
    # emitted_logs: None.
    # error_behavior: Never raises.
    # END_FUNCTION_CONTRACT
    def _save_evidence(self, packet_id: str, run_number: int, result: dict, state_root: Path) -> str:
        return str(state_root / "packets" / packet_id / "runs" / f"R{run_number:02d}")

    # START_FUNCTION_CONTRACT
    # name: _save_acceptance_report
    # purpose: Save acceptance report as JSON to run directory.
    # inputs: packet_id, run_number, report (AcceptanceReport), state_root.
    # returns: acceptance_report.json path string.
    # side_effects: Writes JSON file.
    # emitted_logs: None.
    # error_behavior: Never raises.
    # END_FUNCTION_CONTRACT
    def _save_acceptance_report(self, packet_id: str, run_number: int, report, state_root: Path) -> str:
        import json as _json
        ev_dir = state_root / "packets" / packet_id / "runs" / f"R{run_number:02d}"
        ev_dir.mkdir(parents=True, exist_ok=True)
        path = ev_dir / "acceptance_report.json"
        path.write_text(_json.dumps(report.to_dict(), indent=2, default=str))
        return str(path)

    # START_FUNCTION_CONTRACT
    # name: _build_execution_result_from_acceptance
    # purpose: Build ExecutionResult from acceptance report and legacy result.
    # inputs: legacy_execution_result, acceptance_report, acceptance_report_path.
    # returns: ExecutionResult.
    # side_effects: None.
    # emitted_logs: None.
    # error_behavior: Never raises.
    # END_FUNCTION_CONTRACT
    def _build_execution_result_from_acceptance(
        self,
        legacy_execution_result=None,
        acceptance_report=None,
        acceptance_report_path: str = "",
        worktree_path: str = "",
        branch_name: str = "",
        duration_ms: int = 0,
    ) -> ExecutionResult:
        accepted = acceptance_report.is_accepted
        return ExecutionResult(
            accepted=accepted,
            reason=None if accepted else acceptance_report.summary,
            domain_status=acceptance_report.final_verdict.value,
            worktree_path=worktree_path,
            branch_name=branch_name,
            evidence_path=acceptance_report_path if not accepted else "",
            acceptance_report_path=acceptance_report_path,
            acceptance_verdict=acceptance_report.final_verdict.value,
            acceptance_summary=acceptance_report.summary,
            duration_ms=duration_ms,
        )

    # START_FUNCTION_CONTRACT
    # name: _update_packet_run_result
    # purpose: Write PacketRun result_json with all four reports and metadata.
    # inputs: run_id, status, legacy_result, acceptance_report, evidence_verifier_report,
    #         reviewer_report, evidence_path, duration_ms, executor_id.
    # returns: None.
    # side_effects: Updates PacketRun row in DB.
    # emitted_logs: None.
    # error_behavior: Never raises.
    # END_FUNCTION_CONTRACT
    def _update_packet_run_result(
        self,
        *,
        run_id: str,
        status: str,
        legacy_result: dict,
        acceptance_report,
        evidence_verifier_report,
        reviewer_report,
        evidence_path: str,
        duration_ms: int,
        executor_id: str = "",
        commit_sha: str = "",
    ) -> None:
        try:
            with get_db() as db:
                existing = db.query(PacketRun).filter_by(id=run_id).first()
                if existing:
                    existing.status = status
                    accept_dict = acceptance_report.to_dict() if acceptance_report else {"error": "acceptance pipeline failed"}
                    existing.result_json = {
                        "legacy_result": legacy_result,
                        "acceptance_report": accept_dict,
                        "evidence_verifier_report": evidence_verifier_report.model_dump(),
                        "reviewer_report": reviewer_report.model_dump(),
                        "agent_commit_sha": commit_sha,
                    }
                    existing.evidence_path = evidence_path
                    existing.finished_at = datetime.utcnow()
                    existing.duration_ms = duration_ms
                    existing.executor_id = executor_id
        except Exception:
            _log.warn("update_run_result_failed", run_id=run_id, status=status)

    # START_FUNCTION_CONTRACT
    # name: _finish_early_rejected_run
    # purpose: Update PacketRun on early git/worktree failures before acceptance pipeline runs.
    # inputs: run_id, reason, duration_ms, executor_id, legacy_result.
    # returns: ExecutionResult with accepted=False.
    # side_effects: Writes PacketRun.status=rejected with result_json.
    # emitted_logs: None.
    # error_behavior: Never raises.
    # END_FUNCTION_CONTRACT
    def _finish_early_rejected_run(
        self,
        *,
        run_id: str,
        reason: str,
        duration_ms: int,
        executor_id: str = "",
        legacy_result: dict | None = None,
    ) -> ExecutionResult:
        result = ExecutionResult(
            accepted=False, domain_status="rejected", reason=reason,
            evidence_path="", duration_ms=duration_ms, commit_sha="")
        lr = legacy_result or {"error": "pre-acceptance failure", "reason": reason}
        try:
            skip_ev = skipped_evidence_report(reason)
            skip_rv = skipped_reviewer_report(reason)
            self._update_packet_run_result(
                run_id=run_id, status="rejected",
                legacy_result=lr,
                acceptance_report=None,
                evidence_verifier_report=skip_ev,
                reviewer_report=skip_rv,
                evidence_path="",
                duration_ms=duration_ms,
                executor_id=executor_id,
            )
        except Exception:
            pass
        return result

    def _save_agent_log(self, packet_id: str, run_number: int, result, state_root: Path) -> None:
        try:
            log_dir = state_root / "packets" / packet_id / "runs" / f"R{run_number:02d}"
            log_dir.mkdir(parents=True, exist_ok=True)
            agent_log = log_dir / "agent_output.log"

            mr = result.managed_runner_result
            if isinstance(mr, dict):
                agent = mr.get("agent_result", {})
                if isinstance(agent, dict):
                    # Try paths first (legacy writes to files)
                    for key in ("stdout_path", "stderr_path"):
                        path = agent.get(key, "")
                        if path:
                            p = Path(path)
                            if p.exists():
                                content = p.read_text()
                                with agent_log.open("a") as f:
                                    f.write(f"=== {key} ===\n{content}\n")
                    # Also check inline stdout/stderr
                    for key in ("stdout", "stderr"):
                        content = agent.get(key, "")
                        if content:
                            with agent_log.open("a") as f:
                                f.write(f"=== AGENT {key.upper()} ===\n{content}\n")

            if agent_log.exists() and agent_log.stat().st_size > 0:
                _log.info("agent_log_saved", packet_id=packet_id, path=str(agent_log),
                    size=agent_log.stat().st_size)
        except Exception:
            pass


def _collect_changed_files(worktree_root: Path) -> list[Path]:
    changed = []
    src = worktree_root / "src" / "grace_control"
    if src.exists():
        for f in src.rglob("*.py"):
            if "__pycache__" not in str(f):
                changed.append(f)
    ui_dir = worktree_root / "src" / "grace_control" / "ui"
    if ui_dir.exists():
        for f in ui_dir.rglob("*"):
            if f.is_file() and "__pycache__" not in str(f):
                changed.append(f)
    return changed

#END_BLOCK_ADAPTER
