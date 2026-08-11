# ############################################################################
# AI_HEADER: feature_planning_service
# ROLE: Feature planning orchestration — context builder, architect, approval
# ############################################################################

# START_MODULE_CONTRACT
# purpose: Stable facade for feature planning, approval, repair, and lifecycle state.
# inputs: Database/session collaborators, feature identifiers, planning context, and plan data.
# returns: Planning state, context, Architect plans, approval results, and repair results.
# side_effects: Persists planning runs, plans, packets, artifacts, events, and runtime logs.
# emitted_logs: Feature planning, heartbeat, compiler, materializer, and repair lifecycle messages.
# error_behavior: Raises validation/compiler errors from explicit public operations; stage failures persist safe fallback state.
# END_MODULE_CONTRACT

# START_MODULE_MAP
# mapping:
#   - function: normalize_architect_plan
#   - class: FeaturePlanningService
#     methods:
#       - get_planning_state
#       - run_context_builder
#       - run_architect
#       - approve_plan
#       - try_approve_or_repair_plan
#       - regenerate_plan
# END_MODULE_MAP

from __future__ import annotations

import asyncio
from datetime import UTC, datetime

from grace_control.core.execution_environment import ExecutionEnvironment
from grace_control.core.structured_logger import GraceLogger

_log = GraceLogger("feature_planning")

from grace_control.core.uid import generate_unique_id, new_wave_uid, new_packet_uid, new_run_uid
from grace_control.db import get_db
from grace_control.db.schema import Feature, FeaturePlanningRun, Wave, Packet, Event
from grace_control.db.schema import PacketState
from grace_control.core.stage_instrumentation import stage
from grace_control.services.architect_stage import (
    ArchitectStage,
    build_architect_prompt,
    fallback_plan,
    finalize_plan,
)
from grace_control.services.context_builder_stage import (
    CONTEXT_BUILDER_MUTATED_TARGET_REPO,
    ContextBuilderStage,
)
from grace_control.services.planning_run_support import resolve_plan_target_root
from grace_control.services.planning_workspace_service import (
    _git_snapshot,
    _planning_workspace_mutation,
    _prepare_planning_workspace,
    _remove_planning_workspace,
)

# START_FUNCTION_CONTRACT
# name: normalize_architect_plan
# purpose: Normalize Architect output and enforce the current packet contract
#          when requested while preserving legacy-plan compatibility by default.
# inputs: plan — raw Architect/manual plan; require_current_contract — reject
#         coder packets missing conflict_keys when handling a fresh Architect output.
# returns: Canonical plan dict, or raises ValueError for invalid current-contract data.
# side_effects: Mutates the supplied plan dict; no external writes.
# emitted_logs: None.
# error_behavior: Raises ValueError when current coder packets omit conflict_keys
#                 or when conflict_keys normalization rejects a packet.
# END_FUNCTION_CONTRACT
def normalize_architect_plan(
    plan: dict,
    *,
    require_current_contract: bool = False,
) -> dict:
    """Normalize a raw architect plan dict into canonical form.

    This is the shared normalization path used by run_architect() before
    the plan is persisted or passed to the compiler.  Legacy/manual callers
    keep compatibility defaults; ``require_current_contract=True`` is used
    for a fresh Architect response and rejects coder packets that omit the
    current packet contract before any legacy default is applied.  It:

    1. Unwraps nested ``plan.waves`` if the LLM wrapped its output.
    2. Wraps bare ``packets`` into a single wave.
    3. Ensures every wave has a ``packets`` list.
    4. Sets ``acceptance_profile`` / ``depends_on`` / ``conflict_keys`` defaults.
    5. **W03**: Canonicalizes legacy packet fields (``allowed_files`` →
       ``scope``, etc.) with visible warnings.
    6. Marks all-field-missing packets as legacy for backward-compatible
       same-wave dependency handling.
    7. **W03**: Persists canonicalization warnings under
       ``plan["_architect_schema_warnings"]``.

    Returns the same plan dict (mutated in-place for efficiency).
    """
    from grace_control.core.prompts import canonicalize_packet_fields

    # Unwrap nested structure
    if "plan" in plan and isinstance(plan["plan"], dict) and plan["plan"].get("waves"):
        plan["waves"] = plan["plan"]["waves"]
    if "packets" in plan and not plan.get("waves"):
        plan["waves"] = [{"title": "Phase 1", "packets": plan["packets"]}]
    # Architect sometimes outputs a raw packet (has scope + role) instead of plan
    if "scope" in plan and "role" in plan and not plan.get("waves"):
        packet = dict(plan)
        plan = {"title": packet.get("title", "Phase 1"), "waves": [{"title": packet.get("title", "Phase 1"), "packets": [packet]}]}
    if "waves" not in plan:
        plan["waves"] = []

    # W03: Collect schema canonicalization warnings across all packets
    _schema_warnings: list[str] = []
    has_packets = False
    has_explicit_conflict_keys = False
    missing_current_contract: list[str] = []

    for wi, w in enumerate(plan.get("waves", [])):
        if "packets" not in w:
            w["packets"] = []
        for pi, pkt in enumerate(w["packets"]):
            has_packets = True
            has_explicit_conflict_keys |= "conflict_keys" in pkt
            if (
                require_current_contract
                and pkt.get("role", "coder") == "coder"
                and "conflict_keys" not in pkt
            ):
                missing_current_contract.append(f"waves[{wi}].packets[{pi}]")
            # W02: Do NOT setdefault("scope", []) — empty
            # scope must be caught by the plan compiler as
            # E_CODER_EMPTY_SCOPE, not hidden by a default.
            pkt.setdefault("acceptance_profile", "NORMAL")
            pkt.setdefault("depends_on", [])
            pkt.setdefault("conflict_keys", [])

            # W03: Canonicalize legacy packet fields with visible warnings.
            # This runs BEFORE the plan compiler so that legacy fields
            # (allowed_files, forbidden_files, write_scope, inputs) are
            # mapped to canonical equivalents (scope, frozen_scope,
            # coder_instructions) before validation.
            canon_pkt, pkt_warnings = canonicalize_packet_fields(pkt)
            w["packets"][pi] = canon_pkt
            for _w in pkt_warnings:
                _schema_warnings.append(
                    f"waves[{wi}].packets[{pi}]: {_w}"
                )

    if missing_current_contract:
        locations = ", ".join(missing_current_contract)
        raise ValueError(
            "Current architect packet contract requires conflict_keys for every "
            f"coder packet; missing at {locations}"
        )

    if has_packets and not has_explicit_conflict_keys:
        plan["_legacy_packet_contract"] = True
    else:
        plan.pop("_legacy_packet_contract", None)

    # W03: Persist canonicalization warnings on the plan so they are
    # visible in parsed_plan.json and downstream artifacts.
    if _schema_warnings:
        plan["_architect_schema_warnings"] = _schema_warnings

    plan.setdefault("constraints", {})
    plan.setdefault("verification", {"t0": [], "t1": [], "t2": []})

    return plan


# START_BLOCK_SERVICE
class FeaturePlanningService:
    """Orchestrate feature planning stages."""

    def __init__(self, db):
        self.db = db
        from grace_control.core.runtime_trace import RuntimeTraceContext, generate_trace_id
        from grace_control.core.runtime_artifacts import RuntimeArtifactStore
        from grace_control.core.runtime_events import RuntimeEventLogger
        self._trace_ctx = RuntimeTraceContext(trace_id=generate_trace_id())
        self._artifact_store = RuntimeArtifactStore()
        self._event_logger = RuntimeEventLogger(store=self._artifact_store)

    # START_FUNCTION_CONTRACT
    # name: get_planning_state
    # purpose: Return current feature planning status and persisted run metadata.
    # inputs: feature_id — feature identifier.
    # returns: Planning state dictionary with plan and run lifecycle details.
    # side_effects: Reads planning records from the database.
    # emitted_logs: None.
    # error_behavior: Raises ValueError when the feature does not exist.
    # END_FUNCTION_CONTRACT
    def get_planning_state(self, feature_id: str) -> dict:
        feature = self.db.query(Feature).filter_by(id=feature_id).first()
        if not feature:
            raise ValueError(f"Feature not found: {feature_id}")

        runs = self.db.query(FeaturePlanningRun).filter_by(feature_id=feature_id).order_by(FeaturePlanningRun.created_at).all()

        spec = feature.spec_json or {}
        plan_json = spec.get("plan_json") if isinstance(spec, dict) else None

        current_stage = None
        for r in runs:
            if r.status in ("running", "pending"):
                current_stage = r.stage
                break
        if current_stage is None and runs:
            last = runs[-1]
            if last.status != "done":
                current_stage = last.stage

        return {
            "feature_id": feature_id,
            "status": feature.status,
            "current_stage": current_stage,
            "plan_json": plan_json,
            "runs": [
                {
                    "id": r.id,
                    "stage": r.stage,
                    "status": r.status,
                    "started_at": r.started_at.isoformat() if r.started_at else None,
                    "finished_at": r.finished_at.isoformat() if r.finished_at else None,
                    "duration_ms": r.duration_ms,
                    "executor_id": r.executor_id,
                    "model": r.model,
                    "stdout_path": r.stdout_path,
                    "stderr_path": r.stderr_path,
                    "error": r.error,
                }
                for r in runs
            ],
        }

    # START_FUNCTION_CONTRACT
    # name: run_context_builder
    # purpose: Run Context Builder through the isolated planning stage.
    # inputs: feature_id — feature identifier; target_repo_root — optional target repository root.
    # returns: Context dictionary with summary, complexity, and selected files.
    # side_effects: Persists planning lifecycle state, artifacts, events, and disposable workspace data.
    # emitted_logs: Context Builder lifecycle and mutation-guard messages.
    # error_behavior: Returns fallback context for ordinary failures; re-raises mutation-guard failures.
    # END_FUNCTION_CONTRACT
    @stage("context_builder")
    async def run_context_builder(self, feature_id: str, target_repo_root: str | None = None) -> dict:
        return await ContextBuilderStage(
            db=self.db,
            trace_ctx=self._trace_ctx,
            artifact_store=self._artifact_store,
            event_logger=self._event_logger,
            heartbeat_worker=self._heartbeat_worker,
            emit_event=self._emit_event,
            git_snapshot=_git_snapshot,
            prepare_workspace=_prepare_planning_workspace,
            workspace_mutation=_planning_workspace_mutation,
            remove_workspace=_remove_planning_workspace,
        ).run(feature_id, target_repo_root)
    # START_FUNCTION_CONTRACT
    # name: run_architect
    # purpose: Run Architect through the isolated planning stage with strict current-contract normalization.
    # inputs: feature_id — feature identifier; context — Context Builder result; target_repo_root — optional target root.
    # returns: Normalized Architect plan dictionary.
    # side_effects: Persists planning lifecycle state, artifacts, events, and disposable workspace data.
    # emitted_logs: Architect lifecycle and mutation-guard messages.
    # error_behavior: Retries one rejected response and persists a safe failed fallback when execution fails.
    # END_FUNCTION_CONTRACT
    @stage("architect", llm=True)
    async def run_architect(self, feature_id: str, context: dict, target_repo_root: str | None = None) -> dict:
        return await ArchitectStage(
            db=self.db,
            trace_ctx=self._trace_ctx,
            artifact_store=self._artifact_store,
            event_logger=self._event_logger,
            heartbeat_worker=self._heartbeat_worker,
            normalize_plan=normalize_architect_plan,
            build_prompt=self._build_architect_prompt,
            fallback_plan_builder=self._fallback_plan,
            finalize_plan_callback=self._finalize_plan,
            git_snapshot=_git_snapshot,
            prepare_workspace=_prepare_planning_workspace,
            workspace_mutation=_planning_workspace_mutation,
            remove_workspace=_remove_planning_workspace,
        ).run(feature_id, context, target_repo_root)
    async def _heartbeat_worker(self, run_id: str, interval_s: float = 5.0) -> None:
        """Update run.last_heartbeat every `interval_s` while planning LLM runs.

        The presence of a recent `last_heartbeat` proves the agent is alive —
        distinguishes "actively running" from "stuck / zombie".
        """
        from grace_control.core.structured_logger import GraceLogger
        _log = GraceLogger("planning_heartbeat")
        try:
            while True:
                await asyncio.sleep(interval_s)
                try:
                    with get_db() as db:
                        run = db.query(FeaturePlanningRun).filter_by(id=run_id).first()
                        if not run:
                            break
                        if run.status != "running":
                            break
                        run.last_heartbeat = datetime.now(UTC)
                        db.commit()
                except Exception as e:
                    _log.warn("heartbeat_update_failed", run_id=run_id, error=str(e)[:200])
                    break
        except asyncio.CancelledError:
            pass

    def _finalize_plan(self, feature_id: str, plan: dict, arch_run: FeaturePlanningRun, run_id: str) -> None:
        finalize_plan(
            self.db,
            feature_id,
            plan,
            arch_run,
            run_id,
            emit_event=self._emit_event,
        )

    def _build_architect_prompt(
        self,
        task: str,
        context: dict,
        execution_environment: ExecutionEnvironment,
    ) -> str:
        return build_architect_prompt(
            task,
            context,
            execution_environment,
            trace_ctx=self._trace_ctx,
            event_logger=self._event_logger,
            artifact_store=self._artifact_store,
        )

    def _fallback_plan(self, feature_id: str, task_desc: str) -> dict:
        return fallback_plan(feature_id, task_desc)

    # START_FUNCTION_CONTRACT
    # name: approve_plan
    # purpose: Validate a ready plan with the public compiler and materialize waves and packets.
    # inputs: feature_id — feature whose PLAN_READY plan should be approved.
    # returns: Queued materialization result with wave and packet identifiers.
    # side_effects: Writes compiler/materializer runs, artifacts, events, waves, and packets.
    # emitted_logs: Compiler and packet materializer lifecycle messages.
    # error_behavior: Raises ValueError for missing/invalid status or compiler rejection.
    # END_FUNCTION_CONTRACT
    def approve_plan(self, feature_id: str) -> dict:
        feature = self.db.query(Feature).filter_by(id=feature_id).first()
        if not feature:
            raise ValueError(f"Feature not found: {feature_id}")
        if feature.status != "PLAN_READY":
            raise ValueError(f"Cannot approve plan in status {feature.status}. Must be PLAN_READY.")

        spec = dict(feature.spec_json) if feature.spec_json else {}
        plan = spec.get("plan_json", {}) if isinstance(spec, dict) else {}
        waves = plan.get("waves", []) if isinstance(plan, dict) else []

        # ── Plan Compiler / Preflight Validator ───────────────────────
        if isinstance(plan, dict) and plan.get("waves"):
            from grace_control.core.plan_compiler import PlanCompiler
            from grace_control.core.execution_environment import probe_execution_environment
            from grace_control.config.settings import settings as _settings
            target_root = resolve_plan_target_root(spec, _settings)
            env = probe_execution_environment(target_repo_root=target_root)
            feature_desc = (
                (getattr(feature, "description", None) or "")
                + "\n" + (getattr(feature, "title", None) or "")
                + "\n" + str(spec.get("description", ""))
                + "\n" + str(spec.get("title", ""))
            )
            # ── Runtime observability: persist input plan ──
            self._trace_ctx.feature_id = feature_id
            self._trace_ctx.stage = "plan_compiler"
            self._artifact_store.write_json(
                trace=self._trace_ctx, stage="plan_compiler", name="input_plan.json",
                payload=plan, kind="plan_input",
            )

            # ── Scope Path Canonicalizer (before PlanCompiler) ────────
            self._event_logger.emit(
                trace=self._trace_ctx, event="scope_canonicalizer.started", stage="scope_canonicalizer",
                component="FeaturePlanningService", status="running",
            )
            from grace_control.services.scope_path_canonicalizer import ScopePathCanonicalizer
            canonical = ScopePathCanonicalizer().canonicalize_plan(
                plan,
                target_repo_root=target_root,
            )
            # Persist canonicalizer input/output/fixes
            self._artifact_store.write_json(
                trace=self._trace_ctx, stage="scope_canonicalizer", name="input_plan.json",
                payload=plan, kind="plan_input",
            )
            if canonical.changed and canonical.plan:
                plan = canonical.plan
                spec["plan_json"] = plan
                spec["_scope_canonicalization"] = {
                    "changed": True,
                    "fixes": canonical.fixes,
                    "warnings": canonical.warnings,
                    "errors": canonical.errors,
                }
                feature.spec_json = spec
                _log.info("scope_canonicalized", feature_id=feature_id,
                          fixes=len(canonical.fixes))
                self._artifact_store.write_json(
                    trace=self._trace_ctx, stage="scope_canonicalizer", name="output_plan.json",
                    payload=plan, kind="plan_output",
                )
                self._artifact_store.write_json(
                    trace=self._trace_ctx, stage="scope_canonicalizer", name="fixes.json",
                    payload={"fixes": canonical.fixes, "warnings": canonical.warnings, "errors": canonical.errors},
                    kind="canonicalizer_fixes",
                )
                self._event_logger.emit(
                    trace=self._trace_ctx, event="scope_canonicalizer.fix_applied", stage="scope_canonicalizer",
                    component="FeaturePlanningService", status="completed",
                    payload={"fix_count": len(canonical.fixes)},
                )
            self._event_logger.emit(
                trace=self._trace_ctx, event="scope_canonicalizer.completed", stage="scope_canonicalizer",
                component="FeaturePlanningService", status="completed",
            )

            # Refresh waves after canonicalization (plan may have changed)
            waves = plan.get("waves", [])

            # ── Plan Compiler ────────────────────────────────────────
            self._event_logger.emit(
                trace=self._trace_ctx, event="plan_compiler.started", stage="plan_compiler",
                component="FeaturePlanningService", status="running",
            )
            compiled = PlanCompiler().compile_plan(
                plan, env,
                feature_description=feature_desc,
                target_repo_root=target_root,
            )
            # Persist compiler output
            self._artifact_store.write_json(
                trace=self._trace_ctx, stage="plan_compiler", name="output.json",
                payload={"ok": compiled.ok, "error_count": len(compiled.errors), "warning_count": len(compiled.warnings)},
                kind="plan_compiler_output",
            )
            if compiled.errors:
                self._artifact_store.write_json(
                    trace=self._trace_ctx, stage="plan_compiler", name="errors.json",
                    payload=[e.model_dump() for e in compiled.errors],
                    kind="plan_compiler_errors",
                )
                for e in compiled.errors:
                    self._event_logger.emit(
                        trace=self._trace_ctx, event="plan_compiler.error_detected", stage="plan_compiler",
                        component="FeaturePlanningService", status="error",
                        payload={"code": e.code, "message": e.message[:200]},
                    )
            if compiled.warnings:
                self._artifact_store.write_json(
                    trace=self._trace_ctx, stage="plan_compiler", name="warnings.json",
                    payload=[w.model_dump() for w in compiled.warnings],
                    kind="plan_compiler_warnings",
                )
                for w in compiled.warnings:
                    self._event_logger.emit(
                        trace=self._trace_ctx, event="plan_compiler.warning_detected", stage="plan_compiler",
                        component="FeaturePlanningService", status="warn",
                        payload={"code": w.code, "message": w.message[:200]},
                    )
            spec["_plan_compiler"] = {
                "ok": compiled.ok,
                "errors": [e.model_dump() for e in compiled.errors],
                "warnings": [w.model_dump() for w in compiled.warnings],
            }
            feature.spec_json = spec
            if not compiled.ok:
                self._event_logger.emit(
                    trace=self._trace_ctx, event="plan_compiler.failed", stage="plan_compiler",
                    component="FeaturePlanningService", status="failed",
                    payload={"errors": len(compiled.errors), "warnings": len(compiled.warnings)},
                )
                _log.warn("plan_compiler_rejected", feature_id=feature_id,
                          errors=len(compiled.errors), warnings=len(compiled.warnings))
                for e in compiled.errors:
                    _log.warn("plan_compiler_error", feature_id=feature_id,
                              code=e.code, packet=e.packet_title or "",
                              err_msg=e.message)
                materialize_run = FeaturePlanningRun(
                    id=generate_unique_id(self.db, FeaturePlanningRun, new_run_uid),
                    feature_id=feature_id,
                    stage="materialize",
                    status="failed",
                    started_at=datetime.now(UTC),
                    executor_id="plan_materializer",
                )
                self.db.add(materialize_run)
                feature.status = "PLAN_FAILED"
                materialize_run.error = f"plan compiler rejected: {len(compiled.errors)} errors"
                self.db.flush()
                self.db.commit()
                raise ValueError(
                    f"Plan compiler found {len(compiled.errors)} errors: "
                    + "; ".join(f"{e.code}: {e.message[:80]}" for e in compiled.errors[:3])
                )
            else:
                self._event_logger.emit(
                    trace=self._trace_ctx, event="plan_compiler.completed", stage="plan_compiler",
                    component="FeaturePlanningService", status="completed",
                )

        from grace_control.core.gate_resolver import enrich_packet

        now = datetime.now(UTC)
        materialize_run = FeaturePlanningRun(
            id=generate_unique_id(self.db, FeaturePlanningRun, new_run_uid),
            feature_id=feature_id,
            stage="materialize",
            status="running",
            started_at=now,
            executor_id="plan_materializer",
        )
        self.db.add(materialize_run)

        # ── Runtime observability: materializer ──
        self._trace_ctx.stage = "materializer"
        self._event_logger.emit(
            trace=self._trace_ctx, event="packet_materializer.started", stage="materializer",
            component="FeaturePlanningService", status="running",
        )
        self._artifact_store.write_json(
            trace=self._trace_ctx, stage="materializer", name="input_plan.json",
            payload=plan, kind="materializer_input",
        )

        root_verification = spec.get("verification", plan.get("verification", {}))
        root_constraints = spec.get("constraints", plan.get("constraints", {}))

        packet_ids = []
        packet_details: list[dict] = []
        reserved: set[str] = set()
        for i, w in enumerate(waves):
            wave_id = generate_unique_id(self.db, Wave, new_wave_uid, reserved=reserved)
            reserved.add(wave_id)
            wave_obj = Wave(
                id=wave_id,
                feature_id=feature_id,
                slug=f"wave-{i}",
                title=w.get("title", f"Wave {i}"),
                order=i,
                status="NOT_STARTED",
            )
            self.db.add(wave_obj)

            is_first_wave = i == 0
            for pkt in w.get("packets", []):
                pkt_id = generate_unique_id(self.db, Packet, new_packet_uid, reserved=reserved)
                reserved.add(pkt_id)
                enriched_spec = enrich_packet(pkt, pkt.get("depends_on", []))
                enriched_spec.setdefault("verification", root_verification)
                if root_constraints.get("frozen_scope"):
                    enriched_spec.setdefault("frozen_scope", root_constraints["frozen_scope"])
                # Propagate target_repo_root from feature spec into each packet spec
                # so that packet_executor can route to the correct repo worktree.
                target_repo = spec.get("target_repo_root") if isinstance(spec, dict) else None
                if target_repo:
                    enriched_spec["target_repo_root"] = target_repo
                # Packet coders must receive the source feature/TZ, not only the
                # architect's compact packet summary.  This is especially
                # important for the first documentation/canon wave where the
                # target repository does not yet contain requirements files.
                enriched_spec["feature_context"] = {
                    "feature_id": feature_id,
                    "title": feature.title or "",
                    "description": feature.description or "",
                }
                packet = Packet(
                    id=pkt_id,
                    feature_id=feature_id,
                    wave_id=wave_id,
                    slug=pkt.get("title", f"pkt-{i}").lower().replace(" ", "-"),
                    title=pkt.get("title", f"Packet {i}"),
                    spec_json=enriched_spec,
                    state=PacketState.READY.value if is_first_wave else PacketState.DRAFT.value,
                    acceptance_profile=enriched_spec.get("acceptance_profile", "NORMAL"),
                )
                self.db.add(packet)
                packet_ids.append(pkt_id)
                detail = {
                    "packet_id": pkt_id,
                    "title": pkt.get("title", ""),
                    "role": enriched_spec.get("role", "coder"),
                    "scope": enriched_spec.get("scope", []),
                    "frozen_scope": enriched_spec.get("frozen_scope", []),
                    "acceptance_profile": enriched_spec.get("acceptance_profile", "NORMAL"),
                    "depends_on": pkt.get("depends_on", []),
                }
                packet_details.append(detail)
                self._event_logger.emit(
                    trace=self._trace_ctx, event="packet_materializer.packet_created", stage="materializer",
                    component="FeaturePlanningService", status="created",
                    payload=packet_details,
                )

        materialize_run.status = "done"
        materialize_run.finished_at = datetime.now(UTC)
        materialize_run.duration_ms = int((materialize_run.finished_at - materialize_run.started_at).total_seconds() * 1000)
        materialize_run.result_json = {"waves_count": len(waves), "packets_count": len(packet_ids), "packet_ids": packet_ids}

        # ── Runtime observability: materializer completed ──
        packets_artifact = {
            "waves_count": len(waves),
            "packets_count": len(packet_ids),
            "packets": packet_details,
        }
        self._artifact_store.write_json(
            trace=self._trace_ctx, stage="materializer", name="packets_created.json",
            payload=packets_artifact, kind="materializer_packets",
        )
        self._event_logger.emit(
            trace=self._trace_ctx, event="packet_materializer.completed", stage="materializer",
            component="FeaturePlanningService", status="completed",
            payload={"waves_count": len(waves), "packets_count": len(packet_ids)},
        )

        feature.status = "queued"

        approval_mode = spec.get("approval_mode", "auto") if isinstance(spec, dict) else "auto"
        self._emit_event(feature_id, "plan_materialized", {
            "waves_count": len(waves), "packets_count": len(packet_ids),
            "approval_mode": approval_mode,
        })
        self._emit_event(feature_id, "feature_queued", {})

        self.db.commit()
        return {"status": "queued", "waves_count": len(waves), "packets_count": len(packet_ids), "packet_ids": packet_ids}

    # START_FUNCTION_CONTRACT
    # name: try_approve_or_repair_plan
    # purpose: Approve a plan and run bounded compiler repair when errors are repairable.
    # inputs: feature_id — feature identifier; max_repair_attempts — repair-loop limit.
    # returns: Approval result or PLAN_FAILED result with compiler errors; does not raise for exhausted repair.
    # side_effects: Writes compiler, autofix, repair artifacts/events and updates feature/spec state.
    # emitted_logs: Compiler rejection, autofix, repair attempt, and repair terminal messages.
    # error_behavior: Converts compiler ValueError to a bounded repair result; preserves non-repairable failure.
    # END_FUNCTION_CONTRACT
    async def try_approve_or_repair_plan(
        self,
        feature_id: str,
        *,
        max_repair_attempts: int = 2,
    ) -> dict:
        """Approve plan or run architect repair loop if compiler rejects.

        Returns the final approval result dict (same shape as approve_plan).
        Never raises — returns PLAN_FAILED if repair exhausted.

        W08 fix: approve_plan() raises ValueError on compiler rejection.
        We catch that exception and extract compiler errors from the feature's
        _plan_compiler metadata so the repair path is reachable instead of
        becoming an unhandled error that leaves the feature stuck in PLAN_FAILED.
        """
        try:
            result = self.approve_plan(feature_id)
            status = result.get("status", "")
        except ValueError as exc:
            # W08: approve_plan raises ValueError on compiler rejection.
            # The feature is now in PLAN_FAILED with compiler errors in spec.
            _log.info("approve_plan_compiler_rejection_caught",
                feature_id=feature_id, error=str(exc)[:200])
            status = "PLAN_FAILED"
            result = {"status": "PLAN_FAILED"}

        # If plan passed compiler or failed for a reason other than repairable → return
        if status != "PLAN_FAILED":
            return result

        compiler_errors = result.get("compiler_errors", [])
        if not compiler_errors:
            # W08: When approve_plan raised ValueError, compiler errors are
            # stored in feature.spec_json._plan_compiler.errors, not in the
            # result dict. Extract them so the repair path is reachable.
            feature = self.db.query(Feature).filter_by(id=feature_id).first()
            if feature:
                spec = feature.spec_json or {}
                compiler_data = spec.get("_plan_compiler", {})
                errors = compiler_data.get("errors", [])
                if errors:
                    compiler_errors = errors
                    _log.info("compiler_errors_extracted_from_spec",
                        feature_id=feature_id, error_count=len(compiler_errors))
        if not compiler_errors:
            return result

        # Check if any error is repairable
        from grace_control.services.planning_recovery_service import (
            is_repairable_error,
            classify_compiler_result,
        )
        error_class = classify_compiler_result(compiler_errors)
        if error_class != "repairable":
            _log.info("repair_skipped", feature_id=feature_id, error_class=error_class)
            return result

        # ── Feature data (needed for autofix + repair) ────────────────
        feature = self.db.query(Feature).filter_by(id=feature_id).first()
        if not feature:
            return result

        spec = feature.spec_json or {}
        plan = spec.get("plan_json", {}) or {}

        # W08: Reset feature status to PLAN_READY so that repair attempts
        # can re-approve. approve_plan() set it to PLAN_FAILED when it
        # raised ValueError, but the repair loop needs PLAN_READY to
        # call approve_plan() again after fixing the plan.
        if feature.status == "PLAN_FAILED":
            feature.status = "PLAN_READY"
            self.db.flush()
            _log.info("feature_status_reset_for_repair",
                feature_id=feature_id)

        feature_title = getattr(feature, "title", "") or spec.get("title", "")
        feature_desc = getattr(feature, "description", "") or spec.get("description", "")

        from grace_control.config.settings import settings as _settings
        target_root = resolve_plan_target_root(spec, _settings)

        from grace_control.core.execution_environment import probe_execution_environment
        env = probe_execution_environment(target_repo_root=target_root)
        desc_full = (feature_desc + "\n" + feature_title
                     + "\n" + str(spec.get("description", ""))
                     + "\n" + str(spec.get("title", "")))

        # ── 1. Autofix before LLM repair (iterative, up to 3 passes) ─
        self._trace_ctx.stage = "repair_loop"
        self._artifact_store.write_json(
            trace=self._trace_ctx, stage="repair_loop", name="compiler_errors.json",
            payload={"errors": compiler_errors}, kind="repair_errors",
        )
        from grace_control.services.plan_autofix_service import SafePlanAutofixer

        autofix_attempt = 0
        while autofix_attempt < 3:
            autofix_attempt += 1
            autofix_result = SafePlanAutofixer().apply(plan, compiler_errors)
            if not (autofix_result.applied and autofix_result.patched_plan):
                _log.info("autofix_noop", feature_id=feature_id,
                          attempt=autofix_attempt, skipped=len(autofix_result.skipped))
                break

            _log.info("autofix_applied", feature_id=feature_id,
                      attempt=autofix_attempt, fixes=len(autofix_result.fixes))
            spec["plan_json"] = autofix_result.patched_plan
            spec["_plan_autofix"] = {
                "applied": True,
                "fixes": autofix_result.fixes,
                "skipped": autofix_result.skipped,
                "attempt": autofix_attempt,
            }
            feature.spec_json = spec
            self.db.flush()
            plan = autofix_result.patched_plan
            self._artifact_store.write_json(
                trace=self._trace_ctx, stage="repair_loop", name="autofix_output.json",
                payload={"fixes": autofix_result.fixes, "skipped": autofix_result.skipped,
                         "attempt": autofix_attempt},
                kind="repair_autofix",
            )

            # Re-compile
            from grace_control.core.plan_compiler import PlanCompiler as _PC2
            compiled = _PC2().compile_plan(
                plan, env,
                feature_description=desc_full, target_repo_root=target_root,
            )
            spec["_plan_compiler"] = {
                "ok": compiled.ok,
                "errors": [e.model_dump() for e in compiled.errors],
                "warnings": [w.model_dump() for w in compiled.warnings],
                "autofix": True,
                "attempt": autofix_attempt,
            }
            feature.spec_json = spec
            self.db.flush()
            if compiled.ok:
                _log.info("autofix_success", feature_id=feature_id,
                          attempt=autofix_attempt)
                feature.status = "PLAN_READY"
                self.db.flush()
                return self.approve_plan(feature_id)
            compiler_errors = [e.model_dump() for e in compiled.errors]
            error_class = classify_compiler_result(compiler_errors)
            if error_class != "repairable":
                _log.info("repair_skipped_after_autofix", feature_id=feature_id,
                          error_class=error_class, attempt=autofix_attempt)
                break

        # If after autofix it's still repairable → LLM repair
        if error_class != "repairable":
            _log.info("repair_skipped_after_autofix", feature_id=feature_id,
                      error_class=error_class)
            return {"status": "PLAN_FAILED", "compiler_errors": compiler_errors}

        # ── 2. LLM Repair loop ──────────────────────────────────────
        previous_session = None
        arch_runs = (
            self.db.query(FeaturePlanningRun)
            .filter(
                FeaturePlanningRun.feature_id == feature_id,
                FeaturePlanningRun.stage == "architect",
                FeaturePlanningRun.status == "done",
            )
            .order_by(FeaturePlanningRun.created_at.desc())
            .limit(1)
            .all()
        )
        if arch_runs:
            rj = arch_runs[0].result_json or {}
            sess_raw = rj.get("session_handle")
            if sess_raw:
                try:
                    import json as _json
                    from grace_control.core.agent_session_adapter import AgentSessionHandle
                    raw = _json.loads(sess_raw) if isinstance(sess_raw, str) else sess_raw
                    if isinstance(raw, dict):
                        previous_session = AgentSessionHandle(**raw)
                except Exception:
                    previous_session = None

        attempt = 1
        while attempt <= max_repair_attempts:
            _log.info("repair_attempt", feature_id=feature_id, attempt=attempt)
            self._event_logger.emit(
                trace=self._trace_ctx, event="repair_loop.attempt_started", stage="repair_loop",
                component="FeaturePlanningService", status="running",
                payload={"attempt": attempt, "errors": len(compiler_errors)},
            )

            from grace_control.services.planning_recovery_service import run_architect_repair

            repaired_plan, error = await run_architect_repair(
                feature_title=feature_title,
                feature_description=feature_desc,
                previous_plan=plan,
                compiler_errors=compiler_errors,
                previous_session=previous_session,
                cwd=target_root,
            )

            if error or repaired_plan is None:
                _log.warn("repair_failed", feature_id=feature_id,
                          attempt=attempt, error=error)
                self._event_logger.emit(
                    trace=self._trace_ctx, event="repair_loop.attempt_failed", stage="repair_loop",
                    component="FeaturePlanningService", status="failed",
                    payload={"attempt": attempt, "error": str(error)[:200]},
                )
                break

            # Save repaired plan AND update local plan for next attempt
            spec["plan_json"] = repaired_plan
            plan = repaired_plan  # ← important: attempt 2 uses attempt 1 fixed plan
            self._artifact_store.write_json(
                trace=self._trace_ctx, stage="repair_loop", name=f"repaired_plan_attempt_{attempt}.json",
                payload=plan, kind="repair_plan",
            )

            # Canonicalize scope paths after LLM repair before recompile
            from grace_control.services.scope_path_canonicalizer import ScopePathCanonicalizer
            canonical = ScopePathCanonicalizer().canonicalize_plan(
                plan,
                target_repo_root=target_root,
            )
            if canonical.changed and canonical.plan:
                plan = canonical.plan
                spec["plan_json"] = plan
                spec["_scope_canonicalization"] = {
                    "changed": True,
                    "fixes": canonical.fixes,
                    "warnings": canonical.warnings,
                    "errors": canonical.errors,
                }
                _log.info("repair_scope_canonicalized", feature_id=feature_id,
                          fixes=len(canonical.fixes))

            feature.spec_json = spec
            self.db.flush()

            # Re-compile (target_root and env already computed above)
            from grace_control.core.plan_compiler import PlanCompiler
            compiled = PlanCompiler().compile_plan(
                plan, env,
                feature_description=desc_full,
                target_repo_root=target_root,
            )
            spec["_plan_compiler"] = {
                "ok": compiled.ok,
                "errors": [e.model_dump() for e in compiled.errors],
                "warnings": [w.model_dump() for w in compiled.warnings],
                "repair_attempt": attempt,
            }
            feature.spec_json = spec
            self.db.flush()

            if compiled.ok:
                _log.info("repair_success", feature_id=feature_id,
                          attempt=attempt)
                self._event_logger.emit(
                    trace=self._trace_ctx, event="repair_loop.success", stage="repair_loop",
                    component="FeaturePlanningService", status="completed",
                    payload={"attempt": attempt},
                )
                # Reset status to PLAN_READY so approve_plan accepts it
                feature.status = "PLAN_READY"
                self.db.flush()
                return self.approve_plan(feature_id)

            # Check if errors are still repairable or same
            new_errors = [e.model_dump() for e in compiled.errors]
            new_class = classify_compiler_result(new_errors)
            if new_class != "repairable":
                _log.warn("repair_terminal_error", feature_id=feature_id,
                          attempt=attempt)
                self._event_logger.emit(
                    trace=self._trace_ctx, event="repair_loop.terminal_error", stage="repair_loop",
                    component="FeaturePlanningService", status="failed",
                    payload={"attempt": attempt, "error_class": new_class},
                )
                break

            compiler_errors = new_errors
            attempt += 1

        _log.warn("repair_exhausted", feature_id=feature_id,
                  attempts=attempt, max_attempts=max_repair_attempts)
        self._event_logger.emit(
            trace=self._trace_ctx, event="repair_loop.exhausted", stage="repair_loop",
            component="FeaturePlanningService", status="failed",
            payload={"attempts": attempt, "max_attempts": max_repair_attempts},
        )
        return {"status": "PLAN_FAILED", "compiler_errors": compiler_errors}

    # START_FUNCTION_CONTRACT
    # name: regenerate_plan
    # purpose: Reset a failed/ready feature to planning and schedule a fresh Context Builder run.
    # inputs: feature_id — feature identifier.
    # returns: Current planning state after regeneration is scheduled.
    # side_effects: Updates feature status/spec and inserts a pending planning run.
    # emitted_logs: None.
    # error_behavior: Raises ValueError when the feature is missing or not regenerable.
    # END_FUNCTION_CONTRACT
    def regenerate_plan(self, feature_id: str) -> dict:
        feature = self.db.query(Feature).filter_by(id=feature_id).first()
        if not feature:
            raise ValueError(f"Feature not found: {feature_id}")
        if feature.status not in ("PLAN_READY", "PLAN_FAILED"):
            raise ValueError(f"Cannot regenerate plan in status {feature.status}. Must be PLAN_READY or PLAN_FAILED.")

        feature.status = "PLANNING"

        cb_run = FeaturePlanningRun(
            id=generate_unique_id(self.db, FeaturePlanningRun, new_run_uid),
            feature_id=feature_id,
            stage="context_builder",
            status="pending",
            executor_id="context_collector",
        )
        self.db.add(cb_run)

        spec = dict(feature.spec_json) if feature.spec_json else {}
        spec.pop("plan_json", None)
        feature.spec_json = spec

        self.db.commit()
        return self.get_planning_state(feature_id)

    def _emit_event(self, feature_id: str, event_type: str, payload: dict, trace_id: str = "") -> None:
        event = Event(
            event_type=event_type,
            entity_type="feature",
            entity_id=feature_id,
            payload_json=payload,
            trace_id=trace_id or "",
        )
        self.db.add(event)
# END_BLOCK_SERVICE
