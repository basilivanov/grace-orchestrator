# ############################################################################
# AI_HEADER: architect_stage — execute Architect planning and prompt rendering
# ROLE: Owns Architect lifecycle, isolated execution, strict packet normalization,
#       prompt construction, and final plan persistence behind the stable facade.
# ############################################################################

# START_MODULE_CONTRACT
# purpose: Run the Architect stage and render the canonical planning prompt.
# inputs: Planning collaborators, feature/context data, target repository, and facade callbacks.
# returns: Normalized plan dictionary and prompt/fallback helper results.
# side_effects: Runs the configured LLM, writes logs/artifacts/events, and creates a disposable workspace.
# emitted_logs: architect_context_disabled, architect_mutated_planning_workspace.
# error_behavior: Retries one rejected response, then persists a safe fallback failed plan.
# END_MODULE_CONTRACT

# START_MODULE_MAP
# mapping:
#   - function: build_architect_prompt
#   - function: fallback_plan
#   - function: finalize_plan
#   - class: ArchitectStage
#     methods:
#       - run
# END_MODULE_MAP

from __future__ import annotations

import asyncio
import json
from datetime import UTC, datetime
from pathlib import Path

from grace_control.core.execution_environment import ExecutionEnvironment
from grace_control.core.structured_logger import GraceLogger
from grace_control.db.schema import Feature, FeaturePlanningRun
from grace_control.services.planning_run_support import (
    context_disabled,
    planning_log_paths,
    resolve_planning_workspace_root,
)

_log = GraceLogger("architect_stage")


# START_BLOCK_PROMPT_AND_FINALIZATION
def _format_environment_facts(environment: ExecutionEnvironment) -> str:
    """Render deterministic repository facts without adding semantic guesses."""
    lines = [
        "DETERMINISTIC ENVIRONMENT FACTS",
        "Python: " + (
            ", ".join(environment.python_candidates)
            if environment.python_candidates
            else "none detected"
        ),
        f"Shell: {environment.shell}",
    ]
    for label, values in (
        ("Executable scripts", environment.executable_scripts),
        ("Verification entrypoints", environment.verification_entrypoints),
        ("Compose services", environment.compose_services),
        ("Ignored patterns", environment.ignored_patterns),
        ("Config sources", environment.config_sources),
    ):
        lines.append(f"{label}:")
        lines.extend(f"- {value}" for value in values)
        if not values:
            lines.append("- none detected")
    return "\n".join(lines)


# START_FUNCTION_CONTRACT
# name: build_architect_prompt
# purpose: Render runtime context, deterministic environment facts, and the canonical Architect prompt.
# inputs: task — business requirement; context — collected code context; execution_environment — repository facts; runtime collaborators.
# returns: Complete Architect prompt string.
# side_effects: May load and emit knowledge-graph artifacts/events.
# emitted_logs: None; knowledge-graph service owns its events.
# error_behavior: Omits optional knowledge-graph content when no graph is available.
# END_FUNCTION_CONTRACT
def build_architect_prompt(
    task: str,
    context: dict,
    execution_environment: ExecutionEnvironment,
    *,
    trace_ctx,
    event_logger,
    artifact_store,
) -> str:
    """W03: Render the canonical Architect prompt with runtime context."""
    from grace_control.core.prompts import load_architect_prompt

    all_files = context.get("files", [])
    all_paths = "\n".join(f.get("path", "?") for f in all_files[:60])

    relevant_blocks = []
    other_files = []
    for file_data in all_files:
        if file_data.get("relevant") and file_data.get("content_preview"):
            relevant_blocks.append(
                f"### {file_data['path']} ({file_data.get('size_lines', '?')}L)\n"
                f"{file_data['content_preview'][:2500]}\n"
            )
        else:
            exports = ", ".join(file_data.get("exports", [])[:6])
            other_files.append(
                f"  {file_data['path']} ({file_data.get('size_lines', '?')}L) exports=[{exports}]"
            )

    relevants = "\n".join(relevant_blocks[:12])
    others = "\n".join(other_files[:40])

    prompt = f"""PRIMARY SOURCE OF TRUTH: the business requirement below. Codebase context is for reference only — do not generate packets unrelated to the requirement.

Business requirement: {task}

Codebase context:
- Summary: {context.get('summary', 'Unknown')}
- Complexity: {context.get('complexity_score', '?')}/300

{_format_environment_facts(execution_environment)}
"""

    if relevant_blocks:
        prompt += f"""
RELEVANT FILE CONTENT (study this code before planning):
{relevants}
"""
    if other_files:
        prompt += f"""
Other files (paths only):
{others}
"""

    target_root = context.get("target_repo_root")
    if target_root:
        from grace_control.services.grace_knowledge_graph_service import GraceKnowledgeGraphService

        kg_svc = GraceKnowledgeGraphService(
            trace=trace_ctx, event_logger=event_logger, artifact_store=artifact_store,
        )
        kg = kg_svc.load(Path(target_root))
        if kg:
            extract = kg_svc.extract_relevant_modules(
                kg,
                feature_text=task,
                context_paths=[file_data.get("path", "") for file_data in all_files],
            )
            kg_block = kg_svc.build_kg_prompt_block(
                extract, task,
                context_paths=[file_data.get("path", "") for file_data in all_files],
            )
            prompt += kg_block + "\n"

    prompt += f"""Full file listing for scope reference:
{all_paths}

"""
    prompt += load_architect_prompt()
    return prompt


# START_FUNCTION_CONTRACT
# name: fallback_plan
# purpose: Build the non-executable plan recorded when Architect execution is unavailable.
# inputs: feature_id — feature identifier; task_desc — feature description.
# returns: Safe failed-plan dictionary with no executable coder packets.
# side_effects: None.
# emitted_logs: None.
# error_behavior: Always returns a non-executable fallback plan.
# END_FUNCTION_CONTRACT
def fallback_plan(feature_id: str, task_desc: str) -> dict:
    del task_desc
    return {
        "waves": [],
        "summary": f"PLAN_FAILED: architect LLM unavailable for feature {feature_id}",
        "constraints": {"frozen_scope": []},
        "verification": {"t0": [], "t1": [], "t2": []},
        "_fallback": True,
        "_fallback_reason": "architect_llm_unavailable",
    }


# START_FUNCTION_CONTRACT
# name: finalize_plan
# purpose: Persist the Architect result, feature status, and terminal lifecycle events.
# inputs: db — planning database; trace collaborators; feature_id, plan, run, run_id.
# returns: None.
# side_effects: Updates feature/run records, emits events, and commits the database transaction.
# emitted_logs: None; event logger and facade event callback own observability.
# error_behavior: Propagates database or event persistence errors.
# END_FUNCTION_CONTRACT
def finalize_plan(
    db,
    feature_id: str,
    plan: dict,
    arch_run: FeaturePlanningRun,
    run_id: str,
    *,
    emit_event,
) -> None:
    arch_run.finished_at = datetime.now(UTC)
    if arch_run.started_at:
        arch_run.duration_ms = int((arch_run.finished_at - arch_run.started_at).total_seconds() * 1000)
    else:
        arch_run.duration_ms = 0

    feature = db.query(Feature).filter_by(id=feature_id).first()
    if feature:
        spec = dict(feature.spec_json) if feature.spec_json else {}
        spec["plan_json"] = plan
        feature.spec_json = spec
        feature.status = "PLAN_READY" if arch_run.status == "done" else "PLAN_FAILED"

    emit_event(feature_id, "architect_completed" if arch_run.status == "done" else "architect_failed", {
        "run_id": run_id, "duration_ms": arch_run.duration_ms, "waves_count": len(plan.get("waves", [])),
    })
    if arch_run.status == "done":
        emit_event(feature_id, "plan_ready", {
            "waves_count": len(plan.get("waves", [])),
        })

    db.commit()
# END_BLOCK_PROMPT_AND_FINALIZATION


# START_BLOCK_ARCHITECT
class ArchitectStage:
    """Execute an Architect run using facade-provided compatibility callbacks."""

    def __init__(
        self,
        *,
        db,
        trace_ctx,
        artifact_store,
        event_logger,
        heartbeat_worker,
        normalize_plan,
        build_prompt,
        fallback_plan_builder,
        finalize_plan_callback,
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
        self._normalize_plan = normalize_plan
        self._build_prompt = build_prompt
        self._fallback_plan = fallback_plan_builder
        self._finalize_plan = finalize_plan_callback
        self._git_snapshot = git_snapshot
        self._prepare_workspace = prepare_workspace
        self._workspace_mutation = workspace_mutation
        self._remove_workspace = remove_workspace

    # START_FUNCTION_CONTRACT
    # name: run
    # purpose: Execute Architect, retry rejected responses, and return the persisted normalized plan.
    # inputs: feature_id — feature identifier; context — Context Builder result; target_repo_root — optional target root.
    # returns: Normalized Architect plan dictionary.
    # side_effects: Writes planning run state, prompt/raw/parsed artifacts, events, logs, and a disposable workspace.
    # emitted_logs: architect_context_disabled, architect_mutated_planning_workspace.
    # error_behavior: Retries once after a rejected response and falls back to a failed non-executable plan.
    # END_FUNCTION_CONTRACT
    async def run(self, feature_id: str, context: dict, target_repo_root: str | None = None) -> dict:
        arch_run = self.db.query(FeaturePlanningRun).filter_by(
            feature_id=feature_id, stage="architect"
        ).order_by(FeaturePlanningRun.created_at.desc()).first()

        now = datetime.now(UTC)
        from grace_control.core.uid import generate_unique_id, new_run_uid

        run_id = arch_run.id if arch_run else generate_unique_id(self.db, FeaturePlanningRun, new_run_uid)
        if not arch_run:
            arch_run = FeaturePlanningRun(id=run_id, feature_id=feature_id, stage="architect", status="pending")
            self.db.add(arch_run)

        feature = self.db.query(Feature).filter_by(id=feature_id).first()
        task_desc = (feature.description or feature.title or "") if feature else ""

        arch_run.status = "running"
        arch_run.started_at = now
        arch_run.executor_id = "architect-mini-swe-deepseek"
        arch_run.prompt = task_desc[:2000]

        from grace_control.config.settings import settings

        log_dir, stdout_path, stderr_path = planning_log_paths(feature_id, run_id)
        arch_run.stdout_path = stdout_path
        arch_run.stderr_path = stderr_path
        self.db.commit()

        self._trace_ctx.feature_id = feature_id
        self._trace_ctx.stage = "architect"
        self._event_logger.emit(
            trace=self._trace_ctx, event="architect.started", stage="architect",
            component="FeaturePlanningService", status="running",
        )

        try:
            if context_disabled():
                plan = self._fallback_plan(feature_id, task_desc)
                arch_run.status = "done"
                arch_run.executor_id = "architect-disabled"
                arch_run.model = "disabled"
                arch_run.result_json = plan
                _log.info("architect_context_disabled", feature_id=feature_id)
                self._finalize_plan(feature_id, plan, arch_run, run_id)
                return plan

            self._event_logger.emit(
                trace=self._trace_ctx, event="architect.prompt_build_started", stage="architect",
                component="FeaturePlanningService", status="running",
            )
            worktree_root = resolve_planning_workspace_root(
                target_repo_root, context, settings,
            )
            from grace_control.core.execution_environment import probe_execution_environment

            execution_environment = probe_execution_environment(
                target_repo_root=Path(worktree_root),
            )
            prompt = self._build_prompt(task_desc, context, execution_environment)
            prompt_ref = self._artifact_store.write_text(
                trace=self._trace_ctx, stage="architect", name="prompt.txt",
                content=prompt, kind="prompt",
            )
            self._event_logger.emit(
                trace=self._trace_ctx, event="architect.prompt_built", stage="architect",
                component="FeaturePlanningService", status="completed",
                artifact_refs=[prompt_ref],
            )

            architect_root: Path | None = None
            heartbeat_task = asyncio.create_task(self._heartbeat_worker(run_id, interval_s=5.0))
            try:
                if worktree_root:
                    architect_root = self._prepare_workspace(
                        Path(worktree_root), log_dir, "architect",
                    )
                architect_pre_snapshot = (
                    self._git_snapshot(architect_root) if architect_root else None
                )
                for attempt in range(2):
                    try:
                        from grace_control.core.llm_runner import run_llm
                        from grace_control.core.executor_selector import resolve_model

                        executor = resolve_model("architect")
                        raw = await run_llm(
                            prompt, role="architect",
                            model=executor["model"],
                            cli=executor["executor_id"],
                            cwd=architect_root,
                            session_dir=Path(log_dir),
                            stdout_log_path=arch_run.stdout_path,
                            stderr_log_path=arch_run.stderr_path,
                        )
                        mutation_evidence = self._workspace_mutation(
                            architect_pre_snapshot,
                            self._git_snapshot(architect_root) if architect_root else None,
                        )
                        if mutation_evidence is not None:
                            _log.error(
                                "architect_mutated_planning_workspace",
                                feature_id=feature_id,
                                mutation_evidence=mutation_evidence,
                            )
                            raise RuntimeError(
                                "architect mutated isolated planning workspace"
                            )
                        raw_ref = self._artifact_store.write_text(
                            trace=self._trace_ctx, stage="architect", name="raw_response.txt",
                            content=raw, kind="raw_response",
                        )
                        self._event_logger.emit(
                            trace=self._trace_ctx, event="architect.raw_response_captured", stage="architect",
                            component="FeaturePlanningService", status="completed",
                            artifact_refs=[raw_ref],
                        )

                        plan = json.loads(raw)
                        plan = self._normalize_plan(
                            plan,
                            require_current_contract=True,
                        )
                        self._artifact_store.write_json(
                            trace=self._trace_ctx, stage="architect", name="parsed_plan.json",
                            payload=plan, kind="parsed_plan",
                        )
                        self._event_logger.emit(
                            trace=self._trace_ctx, event="architect.parsed_plan_captured", stage="architect",
                            component="FeaturePlanningService", status="completed",
                        )

                        arch_run.status = "done"
                        arch_run.executor_id = executor["executor_id"]
                        arch_run.model = executor["model"]
                        arch_run.result_json = plan
                        break
                    except Exception as e:
                        if attempt == 1:
                            raise
                        prompt += (
                            "\n\n[Previous architect attempt was rejected: "
                            f"{str(e)[:200]}. Return one valid JSON object that "
                            "matches the current architect packet contract.]"
                        )
            finally:
                heartbeat_task.cancel()
                try:
                    await heartbeat_task
                except (asyncio.CancelledError, Exception):
                    pass
                self._remove_workspace(architect_root)

        except Exception as e:
            plan = self._fallback_plan(feature_id, task_desc)
            arch_run.status = "failed"
            arch_run.error = str(e)[:500]
            arch_run.result_json = plan
            self._event_logger.emit(
                trace=self._trace_ctx, event="architect.failed", stage="architect",
                component="FeaturePlanningService", status="failed",
                payload={"error": str(e)[:200]},
            )

        self._finalize_plan(feature_id, plan, arch_run, run_id)
        return plan
# END_BLOCK_ARCHITECT
