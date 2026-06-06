# AI_HEADER: packet_executor — stateless bridge: DB → backend → acceptance → persist.
# START_MODULE_CONTRACT
# purpose: Execute a packet through its lifecycle. Forwards resolved executor
#          to backend. No subprocess, no shutil, no packet_registry writes.
# inputs: packet_id, worker_id, project_root, state_root, worktree_root.
# returns: ExecutionResult.
# side_effects: Creates PacketRun record.
# error_behavior: Raises on DB/runtime failures.
# END_MODULE_CONTRACT
# START_MODULE_MAP
# mapping:   - class: ExecutionResult   - class: PacketExecutionAdapter
#           - function: _attempt_slug   - function: _attempt_branch
# END_MODULE_MAP

from __future__ import annotations
import time
from datetime import datetime, timezone
from pathlib import Path
from pydantic import BaseModel
from grace_control.agent.backend import ExecutionBackend
from grace_control.core.evidence_verifier import EvidenceVerifierVerdict, run_evidence_verifier, skipped_evidence_report
from grace_control.core.reviewer_gate import ReviewerVerdict, run_reviewer_gate, skipped_reviewer_report
from grace_control.core.structured_logger import GraceLogger
from grace_control.db import get_db
from grace_control.db.schema import Packet, PacketRun
from grace_control.services.agent_commit_service import AgentCommitService
from grace_control.services.worktree_cleanup_service import WorktreeCleanupService
from grace_control.services.worktree_inspector import WorktreeInspector
_log = GraceLogger("adapter")


# Canonical worktree/branch naming helpers — single source of truth.
def _attempt_slug(packet_id: str, attempt: int) -> str:
    return f"{packet_id}-attempt-{attempt:04d}"


def _attempt_branch(packet_id: str, attempt: int) -> str:
    return f"agent/{_attempt_slug(packet_id, attempt)}"


class ExecutionResult(BaseModel):
    accepted: bool; reason: str | None = None; evidence_path: str = ""; duration_ms: int = 0
    domain_status: str = ""; worktree_path: str = ""; branch_name: str = ""
    acceptance_report_path: str = ""; acceptance_verdict: str = ""; acceptance_summary: str = ""
    commit_sha: str = ""


class PacketExecutionAdapter:
    def __init__(self, project_root: Path, state_root: Path, worktree_root: Path,
                 backend: "ExecutionBackend | None" = None):
        self.project_root = Path(project_root); self.state_root = Path(state_root); self.worktree_root = Path(worktree_root)
        if backend is None:
            from grace_control.agent import select_backend
            self._backend = select_backend()
        else:
            self._backend = backend
        from grace_control.services.packet_materializer import PacketMaterializer
        from grace_control.services.evidence_service import EvidenceService
        self._materializer = PacketMaterializer(); self._evidence = EvidenceService(db_factory=get_db)
        self._inspector = WorktreeInspector(); self._committer = AgentCommitService()
        self._worktree_cleanup = WorktreeCleanupService()

    async def execute(self, packet_id: str, worker_id: str) -> ExecutionResult:
        start = time.time(); _log.info("adapter_execute_start", packet_id=packet_id, worker_id=worker_id)
        self.state_root.mkdir(parents=True, exist_ok=True); self.worktree_root.mkdir(parents=True, exist_ok=True)
        from grace_control.db import init_db as _init_db; _init_db()
        run_id, packet_data, run_number = self._load_packet(packet_id, worker_id)
        executor = self._resolve_executor(packet_data); agent_commit_sha = ""
        try:
            packet_path = self._materializer.materialize(packet_data, self.state_root)
            from grace_control.core.contracts import build_packet_contract
            pkt_contract = build_packet_contract(packet_data)
            from grace_control.config.settings import settings
            base_ref = settings.base_branch
            base_sha = self._inspector.base_sha(self.project_root, base_ref)
            evidence_dir = self.state_root / "packets" / packet_id / "runs" / f"R{run_number:02d}"
            result = await self._call_executor(packet_path, pkt_contract, run_number, base_ref, base_sha, executor, evidence_dir)
            _log.debug("executor_run_completed", packet_id=packet_id, ok=result.ok, errors=result.errors[:2])

            wt_ok, agent_commit_sha = self._inspected_worktree(result, pkt_contract, packet_id, packet_data["attempt_count"])
            if not wt_ok: return self._fast_reject(f"Worktree issue", executor.get("executor_id",""), run_id, start)

            accept_report, ar_path, safe_data, changed_files, wt_path, run_dir = await self._run_acceptance(
                pkt_contract, result, packet_id, run_number, base_ref, base_sha, start)

            if not accept_report.is_accepted:
                ev, rv = self._maybe_verify(accept_report, pkt_contract, wt_path, run_dir, changed_files, packet_data)
                return self._persist_run("rejected", run_id, executor, safe_data, accept_report, ev, rv,
                    int((time.time()-start)*1000), ar_path, packet_id, start, commit_sha="")

            se_result = self._self_evolution_guard(packet_data, accept_report, safe_data, run_id, executor, start)
            if se_result: return se_result

            return await self._route_after(start, run_id, packet_id, result, executor, run_number,
                pkt_contract, accept_report, ar_path, safe_data, changed_files, agent_commit_sha, wt_path, run_dir)
        except Exception:
            _log.error("adapter_execute_failed", packet_id=packet_id)
            with get_db() as db:
                e = db.query(PacketRun).filter_by(id=run_id).first()
                if e: e.status = "failed"; e.finished_at = datetime.now(timezone.utc); e.duration_ms = int((time.time()-start)*1000)
            raise

    def _load_packet(self, packet_id: str, worker_id: str):
        with get_db() as db:
            p = db.query(Packet).filter_by(id=packet_id).first()
            if not p: raise ValueError(f"Packet {packet_id} not found")
            rn = p.attempt_count; rid = f"{packet_id}-R{rn:02d}"; slug = _attempt_slug(packet_id, rn)
            self._worktree_cleanup.cleanup_attempt(self.project_root, slug)
            ex = db.query(PacketRun).filter_by(id=rid).first()
            if ex: ex.status = "running"; ex.started_at = datetime.now(timezone.utc)
            else: db.add(PacketRun(id=rid, packet_id=packet_id, run_number=rn, worker_id=worker_id, status="running", started_at=datetime.now(timezone.utc)))
            pd = {k: getattr(p, k) for k in ("id","feature_id","wave_id","slug","title","description","spec_json","state","acceptance_profile","attempt_count","max_attempts")}
        return rid, pd, rn

    def _resolve_executor(self, pd: dict) -> dict:
        from grace_control.core.complexity_router import route_packet
        from grace_control.core.executor_selector import select_executor
        from grace_control.config.agent_profiles import get_agent_profile
        tier = route_packet(pd.get("acceptance_profile","NORMAL"), pd.get("spec_json"))
        spec = pd.get("spec_json") or {}
        rid = (spec.get("recovery") or {}).get("requested_executor_id") if isinstance(spec, dict) else None
        if rid:
            match = get_agent_profile(rid)
            ex = match.to_dict() if match else select_executor("coder", attempt=pd.get("attempt_count",1)+1)
        else: ex = select_executor("coder", attempt=pd.get("attempt_count",1)+1)
        pd["_executor"] = ex; pd["_tier"] = tier.value; return ex

    def _inspected_worktree(self, result, pkt_contract, packet_id, attempt_count):
        if not result.worktree_path or not Path(result.worktree_path).exists(): return False, ""
        wt = Path(result.worktree_path)
        if not self._inspector.is_git_worktree(wt): return True, ""
        if not self._inspector.has_changes(wt, pkt_contract.allowed_write_scope): return False, ""
        sha = self._committer.commit(wt, packet_id, attempt_count); return bool(sha), sha

    def _self_evolution_guard(self, pd, accept_report, safe_data, run_id, executor, start):
        spec = pd.get("spec_json") or {}
        if not (isinstance(spec,dict) and spec.get("origin")=="self_evolution"): return None
        _log.info("self_evolution_guard_check", packet_id=pd["id"])
        from grace_control.core.self_evolution_guard import SelfEvolutionGuard
        gr = SelfEvolutionGuard().check(self._inspector.collect_changed_files(Path(".")), session_id=spec.get("session_id",""))
        if gr.passed: return None
        _log.warn("self_evolution_guard_blocked", packet_id=pd["id"], errors=gr.errors)
        return self._persist_run("rejected", run_id, executor, safe_data, accept_report,
            skipped_evidence_report("guard"), skipped_reviewer_report("guard"), int((time.time()-start)*1000), "", pd["id"], start, commit_sha="")

    async def _run_acceptance(self, pkt_contract, result, packet_id, rn, base_ref, base_sha, start):
        from grace_control.core.acceptance_pipeline import run_acceptance_pipeline
        from grace_control.core.scope_guard import get_changed_files as _gcf
        wt = Path(result.worktree_path) if result.worktree_path else self.project_root
        rd = self.state_root / "packets" / packet_id / "runs" / f"R{rn:02d}"
        try: cf = _gcf(wt, base_ref=base_sha or base_ref)
        except: cf = []
        report = run_acceptance_pipeline(packet=pkt_contract, legacy_result=result, project_root=self.project_root,
            worktree_path=wt, branch_name=result.branch_name or "", run_dir=rd, base_ref=base_ref, base_sha=base_sha)
        _log.info("acceptance_completed", packet_id=packet_id, verdict=report.final_verdict.value)
        arp = self._evidence.save_acceptance_report(packet_id, rn, report, self.state_root)
        try: sl = result.to_dict()
        except: sl = {"ok": result.ok, "domain_status": result.domain_status}
        return report, arp, sl, cf, wt, rd

    def _maybe_verify(self, accept_report, pkt_contract, wt_path, run_dir, changed_files, pd):
        from grace_control.core.recovery_rules import evaluate_ladder
        if evaluate_ladder(pd.get("attempt_count",1)).skip_verifier:
            return skipped_evidence_report("odd skips"), skipped_reviewer_report("fail")
        import asyncio
        ev = asyncio.run(run_evidence_verifier(packet=pkt_contract, acceptance_report=accept_report,
            worktree_path=wt_path, run_dir=run_dir, changed_files=changed_files, artifacts=[]))
        return ev, skipped_reviewer_report("deterministic fail")

    async def _route_after(self, start, run_id, packet_id, result, executor, rn,
                           pkt_contract, accept_report, ar_path, sd, changed_files, sha, wt_path, run_dir):
        from grace_control.core.contracts import AcceptanceProfile
        prof = pkt_contract.acceptance_profile; ev = self._evidence; ex_id = executor.get("executor_id","")
        art = [str(p.relative_to(run_dir)) for p in run_dir.rglob("*") if p.is_file()] if run_dir.exists() else []
        ep = ev.evidence_path(packet_id, rn, self.state_root)
        def _mk(accepted, ds, r=None, e=ep, c=sha):
            return ExecutionResult(accepted=accepted, reason=r, domain_status=ds,
                worktree_path=str(result.worktree_path) if result.worktree_path else "",
                branch_name=result.branch_name or "",
                acceptance_report_path=ar_path, acceptance_verdict=accept_report.final_verdict.value,
                acceptance_summary=accept_report.summary, duration_ms=int((time.time()-start)*1000), commit_sha=c, evidence_path=e)
        def _acc(er, evr, rvr):
            ev.save_agent_log(packet_id, rn, result, self.state_root)
            self._evidence.update_run_result(run_id=run_id, status="accepted", legacy_result=sd,
                acceptance_report=accept_report, evidence_verifier_report=evr, reviewer_report=rvr,
                evidence_path=ep, duration_ms=er.duration_ms, executor_id=ex_id, commit_sha=sha)
            _log.info("adapter_execute_done", packet_id=packet_id, accepted=True, duration_ms=er.duration_ms); return er
        def _rej(domain, reason, evr, rvr):
            er = _mk(False, domain, r=reason, e="")
            self._evidence.update_run_result(run_id=run_id, status=domain, legacy_result=sd,
                acceptance_report=accept_report, evidence_verifier_report=evr, reviewer_report=rvr,
                evidence_path="", duration_ms=er.duration_ms, executor_id=ex_id)
            _log.info("adapter_execute_done", packet_id=packet_id, accepted=False, duration_ms=er.duration_ms); return er

        if prof == AcceptanceProfile.FAST:
            return _acc(_mk(True, "accepted"), skipped_evidence_report("FAST"), skipped_reviewer_report("FAST"))
        evr = await run_evidence_verifier(packet=pkt_contract, acceptance_report=accept_report,
            worktree_path=wt_path, run_dir=run_dir, changed_files=changed_files, artifacts=art)
        if evr.verdict in (EvidenceVerifierVerdict.REWORK_TO_CODER, EvidenceVerifierVerdict.RETURN_TO_ARCHITECT):
            return _rej("rejected" if evr.verdict==EvidenceVerifierVerdict.REWORK_TO_CODER else "blocked", evr.summary, evr, skipped_reviewer_report("ev reject"))
        if prof == AcceptanceProfile.NORMAL:
            return _acc(_mk(True, "accepted"), evr, skipped_reviewer_report("NORMAL"))
        rvr = await run_reviewer_gate(packet=pkt_contract, acceptance_report=accept_report,
            evidence_verifier_report=evr, worktree_path=wt_path, run_dir=run_dir, changed_files=changed_files, artifacts=art)
        if rvr.verdict == ReviewerVerdict.PASS: return _acc(_mk(True, "accepted"), evr, rvr)
        if rvr.verdict in (ReviewerVerdict.REWORK_TO_CODER, ReviewerVerdict.RETURN_TO_ARCHITECT):
            return _rej("rejected" if rvr.verdict==ReviewerVerdict.REWORK_TO_CODER else "blocked", rvr.summary, evr, rvr)
        _log.error("unexpected_reviewer_verdict", packet_id=packet_id, verdict=rvr.verdict.value)
        raise RuntimeError(f"Unexpected reviewer verdict: {rvr.verdict.value}")

    def _persist_run(self, status, run_id, executor, safe_data, accept_report, evr, rvr, dur, ar_path, packet_id, start, *, commit_sha=""):
        er = ExecutionResult(accepted=(status=="accepted"), domain_status=accept_report.final_verdict.value,
            reason=accept_report.summary, worktree_path="", branch_name="",
            acceptance_report_path=ar_path, acceptance_verdict=accept_report.final_verdict.value,
            acceptance_summary=accept_report.summary, duration_ms=dur, commit_sha=commit_sha)
        self._evidence.update_run_result(run_id=run_id, status=status, legacy_result=safe_data,
            acceptance_report=accept_report, evidence_verifier_report=evr, reviewer_report=rvr,
            evidence_path=er.evidence_path, duration_ms=er.duration_ms, executor_id=executor.get("executor_id",""))
        _log.info("adapter_execute_done", packet_id=packet_id, accepted=(status=="accepted"), duration_ms=dur)
        return er

    def _fast_reject(self, reason, executor_id, run_id, start):
        er = ExecutionResult(accepted=False, domain_status="rejected", reason=reason, evidence_path="", duration_ms=int((time.time()-start)*1000))
        try: self._evidence.update_run_result(run_id=run_id, status="rejected", legacy_result={"error":"pre-acceptance failure","reason":reason},
            acceptance_report=None, evidence_verifier_report=skipped_evidence_report(reason), reviewer_report=skipped_reviewer_report(reason),
            evidence_path="", duration_ms=er.duration_ms, executor_id=executor_id)
        except: pass
        return er

    async def _call_executor(self, packet_path: Path, packet_contract, attempt: int,
                             base_ref: str, base_sha: str, executor: dict, evidence_dir: Path | None = None):
        from grace_control.agent.backend import ExecutionRequest
        pid = packet_path.parent.name
        eff = packet_contract.allowed_write_scope; slug = _attempt_slug(pid, attempt)
        self._worktree_cleanup.cleanup_attempt(self.project_root, slug)
        from grace_control.config.settings import settings
        req = ExecutionRequest(packet_id=pid,
            spec={"attempt_count":attempt,"base_ref":base_ref,"allowed_write_scope":eff or [],"frozen_scope":packet_contract.frozen_scope or []},
            worktree_path=self.worktree_root / slug, branch_name=_attempt_branch(pid, attempt),
            scope_paths=list(eff or []), executor=executor, timeout_s=settings.agent_timeout_seconds,
            session_dir=self.state_root, evidence_dir=evidence_dir)
        return await self._backend.run(req)
