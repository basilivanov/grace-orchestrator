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

from grace_control.core.uid import generate_unique_id, new_run_uid
from grace_control.db import get_db
from grace_control.db.schema import Event, Feature, FeaturePlanningRun
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
    # purpose: Delegate plan compilation and wave/packet materialization to the approval owner.
    # inputs: feature_id — feature whose PLAN_READY plan should be approved.
    # returns: Queued materialization result with wave and packet identifiers.
    # side_effects: Persists compiler/materializer runs, artifacts, events, waves, and packets.
    # emitted_logs: Compiler and packet materializer lifecycle messages.
    # error_behavior: Raises ValueError for missing/invalid status or compiler rejection.
    # END_FUNCTION_CONTRACT
    def approve_plan(self, feature_id: str) -> dict:
        from grace_control.services.planning_approval_service import PlanApprovalService

        return PlanApprovalService(self).approve_plan(feature_id)
    # START_FUNCTION_CONTRACT
    # name: try_approve_or_repair_plan
    # purpose: Delegate bounded compiler repair and Architect autofix orchestration to the repair owner.
    # inputs: feature_id — feature identifier; max_repair_attempts — repair-loop limit.
    # returns: Approval result or PLAN_FAILED result with compiler errors; does not raise for exhausted repair.
    # side_effects: Persists compiler, autofix, repair artifacts/events and updates feature/spec state.
    # emitted_logs: Compiler rejection, autofix, repair attempt, and terminal repair messages.
    # error_behavior: Converts compiler ValueError to a bounded repair result; preserves non-repairable failure.
    # END_FUNCTION_CONTRACT
    async def try_approve_or_repair_plan(
        self,
        feature_id: str,
        *,
        max_repair_attempts: int = 2,
    ) -> dict:
        from grace_control.services.planning_repair_service import PlanRepairService

        return await PlanRepairService(self).try_approve_or_repair_plan(
            feature_id,
            max_repair_attempts=max_repair_attempts,
        )
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
