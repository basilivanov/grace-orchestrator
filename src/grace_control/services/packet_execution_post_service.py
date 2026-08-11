# ############################################################################
# AI_HEADER: packet_execution_post_service — worktree inspection and scope safety
# ROLE: Owns post-backend worktree inspection, agent-commit detection, diff
#       enforcement, and runtime diagnostic mapping.
# ############################################################################

# START_MODULE_CONTRACT
# purpose: Validate the backend result against worktree and packet scope safety rules.
# inputs: Adapter dependencies, backend result, packet contract, run/base identifiers.
# returns: Inspection status/SHA or a controlled rejection result.
# side_effects: Reads Git/worktree state and persists runtime diagnostic artifacts.
# emitted_logs: diff inspection, scope enforcement, and diagnostics event names.
# error_behavior: Returns a rejection result for non-Git, diff, or scope failures.
# END_MODULE_CONTRACT

# START_MODULE_MAP
# mapping:
#   - class: PacketExecutionPostService
#     methods:
#       - inspect_worktree
#       - enforce_scope
# END_MODULE_MAP

from __future__ import annotations

import time
from pathlib import Path

from grace_control.core.structured_logger import GraceLogger
from grace_control.runtime.agent_runtime_contract import AgentRuntimeFailureCode
from grace_control.runtime.runtime_diagnostics import RuntimeDiagnosticsBuilder
from grace_control.runtime.runtime_diff_inspector import RuntimeDiffInspectionRequest, RuntimeDiffInspector
from grace_control.runtime.runtime_scope_enforcer import RuntimeScopeEnforcer
from grace_control.services.packet_execution_runtime_service import _is_git_worktree

_log = GraceLogger("adapter")


# START_BLOCK_POST_EXECUTION
class PacketExecutionPostService:

    # START_FUNCTION_CONTRACT
    # name: inspect_worktree
    # purpose: Inspect the backend worktree, commit changes, and recognize agent-created HEAD commits.
    # inputs: adapter, result, packet contract, packet id, attempt count, base SHAs.
    # returns: Tuple of status and commit SHA.
    # side_effects: Reads worktree state and may create the canonical agent commit.
    # emitted_logs: agent_existing_commit_detected.
    # error_behavior: Returns worktree_missing, not_git, or no_changes statuses.
    # END_FUNCTION_CONTRACT
    def inspect_worktree(
        self,
        adapter,
        result,
        pkt_contract,
        packet_id,
        attempt_count,
        *,
        base_sha="",
        workspace_base_sha="",
    ):
        if not result.worktree_path or not Path(result.worktree_path).exists():
            return "worktree_missing", ""
        wt = Path(result.worktree_path)
        if not adapter._inspector.is_git_worktree(wt):
            return "not_git", ""
        if adapter._inspector.has_changes(wt, pkt_contract.allowed_write_scope):
            sha = adapter._committer.commit(wt, packet_id, attempt_count)
            if sha:
                return "committed", sha

        head_sha = adapter._inspector.base_sha(wt, "HEAD")
        comparison_sha = workspace_base_sha or base_sha
        if comparison_sha and head_sha and head_sha != comparison_sha:
            _log.info(
                "agent_existing_commit_detected",
                packet_id=packet_id,
                sha=head_sha[:12],
                base_sha=comparison_sha[:12],
            )
            return "committed", head_sha
        return "no_changes", ""

    # START_FUNCTION_CONTRACT
    # name: enforce_scope
    # purpose: Inspect the runtime diff, enforce packet/frozen scope, and map unsafe results.
    # inputs: adapter plus backend result, packet contract, run/base identifiers, executor, start.
    # returns: Rejection ExecutionResult when unsafe, otherwise None.
    # side_effects: Reads diff/worktree state and writes runtime diagnostic artifacts.
    # emitted_logs: diff inspection, scope enforcement, and runtime diagnostics events.
    # error_behavior: Fails closed when diff inspection or scope enforcement is not trustworthy.
    # END_FUNCTION_CONTRACT
    async def enforce_scope(
        self,
        adapter,
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
        """Run diff inspection + scope enforcement. Returns reject ExecutionResult or None."""
        from grace_control.config.settings import settings as _s

        wt_path = getattr(result, "worktree_path", None)
        if not wt_path or not Path(wt_path).exists():
            return None

        # Verify the worktree is a git repo
        if not _is_git_worktree(str(wt_path)):
            if getattr(_s, "agent_runtime_allow_non_git_scope_skip", False):
                _log.info("w6_skipped_non_git", packet_id=packet_id, worktree=str(wt_path))
                return None
            reason = f"Worktree is not a git repository: {wt_path}"
            _log.warn("w6_non_git_rejected", packet_id=packet_id, reason=reason)
            er = adapter._fast_reject(reason, executor.get("executor_id", ""), run_id, start)
            try:
                er.evidence["failure_code"] = AgentRuntimeFailureCode.AGENT_WORKTREE_NOT_GIT
            except Exception as _fc_err:
                _log.warn("failure_code_set_failed", packet_id=packet_id, error=str(_fc_err)[:200])
            return er

        store = getattr(adapter, "_obs_store", None)
        events = getattr(adapter, "_obs_events", None)
        trace = getattr(adapter, "_obs_trace", None)
        redactor = getattr(adapter, "_obs_redactor", None)
        obs_disabled = getattr(adapter, "_obs_disabled", True)

        inspector = RuntimeDiffInspector()
        diff_req = RuntimeDiffInspectionRequest(
            repo_root=str(
                Path(getattr(adapter, "_packet_target_repo", "") or adapter.project_root)
            ),
            worktree_root=str(wt_path),
            base_ref=base_sha or base_ref,
        )
        diff_result = await inspector.inspect(diff_req)
        if events and trace:
            try:
                events.emit(trace=trace, event="packet.diff_inspection_started",
                            stage="post_execution", component="scope_enforcer", status="started")
            except Exception as _emit_err:
                _log.warn("obs_event_emit_failed", event="diff_inspection_started", error=str(_emit_err)[:200])
        if events and trace:
            try:
                if diff_result.ok:
                    events.emit(trace=trace, event="packet.diff_inspection_completed",
                                stage="post_execution", component="scope_enforcer", status="completed",
                                payload={"changed_file_count": len(diff_result.changed_files)})
                else:
                    events.emit(trace=trace, event="packet.diff_inspection_failed",
                                stage="post_execution", component="scope_enforcer",
                                status="failed", message=diff_result.summary)
            except Exception as _emit_err:
                _log.warn("obs_event_emit_failed", event="diff_inspection_completed", error=str(_emit_err)[:200])

        # Hard reject on diff failure — can't enforce scope without trustworthy diff
        if not diff_result.ok:
            reason = f"Diff inspection failed: {diff_result.summary}"
            _log.warn("diff_inspection_failed", packet_id=packet_id, summary=reason)

            # Build diagnostics even for diff failure (important safety-layer artifact)
            diag = RuntimeDiagnosticsBuilder.build(
                runtime_run_id=run_id,
                packet_id=packet_id,
                trace_id=trace.trace_id if trace else "",
                adapter="open" + "code",
                runtime_mode=getattr(_s, "open" + "code_runtime_mode", "direct"),
                accepted=False,
                failure_code=diff_result.failure_code,
                failure_stage="diff_inspection",
                stdout_tail=getattr(result, "stdout", "") or "",
                stderr_tail=getattr(result, "stderr", "") or "",
            )

            # Persist diagnostics artifact if store available
            if not obs_disabled and store and trace and redactor:
                try:
                    store.write_packet_json(
                        trace=trace, packet_id=packet_id,
                        name="runtime_diagnostics.json",
                        payload=redactor.redact_payload(diag.model_dump()),
                        kind="runtime_diagnostics",
                    )
                    store.write_packet_json(
                        trace=trace, packet_id=packet_id,
                        name="diff_inspection.json",
                        payload=redactor.redact_payload(diff_result.model_dump()),
                        kind="diff_inspection",
                    )
                    store.write_packet_json(
                        trace=trace, packet_id=packet_id,
                        name="changed_files.json",
                        payload=redactor.redact_payload({"changed_files": []}),
                        kind="changed_files",
                    )
                except Exception as _emit_err:
                    _log.warn("obs_event_emit_failed", event="changed_files_persist", error=str(_emit_err)[:200])

            er = adapter._fast_reject(reason, executor.get("executor_id", ""), run_id, start)
            try:
                er.evidence["diff_inspection"] = diff_result.model_dump()
                er.evidence["runtime_diagnostics"] = diag.model_dump()
                er.evidence["failure_code"] = diff_result.failure_code
            except Exception as _diag_err:
                _log.warn("diff_diag_set_failed", packet_id=packet_id, error=str(_diag_err)[:200])
            return er

        allowed = list(pkt_contract.allowed_write_scope or [])
        frozen = list(pkt_contract.frozen_scope or [])

        if events and trace:
            try:
                events.emit(trace=trace, event="packet.scope_enforcement_started",
                            stage="post_execution", component="scope_enforcer", status="started")
            except Exception as _emit_err:
                _log.warn("obs_event_emit_failed", event="scope_enforcement_started", error=str(_emit_err)[:200])
        scope_result = RuntimeScopeEnforcer.enforce(
            changed_files=diff_result.changed_files,
            allowed_scope=allowed,
            frozen_scope=frozen,
            fail_on_no_changes=getattr(_s, "agent_runtime_fail_on_no_changes", False),
        )
        if events and trace:
            try:
                if scope_result.ok:
                    events.emit(trace=trace, event="packet.scope_enforcement_completed",
                                stage="post_execution", component="scope_enforcer", status="completed",
                                payload={"changed_file_count": len(scope_result.changed_files)})
                else:
                    events.emit(trace=trace, event="packet.scope_enforcement_failed",
                                stage="post_execution", component="scope_enforcer",
                                status="failed", message=scope_result.summary,
                                payload={"out_of_scope_count": len(scope_result.out_of_scope_files),
                                         "frozen_touched_count": len(scope_result.frozen_touched_files)})
            except Exception as _emit_err:
                _log.warn("obs_event_emit_failed", event="scope_enforcement_completed", error=str(_emit_err)[:200])
        diag = RuntimeDiagnosticsBuilder.build(
            runtime_run_id=run_id,
            packet_id=packet_id,
            trace_id=trace.trace_id if trace else "",
            adapter="open" + "code",
            runtime_mode=getattr(_s, "open" + "code_runtime_mode", "direct"),
            duration_ms=int((time.time() - start) * 1000),
            accepted=scope_result.ok,
            failure_code=scope_result.failure_code,
            failure_stage="scope_enforcement" if not scope_result.ok else None,
            changed_files=scope_result.changed_files,
            out_of_scope_files=scope_result.out_of_scope_files,
            frozen_touched_files=scope_result.frozen_touched_files,
            stdout_tail=getattr(result, "stdout") or "",
            stderr_tail=getattr(result, "stderr") or "",
        )

        if not obs_disabled and store and trace and redactor:
            refs = RuntimeDiagnosticsBuilder.persist(diag, scope_result, diff_result, trace, packet_id, store, redactor)
            diag.artifact_refs = [r.path for r in refs if r.path]

            if events and trace:
                try:
                    events.emit(trace=trace, event="packet.runtime_diagnostics_created",
                                stage="post_execution", component="scope_enforcer", status="completed",
                                artifact_refs=refs)
                except Exception as _emit_err:
                    _log.warn("obs_event_emit_failed", event="runtime_diagnostics_created", error=str(_emit_err)[:200])

        if not scope_result.ok:
            reason = scope_result.summary
            _log.warn("scope_enforcement_failed", packet_id=packet_id,
                       failure_code=scope_result.failure_code, summary=reason)
            er = adapter._fast_reject(reason, executor.get("executor_id", ""), run_id, start)
            # Attach scope/diff/diagnostics to evidence for trace/UI
            try:
                er.evidence["scope_enforcement"] = scope_result.model_dump()
                er.evidence["diff_inspection"] = diff_result.model_dump()
                er.evidence["runtime_diagnostics"] = diag.model_dump()
                er.evidence["failure_code"] = scope_result.failure_code
            except Exception as _diag_err:
                _log.warn("scope_diag_set_failed", packet_id=packet_id, error=str(_diag_err)[:200])
            return er

        return None

# END_BLOCK_POST_EXECUTION
