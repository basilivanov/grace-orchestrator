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
from datetime import UTC, datetime
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


# ── Failure classification (TZ §6.7) ─────────────────────────────────────────

import re as _re_classify


def _redact_secrets(text: str) -> str:
    """Redact obvious secrets from log tails. Never expose API keys.

    Conservative: redact long token-like substrings, bearer-style auth
    headers, and URLs with embedded credentials.
    """
    if not text:
        return text
    # Bearer / Authorization headers.
    text = _re_classify.sub(
        r"(?i)(authorization\s*:\s*bearer\s+)[A-Za-z0-9._\-]+",
        r"\1***REDACTED***", text)
    # ENV_VAR=value where value is long and token-like.
    text = _re_classify.sub(
        r"(?i)(\b[A-Z][A-Z0-9_]*(?:_KEY|_TOKEN|_SECRET|_PASSWORD|_URL))\s*=\s*([^\s\"']{12,})",
        r"\1***REDACTED***", text)
    # URL with embedded user:pass@.
    text = _re_classify.sub(
        r"([A-Za-z][A-Za-z0-9+\-.]*://)([^\s/@:]+):([^\s/@]+)@",
        r"\1***:***@", text)
    # Long opaque tokens (40+ alnum/dash/underscore).
    text = _re_classify.sub(
        r"\b[A-Za-z0-9_\-]{40,}\b", "***REDACTED***", text)
    return text


_STDOUT_TAIL_LIMIT = 4000
_STDERR_TAIL_LIMIT = 4000


def _tail(s: str, limit: int) -> str:
    if not s:
        return ""
    if len(s) <= limit:
        return s
    return s[-limit:]


# Diagnostics contract surface (TZ §6.6). Keys persisted at top-level of
# result_json["diagnostics"] for UI/admin/trace to consume without traversing
# legacy_result.evidence.
_DIAGNOSTICS_KEYS = (
    "stdout_tail",
    "stderr_tail",
    "exit_code",
    "duration_ms",
    "failure_stage",
    "failure_class",
    "workspace",
    "session_resume",
)


def _extract_diagnostics(result) -> dict:
    """Pull TZ §6.6 diagnostics out of result.evidence into a top-level dict.

    Always returns a dict; missing keys are simply absent. The legacy
    evidence sub-dict is still kept for back-compat with anything reading
    result_json.legacy_result.evidence.
    """
    out: dict = {}
    try:
        ev = getattr(result, "evidence", {}) or {}
    except Exception:
        ev = {}
    for k in _DIAGNOSTICS_KEYS:
        if k in ev:
            out[k] = ev[k]
    return out


def classify_failure(
    stdout: str,
    stderr: str,
    exit_code: int | None,
    stage: str,
) -> str:
    """Deterministic failure classification (TZ §6.7).

    Returns one of: session_not_found, auth_error, timeout, no_changes,
    scope_violation, t1_failed, agent_commit_failed,
    worktree_preflight_failed, unknown.
    """
    blob = ((stdout or "") + "\n" + (stderr or "")).lower()
    if exit_code is None or exit_code != 0:
        if "timed_out" in stage or "timeout" in stage:
            return "timeout"
    if "session not found" in blob:
        return "session_not_found"
    if any(t in blob for t in ("401", "403", "unauthorized", "api key", "missing key", "authentication")):
        return "auth_error"
    if "timed_out" in stage or "timeout" in stage:
        return "timeout"
    if "no changes" in stage or "no_changes" in stage:
        return "no_changes"
    if "scope_violation" in stage or "scope violation" in blob:
        return "scope_violation"
    if "t1" in stage and "fail" in stage:
        return "t1_failed"
    if "git commit" in blob and "fail" in blob:
        return "agent_commit_failed"
    if "preflight" in stage and "fail" in stage:
        return "worktree_preflight_failed"
    if "worktree" in stage and "issue" in stage:
        return "worktree_issue"
    return "unknown"


# Commands that need broader repo context (cannot run in scoped_copy).
# Conservative list: include anything that walks the test tree or imports
# sibling modules not in the packet scope.
_BROAD_REPO_VERIFICATION_PATTERNS = (
    "pytest",
    "py.test",
    "py.test",
    "ruff",
    "mypy",
    "pnpm test",
    "pnpm lint",
    "pnpm typecheck",
    "pnpm exec",
    "npm test",
    "npm run",
    "vitest",
    "playwright",
    "jest",
    "tsc",
    "pnpm guardrails",
    "guardrails",
    "go test",
    "go vet",
    "go build",
    "cargo test",
    "cargo build",
)


def _flatten_verification_for_safety(packet_contract) -> list:
    """Best-effort flatten of all verification command tokens.

    Verification can be structured as t0/t1/t2 lists of [cmd, arg, ...]
    or as flat strings. We flatten everything to a list of strings and
    nested lists (so _verification_unsafe_for_scoped can re-flatten).
    """
    out: list = []
    try:
        v = getattr(packet_contract, "verification", None) or {}
    except Exception:
        v = {}
    if not isinstance(v, dict):
        return out
    for tier in ("t0", "t1", "t2"):
        for cmd in v.get(tier) or []:
            if isinstance(cmd, str):
                out.append(cmd)
            elif isinstance(cmd, (list, tuple)):
                # Keep nested — _verification_unsafe_for_scoped flattens.
                out.append([tok for tok in cmd if isinstance(tok, str)])
            else:
                out.append(str(cmd))
    return out


def _verification_unsafe_for_scoped(verification_tokens: list, scope: list[str]) -> bool:
    """True when verification likely needs files outside packet scope.

    Heuristic: if verification contains a broad-repo command (pytest, tsc,
    etc.) AND the test/config files are not all in scope, scoped_copy
    workspace will fail.

    Accepts flat list of strings OR nested list of strings (verification
    commands can be [cmd, arg, ...] or [cmd, arg, ...] sublists).
    """
    flat: list[str] = []
    for item in verification_tokens or []:
        if isinstance(item, str):
            flat.append(item)
        elif isinstance(item, (list, tuple)):
            for tok in item:
                if isinstance(tok, str):
                    flat.append(tok)
    if not flat:
        return False
    blob = " ".join(flat).lower()
    has_broad = any(p in blob for p in _BROAD_REPO_VERIFICATION_PATTERNS)
    if not has_broad:
        return False
    # If pytest/tsc etc. is in verification, scoped_copy is unsafe unless
    # the user explicitly opted in via workspace_scope_safety.
    return True


class ExecutionResult(BaseModel):
    accepted: bool; reason: str | None = None; evidence_path: str = ""; duration_ms: int = 0
    domain_status: str = ""; worktree_path: str = ""; branch_name: str = ""
    acceptance_report_path: str = ""; acceptance_verdict: str = ""; acceptance_summary: str = ""
    commit_sha: str = ""


class PacketExecutionAdapter:
    def __init__(self, project_root: Path, state_root: Path, worktree_root: Path,
                 backend: ExecutionBackend | None = None):
        self.project_root = Path(project_root); self.state_root = Path(state_root); self.worktree_root = Path(worktree_root)
        if backend is None:
            from grace_control.agent import select_backend
            self._backend = select_backend()
        else:
            self._backend = backend
        from grace_control.core.cleanup_on_state import TerminalStateCleanup
        from grace_control.services.evidence_service import EvidenceService
        from grace_control.services.packet_materializer import PacketMaterializer
        from grace_control.services.session_store import SessionStore
        self._materializer = PacketMaterializer(); self._evidence = EvidenceService(db_factory=get_db)
        self._inspector = WorktreeInspector(); self._committer = AgentCommitService()
        self._worktree_cleanup = WorktreeCleanupService()
        self._terminal_cleanup = TerminalStateCleanup(
            project_root=project_root, worktree_root=worktree_root,
        )
        self._session_store = SessionStore()

    async def execute(self, packet_id: str, worker_id: str,
                       claim_data: dict | None = None) -> ExecutionResult:
        start = time.time(); _log.info("adapter_execute_start", packet_id=packet_id, worker_id=worker_id)
        self.state_root.mkdir(parents=True, exist_ok=True); self.worktree_root.mkdir(parents=True, exist_ok=True)
        if claim_data:
            run_id, packet_data, run_number = self._load_packet_from_claim(packet_id, worker_id, claim_data)
        else:
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

            if not hasattr(result, "evidence") or result.evidence is None:
                result.evidence = {}
            skip_context = executor.get("skip_context_builder", False)
            if skip_context:
                _log.info("context_builder_skipped", packet_id=packet_id,
                          executor_id=executor.get("executor_id", ""),
                          reason="executor.skip_context_builder")
                result.evidence["context_builder"] = {
                    "skipped": True,
                    "reason": "executor.skip_context_builder=true",
                    "executor_id": executor.get("executor_id", ""),
                }
            else:
                result.evidence["context_builder"] = {
                    "skipped": False
                }

            wt_ok, agent_commit_sha = self._inspected_worktree(result, pkt_contract, packet_id, packet_data["attempt_count"])
            if not wt_ok: return self._fast_reject("Worktree issue", executor.get("executor_id",""), run_id, start)

            accept_report, ar_path, safe_data, changed_files, wt_path, run_dir = await self._run_acceptance(
                pkt_contract, result, packet_id, run_number, base_ref, base_sha, start)

            if not accept_report.is_accepted:
                ev, rv = await self._maybe_verify(accept_report, pkt_contract, wt_path, run_dir, changed_files, packet_data)
                return self._persist_run("rejected", run_id, executor, safe_data, accept_report, ev, rv,
                    int((time.time()-start)*1000), ar_path, packet_id, start, commit_sha=agent_commit_sha,
                    wt_path=wt_path, run_dir=run_dir, changed_files=changed_files, base_ref=base_ref, base_sha=base_sha)

            se_result = self._self_evolution_guard(packet_data, accept_report, safe_data, run_id, executor, start)
            if se_result: return se_result

            return await self._route_after(start, run_id, packet_id, result, executor, run_number,
                pkt_contract, accept_report, ar_path, safe_data, changed_files, agent_commit_sha, wt_path, run_dir,
                base_ref=base_ref, base_sha=base_sha)
        except Exception:
            _log.error("adapter_execute_failed", packet_id=packet_id)
            with get_db() as db:
                e = db.query(PacketRun).filter_by(id=run_id).first()
                if e: e.status = "failed"; e.finished_at = datetime.now(UTC); e.duration_ms = int((time.time()-start)*1000)
            raise

    def _load_packet_from_claim(self, packet_id: str, worker_id: str, claim: dict):
        """Build packet_data from claim response — no DB query, no WAL race."""
        rn = claim.get("attempt", 1)
        rid = f"{packet_id}-R{rn:02d}"
        with get_db() as db:
            ex = db.query(PacketRun).filter_by(id=rid).first()
            if ex:
                ex.status = "running"
                ex.started_at = datetime.now(UTC)
            else:
                db.add(PacketRun(id=rid, packet_id=packet_id, run_number=rn,
                    worker_id=worker_id, status="running",
                    started_at=datetime.now(UTC)))
            db.commit()
        cover = claim.get("spec", {})
        pd = {
            "id": packet_id,
            "feature_id": claim.get("feature_id", ""),
            "wave_id": claim.get("wave_id", ""),
            "slug": claim.get("slug", "") or cover.get("slug", ""),
            "title": claim.get("title") or cover.get("title") or "",
            "description": claim.get("description") or cover.get("description") or "",
            "spec_json": cover,
            "state": "running",
            "acceptance_profile": claim.get("acceptance_profile") or cover.get("acceptance_profile") or "NORMAL",
            "attempt_count": rn,
            "max_attempts": claim.get("max_attempts", 3),
        }
        return rid, pd, rn

    def _load_packet(self, packet_id: str, worker_id: str):
        p = None
        for attempt in range(5):
            with get_db() as db:
                p = db.query(Packet).filter_by(id=packet_id).first()
                if p: break
            if p: break
            time.sleep(0.1 * (attempt + 1))
        if not p: raise ValueError(f"Packet {packet_id} not found after retries")
        with get_db() as db:
            rn = p.attempt_count; rid = f"{packet_id}-R{rn:02d}"; slug = _attempt_slug(packet_id, rn)
            self._worktree_cleanup.cleanup_attempt(self.project_root, slug, worktree_root=self.worktree_root)
            ex = db.query(PacketRun).filter_by(id=rid).first()
            if ex: ex.status = "running"; ex.started_at = datetime.now(UTC)
            else: db.add(PacketRun(id=rid, packet_id=packet_id, run_number=rn, worker_id=worker_id, status="running", started_at=datetime.now(UTC)))
            pd = {k: getattr(p, k) for k in ("id","feature_id","wave_id","slug","title","description","spec_json","state","acceptance_profile","attempt_count","max_attempts")}
        return rid, pd, rn

    def _resolve_executor(self, pd: dict) -> dict:
        from grace_control.config.agent_profiles import get_agent_profile
        from grace_control.core.complexity_router import route_packet
        from grace_control.core.executor_selector import select_executor
        tier = route_packet(pd.get("acceptance_profile","NORMAL"), pd.get("spec_json"))
        spec = pd.get("spec_json") or {}
        rid = (spec.get("recovery") or {}).get("requested_executor_id") if isinstance(spec, dict) else None
        if rid:
            match = get_agent_profile(rid)
            ex = match.to_dict() if match else select_executor("coder", attempt=max(pd.get("attempt_count", 0), 1))
        else: ex = select_executor("coder", attempt=max(pd.get("attempt_count", 0), 1))
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
            skipped_evidence_report("guard"), skipped_reviewer_report("guard"), int((time.time()-start)*1000), "", pd["id"], start, commit_sha="",
            wt_path=None, run_dir=None, changed_files=None, base_ref=None, base_sha=None)

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

    async def _maybe_verify(self, accept_report, pkt_contract, wt_path, run_dir, changed_files, pd):
        from grace_control.core.recovery_rules import evaluate_ladder
        if evaluate_ladder(pd.get("attempt_count",1)).skip_verifier:
            return skipped_evidence_report("odd skips"), skipped_reviewer_report("fail")
        ev = await run_evidence_verifier(packet=pkt_contract, acceptance_report=accept_report,
            worktree_path=wt_path, run_dir=run_dir, changed_files=changed_files, artifacts=[])
        return ev, skipped_reviewer_report("deterministic fail")

    async def _route_after(self, start, run_id, packet_id, result, executor, rn,
                           pkt_contract, accept_report, ar_path, sd, changed_files, sha, wt_path, run_dir,
                           base_ref=None, base_sha=None):
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
            dev_rep = self._build_dev_replay_metadata(
                packet_id=packet_id, run_id=run_id, run_number=rn,
                wt_path=wt_path, branch_name=result.branch_name or "",
                base_ref=base_ref, base_sha=base_sha, agent_commit_sha=sha,
                changed_files=changed_files, run_dir=run_dir, ar_path=ar_path,
                acceptance_report=accept_report, evr=evr, rvr=rvr
            )
            self._write_agent_patch(wt_path, run_dir, base_sha)
            ev.save_agent_log(packet_id, rn, result, self.state_root)
            self._evidence.update_run_result(run_id=run_id, status="accepted", legacy_result=sd,
                acceptance_report=accept_report, evidence_verifier_report=evr, reviewer_report=rvr,
                evidence_path=ep, duration_ms=er.duration_ms, executor_id=ex_id, commit_sha=sha,
                model=getattr(result, "model", "") or executor.get("model",""),
                command_preview=getattr(result, "command_preview", None),
                prompt=getattr(result, "prompt", ""), dev_replay=dev_rep,
                diagnostics=getattr(self, "_last_diagnostics", None))
            _log.info("adapter_execute_done", packet_id=packet_id, accepted=True, duration_ms=er.duration_ms); return er
        def _rej(domain, reason, evr, rvr):
            dev_rep = self._build_dev_replay_metadata(
                packet_id=packet_id, run_id=run_id, run_number=rn,
                wt_path=wt_path, branch_name=result.branch_name or "",
                base_ref=base_ref, base_sha=base_sha, agent_commit_sha=sha,
                changed_files=changed_files, run_dir=run_dir, ar_path=ar_path,
                acceptance_report=accept_report, evr=evr, rvr=rvr
            )
            self._write_agent_patch(wt_path, run_dir, base_sha)
            er = _mk(False, domain, r=reason, e="")
            self._evidence.update_run_result(run_id=run_id, status=domain, legacy_result=sd,
                acceptance_report=accept_report, evidence_verifier_report=evr, reviewer_report=rvr,
                evidence_path="", duration_ms=er.duration_ms, executor_id=ex_id,
                model=getattr(result, "model", "") or executor.get("model",""),
                command_preview=getattr(result, "command_preview", None),
                prompt=getattr(result, "prompt", ""), commit_sha=sha, dev_replay=dev_rep,
                diagnostics=getattr(self, "_last_diagnostics", None))
            # TZ_RETENTION_POLICY Phase 1: on REJECTED / BLOCKED, clean up
            # worktree + all attempt-branches for this packet. Run artifacts
            # in .grace/state/.../runs/R0X/ are NOT touched.
            from grace_control.config.settings import settings
            if not settings.dev_keep_failed_worktrees:
                try:
                    effective_target_root = self._effective_cleanup_root(executor)
                    self._terminal_cleanup.run(packet_id=packet_id, attempt=rn, project_root=effective_target_root)
                except Exception as e:
                    _log.warn("terminal_cleanup_exception",
                        packet_id=packet_id, state=domain, error=str(e)[:200])
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

    def _persist_run(self, status, run_id, executor, safe_data, accept_report, evr, rvr, dur, ar_path, packet_id, start, *, commit_sha="", wt_path=None, run_dir=None, changed_files=None, base_ref=None, base_sha=None):
        er = ExecutionResult(accepted=(status=="accepted"), domain_status=accept_report.final_verdict.value if accept_report else "rejected",
            reason=accept_report.summary if accept_report else "", worktree_path="", branch_name="",
            acceptance_report_path=ar_path, acceptance_verdict=accept_report.final_verdict.value if accept_report else "rejected",
            acceptance_summary=accept_report.summary if accept_report else "", duration_ms=dur, commit_sha=commit_sha)
        rn = None
        if run_id and run_id.rfind("-R") != -1:
            try:
                rn = int(run_id.rsplit("-R", 1)[-1])
            except ValueError:
                rn = 1
        else:
            rn = 1
        dev_rep = self._build_dev_replay_metadata(
            packet_id=packet_id, run_id=run_id, run_number=rn,
            wt_path=wt_path, branch_name=safe_data.get("branch_name", ""),
            base_ref=base_ref, base_sha=base_sha, agent_commit_sha=commit_sha,
            changed_files=changed_files, run_dir=run_dir, ar_path=ar_path,
            acceptance_report=accept_report, evr=evr, rvr=rvr
        )
        self._write_agent_patch(wt_path, run_dir, base_sha)
        self._evidence.update_run_result(run_id=run_id, status=status, legacy_result=safe_data,
            acceptance_report=accept_report, evidence_verifier_report=evr, reviewer_report=rvr,
            evidence_path=er.evidence_path, duration_ms=er.duration_ms, executor_id=executor.get("executor_id",""),
            commit_sha=commit_sha, dev_replay=dev_rep,
            diagnostics=getattr(self, "_last_diagnostics", None))
        # TZ_RETENTION_POLICY Phase 1: on REJECTED (acceptance failure), clean
        # up worktree + all attempt-branches for this packet. Run artifacts
        # in .grace/state/ are NOT touched.
        from grace_control.config.settings import settings
        if status in ("rejected", "failed", "blocked", "blocked_recoverable", "blocked_final") and not settings.dev_keep_failed_worktrees:
            try:
                # The attempt number is encoded in run_id (e.g. pkt_xxx-R03).
                rn = None
                if run_id and run_id.rfind("-R") != -1:
                    try:
                        rn = int(run_id.rsplit("-R", 1)[-1])
                    except ValueError:
                        rn = None

                effective_target_root = self._effective_cleanup_root(executor)
                self._terminal_cleanup.run(packet_id=packet_id, attempt=rn, project_root=effective_target_root)
            except Exception as e:
                _log.warn("terminal_cleanup_exception",
                    packet_id=packet_id, state=status, error=str(e)[:200])
        _log.info("adapter_execute_done", packet_id=packet_id, accepted=(status=="accepted"), duration_ms=dur)
        return er

    def _effective_cleanup_root(self, executor: dict) -> Path:
        from grace_control.config.settings import settings
        workspace_mode = executor.get("workspace_mode") or settings.workspace_mode or "full_git_worktree"
        if executor.get("minimal_repo"):
            workspace_mode = "scoped_copy"
        if workspace_mode == "target_repo_worktree":
            return Path(settings.target_repo_root or self.project_root)
        return self.project_root

    def _fast_reject(self, reason, executor_id, run_id, start):
        er = ExecutionResult(accepted=False, domain_status="rejected", reason=reason, evidence_path="", duration_ms=int((time.time()-start)*1000))
        # Synthesize a minimal diagnostics surface so result_json["diagnostics"]
        # has the same shape as terminal runs (failure_class, failure_stage,
        # stderr_tail). Redact secrets defensively.
        try:
            _diag = {
                "failure_stage": "pre_acceptance",
                "failure_class": classify_failure("", reason, None, "pre_acceptance"),
                "stderr_tail": _redact_secrets(_tail(reason or "", _STDERR_TAIL_LIMIT)),
                "exit_code": None,
                "duration_ms": er.duration_ms,
            }
        except Exception:
            _diag = {"failure_stage": "pre_acceptance", "failure_class": "unknown"}
        try: self._evidence.update_run_result(run_id=run_id, status="rejected", legacy_result={"error":"pre-acceptance failure","reason":reason},
            acceptance_report=None, evidence_verifier_report=skipped_evidence_report(reason), reviewer_report=skipped_reviewer_report(reason),
            evidence_path="", duration_ms=er.duration_ms, executor_id=executor_id, diagnostics=_diag)
        except: pass
        # Clean up worktree + agent/* branches for terminal rejection.
        # Extract packet_id and run_number from run_id (e.g. "pkt_xxx-R01").
        from grace_control.config.settings import settings
        if not settings.dev_keep_failed_worktrees:
            try:
                parts = run_id.rsplit("-R", 1)
                if len(parts) == 2:
                    pkt, rn = parts[0], int(parts[1])
                    from grace_control.config.agent_profiles import get_agent_profile
                    prof = get_agent_profile(executor_id)
                    executor_dict = prof.to_dict() if prof else {}
                    effective_target_root = self._effective_cleanup_root(executor_dict)
                    self._terminal_cleanup.run(pkt, attempt=rn, project_root=effective_target_root)
            except Exception:
                pass
        return er

    async def _call_executor(self, packet_path: Path, packet_contract, attempt: int,
                             base_ref: str, base_sha: str, executor: dict, evidence_dir: Path | None = None):
        _preflight_result = None
        from grace_control.agent.backend import ExecutionRequest
        from grace_control.services.git_service import GitService
        pid = packet_path.parent.name
        eff = packet_contract.allowed_write_scope; slug = _attempt_slug(pid, attempt)
        branch = _attempt_branch(pid, attempt)

        from grace_control.config.settings import settings as _s
        workspace_mode = executor.get("workspace_mode") or _s.workspace_mode or "full_git_worktree"
        is_minimal = executor.get("minimal_repo", False)
        # TZ §6.3: auto-upgrade scoped_copy to full_git_worktree if verification
        # contains commands that need broader repo context (pytest, tsc, etc.).
        _workspace_evidence: dict = {}
        if workspace_mode == "scoped_copy":
            try:
                _verification = _flatten_verification_for_safety(packet_contract)
            except Exception:
                _verification = []
            if _verification_unsafe_for_scoped(_verification, eff or []):
                if executor.get("workspace_scope_safety") == "unsafe_allowed_for_fixture":
                    _log.warn("workspace_scope_unsafe",
                              packet_id=pid, reason="verification_requires_repo_context")
                else:
                    _log.warn("workspace_mode_auto_upgraded",
                              packet_id=pid,
                              from_mode="scoped_copy",
                              to_mode="full_git_worktree",
                              reason="verification_requires_repo_context")
                    workspace_mode = "full_git_worktree"
                    is_minimal = False
                    _workspace_evidence = {
                        "workspace_mode": "full_git_worktree",
                        "reason": "verification_requires_repo_context",
                    }
        if is_minimal:
            workspace_mode = "scoped_copy"

        target_root = Path(_s.target_repo_root or self.project_root)
        wt_root = Path(_s.worktree_root or self.worktree_root)
        wt_path = wt_root / slug

        # Fail if worktree path is inside GRACE repo for real-project mode
        if workspace_mode == "target_repo_worktree":
            try:
                wt_path.resolve().relative_to(self.project_root.resolve())
                import os
                if os.environ.get("GRACE_ALLOW_WORKTREE_INSIDE_GRACE") != "1":
                    error_msg = f"worktree_root is inside GRACE project root: {wt_path}. Set GRACE_ALLOW_WORKTREE_INSIDE_GRACE=1 to override."
                    _log.warn("worktree_inside_grace_repo_failed", error=error_msg)
                    from grace_control.agent.backend import ExecutionResult as _ER
                    return _ER(
                        accepted=False,
                        domain_status="failed",
                        worktree_path=wt_path,
                        branch_name=branch,
                        commit_sha="",
                        stdout="",
                        stderr=error_msg,
                        duration_ms=0,
                        errors=[error_msg],
                    )
            except ValueError:
                pass

        git = GitService()

        if workspace_mode == "scoped_copy":
            from grace_control.services.agent_workspace_builder import AgentWorkspaceBuilder
            builder = AgentWorkspaceBuilder(target_root=target_root)
            ws = builder.build_scoped_copy(
                scope_paths=list(eff or []),
                workspace_root=wt_root,
                slug=slug,
                config_allowlist=["pyproject.toml"],
            )
            wt_path = ws.workspace_path
            base_sha = ws.base_sha
            branch = f"minimal-{slug}"
            _workspace_result = ws
            add_result = type("Result", (), {"success": True, "stderr": ""})()
        elif workspace_mode == "target_repo_worktree":
            # Preflight checks
            preflight = git.run_preflight(
                target_root,
                require_clean=_s.require_clean_target_repo,
                require_sync=_s.require_remote_sync,
                base_branch=base_ref,
                remote=_s.git_remote,
                branch=branch,
                worktree_path=wt_path,
            )
            _preflight_result = preflight
            if not preflight.success:
                _log.warn("target_repo_preflight_failed", error=preflight.error)
                from grace_control.agent.backend import ExecutionResult as _ER
                er = _ER(
                    accepted=False,
                    domain_status="failed",
                    worktree_path=wt_path,
                    branch_name=branch,
                    commit_sha="",
                    stdout="",
                    stderr=preflight.error,
                    duration_ms=0,
                    errors=[preflight.error],
                )
                er.evidence["target_repo_preflight"] = preflight.to_dict()
                return er

            # Clean up target repo worktree/branch
            self._worktree_cleanup.cleanup_attempt(
                target_root, slug, worktree_root=wt_root)

            # 2.3: if the branch still exists after cleanup, force-delete it in target repo
            branch_check = git._run(["branch", "--list", branch], target_root)
            if branch_check.stdout.strip():
                git._run(["branch", "-D", branch], target_root)
                _log.info("stale_branch_deleted", branch=branch, packet_id=pid)

            from grace_control.services.agent_workspace_builder import AgentWorkspaceBuilder
            builder = AgentWorkspaceBuilder(target_root=target_root)
            ws = builder.build_target_repo_worktree(
                workspace_root=wt_root,
                slug=slug,
                branch=branch,
                base_ref=base_ref,
            )
            wt_path = ws.workspace_path
            base_sha = ws.base_sha
            _workspace_result = ws
            add_result = type("Result", (), {"success": True, "stderr": ""})()
        else:
            _workspace_result = None
            # Clean up GRACE repo worktree/branch
            self._worktree_cleanup.cleanup_attempt(
                self.project_root, slug, worktree_root=self.worktree_root)
            # 2.3: if the branch still exists after cleanup, force-delete it
            branch_check = git._run(["branch", "--list", branch], self.project_root)
            if branch_check.stdout.strip():
                git._run(["branch", "-D", branch], self.project_root)
                _log.info("stale_branch_deleted", branch=branch, packet_id=pid)
            add_result = git.worktree_add(self.project_root, wt_path, branch, base_ref=base_ref)

        # 2.1: FAIL FAST — if worktree_add failed for any reason other than
        # "already exists" (which means we reuse an existing one), stop here.
        # Do NOT let the agent run in an empty/wrong directory.
        if not add_result.success and "already exists" not in add_result.stderr:
            _log.warn(
                "worktree_add_failed",
                packet_id=pid,
                worktree=str(wt_path),
                branch=branch,
                stderr=add_result.stderr[:400],
            )
            from grace_control.agent.backend import ExecutionResult as _ER
            return _ER(
                accepted=False,
                domain_status="failed",
                worktree_path=wt_path,
                branch_name=branch,
                commit_sha="",
                stdout="",
                stderr=add_result.stderr[:400],
                duration_ms=0,
                errors=[f"worktree_add_failed: {add_result.stderr[:200]}"],
            )

        # 1.2: Pre-flight — verify the worktree actually exists and is a
        # real git worktree before handing it to the agent.
        if not wt_path.exists():
            _log.warn(
                "worktree_missing_after_add",
                packet_id=pid,
                worktree=str(wt_path),
            )
            from grace_control.agent.backend import ExecutionResult as _ER
            return _ER(
                accepted=False,
                domain_status="failed",
                worktree_path=wt_path,
                branch_name=branch,
                commit_sha="",
                stdout="",
                stderr=f"worktree path does not exist after git worktree add: {wt_path}",
                duration_ms=0,
                errors=[f"worktree path does not exist after git worktree add: {wt_path}"],
            )

        from grace_control.config.settings import settings

        # TZ_SESSION_RESUME.md Phase 3: resolve resume session before run
        resume_session_id: str | None = None
        prev_internal_id: str | None = None
        fork = False
        resume_mode = executor.get("resume_mode", "never")
        role = executor.get("role", "coder")
        executor_id = executor.get("executor_id", "")

        # TZ: attempt 7+ with NEW_ARCHITECT → fresh session (no resume).
        # Also initial architect (attempt 0) has no session to resume.
        force_fresh = (role == "architect" and attempt >= 7)

        if not force_fresh and resume_mode in ("always", "on_retry", "on_fork") and attempt > 0:
            with get_db() as db:
                if resume_mode == "on_retry":
                    prev = self._session_store.find_latest(
                        db, pid, role, executor_id=executor_id)
                    if prev:
                        resume_session_id = prev.external_id
                        prev_internal_id = prev.id
                elif resume_mode == "on_fork":
                    prev = self._session_store.find_for_fork(db, pid, role)
                    if prev:
                        resume_session_id = prev.external_id
                        prev_internal_id = prev.id
                        fork = True
                elif resume_mode == "always":
                    prev = self._session_store.find_latest(db, pid, role)
                    if prev:
                        resume_session_id = prev.external_id
                        prev_internal_id = prev.id
                _log.info("session_resolved",
                          packet_id=pid, attempt=attempt, role=role,
                          resume_session_id=resume_session_id, fork=fork)

        req = ExecutionRequest(packet_id=pid,
            spec={"attempt_count":attempt,"base_ref":base_ref,"allowed_write_scope":eff or [],"frozen_scope":packet_contract.frozen_scope or []},
            worktree_path=wt_path, branch_name=branch,
            scope_paths=list(eff or []), executor=executor, timeout_s=settings.agent_timeout_seconds,
            session_dir=self.state_root, evidence_dir=evidence_dir,
            resume_session_id=resume_session_id, fork_session=fork)
        result = await self._backend.run(req)

        # TZ_SESSION_RESUME.md Phase 3: save session after run
        if result.evidence.get("session_id"):
            with get_db() as db:
                self._session_store.save(
                    db,
                    packet_id=pid,
                    run_id=f"{pid}-R{attempt:02d}",
                    role=role,
                    executor_id=executor_id,
                    backend=executor.get("backend", "cli"),
                    attempt_number=attempt,
                    external_id=result.evidence.get("session_id"),
                    parent_session_id=prev_internal_id if fork else None,
                    status="completed" if result.accepted else "failed",
                )
        # Persist session_resume audit info in evidence so it appears
        # in PacketRun.result_json for trace and recovery audit trail.
        if resume_session_id:
            result.evidence["session_resume"] = {
                "resume_session_id": resume_session_id,
                "fork": fork,
                "prev_internal_id": prev_internal_id,
            }
        # Persist workspace report in evidence
        if _workspace_evidence:
            result.evidence["workspace"] = _workspace_evidence
        elif _workspace_result is not None:
            result.evidence["workspace"] = _workspace_result.to_dict()
        elif workspace_mode == "full_git_worktree":
            result.evidence["workspace"] = {"workspace_mode": "full_git_worktree"}

        # TZ §6.6: persist diagnostics contract in evidence for every
        # terminal run. Use fields already on the ExecutionResult.
        try:
            _stdout = getattr(result, "stdout", "") or ""
            _stderr = getattr(result, "stderr", "") or ""
            _stage = "agent_run"
            if not result.accepted:
                # Best-effort stage detection.
                if "agent_commit_failed" in _stderr or "cannot commit" in _stderr:
                    _stage = "agent_commit"
                elif "worktree" in _stderr.lower() and "missing" in _stderr.lower():
                    _stage = "worktree_inspection"
            result.evidence["stdout_tail"] = _redact_secrets(_tail(_stdout, _STDOUT_TAIL_LIMIT))
            result.evidence["stderr_tail"] = _redact_secrets(_tail(_stderr, _STDERR_TAIL_LIMIT))
            result.evidence["exit_code"] = getattr(result, "exit_code", None)
            result.evidence["duration_ms"] = getattr(result, "duration_ms", None)
            result.evidence["failure_stage"] = _stage
            result.evidence["failure_class"] = classify_failure(
                _stdout, _stderr, result.evidence["exit_code"], _stage)
            if result.evidence["failure_class"] != "unknown":
                _log.warn(
                    "failure_classified",
                    packet_id=pid,
                    failure_class=result.evidence["failure_class"],
                    failure_stage=_stage,
                    exit_code=result.evidence["exit_code"],
                )
            else:
                _log.debug("failure_classified",
                           packet_id=pid,
                           failure_class="unknown",
                           failure_stage=_stage)
        except Exception as _e:
            _log.warn("diagnostics_persist_failed", packet_id=pid, reason=str(_e))

        # TZ §6.6: snapshot top-level diagnostics for the upcoming
        # update_run_result call. Anything in result.evidence under one of
        # _DIAGNOSTICS_KEYS is lifted to result_json["diagnostics"] (see
        # evidence_service.update_run_result). This makes UI / admin /
        # trace read the same shape regardless of which code path called
        # the persistence layer.
        try:
            self._last_diagnostics = _extract_diagnostics(result)
        except Exception:
            self._last_diagnostics = {}

        # TZ §6.4: persist session_resume evidence (whether injected or skipped).
        try:
            _last_session_resume = getattr(self, "_last_session_resume", None)
            if _last_session_resume:
                result.evidence["session_resume"] = _last_session_resume
        except Exception:
            pass

        _log.info("run_diagnostics_persisted",
                  packet_id=pid,
                  accepted=result.accepted,
                  failure_class=result.evidence.get("failure_class"),
                  failure_stage=result.evidence.get("failure_stage"),
                  exit_code=result.evidence.get("exit_code"),
                  has_stderr_tail=bool(result.evidence.get("stderr_tail")),
                  has_stdout_tail=bool(result.evidence.get("stdout_tail")))
        # Persist preflight report if it exists
        if _preflight_result is not None:
            result.evidence["target_repo_preflight"] = _preflight_result.to_dict()
        return result

    def _build_dev_replay_metadata(
        self, packet_id: str, run_id: str, run_number: int,
        wt_path: Path | None, branch_name: str | None,
        base_ref: str | None, base_sha: str | None,
        agent_commit_sha: str | None, changed_files: list[str] | None,
        run_dir: Path | None, ar_path: str | None,
        acceptance_report, evr, rvr,
    ) -> dict:
        failed_stage = None
        if acceptance_report and not acceptance_report.is_accepted:
            for stage in acceptance_report.stages:
                if stage.status.value == "failed":
                    failed_stage = stage.name.value
                    break
            if not failed_stage:
                failed_stage = "ACCEPTANCE"
        elif evr and hasattr(evr, "verdict") and evr.verdict in ("REWORK_TO_CODER", "RETURN_TO_ARCHITECT", "rework_required"):
            failed_stage = "EVIDENCE_VERIFIER"
        elif rvr and hasattr(rvr, "verdict") and rvr.verdict in ("REWORK_TO_CODER", "RETURN_TO_ARCHITECT", "rework_required"):
            failed_stage = "REVIEWER"

        metadata = {
            "version": 1,
            "replayable": True,
            "packet_id": packet_id,
            "run_id": run_id,
            "run_number": run_number,
            "worktree_path": str(wt_path) if wt_path else "",
            "branch_name": branch_name or "",
            "base_ref": base_ref or "",
            "base_sha": base_sha or "",
            "agent_commit_sha": agent_commit_sha or "",
            "changed_files": list(changed_files) if changed_files else [],
            "run_dir": str(run_dir) if run_dir else "",
            "acceptance_report_path": ar_path or "",
            "evidence_path": str(run_dir) if run_dir else "",
            "failed_stage": failed_stage,
            "created_at": datetime.now(UTC).isoformat() + "Z",
        }
        return metadata

    def _write_agent_patch(self, wt_path: Path | None, run_dir: Path | None, base_sha: str | None) -> None:
        if not wt_path or not run_dir or not base_sha:
            return
        if not wt_path.exists() or not run_dir.exists():
            return
        try:
            import subprocess
            res = subprocess.run(
                ["git", "diff", base_sha],
                cwd=str(wt_path),
                capture_output=True,
                text=True,
                timeout=10,
            )
            if res.returncode == 0:
                patch_file = Path(run_dir) / "agent.patch"
                patch_file.write_text(res.stdout)
                _log.info("agent_patch_written", run_dir=str(run_dir))
        except Exception as e:
            _log.warn("agent_patch_write_failed", error=str(e)[:200])
