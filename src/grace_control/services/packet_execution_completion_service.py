# ############################################################################
# AI_HEADER: packet_execution_completion_service — finalize packet execution
# ROLE: Owns acceptance routing, terminal persistence, replay metadata, and
#       rework packet creation after backend execution has completed.
# ############################################################################

# START_MODULE_CONTRACT
# purpose: Finalize packet outcomes while keeping terminal persistence and routing rules together.
# inputs: Adapter dependencies, backend/acceptance results, packet/run metadata.
# returns: ExecutionResult or completion metadata used by the execution facade.
# side_effects: Persists run evidence, writes replay patches, cleans failed worktrees,
#               and may create a rework packet.
# emitted_logs: Acceptance routing, completion, cleanup, and rework packet events.
# error_behavior: Persists controlled rejection results; rework creation failures are logged.
# END_MODULE_CONTRACT

# START_MODULE_MAP
# mapping:
#   - class: PacketExecutionCompletionService
#     methods:
#       - route_after
#       - persist_run
#       - effective_cleanup_root
#       - fast_reject
#       - build_dev_replay_metadata
#       - maybe_create_rework_packet
#       - write_agent_patch
# END_MODULE_MAP

from __future__ import annotations

import time
from datetime import UTC, datetime
from pathlib import Path

from grace_control.core.evidence_verifier import (
    EvidenceVerifierVerdict,
    skipped_evidence_report,
)
from grace_control.core.reviewer_gate import (
    ReviewerVerdict,
    skipped_reviewer_report,
)
from grace_control.core.structured_logger import GraceLogger
from grace_control.db.schema import Packet
from grace_control.services.packet_execution_runtime_service import (
    _STDERR_TAIL_LIMIT,
    _redact_secrets,
    _tail,
    classify_failure,
)

_log = GraceLogger("adapter")


# START_BLOCK_COMPLETION
class PacketExecutionCompletionService:

    # START_FUNCTION_CONTRACT
    # name: route_after
    # purpose: Route an accepted backend result through verifier/reviewer gates and persist the outcome.
    # inputs: adapter, execution/acceptance results, packet/run identifiers, worktree and base metadata.
    # returns: Adapter ExecutionResult for accepted, rejected, or blocked routing.
    # side_effects: Runs verifier/reviewer gates, writes evidence, creates rework packets, and cleans failures.
    # emitted_logs: Acceptance routing and packet execution completion events.
    # error_behavior: Raises for an unexpected reviewer verdict after persisting normal outcomes.
    # END_FUNCTION_CONTRACT
    async def route_after(
        self,
        adapter,
        start,
        run_id,
        packet_id,
        result,
        executor,
        rn,
        pkt_contract,
        accept_report,
        ar_path,
        sd,
        changed_files,
        sha,
        wt_path,
        run_dir,
        base_ref=None,
        base_sha=None,
    ):
        from grace_control.adapters.packet_executor import ExecutionResult
        from grace_control.adapters import packet_executor as facade
        from grace_control.core.contracts import AcceptanceProfile

        prof = pkt_contract.acceptance_profile
        evidence = adapter._evidence
        executor_id = executor.get("executor_id", "")
        artifacts = (
            [str(path.relative_to(run_dir)) for path in run_dir.rglob("*") if path.is_file()]
            if run_dir.exists()
            else []
        )
        evidence_path = evidence.evidence_path(packet_id, rn, adapter.state_root)

        def make_result(accepted, domain_status, reason=None, commit_sha=sha, path=evidence_path):
            return ExecutionResult(
                accepted=accepted,
                reason=reason,
                domain_status=domain_status,
                worktree_path=str(result.worktree_path) if result.worktree_path else "",
                branch_name=result.branch_name or "",
                acceptance_report_path=ar_path,
                acceptance_verdict=accept_report.final_verdict.value,
                acceptance_summary=accept_report.summary,
                duration_ms=int((time.time() - start) * 1000),
                commit_sha=commit_sha,
                evidence_path=path,
            )

        def persist_accepted(accepted_result, verification_report, reviewer_report):
            dev_replay = adapter._build_dev_replay_metadata(
                packet_id=packet_id,
                run_id=run_id,
                run_number=rn,
                wt_path=wt_path,
                branch_name=result.branch_name or "",
                base_ref=base_ref,
                base_sha=base_sha,
                agent_commit_sha=sha,
                changed_files=changed_files,
                run_dir=run_dir,
                ar_path=ar_path,
                acceptance_report=accept_report,
                evr=verification_report,
                rvr=reviewer_report,
            )
            adapter._write_agent_patch(wt_path, run_dir, base_sha)
            diff_ref = adapter._capture_diff_patch_artifact(wt_path, run_dir, base_sha)
            ev_ref, meta_ref = adapter._capture_evidence_artifact(
                packet_id,
                run_id,
                rn,
                sha,
                changed_files,
                accept_report,
                verification_report,
                accepted_result,
            )
            refs = [ref for ref in (diff_ref, ev_ref, meta_ref) if ref is not None]
            adapter._obs_event(
                "packet.evidence_captured",
                status="completed",
                artifact_refs=refs if refs else None,
            )
            adapter._obs_event(
                "packet.execution_completed",
                status="accepted",
                duration_ms=accepted_result.duration_ms,
            )
            evidence.save_agent_log(packet_id, rn, result, adapter.state_root)
            evidence.update_run_result(
                run_id=run_id,
                status="accepted",
                legacy_result=sd,
                acceptance_report=accept_report,
                evidence_verifier_report=verification_report,
                reviewer_report=reviewer_report,
                evidence_path=evidence_path,
                duration_ms=accepted_result.duration_ms,
                executor_id=executor_id,
                commit_sha=sha,
                model=getattr(result, "model", "") or executor.get("model", ""),
                command_preview=getattr(result, "command_preview", None),
                prompt=getattr(result, "prompt", ""),
                dev_replay=dev_replay,
                diagnostics=getattr(adapter, "_last_diagnostics", None),
                base_sha=base_sha,
                parallel_execution=(getattr(result, "evidence", {}) or {}).get("parallel_execution"),
                tokens_in=getattr(result, "tokens_in", None),
                tokens_out=getattr(result, "tokens_out", None),
                cost_usd=getattr(result, "cost_usd", None),
            )
            _log.info(
                "adapter_execute_done",
                packet_id=packet_id,
                accepted=True,
                duration_ms=accepted_result.duration_ms,
            )
            return accepted_result

        def persist_rejected(domain_status, reason, verification_report, reviewer_report):
            dev_replay = adapter._build_dev_replay_metadata(
                packet_id=packet_id,
                run_id=run_id,
                run_number=rn,
                wt_path=wt_path,
                branch_name=result.branch_name or "",
                base_ref=base_ref,
                base_sha=base_sha,
                agent_commit_sha=sha,
                changed_files=changed_files,
                run_dir=run_dir,
                ar_path=ar_path,
                acceptance_report=accept_report,
                evr=verification_report,
                rvr=reviewer_report,
            )
            adapter._write_agent_patch(wt_path, run_dir, base_sha)
            rejected_result = make_result(False, domain_status, reason=reason, path="")
            diff_ref = adapter._capture_diff_patch_artifact(wt_path, run_dir, base_sha)
            ev_ref, meta_ref = adapter._capture_evidence_artifact(
                packet_id,
                run_id,
                rn,
                sha,
                changed_files,
                accept_report,
                verification_report,
                rejected_result,
            )
            refs = [ref for ref in (diff_ref, ev_ref, meta_ref) if ref is not None]
            adapter._obs_event(
                "packet.evidence_captured",
                status="completed",
                artifact_refs=refs if refs else None,
            )
            adapter._obs_event(
                "packet.execution_completed",
                status=domain_status,
                duration_ms=rejected_result.duration_ms,
            )
            evidence.update_run_result(
                run_id=run_id,
                status=domain_status,
                legacy_result=sd,
                acceptance_report=accept_report,
                evidence_verifier_report=verification_report,
                reviewer_report=reviewer_report,
                evidence_path="",
                duration_ms=rejected_result.duration_ms,
                executor_id=executor_id,
                model=getattr(result, "model", "") or executor.get("model", ""),
                command_preview=getattr(result, "command_preview", None),
                prompt=getattr(result, "prompt", ""),
                commit_sha=sha,
                dev_replay=dev_replay,
                diagnostics=getattr(adapter, "_last_diagnostics", None),
                base_sha=base_sha,
                parallel_execution=(getattr(result, "evidence", {}) or {}).get("parallel_execution"),
                tokens_in=getattr(result, "tokens_in", None),
                tokens_out=getattr(result, "tokens_out", None),
                cost_usd=getattr(result, "cost_usd", None),
            )
            from grace_control.config.settings import settings

            if not settings.dev_keep_failed_worktrees:
                try:
                    effective_target_root = adapter._effective_cleanup_root(executor)
                    adapter._terminal_cleanup.run(
                        packet_id=packet_id,
                        attempt=rn,
                        project_root=effective_target_root,
                    )
                except Exception as error:
                    _log.warn(
                        "terminal_cleanup_exception",
                        packet_id=packet_id,
                        state=domain_status,
                        error=str(error)[:200],
                    )
            _log.info(
                "adapter_execute_done",
                packet_id=packet_id,
                accepted=False,
                duration_ms=rejected_result.duration_ms,
            )
            return rejected_result

        if prof == AcceptanceProfile.FAST:
            return persist_accepted(
                make_result(True, "accepted"),
                skipped_evidence_report("FAST"),
                skipped_reviewer_report("FAST"),
            )
        verification_report = await facade.run_evidence_verifier(
            packet=pkt_contract,
            acceptance_report=accept_report,
            worktree_path=wt_path,
            run_dir=run_dir,
            changed_files=changed_files,
            artifacts=artifacts,
        )
        if verification_report.verdict in (
            EvidenceVerifierVerdict.REWORK_TO_CODER,
            EvidenceVerifierVerdict.RETURN_TO_ARCHITECT,
        ):
            if verification_report.verdict == EvidenceVerifierVerdict.REWORK_TO_CODER:
                adapter._maybe_create_rework_packet(
                    packet_id,
                    verdict_source="evidence_verifier",
                    summary=verification_report.summary,
                    blocking_issues=verification_report.failed_checks,
                    coder_instructions=verification_report.coder_instructions,
                    rework_base_sha=sha,
                )
            domain = (
                "rejected"
                if verification_report.verdict == EvidenceVerifierVerdict.REWORK_TO_CODER
                else "blocked"
            )
            return persist_rejected(
                domain,
                verification_report.summary,
                verification_report,
                skipped_reviewer_report("ev reject"),
            )

        reviewer_report = await facade.run_reviewer_gate(
            packet=pkt_contract,
            acceptance_report=accept_report,
            evidence_verifier_report=verification_report,
            worktree_path=wt_path,
            run_dir=run_dir,
            changed_files=changed_files,
            artifacts=artifacts,
        )
        if reviewer_report.verdict == ReviewerVerdict.PASS:
            return persist_accepted(
                make_result(True, "accepted"), verification_report, reviewer_report
            )
        if reviewer_report.verdict in (
            ReviewerVerdict.REWORK_TO_CODER,
            ReviewerVerdict.RETURN_TO_ARCHITECT,
        ):
            if reviewer_report.verdict == ReviewerVerdict.REWORK_TO_CODER:
                adapter._maybe_create_rework_packet(
                    packet_id,
                    verdict_source="reviewer",
                    summary=reviewer_report.summary,
                    blocking_issues=reviewer_report.required_changes,
                    coder_instructions=reviewer_report.risks,
                    rework_base_sha=sha,
                )
            domain = (
                "rejected"
                if reviewer_report.verdict == ReviewerVerdict.REWORK_TO_CODER
                else "blocked"
            )
            return persist_rejected(
                domain,
                reviewer_report.summary,
                verification_report,
                reviewer_report,
            )
        _log.error(
            "unexpected_reviewer_verdict",
            packet_id=packet_id,
            verdict=reviewer_report.verdict.value,
        )
        raise RuntimeError(f"Unexpected reviewer verdict: {reviewer_report.verdict.value}")

    # START_FUNCTION_CONTRACT
    # name: persist_run
    # purpose: Persist an acceptance-failed or controlled terminal packet run.
    # inputs: status, run/evidence identifiers, acceptance and verifier reports, base/worktree metadata.
    # returns: Rejected ExecutionResult with persisted evidence references.
    # side_effects: Writes replay metadata, patches, evidence, run status, and failed-worktree cleanup.
    # emitted_logs: Evidence captured, execution completed, cleanup, and adapter completion events.
    # error_behavior: Returns the constructed terminal result; cleanup failures are logged.
    # END_FUNCTION_CONTRACT
    def persist_run(
        self,
        adapter,
        status,
        run_id,
        executor,
        safe_data,
        accept_report,
        evr,
        rvr,
        dur,
        ar_path,
        packet_id,
        start,
        *,
        commit_sha="",
        wt_path=None,
        run_dir=None,
        changed_files=None,
        base_ref=None,
        base_sha=None,
    ):
        from grace_control.adapters.packet_executor import ExecutionResult

        er = ExecutionResult(
            accepted=status == "accepted",
            domain_status=accept_report.final_verdict.value if accept_report else "rejected",
            reason=accept_report.summary if accept_report else "",
            worktree_path="",
            branch_name="",
            acceptance_report_path=ar_path,
            acceptance_verdict=accept_report.final_verdict.value if accept_report else "rejected",
            acceptance_summary=accept_report.summary if accept_report else "",
            duration_ms=dur,
            commit_sha=commit_sha,
        )
        try:
            run_number = int(run_id.rsplit("-R", 1)[-1]) if run_id and "-R" in run_id else 1
        except ValueError:
            run_number = 1
        dev_replay = adapter._build_dev_replay_metadata(
            packet_id=packet_id,
            run_id=run_id,
            run_number=run_number,
            wt_path=wt_path,
            branch_name=safe_data.get("branch_name", ""),
            base_ref=base_ref,
            base_sha=base_sha,
            agent_commit_sha=commit_sha,
            changed_files=changed_files,
            run_dir=run_dir,
            ar_path=ar_path,
            acceptance_report=accept_report,
            evr=evr,
            rvr=rvr,
        )
        adapter._write_agent_patch(wt_path, run_dir, base_sha)
        diff_ref = adapter._capture_diff_patch_artifact(wt_path, run_dir, base_sha)
        ev_ref, meta_ref = adapter._capture_evidence_artifact(
            packet_id,
            run_id,
            run_number,
            commit_sha,
            changed_files,
            accept_report,
            evr,
            er,
        )
        refs = [ref for ref in (diff_ref, ev_ref, meta_ref) if ref is not None]
        adapter._obs_event(
            "packet.evidence_captured",
            status="completed",
            artifact_refs=refs if refs else None,
        )
        adapter._obs_event("packet.execution_completed", status=status, duration_ms=dur)
        parallel = (
            (safe_data or {}).get("evidence", {}).get("parallel_execution")
            if isinstance((safe_data or {}).get("evidence", {}), dict)
            else None
        )
        adapter._evidence.update_run_result(
            run_id=run_id,
            status=status,
            legacy_result=safe_data,
            acceptance_report=accept_report,
            evidence_verifier_report=evr,
            reviewer_report=rvr,
            evidence_path=er.evidence_path,
            duration_ms=er.duration_ms,
            executor_id=executor.get("executor_id", ""),
            commit_sha=commit_sha,
            dev_replay=dev_replay,
            diagnostics=getattr(adapter, "_last_diagnostics", None),
            base_sha=base_sha,
            parallel_execution=parallel,
            tokens_in=(safe_data or {}).get("tokens_in"),
            tokens_out=(safe_data or {}).get("tokens_out"),
            cost_usd=(safe_data or {}).get("cost_usd"),
        )
        from grace_control.config.settings import settings

        if (
            status in ("rejected", "failed", "blocked", "blocked_recoverable", "blocked_final")
            and not settings.dev_keep_failed_worktrees
        ):
            try:
                attempt = None
                if run_id and "-R" in run_id:
                    try:
                        attempt = int(run_id.rsplit("-R", 1)[-1])
                    except ValueError:
                        pass
                adapter._terminal_cleanup.run(
                    packet_id=packet_id,
                    attempt=attempt,
                    project_root=adapter._effective_cleanup_root(executor),
                )
            except Exception as error:
                _log.warn(
                    "terminal_cleanup_exception",
                    packet_id=packet_id,
                    state=status,
                    error=str(error)[:200],
                )
        _log.info(
            "adapter_execute_done",
            packet_id=packet_id,
            accepted=status == "accepted",
            duration_ms=dur,
        )
        return er

    # START_FUNCTION_CONTRACT
    # name: effective_cleanup_root
    # purpose: Resolve the target repository root used for terminal cleanup.
    # inputs: executor — selected executor profile and workspace options.
    # returns: Effective cleanup Path.
    # side_effects: None.
    # emitted_logs: None.
    # error_behavior: Uses configured project root when no override applies.
    # END_FUNCTION_CONTRACT
    def effective_cleanup_root(self, adapter, executor: dict) -> Path:
        from grace_control.config.settings import settings

        packet_repo = getattr(adapter, "_packet_target_repo", None) or settings.target_repo_root
        workspace_mode = executor.get("workspace_mode") or settings.workspace_mode or "full_git_worktree"
        if executor.get("minimal_repo"):
            workspace_mode = "scoped_copy"
        if workspace_mode == "target_repo_worktree":
            return Path(packet_repo or adapter.project_root)
        if packet_repo and str(packet_repo) != str(adapter.project_root):
            return Path(packet_repo)
        return adapter.project_root

    # START_FUNCTION_CONTRACT
    # name: fast_reject
    # purpose: Persist and return a minimal rejection before acceptance starts.
    # inputs: reason, executor/run identifiers, start time, optional failure code/stage.
    # returns: Rejected ExecutionResult.
    # side_effects: Persists diagnostics, emits failure events, and cleans failed worktrees.
    # emitted_logs: Pre-acceptance evidence and terminal cleanup events.
    # error_behavior: Best-effort evidence/cleanup failures are logged; rejection is returned.
    # END_FUNCTION_CONTRACT
    def fast_reject(
        self,
        adapter,
        reason,
        executor_id,
        run_id,
        start,
        failure_code: str | None = None,
        failure_stage: str | None = None,
    ):
        from grace_control.adapters.packet_executor import ExecutionResult

        er = ExecutionResult(
            accepted=False,
            domain_status="rejected",
            reason=reason,
            evidence_path="",
            duration_ms=int((time.time() - start) * 1000),
        )
        try:
            diagnostics = {
                "failure_stage": failure_stage or "pre_acceptance",
                "failure_class": classify_failure(
                    "", reason, None, failure_stage or "pre_acceptance"
                ),
                "stderr_tail": _redact_secrets(_tail(reason or "", _STDERR_TAIL_LIMIT)),
                "exit_code": None,
                "duration_ms": er.duration_ms,
            }
            if failure_code:
                diagnostics["failure_code"] = failure_code
        except Exception:
            diagnostics = {
                "failure_stage": failure_stage or "pre_acceptance",
                "failure_class": "unknown",
            }
        try:
            adapter._evidence.update_run_result(
                run_id=run_id,
                status="rejected",
                legacy_result={"error": "pre-acceptance failure", "reason": reason},
                acceptance_report=None,
                evidence_verifier_report=skipped_evidence_report(reason),
                reviewer_report=skipped_reviewer_report(reason),
                evidence_path="",
                duration_ms=er.duration_ms,
                executor_id=executor_id,
                diagnostics=diagnostics,
            )
        except Exception as error:
            _log.warn(
                "pre_acceptance_evidence_update_failed",
                run_id=run_id,
                error=str(error)[:500],
            )
        from grace_control.config.settings import settings

        if not settings.dev_keep_failed_worktrees:
            try:
                parts = run_id.rsplit("-R", 1)
                if len(parts) == 2:
                    packet_id, attempt = parts[0], int(parts[1])
                    from grace_control.config.agent_profiles import get_agent_profile

                    profile = get_agent_profile(executor_id)
                    executor_dict = profile.to_dict() if profile else {}
                    adapter._terminal_cleanup.run(
                        packet_id,
                        attempt=attempt,
                        project_root=adapter._effective_cleanup_root(executor_dict),
                    )
            except Exception as error:
                _log.warn(
                    "terminal_cleanup_failed",
                    run_id=run_id,
                    error=str(error)[:500],
                )
        adapter._obs_event("packet.execution_failed", status="rejected", message=reason[:200])
        return er

    # START_FUNCTION_CONTRACT
    # name: build_dev_replay_metadata
    # purpose: Build the stable replay metadata payload for a packet attempt.
    # inputs: Packet/run, worktree/base, changed files, acceptance, verifier, and reviewer data.
    # returns: Replay metadata dictionary.
    # side_effects: None.
    # emitted_logs: None.
    # error_behavior: Missing optional values are represented as empty metadata fields.
    # END_FUNCTION_CONTRACT
    def build_dev_replay_metadata(
        self,
        adapter,
        packet_id: str,
        run_id: str,
        run_number: int,
        wt_path: Path | None,
        branch_name: str | None,
        base_ref: str | None,
        base_sha: str | None,
        agent_commit_sha: str | None,
        changed_files: list[str] | None,
        run_dir: Path | None,
        ar_path: str | None,
        acceptance_report,
        evr,
        rvr,
    ) -> dict:
        del adapter
        failed_stage = None
        if acceptance_report and not acceptance_report.is_accepted:
            for stage in acceptance_report.stages:
                if stage.status.value == "failed":
                    failed_stage = stage.name.value
                    break
            if not failed_stage:
                failed_stage = "ACCEPTANCE"
        elif evr and hasattr(evr, "verdict") and evr.verdict in (
            "REWORK_TO_CODER",
            "RETURN_TO_ARCHITECT",
            "rework_required",
        ):
            failed_stage = "EVIDENCE_VERIFIER"
        elif rvr and hasattr(rvr, "verdict") and rvr.verdict in (
            "REWORK_TO_CODER",
            "RETURN_TO_ARCHITECT",
            "rework_required",
        ):
            failed_stage = "REVIEWER"

        return {
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

    # START_FUNCTION_CONTRACT
    # name: maybe_create_rework_packet
    # purpose: Create one idempotent rework packet for a verifier/reviewer rejection.
    # inputs: Original packet id, verdict source, summary, issues, instructions, and rework base SHA.
    # returns: None.
    # side_effects: Reads and writes Packet rows and commits a rework packet.
    # emitted_logs: Rework packet disabled, found, committed, and failure events.
    # error_behavior: Logs and absorbs rework creation failures to preserve terminal routing.
    # END_FUNCTION_CONTRACT
    def maybe_create_rework_packet(
        self,
        adapter,
        original_packet_id: str,
        *,
        verdict_source: str,
        summary: str,
        blocking_issues: list[str] | None = None,
        coder_instructions: list[str] | None = None,
        rework_base_sha: str = "",
    ) -> None:
        del adapter
        from grace_control.adapters import packet_executor as facade
        from grace_control.config.settings import settings as _s

        if not getattr(_s, "agent_runtime_rework_packets_enabled", True):
            _log.info("rework_packets_disabled", original_packet_id=original_packet_id)
            return
        try:
            with facade.get_db() as db:
                original = db.query(Packet).filter_by(id=original_packet_id).first()
                if not original:
                    _log.warn("rework_original_not_found", original_packet_id=original_packet_id)
                    return
                existing_rework = db.query(Packet).filter(
                    Packet.spec_json["origin"].as_string() == "review_rework",
                    Packet.spec_json["parent_packet_id"].as_string() == original_packet_id,
                    Packet.spec_json["rework_source"].as_string() == verdict_source,
                    Packet.state.in_(["ready", "running", "rejected", "accepted", "merged"]),
                ).first()
                if existing_rework is not None:
                    _log.info(
                        "rework_packet_already_exists",
                        original_packet_id=original_packet_id,
                        existing_rework_id=existing_rework.id,
                        verdict_source=verdict_source,
                    )
                    return

                facade.create_rework_packet(
                    db,
                    original_packet_id=original_packet_id,
                    feature_id=original.feature_id,
                    wave_id=original.wave_id,
                    original_spec=original.spec_json or {},
                    acceptance_profile=original.acceptance_profile or "NORMAL",
                    title=original.title or "",
                    slug=original.slug or "",
                    max_attempts=original.max_attempts or 3,
                    verdict_source=verdict_source,
                    summary=summary,
                    blocking_issues=blocking_issues or [],
                    coder_instructions=coder_instructions,
                    rework_base_sha=rework_base_sha,
                    parent_attempt_count=original.attempt_count or 1,
                )
                db.commit()
                _log.info(
                    "rework_packet_committed",
                    original_packet_id=original_packet_id,
                    verdict_source=verdict_source,
                )
        except Exception as error:
            _log.error(
                "rework_packet_creation_failed",
                original_packet_id=original_packet_id,
                error=str(error)[:300],
            )

    # START_FUNCTION_CONTRACT
    # name: write_agent_patch
    # purpose: Capture the agent diff into the run directory for replay/debugging.
    # inputs: Worktree path, run directory, and base SHA.
    # returns: None.
    # side_effects: Reads a Git diff and writes agent.patch.
    # emitted_logs: Agent patch written or write failure events.
    # error_behavior: Missing paths and Git/write failures are logged and ignored.
    # END_FUNCTION_CONTRACT
    def write_agent_patch(
        self,
        adapter,
        wt_path: Path | None,
        run_dir: Path | None,
        base_sha: str | None,
    ) -> None:
        del adapter
        if not wt_path or not run_dir or not base_sha:
            return
        if not wt_path.exists() or not run_dir.exists():
            return
        try:
            from grace_control.services.git_service import GitService

            result = GitService()._run(["diff", base_sha], wt_path, timeout=10)
            if result.success:
                patch_file = Path(run_dir) / "agent.patch"
                patch_file.write_text(result.stdout)
                _log.info("agent_patch_written", run_dir=str(run_dir))
        except Exception as error:
            _log.warn("agent_patch_write_failed", error=str(error)[:200])

# END_BLOCK_COMPLETION
