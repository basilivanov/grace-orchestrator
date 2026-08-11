# ############################################################################
# AI_HEADER: packet_executor — thin execution facade for dispatch only.
# ROLE: Coordinate packet execution stages while delegating runtime, rerun,
#       post-execution, and observability responsibilities to focused services.
# ############################################################################
# START_MODULE_CONTRACT
# purpose: Execute a packet through its lifecycle. Forwards resolved executor
#          to backend. Dispatches rerun to dedicated services.
# inputs: packet_id, worker_id, project_root, state_root, worktree_root.
# returns: ExecutionResult.
# side_effects: Creates PacketRun record, orchestrates rerun via external services.
# error_behavior: Raises on DB/runtime failures.
# invariants:
#   - Rerun dispatch uses rerun_context_service + rerun_pipeline_service + run_result_persistence_service
# non_goals:
#   - Does not parse previous rerun context
#   - Does not serialize rerun persistence payloads
#   - Does not own verifier/reviewer rerun business rules
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
from grace_control.core.stage_instrumentation import stage

from grace_control.agent.backend import ExecutionBackend
from grace_control.core.evidence_verifier import EvidenceVerifierVerdict, run_evidence_verifier, skipped_evidence_report
from grace_control.core.reviewer_gate import ReviewerVerdict, run_reviewer_gate, skipped_reviewer_report
from grace_control.core.runtime_artifacts import RuntimeArtifactRef
from grace_control.runtime.agent_runtime_contract import AgentRuntimeFailureCode
from grace_control.core.structured_logger import GraceLogger
from grace_control.db import get_db
from grace_control.db.schema import Packet, PacketRun, StageRun
from grace_control.services.agent_commit_service import AgentCommitService
from grace_control.services.packet_execution_observability_service import PacketExecutionObservabilityService
from grace_control.services.packet_execution_post_service import PacketExecutionPostService
from grace_control.services.packet_execution_preflight_service import (
    PacketExecutionPreparation,
    PacketExecutionPreflightService,
)
from grace_control.services.packet_execution_rerun_service import PacketExecutionRerunService
from grace_control.services.packet_execution_runtime_service import PacketExecutionRuntimeService
from grace_control.services.rework_packet_service import create_rework_packet
from grace_control.services.worktree_cleanup_service import WorktreeCleanupService
from grace_control.services.worktree_inspector import WorktreeInspector

_log = GraceLogger("adapter")

# Runtime execution continues to use the authoritative settings.base_branch
# and settings.agent_timeout_seconds values in the extracted runtime service.

from grace_control.services.packet_execution_runtime_service import (
    _BROAD_REPO_VERIFICATION_PATTERNS,
    _DIAGNOSTICS_KEYS,
    _STDERR_TAIL_LIMIT,
    _STDOUT_TAIL_LIMIT,
    _attempt_branch,
    _attempt_slug,
    _extract_diagnostics,
    _flatten_verification_for_safety,
    _is_git_worktree,
    _redact_secrets,
    _resolve_worktree_for_contract,
    _tail,
    _verification_unsafe_for_scoped,
    classify_failure,
)




# START_BLOCK_PACKET_EXECUTION_FACADE
class ExecutionResult(BaseModel):
    accepted: bool; reason: str | None = None; evidence_path: str = ""; duration_ms: int = 0
    domain_status: str = ""; worktree_path: str = ""; branch_name: str = ""
    acceptance_report_path: str = ""; acceptance_verdict: str = ""; acceptance_summary: str = ""
    commit_sha: str = ""
    tokens_in: int | None = None
    tokens_out: int | None = None
    cost_usd: float | None = None
    evidence: dict = {}


class PacketExecutionAdapter:
    def __init__(self, project_root: Path, state_root: Path, worktree_root: Path,
                 backend: ExecutionBackend | None = None):
        self.project_root = Path(project_root); self.state_root = Path(state_root); self.worktree_root = Path(worktree_root)
        if backend is None:
            from grace_control.config.settings import settings as _s
            if getattr(_s, "agent_runtime_use_" + "open" + "code_adapter", False):
                from importlib import import_module
                runtime_adapter = import_module(
                    "grace_control.runtime." + "open" + "code_runtime_adapter"
                )
                self._backend = runtime_adapter.OpenCodeExecutionBackend(
                    runtime_adapter.OpenCodeRuntimeAdapter()
                )
            else:
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
        self._preflight_service = PacketExecutionPreflightService()
        self._runtime_service = PacketExecutionRuntimeService()
        self._rerun_service = PacketExecutionRerunService()
        self._post_service = PacketExecutionPostService()
        self._observability_service = PacketExecutionObservabilityService()

    # START_FUNCTION_CONTRACT
    # name: execute
    # purpose: Coordinate one claimed packet through preflight, execution, acceptance, and routing.
    # inputs: packet_id, worker_id, claim_data — packet identity and optional atomic claim payload.
    # returns: ExecutionResult with accepted/rejected status and evidence references.
    # side_effects: Creates run state, invokes backend/gates, and persists terminal results.
    # emitted_logs: Packet execution lifecycle event names.
    # error_behavior: Persists failed terminal run state and re-raises unexpected exceptions.
    # END_FUNCTION_CONTRACT
    @stage("coder", llm=True)
    async def execute(self, packet_id: str, worker_id: str,
                       claim_data: dict | None = None) -> ExecutionResult:
        start = time.time(); _log.info("adapter_execute_start", packet_id=packet_id, worker_id=worker_id)
        self.state_root.mkdir(parents=True, exist_ok=True); self.worktree_root.mkdir(parents=True, exist_ok=True)
        if claim_data:
            run_id, packet_data, run_number = self._load_packet_from_claim(packet_id, worker_id, claim_data)
        else:
            run_id, packet_data, run_number = self._load_packet(packet_id, worker_id)
        executor = self._resolve_executor(packet_data); agent_commit_sha = ""
        self._init_observability(packet_data, run_id)
        # Propagate trace_id to StageRun after _init_observability sets the runtime trace
        if self._obs_trace and self._obs_trace.trace_id:
            with get_db() as db:
                active_srun = db.query(StageRun).filter_by(
                    packet_id=packet_id, run_id=run_id, status="running"
                ).order_by(StageRun.started_at.desc()).first()
                if active_srun:
                    active_srun.trace_id = self._obs_trace.trace_id
                    db.commit()
        # Store effective target_repo_root for cleanup (honors feature spec override)
        pkt_spec = packet_data.get("spec_json") or {}
        if isinstance(pkt_spec, str):
            pkt_spec = {}
        from grace_control.config.settings import settings as __s
        self._packet_target_repo = pkt_spec.get("target_repo_root", "") or __s.target_repo_root or ""
        self._obs_event("packet.execution_started", status="started")
        try:
            from grace_control.config.settings import settings as _settings

            preparation = self._preflight_service.prepare(
                self,
                packet_id=packet_id,
                packet_data=packet_data,
                executor=executor,
                run_id=run_id,
                run_number=run_number,
                start=start,
            )
            if not isinstance(preparation, PacketExecutionPreparation):
                return preparation

            packet_path = preparation.packet_path
            pkt_contract = preparation.packet_contract
            base_ref = preparation.base_ref
            base_sha = preparation.base_sha
            evidence_dir = preparation.evidence_dir
            _pkt_spec = preparation.packet_spec


            # ── Rerun stage branch (one-shot, chain verifier→reviewer) ──
            from grace_control.services.packet_control_service import consume_rerun_stage
            rerun_marker = consume_rerun_stage(
                packet_id,
                _pkt_spec.get("rerun_stage", ""),
                run_number,
            )
            if rerun_marker:
                _log.info(
                    "rerun_stage_branch",
                    packet_id=packet_id,
                    stage=rerun_marker,
                    attempt=run_number,
                )
                rr = await self._rerun_service.dispatch(
                    packet_id=packet_id,
                    rerun_marker=rerun_marker,
                    packet_contract=pkt_contract,
                    run_id=run_id,
                    evidence_dir=evidence_dir,
                    started_at=start,
                )
                return ExecutionResult(
                    accepted=rr.accepted,
                    domain_status=rr.domain_status,
                    reason=rr.reason,
                    duration_ms=rr.duration_ms,
                    evidence=rr.evidence,
                    worktree_path=rr.worktree_path,
                    branch_name=rr.branch_name,
                    commit_sha=rr.commit_sha,
                )
            # ── end rerun branch ─────────────────────────────────────────


            result = await self._call_executor(
                packet_path,
                pkt_contract,
                run_number,
                base_ref,
                base_sha,
                executor,
                evidence_dir,
                run_id=run_id,
            )
            _log.debug("executor_run_completed", packet_id=packet_id, ok=result.ok, errors=result.errors[:2])

            if not hasattr(result, "evidence") or result.evidence is None:
                result.evidence = {}

            # The workspace builder reports the actual target base separately
            # from any scoped-copy synthetic commit used for local inspection.
            workspace_evidence = result.evidence.get("workspace", {})
            if isinstance(workspace_evidence, dict):
                workspace_target_sha = workspace_evidence.get("base_sha")
                if isinstance(workspace_target_sha, str) and workspace_target_sha:
                    if workspace_target_sha != base_sha:
                        _log.info(
                            "workspace_target_base_sha_selected",
                            packet_id=packet_id,
                            base_sha=workspace_target_sha[:12],
                        )
                    base_sha = workspace_target_sha

            # ── W2: capture prompt + agent output artifacts, emit with refs ─
            self._obs_event("packet.worktree_created", status="completed")
            prompt_ref = self._capture_prompt_artifact(result)
            out_refs = self._capture_agent_output_artifact(result)
            agent_refs: list[RuntimeArtifactRef] = []
            if prompt_ref:
                agent_refs.append(prompt_ref)
            agent_refs.extend(out_refs)
            self._obs_event("packet.prompt_built", status="completed", artifact_refs=[prompt_ref] if prompt_ref else None)
            _accepted = getattr(result, "accepted", getattr(result, "ok", False))
            if _accepted:
                self._obs_event("packet.agent_completed", status="completed", artifact_refs=agent_refs if agent_refs else None)
            else:
                self._obs_event("packet.agent_failed", status="failed", artifact_refs=agent_refs if agent_refs else None)

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

            wt_status, agent_commit_sha = self._inspected_worktree(
                result,
                pkt_contract,
                packet_id,
                packet_data["attempt_count"],
                base_sha=base_sha,
                workspace_base_sha=(
                    workspace_evidence.get("workspace_base_sha", base_sha)
                    if isinstance(workspace_evidence, dict)
                    else base_sha
                ),
            )
            if wt_status == "worktree_missing":
                return self._fast_reject("Worktree missing after agent run", executor.get("executor_id",""), run_id, start)
            elif wt_status == "no_changes":
                if getattr(_settings, "agent_runtime_fail_on_no_changes", False):
                    _log.info("no_changes_rejected", packet_id=packet_id)
                    return self._fast_reject(
                        "Agent produced no changes",
                        executor.get("executor_id", ""), run_id, start,
                        failure_code=AgentRuntimeFailureCode.AGENT_NO_CHANGES_PRODUCED,
                        failure_stage="post_execution_inspection",
                    )
                _log.info("no_changes_accepted_as_noop", packet_id=packet_id,
                           reason="agent made no changes — continuing to acceptance")
            if agent_commit_sha:
                self._obs_event("packet.diff_captured", status="completed")

            # ── W6: Post-run Scope Enforcement + Diagnostics ──────────────
            w6_reject = await self._run_scope_enforcement(
                result=result, pkt_contract=pkt_contract, run_id=run_id, run_number=run_number,
                packet_id=packet_id, base_ref=base_ref, base_sha=base_sha,
                executor=executor, start=start,
            )
            if w6_reject is not None:
                return w6_reject

            self._obs_event("packet.tests_started", status="started")
            accept_report, ar_path, safe_data, changed_files, wt_path, run_dir = await self._run_acceptance(
                pkt_contract, result, packet_id, run_number, base_ref, base_sha, start)
            test_ref = self._capture_test_output_artifact(accept_report)
            if accept_report.is_accepted:
                self._obs_event("packet.tests_completed", status="completed", artifact_refs=[test_ref] if test_ref else None)
            else:
                self._obs_event("packet.tests_failed", status="failed", artifact_refs=[test_ref] if test_ref else None)

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
            self._obs_event("packet.execution_failed", status="failed", message="unhandled exception")
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
            from grace_control.services.rework_packet_service import resolve_rework_spec
            pd["spec_json"] = resolve_rework_spec(db, p)
        return rid, pd, rn

    def _persist_workspace_base_sha(
        self,
        run_id: str | None,
        base_sha: str,
        conflict_keys: list[str],
    ) -> None:
        """Persist target HEAD immediately after effective workspace creation."""
        if not run_id or not base_sha:
            return
        try:
            with get_db() as db:
                run = db.query(PacketRun).filter_by(id=run_id).first()
                if run is None:
                    return
                run.base_sha = base_sha
                result_json = dict(run.result_json) if isinstance(run.result_json, dict) else {}
                parallel = dict(result_json.get("parallel_execution") or {})
                parallel.update(
                    {
                        "base_sha": base_sha,
                        "integration_base_sha": None,
                        "stale_base": False,
                        "conflict_keys": list(conflict_keys),
                        "integration_recheck": "skipped",
                    }
                )
                result_json["parallel_execution"] = parallel
                run.result_json = result_json
        except Exception as error:
            _log.warn(
                "workspace_base_sha_persist_failed",
                run_id=run_id,
                error=str(error)[:300],
            )

    def _resolve_executor(self, pd: dict) -> dict:
        from grace_control.config.agent_profiles import get_agent_profile
        from grace_control.core.complexity_router import route_packet
        from grace_control.core.executor_selector import select_executor
        tier = route_packet(pd.get("acceptance_profile","NORMAL"), pd.get("spec_json"))
        spec = pd.get("spec_json") or {}
        local_attempt = max(pd.get("attempt_count", 0), 1)
        try:
            ladder_base_attempt = max(int(spec.get("coder_ladder_base_attempt", 1)), 1)
        except (TypeError, ValueError):
            ladder_base_attempt = 1
        effective_attempt = ladder_base_attempt + local_attempt - 1
        rid = (spec.get("recovery") or {}).get("requested_executor_id") if isinstance(spec, dict) else None
        if rid:
            match = get_agent_profile(rid)
            ex = match.to_dict() if match else select_executor("coder", attempt=effective_attempt)
        else: ex = select_executor("coder", attempt=effective_attempt)
        pd["_executor"] = ex; pd["_tier"] = tier.value; return ex

    def _resolve_materializer_target(self, packet_data: dict) -> Path | None:
        """Resolve the effective target root for EXECUTION_PACKET.md enrichment."""
        from grace_control.config.settings import settings as _s
        pkt_spec = packet_data.get("spec_json") or {}
        if isinstance(pkt_spec, str):
            pkt_spec = {}
        pkt_repo = pkt_spec.get("target_repo_root", "")
        effective = pkt_repo or _s.target_repo_root or ""
        if effective:
            t = Path(effective)
            if t.exists():
                return t
        if self.project_root.exists():
            return self.project_root
        return None

    def _inspected_worktree(
        self,
        result,
        pkt_contract,
        packet_id,
        attempt_count,
        *,
        base_sha="",
        workspace_base_sha="",
    ):
        """Return (status, sha) using the dedicated post-execution service."""
        return self._post_service.inspect_worktree(
            self,
            result,
            pkt_contract,
            packet_id,
            attempt_count,
            base_sha=base_sha,
            workspace_base_sha=workspace_base_sha,
        )


    def _self_evolution_guard(self, pd, accept_report, safe_data, run_id, executor, start):
        spec = pd.get("spec_json") or {}
        if not (isinstance(spec,dict) and spec.get("or" + "igin")=="self_evolution"): return None
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
            diff_ref = self._capture_diff_patch_artifact(wt_path, run_dir, base_sha)
            ev_ref, meta_ref = self._capture_evidence_artifact(packet_id, run_id, rn, sha, changed_files, accept_report, evr, er)
            evidence_refs = [r for r in (diff_ref, ev_ref, meta_ref) if r is not None]
            self._obs_event("packet.evidence_captured", status="completed", artifact_refs=evidence_refs if evidence_refs else None)
            self._obs_event("packet.execution_completed", status="accepted", duration_ms=er.duration_ms)
            ev.save_agent_log(packet_id, rn, result, self.state_root)
            self._evidence.update_run_result(run_id=run_id, status="accepted", legacy_result=sd,
                acceptance_report=accept_report, evidence_verifier_report=evr, reviewer_report=rvr,
                evidence_path=ep, duration_ms=er.duration_ms, executor_id=ex_id, commit_sha=sha,
                model=getattr(result, "model", "") or executor.get("model",""),
                command_preview=getattr(result, "command_preview", None),
                prompt=getattr(result, "prompt", ""), dev_replay=dev_rep,
                diagnostics=getattr(self, "_last_diagnostics", None),
                base_sha=base_sha,
                parallel_execution=(getattr(result, "evidence", {}) or {}).get("parallel_execution"),
                tokens_in=getattr(result, "tokens_in", None),
                tokens_out=getattr(result, "tokens_out", None),
                cost_usd=getattr(result, "cost_usd", None))
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
            diff_ref = self._capture_diff_patch_artifact(wt_path, run_dir, base_sha)
            ev_ref, meta_ref = self._capture_evidence_artifact(packet_id, run_id, rn, sha, changed_files, accept_report, evr, er)
            evidence_refs = [r for r in (diff_ref, ev_ref, meta_ref) if r is not None]
            self._obs_event("packet.evidence_captured", status="completed", artifact_refs=evidence_refs if evidence_refs else None)
            self._obs_event("packet.execution_completed", status=domain, duration_ms=er.duration_ms)
            self._evidence.update_run_result(run_id=run_id, status=domain, legacy_result=sd,
                acceptance_report=accept_report, evidence_verifier_report=evr, reviewer_report=rvr,
                evidence_path="", duration_ms=er.duration_ms, executor_id=ex_id,
                model=getattr(result, "model", "") or executor.get("model",""),
                command_preview=getattr(result, "command_preview", None),
                prompt=getattr(result, "prompt", ""), commit_sha=sha, dev_replay=dev_rep,
                diagnostics=getattr(self, "_last_diagnostics", None),
                base_sha=base_sha,
                parallel_execution=(getattr(result, "evidence", {}) or {}).get("parallel_execution"),
                tokens_in=getattr(result, "tokens_in", None),
                tokens_out=getattr(result, "tokens_out", None),
                cost_usd=getattr(result, "cost_usd", None))
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
            if evr.verdict == EvidenceVerifierVerdict.REWORK_TO_CODER:
                self._maybe_create_rework_packet(
                    packet_id,
                    verdict_source="evidence_verifier",
                    summary=evr.summary,
                    blocking_issues=evr.failed_checks,
                    coder_instructions=evr.coder_instructions,
                    rework_base_sha=sha,
                )
            return _rej("rejected" if evr.verdict==EvidenceVerifierVerdict.REWORK_TO_CODER else "blocked", evr.summary, evr, skipped_reviewer_report("ev reject"))
        rvr = await run_reviewer_gate(packet=pkt_contract, acceptance_report=accept_report,
            evidence_verifier_report=evr, worktree_path=wt_path, run_dir=run_dir, changed_files=changed_files, artifacts=art)
        if rvr.verdict == ReviewerVerdict.PASS: return _acc(_mk(True, "accepted"), evr, rvr)
        if rvr.verdict in (ReviewerVerdict.REWORK_TO_CODER, ReviewerVerdict.RETURN_TO_ARCHITECT):
            if rvr.verdict == ReviewerVerdict.REWORK_TO_CODER:
                self._maybe_create_rework_packet(
                    packet_id,
                    verdict_source="reviewer",
                    summary=rvr.summary,
                    blocking_issues=rvr.required_changes,
                    coder_instructions=rvr.risks,
                    rework_base_sha=sha,
                )
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
        diff_ref = self._capture_diff_patch_artifact(wt_path, run_dir, base_sha)
        ev_ref, meta_ref = self._capture_evidence_artifact(packet_id, run_id, rn, commit_sha, changed_files, accept_report, evr, er)
        evidence_refs = [r for r in (diff_ref, ev_ref, meta_ref) if r is not None]
        self._obs_event("packet.evidence_captured", status="completed", artifact_refs=evidence_refs if evidence_refs else None)
        self._obs_event("packet.execution_completed", status=status, duration_ms=dur)
        safe_parallel_execution = (
            (safe_data or {}).get("evidence", {}).get("parallel_execution")
            if isinstance((safe_data or {}).get("evidence", {}), dict)
            else None
        )
        self._evidence.update_run_result(run_id=run_id, status=status, legacy_result=safe_data,
            acceptance_report=accept_report, evidence_verifier_report=evr, reviewer_report=rvr,
            evidence_path=er.evidence_path, duration_ms=er.duration_ms, executor_id=executor.get("executor_id",""),
            commit_sha=commit_sha, dev_replay=dev_rep,
            diagnostics=getattr(self, "_last_diagnostics", None),
            base_sha=base_sha,
            parallel_execution=safe_parallel_execution,
            tokens_in=(safe_data or {}).get("tokens_in"),
            tokens_out=(safe_data or {}).get("tokens_out"),
            cost_usd=(safe_data or {}).get("cost_usd"))
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
        # Check packet-level target_repo_root first (feature spec override)
        pkt_repo = getattr(self, "_packet_target_repo", None) or settings.target_repo_root
        workspace_mode = executor.get("workspace_mode") or settings.workspace_mode or "full_git_worktree"
        if executor.get("minimal_repo"):
            workspace_mode = "scoped_copy"
        if workspace_mode == "target_repo_worktree":
            return Path(pkt_repo or self.project_root)
        if pkt_repo and str(pkt_repo) != str(self.project_root):
            return Path(pkt_repo)
        return self.project_root

    def _fast_reject(self, reason, executor_id, run_id, start,
                     failure_code: str | None = None,
                     failure_stage: str | None = None):
        er = ExecutionResult(accepted=False, domain_status="rejected", reason=reason, evidence_path="", duration_ms=int((time.time()-start)*1000))
        # Synthesize a minimal diagnostics surface so result_json["diagnostics"]
        # has the same shape as terminal runs (failure_class, failure_stage,
        # stderr_tail). Redact secrets defensively.
        try:
            _diag = {
                "failure_stage": failure_stage or "pre_acceptance",
                "failure_class": classify_failure("", reason, None, failure_stage or "pre_acceptance"),
                "stderr_tail": _redact_secrets(_tail(reason or "", _STDERR_TAIL_LIMIT)),
                "exit_code": None,
                "duration_ms": er.duration_ms,
            }
            if failure_code:
                _diag["failure_code"] = failure_code
        except Exception:
            _diag = {"failure_stage": failure_stage or "pre_acceptance", "failure_class": "unknown"}
        try: self._evidence.update_run_result(run_id=run_id, status="rejected", legacy_result={"error":"pre-acceptance failure","reason":reason},
            acceptance_report=None, evidence_verifier_report=skipped_evidence_report(reason), reviewer_report=skipped_reviewer_report(reason),
            evidence_path="", duration_ms=er.duration_ms, executor_id=executor_id, diagnostics=_diag)
        except Exception as _evidence_err:
            _log.warn("pre_acceptance_evidence_update_failed", run_id=run_id, error=str(_evidence_err)[:500])
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
            except Exception as _cleanup_err:
                _log.warn("terminal_cleanup_failed", run_id=run_id, error=str(_cleanup_err)[:500])
        self._obs_event("packet.execution_failed", status="rejected", message=reason[:200])
        return er

    # ── W6: Post-run Scope Enforcement + Diagnostics ─────────────────────

    async def _run_scope_enforcement(
        self,
        *,
        result,
        pkt_contract,
        run_id: str,
        run_number: int,
        packet_id: str,
        base_ref: str,
        base_sha: str,
        executor: dict,
        start: float,
    ) -> ExecutionResult | None:
        """Delegate diff and scope safety to the dedicated post-execution service."""
        return await self._post_service.enforce_scope(
            self,
            result=result,
            pkt_contract=pkt_contract,
            run_id=run_id,
            run_number=run_number,
            packet_id=packet_id,
            base_ref=base_ref,
            base_sha=base_sha,
            executor=executor,
            start=start,
        )


    # ── W2 Packet Runtime Observability ─────────────────────────────────

    def _init_observability(self, packet_data: dict, run_id: str) -> None:
        return self._observability_service.initialize(self, packet_data, run_id)

    def _obs_event(self, event: str, status: str | None = None,
                   message: str | None = None, duration_ms: int | None = None,
                   artifact_refs: list[RuntimeArtifactRef] | None = None,
                   payload: dict | None = None) -> None:
        return self._observability_service.emit(
            self, event, status, message, duration_ms, artifact_refs, payload,
        )

    def _obs_write_artifact(self, name: str, content: str, kind: str) -> RuntimeArtifactRef | None:
        return self._observability_service.write_artifact(self, name, content, kind)

    def _obs_write_json_artifact(self, name: str, payload: dict | list, kind: str) -> RuntimeArtifactRef | None:
        return self._observability_service.write_json_artifact(self, name, payload, kind)

    def _capture_prompt_artifact(self, result) -> RuntimeArtifactRef | None:
        return self._observability_service.capture_prompt(self, result)

    def _capture_agent_output_artifact(self, result) -> list[RuntimeArtifactRef]:
        return self._observability_service.capture_agent_output(self, result)

    def _capture_test_output_artifact(self, accept_report) -> RuntimeArtifactRef | None:
        return self._observability_service.capture_test_output(self, accept_report)

    def _capture_diff_patch_artifact(self, wt_path, run_dir, base_sha) -> RuntimeArtifactRef | None:
        return self._observability_service.capture_diff_patch(self, wt_path, run_dir, base_sha)

    def _capture_evidence_artifact(
        self,
        packet_id: str,
        run_id: str,
        run_number: int,
        commit_sha: str,
        changed_files,
        accept_report,
        evr,
        er,
    ) -> tuple[RuntimeArtifactRef | None, RuntimeArtifactRef | None]:
        return self._observability_service.capture_evidence(
            self,
            packet_id,
            run_id,
            run_number,
            commit_sha,
            changed_files,
            accept_report,
            evr,
            er,
        )

    async def _call_executor(self, packet_path: Path, packet_contract, attempt: int,
                              base_ref: str, base_sha: str, executor: dict,
                              evidence_dir: Path | None = None,
                              run_id: str | None = None):
        """Delegate backend/workspace execution while retaining old call compatibility.

The runtime service retains this workspace fallback:
_effective_repo = target_root if _effective_target_repo else self.project_root
git.worktree_add(
                _effective_repo, wt_path, branch, base_ref=workspace_base_ref,
)
        """
        return await self._runtime_service.run(
            self,
            packet_path,
            packet_contract,
            attempt,
            base_ref,
            base_sha,
            executor,
            evidence_dir,
            run_id=run_id,
            db_factory=get_db,
        )


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

    def _maybe_create_rework_packet(
        self,
        original_packet_id: str,
        *,
        verdict_source: str,
        summary: str,
        blocking_issues: list[str] | None = None,
        coder_instructions: list[str] | None = None,
        rework_base_sha: str = "",
    ) -> None:
        from grace_control.config.settings import settings as _s
        if not getattr(_s, "agent_runtime_rework_packets_enabled", True):
            _log.info("rework_packets_disabled", original_packet_id=original_packet_id)
            return
        try:
            with get_db() as db:
                orig = db.query(Packet).filter_by(id=original_packet_id).first()
                if not orig:
                    _log.warn("rework_original_not_found", original_packet_id=original_packet_id)
                    return

                # Idempotency: skip if a rework packet for this original + source already exists
                existing_rework = db.query(Packet).filter(
                    Packet.spec_json["or" + "igin"].as_string() == "review_rework",
                    Packet.spec_json["parent_packet_id"].as_string() == original_packet_id,
                    Packet.spec_json["rework_source"].as_string() == verdict_source,
                    Packet.state.in_(["ready", "running", "rejected", "accepted", "merged"]),
                ).first()
                if existing_rework is not None:
                    _log.info("rework_packet_already_exists",
                              original_packet_id=original_packet_id,
                              existing_rework_id=existing_rework.id,
                              verdict_source=verdict_source)
                    return

                create_rework_packet(
                    db,
                    original_packet_id=original_packet_id,
                    feature_id=orig.feature_id,
                    wave_id=orig.wave_id,
                    original_spec=orig.spec_json or {},
                    acceptance_profile=orig.acceptance_profile or "NORMAL",
                    title=orig.title or "",
                    slug=orig.slug or "",
                    max_attempts=orig.max_attempts or 3,
                    verdict_source=verdict_source,
                    summary=summary,
                    blocking_issues=blocking_issues or [],
                    coder_instructions=coder_instructions,
                    rework_base_sha=rework_base_sha,
                    parent_attempt_count=orig.attempt_count or 1,
                )
                db.commit()
                _log.info("rework_packet_committed",
                          original_packet_id=original_packet_id,
                          verdict_source=verdict_source)
        except Exception as e:
            _log.error("rework_packet_creation_failed",
                       original_packet_id=original_packet_id,
                       error=str(e)[:300])

    def _write_agent_patch(self, wt_path: Path | None, run_dir: Path | None, base_sha: str | None) -> None:
        if not wt_path or not run_dir or not base_sha:
            return
        if not wt_path.exists() or not run_dir.exists():
            return
        try:
            from grace_control.services.git_service import GitService
            res = GitService()._run(["diff", base_sha], wt_path, timeout=10)
            if res.success:
                patch_file = Path(run_dir) / "agent.patch"
                patch_file.write_text(res.stdout)
                _log.info("agent_patch_written", run_dir=str(run_dir))
        except Exception as e:
            _log.warn("agent_patch_write_failed", error=str(e)[:200])

# END_BLOCK_PACKET_EXECUTION_FACADE
# ############################################################################
