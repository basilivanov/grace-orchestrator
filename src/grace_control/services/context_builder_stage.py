# ############################################################################
# AI_HEADER: context_builder_stage — execute isolated Context Builder planning
# ROLE: Owns the Context Builder lifecycle, artifact/event emission, heartbeat,
#       and mutation guard while FeaturePlanningService remains the stable facade.
# ############################################################################

# START_MODULE_CONTRACT
# purpose: Run Context Builder in a disposable planning workspace and persist its lifecycle.
# inputs: Database/session collaborators, runtime observability collaborators, feature id, target root.
# returns: Normalized context dictionary with selected files and summary metadata.
# side_effects: Creates planning runs/logs/artifacts/events and a disposable repository copy.
# emitted_logs: context_builder_pre_snapshot_dirty, CONTEXT_BUILDER_MUTATED_TARGET_REPO.
# error_behavior: Returns fallback context on ordinary failures; re-raises mutation-guard failures.
# END_MODULE_CONTRACT

# START_MODULE_MAP
# mapping:
#   - class: CONTEXT_BUILDER_MUTATED_TARGET_REPO
#   - class: ContextBuilderStage
#     methods:
#       - run
# END_MODULE_MAP

from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from pathlib import Path

from grace_control.core.structured_logger import GraceLogger
from grace_control.db.schema import Feature, FeaturePlanningRun
from grace_control.services.planning_run_support import (
    planning_log_paths,
    resolve_planning_workspace_root,
)

_log = GraceLogger("context_builder_stage")

_CONTENT_PREVIEW_CHARS = 2500
_MAX_RELEVANT_FILES = 15


# START_BLOCK_CONTEXT_BUILDER
class CONTEXT_BUILDER_MUTATED_TARGET_REPO(Exception):
    """Raised when Context Builder mutates its isolated planning workspace."""


class ContextBuilderStage:
    """Execute the Context Builder stage behind the planning facade."""

    def __init__(
        self,
        *,
        db,
        trace_ctx,
        artifact_store,
        event_logger,
        heartbeat_worker,
        emit_event,
        git_snapshot,
        prepare_workspace,
        workspace_mutation,
        remove_workspace,
    ):
        self.db = db
        self._trace_ctx = trace_ctx
        self._artifact_store = artifact_store
        self._event_logger = event_logger
        self._heartbeat_worker = heartbeat_worker
        self._emit_event = emit_event
        self._git_snapshot = git_snapshot
        self._prepare_workspace = prepare_workspace
        self._workspace_mutation = workspace_mutation
        self._remove_workspace = remove_workspace

    # START_FUNCTION_CONTRACT
    # name: run
    # purpose: Execute Context Builder and return collected context with lifecycle state.
    # inputs: feature_id — feature identifier; target_repo_root — optional target repository root.
    # returns: Context dictionary containing summary, complexity, files, and target root.
    # side_effects: Writes planning run state, logs, runtime artifacts/events, and disposable workspace files.
    # emitted_logs: context_builder_pre_snapshot_dirty, CONTEXT_BUILDER_MUTATED_TARGET_REPO.
    # error_behavior: Returns fallback context for ordinary failures and re-raises mutation evidence.
    # END_FUNCTION_CONTRACT
    async def run(self, feature_id: str, target_repo_root: str | None = None) -> dict:
        cb_run = self.db.query(FeaturePlanningRun).filter_by(
            feature_id=feature_id, stage="context_builder"
        ).order_by(FeaturePlanningRun.created_at.desc()).first()

        now = datetime.now(UTC)
        from grace_control.core.uid import generate_unique_id, new_run_uid

        run_id = cb_run.id if cb_run else generate_unique_id(self.db, FeaturePlanningRun, new_run_uid)
        if not cb_run:
            cb_run = FeaturePlanningRun(id=run_id, feature_id=feature_id, stage="context_builder", status="pending")
            self.db.add(cb_run)

        cb_run.status = "running"
        cb_run.started_at = now
        cb_run.executor_id = "context_collector"

        log_dir, stdout_path, stderr_path = planning_log_paths(feature_id, run_id)
        cb_run.stdout_path = stdout_path
        cb_run.stderr_path = stderr_path
        self.db.commit()

        feature = self.db.query(Feature).filter_by(id=feature_id).first()
        task_desc = (feature.description or feature.title or "") if feature else ""

        # ── Runtime observability: trace + events ──
        self._trace_ctx.feature_id = feature_id
        self._trace_ctx.runtime_run_id = run_id
        self._trace_ctx.stage = "feature"
        self._event_logger.emit(
            trace=self._trace_ctx, event="feature.trace_started", stage="feature",
            component="FeaturePlanningService", status="started",
            payload={"feature_id": feature_id},
        )
        self._event_logger.emit(
            trace=self._trace_ctx, event="feature.input_captured", stage="feature",
            component="FeaturePlanningService", status="completed",
            payload={"task_desc": task_desc[:200]},
        )
        self._event_logger.emit(
            trace=self._trace_ctx, event="feature.target_repo_resolved", stage="feature",
            component="FeaturePlanningService", status="completed",
            payload={"target_repo_root": target_repo_root},
        )

        from grace_control.config.settings import settings

        worktree_root = resolve_planning_workspace_root(
            target_repo_root, None, settings,
        )
        root = Path(worktree_root).resolve()
        pre_snapshot = self._git_snapshot(root)
        if pre_snapshot and not pre_snapshot["is_clean"]:
            _log.warn(
                "context_builder_pre_snapshot_dirty",
                feature_id=feature_id,
                status=pre_snapshot["status_short"][:200],
            )

        self._event_logger.emit(
            trace=self._trace_ctx, event="context_builder.started", stage="context_builder",
            component="FeaturePlanningService", status="running",
        )

        agent_root: Path | None = None
        try:
            agent_root = self._prepare_workspace(root, log_dir, "context-builder")
            agent_pre_snapshot = self._git_snapshot(agent_root)
            spec = feature.spec_json or {} if feature else {}
            scope = spec.get("scope") if isinstance(spec, dict) else None

            self._event_logger.emit(
                trace=self._trace_ctx, event="context_builder.input_captured", stage="context_builder",
                component="FeaturePlanningService", status="completed",
                payload={"target_repo_root": str(root), "scope": scope, "model": "", "executor_id": "context_collector"},
            )
            feature_input = {"task_desc": task_desc[:500], "scope": scope, "target_repo_root": str(root)}
            self._artifact_store.write_json(
                trace=self._trace_ctx, stage="feature", name="feature_input.json",
                payload=feature_input, kind="feature_input",
            )

            from grace_control.core.context_collector import ContextCollector
            from grace_control.core.executor_selector import resolve_model

            ctx_model = resolve_model("context_collector")
            collector = ContextCollector(
                project_root=agent_root,
                model=ctx_model.get("model"),
                cli=ctx_model.get("command", ""),
                executor_id=ctx_model.get("executor_id"),
                stdout_log_path=stdout_path,
                stderr_log_path=stderr_path,
            )
            heartbeat_task = asyncio.create_task(self._heartbeat_worker(run_id, interval_s=5.0))
            try:
                code_ctx = await collector.collect(
                    task_description=task_desc,
                    target_scope=scope,
                    project_root=agent_root,
                )
            finally:
                heartbeat_task.cancel()
                try:
                    await heartbeat_task
                except (asyncio.CancelledError, Exception):
                    pass

            context = {
                "summary": code_ctx.summary,
                "estimated_scope": code_ctx.estimated_scope,
                "complexity_score": code_ctx.complexity_score,
                "file_count": len(code_ctx.files),
                "files": [
                    {
                        "path": f.path,
                        "size_lines": f.size_lines,
                        "exports": f.exports[:8],
                        "content_preview": f.content_preview[:_CONTENT_PREVIEW_CHARS] if f.content_preview else "",
                        "relevant": f.relevant,
                    }
                    for f in code_ctx.files[:_MAX_RELEVANT_FILES]
                ],
                "target_repo_root": str(root.resolve()),
            }
            cb_run.status = "done"
            cb_run.model = ctx_model.get("model", "")

            self._artifact_store.write_json(
                trace=self._trace_ctx, stage="context_builder", name="input.json",
                payload={"target_repo_root": str(root), "scope": scope, "executor_id": "context_collector"},
                kind="context_input",
            )
            self._artifact_store.write_json(
                trace=self._trace_ctx, stage="context_builder", name="output.json",
                payload=context, kind="context_output",
            )
            files_artifact = {
                "file_count": len(code_ctx.files),
                "selected_files": [f.path for f in code_ctx.files[:_MAX_RELEVANT_FILES] if f.relevant],
                "summary": code_ctx.summary,
                "complexity_score": code_ctx.complexity_score,
            }
            self._artifact_store.write_json(
                trace=self._trace_ctx, stage="context_builder", name="files.json",
                payload=files_artifact, kind="context_files",
            )
            self._event_logger.emit(
                trace=self._trace_ctx, event="context_builder.output_captured", stage="context_builder",
                component="FeaturePlanningService", status="completed",
                payload={"file_count": len(code_ctx.files), "complexity_score": code_ctx.complexity_score},
            )
            self._event_logger.emit(
                trace=self._trace_ctx, event="context_builder.completed", stage="context_builder",
                component="FeaturePlanningService", status="completed",
            )

            mutation_evidence = self._workspace_mutation(
                agent_pre_snapshot,
                self._git_snapshot(agent_root),
            )
            if mutation_evidence is not None:
                evidence_dir = Path(log_dir)
                evidence_dir.mkdir(parents=True, exist_ok=True)
                (evidence_dir / "context-builder-status.txt").write_text(
                    mutation_evidence.get("status_short", "")
                )
                _log.error(
                    "CONTEXT_BUILDER_MUTATED_TARGET_REPO",
                    feature_id=feature_id,
                    mutation_evidence=mutation_evidence,
                )
                cb_run.status = "failed"
                cb_run.error = "CONTEXT_BUILDER_MUTATED_TARGET_REPO"
                raise CONTEXT_BUILDER_MUTATED_TARGET_REPO(
                    "context-builder mutated its isolated planning workspace; "
                    f"target repo remained untouched at {root}. "
                    f"Evidence saved in {evidence_dir}"
                )
        except Exception as e:
            if isinstance(e, CONTEXT_BUILDER_MUTATED_TARGET_REPO):
                cb_run.finished_at = datetime.now(UTC)
                cb_run.duration_ms = int((cb_run.finished_at - cb_run.started_at).total_seconds() * 1000)
                cb_run.result_json = {
                    "summary": str(e)[:200], "file_count": 0, "files": [],
                    "error": "CONTEXT_BUILDER_MUTATED_TARGET_REPO",
                }
                self._event_logger.emit(
                    trace=self._trace_ctx, event="context_builder.failed", stage="context_builder",
                    component="FeaturePlanningService", status="failed",
                    payload={"reason": "CONTEXT_BUILDER_MUTATED_TARGET_REPO"},
                )
                self._emit_event(feature_id, "context_builder_failed", {
                    "run_id": run_id, "duration_ms": cb_run.duration_ms, "status": "failed",
                    "reason": "CONTEXT_BUILDER_MUTATED_TARGET_REPO",
                })
                self.db.commit()
                raise
            context = {
                "summary": f"Fallback: {task_desc[:200]}",
                "file_count": 0,
                "files": [],
                "error": str(e)[:200],
            }
            cb_run.status = "failed"
            cb_run.error = str(e)[:500]
        finally:
            self._remove_workspace(agent_root)

        cb_run.finished_at = datetime.now(UTC)
        cb_run.duration_ms = int((cb_run.finished_at - cb_run.started_at).total_seconds() * 1000)
        cb_run.result_json = context

        if cb_run.status == "failed":
            self._event_logger.emit(
                trace=self._trace_ctx, event="context_builder.failed", stage="context_builder",
                component="FeaturePlanningService", status="failed",
                payload={"error": cb_run.error[:200]},
            )

        self._emit_event(
            feature_id,
            "context_builder_completed" if cb_run.status == "done" else "context_builder_failed",
            {"run_id": run_id, "duration_ms": cb_run.duration_ms, "status": cb_run.status},
        )
        self.db.commit()
        return context
# END_BLOCK_CONTEXT_BUILDER
