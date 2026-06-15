# ############################################################################
# AI_HEADER: feature_planning_service
# ROLE: Feature planning orchestration — context builder, architect, approval
# ############################################################################

from __future__ import annotations

import asyncio
import json
import subprocess
import uuid
from datetime import UTC, datetime
from pathlib import Path

from grace_control.core.structured_logger import GraceLogger

_log = GraceLogger("feature_planning")

from grace_control.core.uid import generate_unique_id, new_wave_uid, new_packet_uid, new_run_uid
from grace_control.db import get_db
from grace_control.db.schema import Feature, FeaturePlanningRun, Wave, Packet, Event
from grace_control.db.schema import PacketState

_CONTENT_PREVIEW_CHARS = 2500
_MAX_RELEVANT_FILES = 15


class CONTEXT_BUILDER_MUTATED_TARGET_REPO(Exception):
    """Raised when context-builder mutates files in the target repo."""


def _git_snapshot(repo_root: Path) -> dict | None:
    """Return a snapshot of HEAD SHA and changed files for a git repo.

    Returns None if repo_root is not a git repo.
    """
    try:
        head = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=str(repo_root), capture_output=True, text=True, timeout=10,
        )
        if head.returncode != 0:
            return None
        status = subprocess.run(
            ["git", "status", "--short"],
            cwd=str(repo_root), capture_output=True, text=True, timeout=10,
        )
        return {
            "head": head.stdout.strip(),
            "status_short": status.stdout.strip(),
            "is_clean": status.stdout.strip() == "",
        }
    except Exception:
        return None


def _git_reset_hard(repo_root: Path, head_sha: str) -> None:
    """Reset target repo to a known clean state."""
    try:
        subprocess.run(["git", "reset", "--hard", head_sha],
                        cwd=str(repo_root), capture_output=True, text=True, timeout=30)
        subprocess.run(["git", "clean", "-fd"],
                        cwd=str(repo_root), capture_output=True, text=True, timeout=30)
    except Exception:
        pass


def normalize_architect_plan(plan: dict) -> dict:
    """Normalize a raw architect plan dict into canonical form.

    This is the shared normalization path used by run_architect() before
    the plan is persisted or passed to the compiler.  It:

    1. Unwraps nested ``plan.waves`` if the LLM wrapped its output.
    2. Wraps bare ``packets`` into a single wave.
    3. Ensures every wave has a ``packets`` list.
    4. Sets ``acceptance_profile`` / ``depends_on`` defaults.
    5. **W03**: Canonicalizes legacy packet fields (``allowed_files`` →
       ``scope``, etc.) with visible warnings.
    6. **W03**: Persists canonicalization warnings under
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

    for wi, w in enumerate(plan.get("waves", [])):
        if "packets" not in w:
            w["packets"] = []
        for pi, pkt in enumerate(w["packets"]):
            # W02: Do NOT setdefault("scope", []) — empty
            # scope must be caught by the plan compiler as
            # E_CODER_EMPTY_SCOPE, not hidden by a default.
            pkt.setdefault("acceptance_profile", "NORMAL")
            pkt.setdefault("depends_on", [])

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

    # W03: Persist canonicalization warnings on the plan so they are
    # visible in parsed_plan.json and downstream artifacts.
    if _schema_warnings:
        plan["_architect_schema_warnings"] = _schema_warnings

    plan.setdefault("constraints", {})
    plan.setdefault("verification", {"t0": [], "t1": [], "t2": []})

    return plan


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

    async def run_context_builder(self, feature_id: str, target_repo_root: str | None = None) -> dict:
        cb_run = self.db.query(FeaturePlanningRun).filter_by(
            feature_id=feature_id, stage="context_builder"
        ).order_by(FeaturePlanningRun.created_at.desc()).first()

        now = datetime.now(UTC)
        run_id = cb_run.id if cb_run else generate_unique_id(self.db, FeaturePlanningRun, new_run_uid)
        if not cb_run:
            cb_run = FeaturePlanningRun(id=run_id, feature_id=feature_id, stage="context_builder", status="pending")
            self.db.add(cb_run)

        cb_run.status = "running"
        cb_run.started_at = now
        cb_run.executor_id = "context_collector"

        # Set up live log paths
        from grace_control.config.settings import settings as _ctx_settings
        _log_root = Path(_ctx_settings.planning_logs_root)
        log_dir = _log_root / feature_id / run_id
        log_dir.mkdir(parents=True, exist_ok=True)
        stdout_path = str(log_dir / "stdout.log")
        stderr_path = str(log_dir / "stderr.log")
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

        # ── Mutation guard: pre-snapshot target repo ──
        worktree_root = target_repo_root or _ctx_settings.target_repo_root or "."
        root = Path(worktree_root)
        pre_snapshot = _git_snapshot(root)
        if pre_snapshot and not pre_snapshot["is_clean"]:
            _log.warn("context_builder_pre_snapshot_dirty",
                       feature_id=feature_id, status=pre_snapshot["status_short"][:200])

        self._event_logger.emit(
            trace=self._trace_ctx, event="context_builder.started", stage="context_builder",
            component="FeaturePlanningService", status="running",
        )

        try:
            # Determine scope from feature spec_json
            spec = feature.spec_json or {} if feature else {}
            scope = spec.get("scope") if isinstance(spec, dict) else None

            self._event_logger.emit(
                trace=self._trace_ctx, event="context_builder.input_captured", stage="context_builder",
                component="FeaturePlanningService", status="completed",
                payload={"target_repo_root": str(root), "scope": scope, "model": "", "executor_id": "context_collector"},
            )
            # Persist feature_input.json
            feature_input = {"task_desc": task_desc[:500], "scope": scope, "target_repo_root": str(root)}
            self._artifact_store.write_json(
                trace=self._trace_ctx, stage="feature", name="feature_input.json",
                payload=feature_input, kind="feature_input",
            )

            from grace_control.core.context_collector import ContextCollector
            from grace_control.core.executor_selector import resolve_model

            ctx_model = resolve_model("context_collector")
            collector = ContextCollector(
                project_root=root,
                model=ctx_model.get("model"),
                cli=ctx_model.get("command", "opencode"),
                executor_id=ctx_model.get("executor_id"),
                stdout_log_path=stdout_path,
                stderr_log_path=stderr_path,
            )
            _hb_task = asyncio.create_task(self._heartbeat_worker(run_id, interval_s=5.0))
            try:
                code_ctx = await collector.collect(
                    task_description=task_desc,
                    target_scope=scope,
                    project_root=root,
                )
            finally:
                _hb_task.cancel()
                try:
                    await _hb_task
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

            # ── Runtime observability: context_builder artifacts + events ──
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

            # ── Mutation guard: post-run check ──
            post_snapshot = _git_snapshot(root)
            if post_snapshot and pre_snapshot and pre_snapshot["is_clean"]:
                if not post_snapshot["is_clean"]:
                    diff_result = subprocess.run(
                        ["git", "diff", "--exit-code"],
                        cwd=str(root), capture_output=True, text=True, timeout=30,
                    )
                    status_result = subprocess.run(
                        ["git", "status", "--short"],
                        cwd=str(root), capture_output=True, text=True, timeout=10,
                    )
                    mutation_evidence = {
                        "pre_head": pre_snapshot["head"],
                        "post_head": post_snapshot["head"],
                        "diff_exit_code": diff_result.returncode,
                        "status_short": status_result.stdout.strip()[:2000],
                        "diff_stdout": diff_result.stdout[:4000] if diff_result.stdout else "",
                        "diff_stderr": diff_result.stderr[:1000] if diff_result.stderr else "",
                    }
                    # Save mutation evidence to planning log dir
                    evidence_dir = Path(log_dir)
                    evidence_dir.mkdir(parents=True, exist_ok=True)
                    (evidence_dir / "context-builder-diff.txt").write_text(
                        diff_result.stdout if diff_result.stdout else ""
                    )
                    (evidence_dir / "context-builder-status.txt").write_text(
                        status_result.stdout
                    )
                    _log.error("CONTEXT_BUILDER_MUTATED_TARGET_REPO",
                               feature_id=feature_id,
                               mutation_evidence=mutation_evidence)
                    # Reset target repo to clean state
                    _git_reset_hard(root, pre_snapshot["head"])
                    # Mark planning run failed and raise
                    cb_run.status = "failed"
                    cb_run.error = "CONTEXT_BUILDER_MUTATED_TARGET_REPO"
                    raise CONTEXT_BUILDER_MUTATED_TARGET_REPO(
                        f"context-builder mutated target repo at {root}. "
                        f"Repo has been reset to pre-run state. "
                        f"Evidence saved in {evidence_dir}"
                    )
        except Exception as e:
            if isinstance(e, CONTEXT_BUILDER_MUTATED_TARGET_REPO):
                # Mutation guard: re-raise after cleanup is already done above
                cb_run.finished_at = datetime.now(UTC)
                cb_run.duration_ms = int((cb_run.finished_at - cb_run.started_at).total_seconds() * 1000)
                cb_run.result_json = {"summary": str(e)[:200], "file_count": 0, "files": [], "error": "CONTEXT_BUILDER_MUTATED_TARGET_REPO"}
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

        cb_run.finished_at = datetime.now(UTC)
        cb_run.duration_ms = int((cb_run.finished_at - cb_run.started_at).total_seconds() * 1000)
        cb_run.result_json = context

        if cb_run.status == "failed":
            self._event_logger.emit(
                trace=self._trace_ctx, event="context_builder.failed", stage="context_builder",
                component="FeaturePlanningService", status="failed",
                payload={"error": cb_run.error[:200]},
            )

        self._emit_event(feature_id, "context_builder_completed" if cb_run.status == "done" else "context_builder_failed", {
            "run_id": run_id, "duration_ms": cb_run.duration_ms, "status": cb_run.status,
        })

        self.db.commit()
        return context

    async def run_architect(self, feature_id: str, context: dict, target_repo_root: str | None = None) -> dict:
        arch_run = self.db.query(FeaturePlanningRun).filter_by(
            feature_id=feature_id, stage="architect"
        ).order_by(FeaturePlanningRun.created_at.desc()).first()

        now = datetime.now(UTC)
        run_id = arch_run.id if arch_run else generate_unique_id(self.db, FeaturePlanningRun, new_run_uid)
        if not arch_run:
            arch_run = FeaturePlanningRun(id=run_id, feature_id=feature_id, stage="architect", status="pending")
            self.db.add(arch_run)

        feature = self.db.query(Feature).filter_by(id=feature_id).first()
        task_desc = (feature.description or feature.title or "") if feature else ""

        arch_run.status = "running"
        arch_run.started_at = now
        arch_run.executor_id = "deepseek-v4-pro"
        arch_run.prompt = task_desc[:2000]

        # Set up live log paths
        from grace_control.config.settings import settings as _arch_settings
        _log_root = Path(_arch_settings.planning_logs_root)
        log_dir = _log_root / feature_id / run_id
        log_dir.mkdir(parents=True, exist_ok=True)
        stdout_path = str(log_dir / "stdout.log")
        stderr_path = str(log_dir / "stderr.log")
        arch_run.stdout_path = stdout_path
        arch_run.stderr_path = stderr_path
        self.db.commit()

        # ── Runtime observability: architect ──
        self._trace_ctx.feature_id = feature_id
        self._trace_ctx.stage = "architect"
        self._event_logger.emit(
            trace=self._trace_ctx, event="architect.started", stage="architect",
            component="FeaturePlanningService", status="running",
        )

        try:
            # Build prompt — reuses the same prompt structure as _call_architect_llm
            self._event_logger.emit(
                trace=self._trace_ctx, event="architect.prompt_build_started", stage="architect",
                component="FeaturePlanningService", status="running",
            )
            prompt = self._build_architect_prompt(task_desc, context)
            # Persist prompt artifact
            prompt_ref = self._artifact_store.write_text(
                trace=self._trace_ctx, stage="architect", name="prompt.txt",
                content=prompt, kind="prompt",
            )
            self._event_logger.emit(
                trace=self._trace_ctx, event="architect.prompt_built", stage="architect",
                component="FeaturePlanningService", status="completed",
                artifact_refs=[prompt_ref],
            )

            worktree_root = target_repo_root or _arch_settings.target_repo_root or ""

            _hb_task = asyncio.create_task(self._heartbeat_worker(run_id, interval_s=5.0))
            try:
                for attempt in range(2):
                    try:
                        from grace_control.core.llm_runner import run_llm
                        cli_name = "deepseek-v4-pro" if worktree_root else "architect-premium"
                        raw = await run_llm(
                            prompt, role="architect",
                            model="",
                            cli=cli_name,
                            cwd=Path(worktree_root) if worktree_root else None,
                            stdout_log_path=arch_run.stdout_path,
                            stderr_log_path=arch_run.stderr_path,
                        )
                        # Persist raw response
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

                        # Normalize plan structure (including W03 canonicalization)
                        normalize_architect_plan(plan)

                        # Persist parsed plan
                        self._artifact_store.write_json(
                            trace=self._trace_ctx, stage="architect", name="parsed_plan.json",
                            payload=plan, kind="parsed_plan",
                        )
                        self._event_logger.emit(
                            trace=self._trace_ctx, event="architect.parsed_plan_captured", stage="architect",
                            component="FeaturePlanningService", status="completed",
                        )

                        arch_run.status = "done"
                        arch_run.model = cli_name
                        arch_run.result_json = plan
                        break
                    except Exception as e:
                        if attempt == 1:
                            raise
                        prompt += f"\n\n[Previous attempt failed with invalid JSON: {str(e)[:200]}. Ensure valid JSON output.]"
            finally:
                _hb_task.cancel()
                try:
                    await _hb_task
                except (asyncio.CancelledError, Exception):
                    pass

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
        arch_run.finished_at = datetime.now(UTC)
        if arch_run.started_at:
            arch_run.duration_ms = int((arch_run.finished_at - arch_run.started_at).total_seconds() * 1000)
        else:
            arch_run.duration_ms = 0

        feature = self.db.query(Feature).filter_by(id=feature_id).first()
        if feature:
            spec = dict(feature.spec_json) if feature.spec_json else {}
            spec["plan_json"] = plan
            feature.spec_json = spec
            feature.status = "PLAN_READY" if arch_run.status == "done" else "PLAN_FAILED"

        self._emit_event(feature_id, "architect_completed" if arch_run.status == "done" else "architect_failed", {
            "run_id": run_id, "duration_ms": arch_run.duration_ms, "waves_count": len(plan.get("waves", [])),
        })
        if arch_run.status == "done":
            self._emit_event(feature_id, "plan_ready", {
                "waves_count": len(plan.get("waves", [])),
            })

        self.db.commit()

    def _build_architect_prompt(self, task: str, context: dict) -> str:
        """W03: Thin renderer around the canonical architect prompt.

        Loads the canonical prompt from architect_prompt.md and prepends
        runtime context (business requirement, codebase context, file listing,
        knowledge graph). The canonical prompt body is the single source of
        truth for schema, rules, and output format — not duplicated here.
        """
        from grace_control.core.prompts import load_architect_prompt

        all_files = context.get("files", [])
        all_paths = "\n".join(f.get("path", "?") for f in all_files[:60])

        relevant_blocks = []
        other_files = []
        for f in all_files:
            if f.get("relevant") and f.get("content_preview"):
                relevant_blocks.append(
                    f"### {f['path']} ({f.get('size_lines', '?')}L)\n"
                    f"{f['content_preview'][:2500]}\n"
                )
            else:
                exports = ", ".join(f.get("exports", [])[:6])
                other_files.append(f"  {f['path']} ({f.get('size_lines', '?')}L) exports=[{exports}]")

        relevants = "\n".join(relevant_blocks[:12])
        others = "\n".join(other_files[:40])

        # ── Runtime context header (prepended before canonical prompt) ──
        prompt = f"""PRIMARY SOURCE OF TRUTH: the business requirement below. Codebase context is for reference only — do not generate packets unrelated to the requirement.

Business requirement: {task}

Codebase context:
- Summary: {context.get('summary', 'Unknown')}
- Complexity: {context.get('complexity_score', '?')}/300
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

        # ── GRACE CANON — Knowledge Graph Extract ────────────────
        target_root = context.get("target_repo_root")
        if target_root:
            from grace_control.services.grace_knowledge_graph_service import GraceKnowledgeGraphService
            from pathlib import Path
            kg_svc = GraceKnowledgeGraphService(
                trace=self._trace_ctx, event_logger=self._event_logger, artifact_store=self._artifact_store,
            )
            kg = kg_svc.load(Path(target_root))
            if kg:
                extract = kg_svc.extract_relevant_modules(
                    kg,
                    feature_text=task,
                    context_paths=[f.get("path", "") for f in all_files],
                )
                kg_block = kg_svc.build_kg_prompt_block(
                    extract, task,
                    context_paths=[f.get("path", "") for f in all_files],
                )
                prompt += kg_block + "\n"

        prompt += f"""Full file listing for scope reference:
{all_paths}

"""

        # ── W03: Append canonical prompt body (single source of truth) ──
        prompt += load_architect_prompt()

        return prompt

    def _fallback_plan(self, feature_id: str, task_desc: str) -> dict:
        """W02: Architect fallback does NOT create executable coder packets.

        When the architect LLM fails, we set PLAN_FAILED instead of creating
        a coder packet with empty scope. The fallback plan is non-executable —
        it records that planning failed but does not enqueue unsafe work.
        """
        return {
            "waves": [],
            "summary": f"PLAN_FAILED: architect LLM unavailable for feature {feature_id}",
            "constraints": {"frozen_scope": []},
            "verification": {"t0": [], "t1": [], "t2": []},
            "_fallback": True,
            "_fallback_reason": "architect_llm_unavailable",
        }

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
            import os as _os
            target_root_str = (
                spec.get("target_repo_root")
                or _settings.target_repo_root
                or _os.environ.get("GRACE_TARGET_REPO_ROOT")
                or "."
            )
            target_root = Path(target_root_str) if isinstance(target_root_str, str) else Path(".")
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
            canonical = ScopePathCanonicalizer().canonicalize_plan(plan)
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
                packet = Packet(
                    id=pkt_id,
                    feature_id=feature_id,
                    wave_id=wave_id,
                    slug=pkt.get("title", f"pkt-{i}").lower().replace(" ", "-"),
                    title=pkt.get("title", f"Packet {i}"),
                    spec_json=enriched_spec,
                    state=PacketState.READY.value if is_first_wave else PacketState.DRAFT.value,
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
        import os as _os
        target_root_str = (
            spec.get("target_repo_root")
            or _settings.target_repo_root
            or _os.environ.get("GRACE_TARGET_REPO_ROOT")
            or "."
        )
        target_root = Path(target_root_str) if isinstance(target_root_str, str) else Path(".")

        from grace_control.core.execution_environment import probe_execution_environment
        env = probe_execution_environment(target_repo_root=target_root)
        desc_full = (feature_desc + "\n" + feature_title
                     + "\n" + str(spec.get("description", ""))
                     + "\n" + str(spec.get("title", "")))

        # ── 1. Autofix before LLM repair ────────────────────────────
        self._trace_ctx.stage = "repair_loop"
        self._artifact_store.write_json(
            trace=self._trace_ctx, stage="repair_loop", name="compiler_errors.json",
            payload={"errors": compiler_errors}, kind="repair_errors",
        )
        from grace_control.services.plan_autofix_service import SafePlanAutofixer
        autofix_result = SafePlanAutofixer().apply(plan, compiler_errors)
        if autofix_result.applied and autofix_result.patched_plan:
            _log.info("autofix_applied", feature_id=feature_id,
                      fixes=len(autofix_result.fixes))
            spec["plan_json"] = autofix_result.patched_plan
            spec["_plan_autofix"] = {
                "applied": True,
                "fixes": autofix_result.fixes,
                "skipped": autofix_result.skipped,
                "attempt": 1,
            }
            feature.spec_json = spec
            self.db.flush()
            plan = autofix_result.patched_plan
            self._artifact_store.write_json(
                trace=self._trace_ctx, stage="repair_loop", name="autofix_output.json",
                payload={"fixes": autofix_result.fixes, "skipped": autofix_result.skipped},
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
            }
            feature.spec_json = spec
            self.db.flush()
            if compiled.ok:
                _log.info("autofix_success", feature_id=feature_id)
                feature.status = "PLAN_READY"
                self.db.flush()
                return self.approve_plan(feature_id)
            compiler_errors = [e.model_dump() for e in compiled.errors]
            error_class = classify_compiler_result(compiler_errors)

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
            canonical = ScopePathCanonicalizer().canonicalize_plan(plan)
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
