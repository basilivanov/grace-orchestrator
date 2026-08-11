# ############################################################################
# AI_HEADER: planning_approval_service — compile and materialize feature plans
# ROLE: Owns plan approval, public compiler orchestration, and wave/packet
#       materialization while FeaturePlanningService remains the stable facade.
# ############################################################################

# START_MODULE_CONTRACT
# purpose: Validate PLAN_READY plans and materialize their compiled waves and packets.
# inputs: Facade planning collaborators and a feature identifier.
# returns: Queued materialization result with wave and packet identifiers.
# side_effects: Writes compiler/materializer runs, artifacts, events, waves, and packets.
# emitted_logs: Scope canonicalizer, plan compiler, and packet materializer lifecycle messages.
# error_behavior: Raises ValueError for invalid status or compiler rejection.
# END_MODULE_CONTRACT

# START_MODULE_MAP
# mapping:
#   - class: PlanApprovalService
#     methods:
#       - approve_plan
# END_MODULE_MAP

from __future__ import annotations

from datetime import UTC, datetime

from grace_control.core.structured_logger import GraceLogger
from grace_control.core.uid import (
    generate_unique_id,
    new_packet_uid,
    new_run_uid,
    new_wave_uid,
)
from grace_control.db.schema import Feature, FeaturePlanningRun, Packet, PacketState, Wave
from grace_control.services.planning_run_support import resolve_plan_target_root

_log = GraceLogger("feature_planning")


# START_BLOCK_APPROVAL
class PlanApprovalService:
    """Own public compiler and packet materialization orchestration."""

    def __init__(self, facade):
        self.db = facade.db
        self._trace_ctx = facade._trace_ctx
        self._artifact_store = facade._artifact_store
        self._event_logger = facade._event_logger
        self._emit_event = facade._emit_event

    # START_FUNCTION_CONTRACT
    # name: approve_plan
    # purpose: Validate a ready plan, then delegate compiler and materialization stages.
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
        spec, plan, waves = self._compile_plan(feature_id, feature, spec, plan)
        return self._materialize_plan(feature_id, feature, spec, plan, waves)

    def _compile_plan(
        self,
        feature_id: str,
        feature: Feature,
        spec: dict,
        plan: dict,
    ) -> tuple[dict, dict, list]:
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
        return spec, plan, plan.get("waves", []) if isinstance(plan, dict) else []

    def _materialize_plan(
        self,
        feature_id: str,
        feature: Feature,
        spec: dict,
        plan: dict,
        waves: list,
    ) -> dict:
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

# END_BLOCK_APPROVAL
