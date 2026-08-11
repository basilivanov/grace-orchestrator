# ############################################################################
# AI_HEADER: planning_repair_service — repair and autofix rejected plans
# ROLE: Owns deterministic plan autofix, Architect repair attempts, compiler
#       rechecks, and terminal routing behind the stable planning facade.
# ############################################################################

# START_MODULE_CONTRACT
# purpose: Recover compiler-rejected plans through bounded autofix and Architect repair.
# inputs: Facade planning collaborators, feature identifier, and repair attempt limit.
# returns: Approval result or PLAN_FAILED result with compiler diagnostics.
# side_effects: Writes compiler/autofix/repair artifacts and events and updates feature/spec state.
# emitted_logs: Compiler rejection, autofix, repair attempt, success, terminal, and exhausted messages.
# error_behavior: Does not raise for exhausted repair; preserves bounded repair failure results.
# END_MODULE_CONTRACT

# START_MODULE_MAP
# mapping:
#   - class: PlanRepairService
#     methods:
#       - try_approve_or_repair_plan
# END_MODULE_MAP

from __future__ import annotations

from grace_control.core.structured_logger import GraceLogger
from grace_control.db.schema import Feature, FeaturePlanningRun
from grace_control.services.planning_run_support import resolve_plan_target_root

_log = GraceLogger("feature_planning")


# START_BLOCK_REPAIR
class PlanRepairService:
    """Own deterministic and LLM-based plan repair orchestration."""

    def __init__(self, facade):
        self._facade = facade
        self.db = facade.db
        self._trace_ctx = facade._trace_ctx
        self._artifact_store = facade._artifact_store
        self._event_logger = facade._event_logger

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
            result = self._facade.approve_plan(feature_id)
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
                return self._facade.approve_plan(feature_id)
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

        return await self._run_llm_repair(
            feature_id=feature_id,
            feature=feature,
            spec=spec,
            plan=plan,
            compiler_errors=compiler_errors,
            feature_title=feature_title,
            feature_desc=feature_desc,
            target_root=target_root,
            env=env,
            desc_full=desc_full,
            max_repair_attempts=max_repair_attempts,
        )

    async def _run_llm_repair(
        self,
        *,
        feature_id: str,
        feature,
        spec: dict,
        plan: dict,
        compiler_errors: list,
        feature_title: str,
        feature_desc: str,
        target_root,
        env,
        desc_full: str,
        max_repair_attempts: int,
    ) -> dict:
        from grace_control.services.planning_recovery_service import classify_compiler_result
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
                return self._facade.approve_plan(feature_id)

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

# END_BLOCK_REPAIR
