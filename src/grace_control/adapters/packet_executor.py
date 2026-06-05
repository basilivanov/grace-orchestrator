# ############################################################################
# AI_HEADER: packet_executor
# ROLE: Bridge between DB packets and execution backends. STATELESS.
#       Target < 300 lines per file budget.
# ############################################################################

# START_MODULE_CONTRACT
# purpose: Materialize DB packet → call execution backend → route through
#          acceptance pipeline → persist result. State ownership belongs
#          to API endpoints (claim/release), not this adapter.
# inputs: packet_id, worker_id, project_root, state_root, worktree_root.
# returns: ExecutionResult.
# side_effects: Creates PacketRun record. Does NOT change packet state.
# emitted_logs: adapter_execute_start / _done / _failed.
# error_behavior: Raises on DB/runtime failures.
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

from grace_control.agent.backend import ExecutionBackend
from grace_control.core.evidence_verifier import (
    EvidenceVerifierVerdict, run_evidence_verifier, skipped_evidence_report,
)
from grace_control.core.reviewer_gate import (
    ReviewerVerdict, run_reviewer_gate, skipped_reviewer_report,
)
from grace_control.core.structured_logger import GraceLogger
from grace_control.db import get_db
from grace_control.db.schema import Packet, PacketRun
from grace_control.services.agent_commit_service import AgentCommitService
from grace_control.services.worktree_inspector import WorktreeInspector

_log = GraceLogger("adapter")

_LEGACY_BRANCH_FORMAT = "agent/default/{packet_id}/{attempt_slug}"


def _legacy_branch_name(packet_id: str, attempt_slug: str) -> str:
    return _LEGACY_BRANCH_FORMAT.format(packet_id=packet_id, attempt_slug=attempt_slug)


def _legacy_prepare_worktree(project_root: Path, packet_id: str, attempt_slug: str) -> tuple[Path, str]:
    import shutil, subprocess
    wt_path = Path(project_root) / f"{packet_id}-{attempt_slug}"
    branch = _legacy_branch_name(packet_id, attempt_slug)
    try:
        subprocess.run(["git", "-C", str(project_root), "worktree", "prune"], capture_output=True, timeout=10)
        if wt_path.exists():
            subprocess.run(["git", "-C", str(project_root), "worktree", "remove", str(wt_path), "--force"],
                           capture_output=True, timeout=10)
            shutil.rmtree(wt_path, ignore_errors=True)
        subprocess.run(["git", "-C", str(project_root), "branch", "-D", branch], capture_output=True, timeout=10)
    except Exception as e:
        _log.warn("legacy_prepare_worktree_failed", packet_id=packet_id, error=str(e)[:200])
    return wt_path, branch


# START_BLOCK_MODELS
class ExecutionResult(BaseModel):
    """Structured result returned by adapter for PacketRun."""
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
    """Stateless bridge — materialize → backend → acceptance → persist."""

    def __init__(self, project_root: Path, state_root: Path, worktree_root: Path,
                 backend: "ExecutionBackend | None" = None):
        self.project_root = Path(project_root)
        self.state_root = Path(state_root)
        self.worktree_root = Path(worktree_root)
        if backend is None:
            from grace_control.agent import select_backend
            self._backend = select_backend()
        else:
            self._backend = backend
        from grace_control.services.packet_materializer import PacketMaterializer
        from grace_control.services.evidence_service import EvidenceService
        self._materializer = PacketMaterializer()
        self._evidence = EvidenceService(db_factory=get_db)
        self._inspector = WorktreeInspector()
        self._committer = AgentCommitService()

    async def execute(self, packet_id: str, worker_id: str) -> ExecutionResult:
        start = time.time()
        _log.info("adapter_execute_start", packet_id=packet_id, worker_id=worker_id)
        self.state_root.mkdir(parents=True, exist_ok=True)
        self.worktree_root.mkdir(parents=True, exist_ok=True)
        from grace_control.db import init_db as _init_db
        _init_db()

        run_id, packet_data, run_number = self._load_packet(packet_id, worker_id, start)
        executor = self._resolve_executor(packet_data)
        agent_commit_sha = ""

        try:
            packet_path = self._materializer.materialize(packet_data, self.state_root)
            from grace_control.core.contracts import build_packet_contract
            pkt_contract = build_packet_contract(packet_data)
            from grace_control.config.settings import settings
            base_ref = os.environ.get("GRACE_BASE_REF", settings.base_branch)
            base_sha = self._inspector.base_sha(self.project_root, base_ref)

            result = await self._call_legacy_runner(
                packet_path, self.state_root, self.worktree_root,
                allowed_scope=pkt_contract.allowed_write_scope,
                frozen_scope=pkt_contract.frozen_scope,
                packet_contract=pkt_contract, attempt=run_number, base_ref=base_ref)
            _log.debug("legacy_runner_completed", packet_id=packet_id,
                ok=result.ok, domain=result.domain_status, errors=result.errors[:3])

            wt_ok, agent_commit_sha = self._handle_worktree(result, pkt_contract, packet_id, packet_data["attempt_count"], executor, start)
            if not wt_ok:
                return self._finish_early(reason="Worktree cleaned or no changes", executor_id=executor.get("executor_id", ""),
                    run_id=run_id, duration_ms=int((time.time() - start) * 1000))

            accept_report, accept_report_path, safe_legacy_dict, changed_files, wt_path, run_dir = await self._run_acceptance(
                pkt_contract, result, packet_id, run_number, run_id, base_ref, base_sha, start, executor)
            if not accept_report.is_accepted:
                from grace_control.core.recovery_rules import evaluate_ladder
                route = evaluate_ladder(packet_data.get("attempt_count", 1))
                if route.skip_verifier:
                    ev_report, rv_report = skipped_evidence_report("odd skips"), skipped_reviewer_report("fail")
                else:
                    ev_report = await run_evidence_verifier(packet=pkt_contract, acceptance_report=accept_report,
                        worktree_path=wt_path, run_dir=run_dir, changed_files=changed_files, artifacts=[])
                    rv_report = skipped_reviewer_report("deterministic fail")
                return self._persist_run("rejected", run_id, executor, safe_legacy_dict, accept_report,
                    ev_report, rv_report, int((time.time() - start) * 1000), accept_report_path,
                    packet_id, start, result=result, commit_sha="")

            se_result = self._check_self_evolution(packet_data, accept_report, safe_legacy_dict, run_id, executor, start)
            if se_result:
                return se_result

            artifacts = []
            run_dir = self.state_root / "packets" / packet_id / "runs" / f"R{run_number:02d}"
            if run_dir.exists():
                try:
                    artifacts = [str(p.relative_to(run_dir)) for p in run_dir.rglob("*") if p.is_file()]
                except Exception:
                    artifacts = []

            return await self._route_after_acceptance(
                start=start, run_id=run_id, packet_id=packet_id, result=result,
                pkt_contract=pkt_contract, accept_report=accept_report,
                accept_report_path=accept_report_path, safe_legacy_dict=safe_legacy_dict,
                changed_files=changed_files, artifacts=artifacts, agent_commit_sha=agent_commit_sha,
                executor=executor, run_number=run_number, state_root=self.state_root,
                evidence=self._evidence, wt_path=wt_path, run_dir=run_dir)
        except Exception:
            _log.error("adapter_execute_failed", packet_id=packet_id)
            with get_db() as db:
                existing = db.query(PacketRun).filter_by(id=run_id).first()
                if existing:
                    existing.status = "failed"
                    existing.finished_at = datetime.now(timezone.utc)
                    existing.duration_ms = int((time.time() - start) * 1000)
            raise

    def _load_packet(self, packet_id: str, worker_id: str, start: float) -> tuple[str, dict, int]:
        with get_db() as db:
            packet = db.query(Packet).filter_by(id=packet_id).first()
            if not packet:
                raise ValueError(f"Packet {packet_id} not found")
            run_number = packet.attempt_count
            run_id = f"{packet_id}-R{run_number:02d}"
            attempt_slug = f"attempt-{run_number:04d}"
            _legacy_prepare_worktree(self.project_root, packet_id, attempt_slug)
            existing = db.query(PacketRun).filter_by(id=run_id).first()
            if existing:
                existing.status = "running"
                existing.started_at = datetime.now(timezone.utc)
            else:
                db.add(PacketRun(id=run_id, packet_id=packet_id, run_number=run_number,
                      worker_id=worker_id, status="running", started_at=datetime.now(timezone.utc)))
            packet_data = {k: getattr(packet, k) for k in (
                "id", "feature_id", "wave_id", "slug", "title", "description",
                "spec_json", "state", "acceptance_profile", "attempt_count", "max_attempts")}
        return run_id, packet_data, run_number

    def _resolve_executor(self, packet_data: dict) -> dict:
        from grace_control.core.complexity_router import route_packet
        from grace_control.core.executor_selector import select_executor
        tier = route_packet(packet_data.get("acceptance_profile", "NORMAL"), packet_data.get("spec_json"))
        spec_json = packet_data.get("spec_json") or {}
        recovery = spec_json.get("recovery", {}) if isinstance(spec_json, dict) else {}
        rid = recovery.get("requested_executor_id")
        if isinstance(spec_json, dict) and rid:
            from grace_control.core.executor_selector import load_profiles
            profiles = load_profiles()
            matching = [e for e in profiles.get("codex", {}).get("executors", []) if e.get("executor_id") == rid]
            executor = matching[0] if matching else select_executor("coder", attempt=packet_data.get("attempt_count", 1) + 1)
        else:
            executor = select_executor("coder", attempt=packet_data.get("attempt_count", 1) + 1)
        packet_data["_executor"] = executor
        packet_data["_tier"] = tier.value
        return executor

    def _handle_worktree(self, result, pkt_contract, packet_id: str, attempt_count: int,
                         executor: dict, start: float) -> tuple[bool, str]:
        if not result.worktree_path or not Path(result.worktree_path).exists():
            _log.warn("worktree_cleaned_or_missing", packet_id=packet_id)
            return False, ""
        wt = Path(result.worktree_path)
        if not self._inspector.is_git_worktree(wt):
            return True, ""
        if not self._inspector.has_changes(wt, pkt_contract.allowed_write_scope):
            _log.warn("no_changes_produced", packet_id=packet_id)
            return False, ""
        sha = self._committer.commit(wt, packet_id, attempt_count)
        return bool(sha), sha

    def _check_self_evolution(self, packet_data: dict, accept_report, safe_legacy_dict, run_id, executor, start):
        spec_json = packet_data.get("spec_json") or {}
        if not (isinstance(spec_json, dict) and spec_json.get("origin") == "self_evolution"):
            return None
        _log.info("self_evolution_guard_check", packet_id=packet_data["id"])
        from grace_control.core.self_evolution_guard import SelfEvolutionGuard
        guard = SelfEvolutionGuard()
        wt_path = Path(".")
        changed = self._inspector.collect_changed_files(wt_path)
        gr = guard.check(changed, session_id=spec_json.get("session_id", ""))
        if gr.passed:
            _log.info("self_evolution_guard_passed", packet_id=packet_data["id"])
            return None
        _log.warn("self_evolution_guard_blocked", packet_id=packet_data["id"], errors=gr.errors)
        return self._persist_run("rejected", run_id, executor, safe_legacy_dict, accept_report,
            skipped_evidence_report("evolution guard"), skipped_reviewer_report("evolution guard"),
            int((time.time() - start) * 1000), "", packet_id, start, accept_report_path="",
            result=None, commit_sha="")

    async def _run_acceptance(self, pkt_contract, result, packet_id, run_number, run_id,
                              base_ref, base_sha, start, executor):
        from grace_control.core.acceptance_pipeline import run_acceptance_pipeline
        from grace_control.core.scope_guard import get_changed_files
        wt_path = Path(result.worktree_path) if result.worktree_path else self.project_root
        run_dir = self.state_root / "packets" / packet_id / "runs" / f"R{run_number:02d}"
        try:
            changed_files = get_changed_files(wt_path, base_ref=base_sha or base_ref)
        except Exception:
            changed_files = []
        accept_report = run_acceptance_pipeline(
            packet=pkt_contract, legacy_result=result, project_root=self.project_root,
            worktree_path=wt_path, branch_name=result.branch_name or "", run_dir=run_dir,
            base_ref=base_ref, base_sha=base_sha)
        _log.info("acceptance_completed", packet_id=packet_id, verdict=accept_report.final_verdict.value)
        accept_report_path = self._evidence.save_acceptance_report(packet_id, run_number, accept_report, self.state_root)
        try:
            safe_legacy_dict = result.to_dict()
        except Exception:
            safe_legacy_dict = {"ok": result.ok, "domain_status": result.domain_status}
        return accept_report, accept_report_path, safe_legacy_dict, changed_files, wt_path, run_dir

    async def _handle_fail(self, accept_report, accept_report_path, run_id, packet_data,
                           executor, safe_legacy_dict, result, changed_files, start):
        from grace_control.core.recovery_rules import evaluate_ladder
        route = evaluate_ladder(packet_data.get("attempt_count", 1))
        if route.skip_verifier:
            ev_report, rv_report = skipped_evidence_report("odd skips verifier"), skipped_reviewer_report("fail")
        else:
            ev_report = await run_evidence_verifier(
                packet=packet_data.get("_executor", {}), acceptance_report=accept_report,
                worktree_path=Path(result.worktree_path) if result.worktree_path else self.project_root,
                run_dir=self.state_root, changed_files=changed_files, artifacts=[])
            rv_report = skipped_reviewer_report("deterministic fail")
        return self._persist_run("rejected", run_id, executor, safe_legacy_dict, accept_report,
            ev_report, rv_report, int((time.time() - start) * 1000), accept_report_path,
            packet_data["id"], start, result=result, commit_sha="")

    # ── Profile routing ────────────────────────────────────────────

    async def _route_after_acceptance(self, **kw):
        from grace_control.core.contracts import AcceptanceProfile
        profile = kw["pkt_contract"].acceptance_profile
        result, executor = kw["result"], kw["executor"]
        start, run_id, packet_id = kw["start"], kw["run_id"], kw["packet_id"]
        sf, accept_report, ar_path = kw["safe_legacy_dict"], kw["accept_report"], kw["accept_report_path"]
        cf, artifacts, commit_sha = kw["changed_files"], kw["artifacts"], kw["agent_commit_sha"]
        rn, sr, ev = kw["run_number"], kw["state_root"], kw["evidence"]
        wt_path, run_dir, pkt_contract = kw["wt_path"], kw["run_dir"], kw["pkt_contract"]

        evidence_path = ev.evidence_path(packet_id, rn, sr)
        executor_id = executor.get("executor_id", "")
        acc_verdict = accept_report.final_verdict.value
        wt = result.worktree_path or ""
        bn = result.branch_name or ""

        def _mk(accepted, status, reason=None, ep="", sha=commit_sha):
            return ExecutionResult(accepted=accepted, reason=reason, domain_status=status,
                worktree_path=wt, branch_name=bn, acceptance_report_path=ar_path,
                acceptance_verdict=acc_verdict, acceptance_summary=accept_report.summary,
                duration_ms=int((time.time() - start) * 1000), commit_sha=sha, evidence_path=ep)

        if profile == AcceptanceProfile.FAST:
            er = _mk(True, "accepted", ep=evidence_path)
            ev.save_agent_log(packet_id, rn, result, sr)
            self._update_run(run_id, "accepted", sf, accept_report,
                skipped_evidence_report("FAST"), skipped_reviewer_report("FAST"),
                er, executor_id, evidence_path, commit_sha)
            _log.info("adapter_execute_done", packet_id=packet_id, accepted=True, duration_ms=er.duration_ms)
            return er

        ev_report = await run_evidence_verifier(
            packet=pkt_contract, acceptance_report=accept_report,
            worktree_path=wt_path, run_dir=run_dir, changed_files=cf, artifacts=artifacts)

        if ev_report.verdict in (EvidenceVerifierVerdict.REWORK_TO_CODER, EvidenceVerifierVerdict.RETURN_TO_ARCHITECT):
            return self._reject_with(ev_report.summary, run_id, executor_id, sf, accept_report,
                ev_report, skipped_reviewer_report("ev reject"), start, packet_id, ar_path, result,
                "rejected" if ev_report.verdict == EvidenceVerifierVerdict.REWORK_TO_CODER else "blocked")

        if profile == AcceptanceProfile.NORMAL:
            er = _mk(True, "accepted", ep=evidence_path)
            ev.save_agent_log(packet_id, rn, result, sr)
            self._update_run(run_id, "accepted", sf, accept_report, ev_report,
                skipped_reviewer_report("NORMAL"), er, executor_id, evidence_path, commit_sha)
            _log.info("adapter_execute_done", packet_id=packet_id, accepted=True, duration_ms=er.duration_ms)
            return er

        reviewer_report = await run_reviewer_gate(
            packet=pkt_contract, acceptance_report=accept_report, evidence_verifier_report=ev_report,
            worktree_path=wt_path, run_dir=run_dir, changed_files=cf, artifacts=artifacts)
        rv_v = reviewer_report.verdict
        if rv_v == ReviewerVerdict.PASS:
            er = _mk(True, "accepted", ep=evidence_path)
            ev.save_agent_log(packet_id, rn, result, sr)
            self._update_run(run_id, "accepted", sf, accept_report, ev_report, reviewer_report,
                er, executor_id, evidence_path, commit_sha)
            _log.info("adapter_execute_done", packet_id=packet_id, accepted=True, duration_ms=er.duration_ms)
            return er
        if rv_v in (ReviewerVerdict.REWORK_TO_CODER, ReviewerVerdict.RETURN_TO_ARCHITECT):
            return self._reject_with(reviewer_report.summary, run_id, executor_id, sf, accept_report,
                ev_report, reviewer_report, start, packet_id, ar_path, result,
                "rejected" if rv_v == ReviewerVerdict.REWORK_TO_CODER else "blocked")
        _log.error("unexpected_reviewer_verdict", packet_id=packet_id, verdict=rv_v.value)
        raise RuntimeError(f"Unexpected reviewer verdict: {rv_v.value}")

    def _reject_with(self, summary, run_id, executor_id, safe_dict, accept_report,
                     ev_report, rv_report, start, packet_id, ar_path, result, status):
        er = ExecutionResult(accepted=False, reason=summary, domain_status=status,
            worktree_path=result.worktree_path or "", branch_name=result.branch_name or "",
            acceptance_report_path=ar_path, acceptance_verdict=accept_report.final_verdict.value,
            acceptance_summary=accept_report.summary,
            duration_ms=int((time.time() - start) * 1000))
        self._evidence.update_run_result(run_id=run_id, status=status, legacy_result=safe_dict,
            acceptance_report=accept_report, evidence_verifier_report=ev_report,
            reviewer_report=rv_report, evidence_path=er.evidence_path,
            duration_ms=er.duration_ms, executor_id=executor_id)
        _log.info("adapter_execute_done", packet_id=packet_id, accepted=False, duration_ms=er.duration_ms)
        return er

    def _update_run(self, run_id, status, safe_dict, accept_report, ev_report, rv_report,
                    er, executor_id, evidence_path, commit_sha):
        self._evidence.update_run_result(run_id=run_id, status=status, legacy_result=safe_dict,
            acceptance_report=accept_report, evidence_verifier_report=ev_report,
            reviewer_report=rv_report, evidence_path=evidence_path,
            duration_ms=er.duration_ms, executor_id=executor_id, commit_sha=commit_sha)

    def _persist_run(self, status, run_id, executor, safe_dict, accept_report, ev_report,
                     rv_report, duration_ms, ar_path, packet_id, start, *, result=None, commit_sha=""):
        er = ExecutionResult(
            accepted=(status == "accepted"),
            domain_status=accept_report.final_verdict.value,
            reason=None if status == "accepted" else accept_report.summary,
            worktree_path=result.worktree_path if result else "",
            branch_name=result.branch_name if result else "",
            acceptance_report_path=ar_path, acceptance_verdict=accept_report.final_verdict.value,
            acceptance_summary=accept_report.summary, duration_ms=duration_ms, commit_sha=commit_sha)
        self._evidence.update_run_result(run_id=run_id, status=status, legacy_result=safe_dict,
            acceptance_report=accept_report, evidence_verifier_report=ev_report,
            reviewer_report=rv_report, evidence_path=er.evidence_path,
            duration_ms=er.duration_ms, executor_id=executor.get("executor_id", ""))
        _log.info("adapter_execute_done", packet_id=packet_id, accepted=(status == "accepted"), duration_ms=duration_ms)
        return er

    def _finish_early(self, *, reason, executor_id, run_id, duration_ms):
        er = ExecutionResult(accepted=False, domain_status="rejected", reason=reason,
            evidence_path="", duration_ms=duration_ms, commit_sha="")
        try:
            self._evidence.update_run_result(run_id=run_id, status="rejected",
                legacy_result={"error": "pre-acceptance failure", "reason": reason},
                acceptance_report=None, evidence_verifier_report=skipped_evidence_report(reason),
                reviewer_report=skipped_reviewer_report(reason), evidence_path="",
                duration_ms=duration_ms, executor_id=executor_id)
        except Exception:
            pass
        return er

    async def _call_legacy_runner(self, packet_path: Path, state_root: Path, worktree_root: Path,
                                   allowed_scope=None, frozen_scope=None, packet_contract=None,
                                   attempt: int = 1, base_ref: str = "HEAD"):
        from grace_control.agent.backend import ExecutionRequest
        packet_id = packet_path.parent.name
        os.environ.setdefault("GRACE_ALLOW_SANDBOX_BYPASS", "true")
        eff_allowed = packet_contract.allowed_write_scope if packet_contract else allowed_scope
        eff_frozen = packet_contract.frozen_scope if packet_contract else frozen_scope
        reg_dir = state_root / "state"
        reg_dir.mkdir(parents=True, exist_ok=True)
        reg_file = reg_dir / "packet_registry.yaml"
        try:
            existing = {}
            if reg_file.exists():
                existing = yaml.safe_load(reg_file.read_text()) or {}
            existing[packet_id] = {"packet_id": packet_id, "feature_id": packet_id[:15], "wave_id": "W01",
                "status": "ready", "phase": "PHASE-TEST", "packet_path": str(packet_path),
                "allowed_write_scope": eff_allowed or [], "frozen_scope": eff_frozen or [], "depends_on": []}
            reg_file.write_text(yaml.dump(existing, default_flow_style=False))
        except Exception:
            pass
        attempt_slug = f"attempt-{attempt:04d}"
        _legacy_prepare_worktree(self.project_root, packet_id, attempt_slug)
        from grace_control.config.settings import settings
        timeout = int(os.environ.get("GRACE_AGENT_TIMEOUT", str(settings.agent_timeout_seconds)))
        request = ExecutionRequest(packet_id=packet_id,
            spec={"attempt_count": attempt, "base_ref": base_ref,
                  "allowed_write_scope": eff_allowed or [], "frozen_scope": eff_frozen or []},
            worktree_path=worktree_root / f"{packet_id}-{attempt_slug}",
            branch_name=_legacy_branch_name(packet_id, attempt_slug),
            scope_paths=list(eff_allowed or []), executor={"executor_id": "legacy", "model": "prefect"},
            timeout_s=timeout, session_dir=state_root)
        return await self._backend.run(request)
#END_BLOCK_ADAPTER
