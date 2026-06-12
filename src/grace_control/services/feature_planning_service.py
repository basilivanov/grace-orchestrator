# ############################################################################
# AI_HEADER: feature_planning_service
# ROLE: Feature planning orchestration — context builder, architect, approval
# ############################################################################

from __future__ import annotations

import json
import os
import uuid
from datetime import UTC, datetime
from pathlib import Path

from grace_control.core.uid import generate_unique_id, new_wave_uid, new_packet_uid, new_run_uid
from grace_control.db.schema import Feature, FeaturePlanningRun, Wave, Packet, Event
from grace_control.db.schema import PacketState

_CONTENT_PREVIEW_CHARS = 2500
_MAX_RELEVANT_FILES = 15


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
        log_dir = Path(f"/tmp/grace_planning_logs/{feature_id}/{run_id}")
        log_dir.mkdir(parents=True, exist_ok=True)
        stdout_path = str(log_dir / "stdout.log")
        stderr_path = str(log_dir / "stderr.log")
        cb_run.stdout_path = stdout_path
        cb_run.stderr_path = stderr_path
        self.db.commit()

        feature = self.db.query(Feature).filter_by(id=feature_id).first()
        task_desc = (feature.description or feature.title or "") if feature else ""

        if os.environ.get("GRACE_CONTEXT_DISABLED"):
            context = {
                "summary": f"Context collection disabled for: {task_desc[:200]}",
                "file_count": 0,
                "files": [],
                "disabled": True,
            }
            cb_run.status = "done"
            cb_run.finished_at = datetime.now(UTC)
            cb_run.duration_ms = 0
            cb_run.result_json = context
            self._emit_event(feature_id, "context_builder_completed", {
                "run_id": run_id, "duration_ms": 0, "status": "done",
            })
            self.db.commit()
            return context

        try:
            from grace_control.config.settings import settings
            worktree_root = target_repo_root or settings.target_repo_root or "."
            root = Path(worktree_root)

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
                stdout_log_path=stdout_path,
                stderr_log_path=stderr_path,
            )
            code_ctx = await collector.collect(
                task_description=task_desc,
                target_scope=scope,
                project_root=root,
            )

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
        except Exception as e:
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
        arch_run.executor_id = "architect-business-flash"
        arch_run.prompt = task_desc[:2000]

        # Set up live log paths
        log_dir = Path(f"/tmp/grace_planning_logs/{feature_id}/{run_id}")
        log_dir.mkdir(parents=True, exist_ok=True)
        stdout_path = str(log_dir / "stdout.log")
        stderr_path = str(log_dir / "stderr.log")
        arch_run.stdout_path = stdout_path
        arch_run.stderr_path = stderr_path
        self.db.commit()

        # If context is disabled (test mode), use fallback plan
        if os.environ.get("GRACE_CONTEXT_DISABLED"):
            plan = self._fallback_plan(feature_id, task_desc)
            arch_run.status = "done"
            arch_run.model = "disabled"
            arch_run.result_json = plan
            self._finalize_plan(feature_id, plan, arch_run, run_id)
            return plan

        try:
            # Build prompt — reuses the same prompt structure as _call_architect_llm
            prompt = self._build_architect_prompt(task_desc, context)

            from grace_control.config.settings import settings
            worktree_root = target_repo_root or settings.target_repo_root or ""

            for attempt in range(2):
                try:
                    from grace_control.core.llm_runner import run_llm
                    cli_name = "architect-business-flash" if worktree_root else "architect-premium"
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

        except Exception as e:
            plan = self._fallback_plan(feature_id, task_desc)
            arch_run.status = "failed"
            arch_run.error = str(e)[:500]
            arch_run.result_json = plan

        self._finalize_plan(feature_id, plan, arch_run, run_id)
        return plan

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
5. Use acceptance_profile: FAST (simple), NORMAL (moderate), STRICT (needs review).
6. depends_on: optional list of packet titles that must complete first (within same wave).
7. Include `constraints` block with: frozen_scope (files NEVER to touch).
8. Include `verification` dict with t0/t1/t2 lists of shell commands to run.
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
          "acceptance_profile": "NORMAL",
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

        self._emit_event(feature_id, "plan_materialized", {
            "waves_count": len(waves), "packets_count": len(packet_ids),
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
