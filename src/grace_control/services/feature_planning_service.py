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


class FeaturePlanningService:
    """Orchestrate feature planning stages."""

    def __init__(self, db):
        self.db = db

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

        # ── Mutation guard: pre-snapshot target repo ──
        worktree_root = target_repo_root or _ctx_settings.target_repo_root or "."
        root = Path(worktree_root)
        pre_snapshot = _git_snapshot(root)
        if pre_snapshot and not pre_snapshot["is_clean"]:
            _log.warn("context_builder_pre_snapshot_dirty",
                       feature_id=feature_id, status=pre_snapshot["status_short"][:200])

        try:
            # Determine scope from feature spec_json
            spec = feature.spec_json or {} if feature else {}
            scope = spec.get("scope") if isinstance(spec, dict) else None

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
            }
            cb_run.status = "done"
            cb_run.model = ctx_model.get("model", "")

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

        try:
            # Build prompt — reuses the same prompt structure as _call_architect_llm
            prompt = self._build_architect_prompt(task_desc, context)

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
                        plan = json.loads(raw)

                        # Normalize plan structure
                        if "plan" in plan and isinstance(plan["plan"], dict) and plan["plan"].get("waves"):
                            plan["waves"] = plan["plan"]["waves"]
                        if "packets" in plan and not plan.get("waves"):
                            plan["waves"] = [{"title": "Phase 1", "packets": plan["packets"]}]
                        if "waves" not in plan:
                            plan["waves"] = []
                        for w in plan.get("waves", []):
                            if "packets" not in w:
                                w["packets"] = []
                            for pkt in w["packets"]:
                                pkt.setdefault("scope", [])
                                pkt.setdefault("acceptance_profile", "NORMAL")
                                pkt.setdefault("depends_on", [])

                        plan.setdefault("constraints", {})
                        plan.setdefault("verification", {"t0": [], "t1": [], "t2": []})

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

        prompt = f"""You are a software architect planning code changes for a project.

PRIMARY SOURCE OF TRUTH: the business requirement below. Codebase context is for reference only — do not generate packets unrelated to the requirement.

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

        prompt += f"""Full file listing for scope reference:
{all_paths}

Your job: create an execution plan as waves and packets.
CRITICAL: scope MUST match the business requirement. Use paths from the file listing only if relevant to the task.

Rules:
1. Each wave is a logical phase. Wave 2 starts only after ALL Wave 1 packets are merged.
2. Each packet = one atomic code change (1-3 files max).
3. Scope MUST list actual file paths to write (relative to project root).
4. NO TWO packets may share the same file in their scope. If changes affect the same file, merge them into ONE packet.
5. Use acceptance_profile — default is STRICT for every packet:
   - STRICT: default for any code change, migration, contract, or behavior
     modification. Triggers T0/T1/T2 + verifier + reviewer gates.
   - NORMAL: default for regular product changes (refactoring, feature work).
     Triggers T0/T1/T2 + verifier + reviewer gates.
   - FAST: use ONLY for documentation-only packets (markdown, docs, comments).
     No code changes involved. Triggers T0/T1/T2 only.
6. depends_on: optional list of packet titles that must complete first (within same wave).
7. Include `constraints` block with: frozen_scope (files NEVER to touch).
8. Include `verification` dict with t0/t1/t2 lists of shell commands to run.

    CRITICAL — verification quoting rules (shell commands run via `sh -c`):
   - Prefer simple shell commands: grep, diff, test, find, cd, python3 with
     script paths instead of inline code.
   - If inline Python is unavoidable, ALWAYS start with `import sys;` and
     validate the command with syntax: `python3 -c 'import sys; ...'`.
   - NEVER generate `python3 -c` without proper single quotes around the
     Python code and always import all needed modules (sys, os, yaml, etc).
   - Example SAFE: `python3 -c 'import sys; import yaml; yaml.safe_load(open(sys.argv[1])); print(\"OK\")' path/to/file`
   - Example BROKEN: `python3 -c import yaml; yaml.safe_load(open(...))` (missing quotes, missing imports)
   - Example BROKEN: `python3 -c "import yaml; print(d[\"key\"])"` (double quotes break because bash interprets `\"`)
   - Prefer calling scripts or using file-based checks over inline
     Python when the command path or assertion contains quote-sensitive
     characters like file paths with slashes, single quotes, or braces.

   CRITICAL — verification timing (commands run AFTER agent changes):
   - T0/T1/T2 commands run AFTER the agent has made all changes.
   - If the packet REMOVES something, T0 must check for ABSENCE
     (e.g. `grep -c 'pattern' file || true`, expecting 0 matches).
   - If the packet ADDS something, T0 must check for PRESENCE.
   - NEVER write a verification command that expects pre-packet state;
     always verify the expected END state of this packet.
   - A packet that deletes a feature must pass a check that the
     feature is gone, not that it still exists.

   CRITICAL — packet sanity rules (check BEFORE emitting any packet):
   - Scope vs acceptance: If T1/T2 verification depends on files that
     may need updates, those files must be in write scope. If tests are
     intentionally outside scope, the implementation must preserve
     backward compatibility so those tests still pass. Never create a
     packet where acceptance requires passing tests that will fail
     because test updates are outside scope.
   - Symbol move/rename: Before moving/renaming/deleting a method or
     class, require a compatibility strategy. If existing tests or call
     sites reference the old symbol and are outside scope, keep a
     deprecated shim/wrapper. Only delete the old symbol when all call
     sites and tests are included in scope.
   - Impossible packet detection: If the intended change conflicts with
     frozen scope or write scope, emit `architect_repack_needed`, not a
     coder packet. Use reason `scope impossible: required acceptance
     depends on files outside write scope`.
   - Verification-only work: Do not create coder packets for read-only
     verification. Use `role: verifier` or fold the check into architect
     evidence. A coder packet must normally produce a diff.
   - Acceptance wording: Avoid "all existing tests pass" unless the
     write scope includes everything needed to make that true. Prefer
     targeted acceptance like `Existing tests pass without modifying
     tests because <old_method> remains as compatibility shim`.
   - T0/T1 commands: T0 checks intended architecture. T1 runs only
     tests the packet can satisfy within scope. If a T1 failure can
     only be fixed by changing files outside scope, the packet is
     invalid and must be repacked before coder execution.
   - T2/FULL: do NOT run full guardrails.sh (strict/normal/fast).
     Only run targeted commands specific to this packet's changes
     (e.g. grep, test, diff). Running the entire guardrails suite
     will pick up pre-existing failures unrelated to this packet.
   - Frozen scope and scope must use ONLY relative paths (relative to
     project root). Absolute paths (starting with /) are rejected by
     contract validation and will cause the packet to fail immediately.

   CRITICAL — runtime environment rules (all commands run via /bin/sh, NOT bash):
   - NEVER use `source` — use `.` (dot) for venv activation:
     `. .venv/bin/activate` not `source .venv/bin/activate`.
   - `/bin/sh` is dash, not bash. Bash-only features (source, arrays,
     [[ ]], ${VAR//x/y}) will fail. Use POSIX-compatible syntax only.

   CRITICAL — expected_evidence rules:
   - NEVER use `kind=diff` with pattern=`agent.patch`.
   - For creating new files: `kind=file` with pattern matching the filename.
   - For modifying existing files: `kind=diff` WITHOUT a pattern — just
     checking that changed_files is non-empty is enough.
   - Example CORRECT: `{"id":"EV","kind":"file","artifact_patterns":["llm/russian.py"]}`
   - Example WRONG: `{"id":"EV","kind":"diff","artifact_patterns":["agent.patch"]}`

   CRITICAL — frozen_scope rules:
   - NEVER put any file from the packet's own scope into frozen_scope.
   - frozen_scope is STRICTLY for files that MUST NOT be touched by this
     packet. If a file needs to be created or modified, it belongs in
     scope, NOT in frozen_scope.
   - Overlap between scope and frozen_scope makes the file unwritable
     and causes immediate packet failure.

   Default method-extraction pattern:
   • Add new canonical method in the target service.
   • Update production call site to use the new method.
   • Keep old method as compatibility shim if tests/callers outside
     scope still reference it.
   • Add TODO comment for removal in a later packet with expanded scope.

9. CRITICAL: Each packet MUST be small enough for a single agent run (~2-5 min, ~200 lines max).

Respond ONLY with valid JSON (no markdown, no backticks):

{{
  "waves": [
    {{
      "title": "Phase 1 name",
      "packets": [
        {{
          "title": "Packet title",
          "scope": ["path/to/file1.py", "path/to/file2.py"],
          "acceptance_profile": "STRICT",
          "depends_on": [],
          "description": "what this packet does",
          "verification": {{
            "t0": [],
            "t1": ["python3 -m pytest tests/... -q"],
            "t2": []
          }},
          "expected_evidence": []
        }}
      ]
    }}
  ],
  "constraints": {{
    "frozen_scope": ["docs/archived/legacy_prefect_grace/"]
  }},
  "verification": {{
    "t0": [],
    "t1": [],
    "t2": []
  }}
}}"""
        return prompt

    def _fallback_plan(self, feature_id: str, task_desc: str) -> dict:
        return {
            "waves": [
                {
                    "id": f"wave_{uuid.uuid4().hex[:12]}",
                    "title": "Implementation",
                    "packets": [
                        {
                            "id": f"pkt_{uuid.uuid4().hex[:12]}",
                            "title": "Initial implementation",
                            "scope": [],
                            "acceptance_profile": "FAST",
                            "depends_on": [],
                            "description": task_desc[:500],
                            "verification": {"t0": [], "t1": [], "t2": []},
                            "expected_evidence": [],
                        }
                    ],
                }
            ],
            "summary": f"Fallback plan for feature {feature_id} — architect LLM unavailable",
            "constraints": {"frozen_scope": []},
            "verification": {"t0": [], "t1": [], "t2": []},
        }

    def approve_plan(self, feature_id: str) -> dict:
        feature = self.db.query(Feature).filter_by(id=feature_id).first()
        if not feature:
            raise ValueError(f"Feature not found: {feature_id}")
        if feature.status != "PLAN_READY":
            raise ValueError(f"Cannot approve plan in status {feature.status}. Must be PLAN_READY.")

        spec = feature.spec_json or {}
        plan = spec.get("plan_json", {}) if isinstance(spec, dict) else {}
        waves = plan.get("waves", []) if isinstance(plan, dict) else []

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

        root_verification = spec.get("verification", plan.get("verification", {}))
        root_constraints = spec.get("constraints", plan.get("constraints", {}))

        packet_ids = []
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

        materialize_run.status = "done"
        materialize_run.finished_at = datetime.now(UTC)
        materialize_run.duration_ms = int((materialize_run.finished_at - materialize_run.started_at).total_seconds() * 1000)
        materialize_run.result_json = {"waves_count": len(waves), "packets_count": len(packet_ids), "packet_ids": packet_ids}

        feature.status = "queued"

        approval_mode = spec.get("approval_mode", "auto") if isinstance(spec, dict) else "auto"
        self._emit_event(feature_id, "plan_materialized", {
            "waves_count": len(waves), "packets_count": len(packet_ids),
            "approval_mode": approval_mode,
        })
        self._emit_event(feature_id, "feature_queued", {})

        self.db.commit()
        return {"status": "queued", "waves_count": len(waves), "packets_count": len(packet_ids), "packet_ids": packet_ids}

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
