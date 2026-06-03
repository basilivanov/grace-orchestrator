# ############################################################################
# AI_HEADER: architect_router
# ROLE: FastAPI router for /api/architect/plan — context-warmed feature planning.
#       Two modes: YAML with waves (legacy) or business-TZ (LLM generates plan).
# ############################################################################

# START_MODULE_CONTRACT
# purpose: Accept feature spec (YAML or business description), collect context,
#          optionally call Architect LLM to generate waves/packets, persist in DB.
# inputs: HTTP POST with feature_spec dict.
# returns: JSON with feature_id, waves/packets, context.
# side_effects: DB inserts, 2 LLM calls (context + architect).
# emitted_logs: context_collected, architect_generated, architect_retry.
# error_behavior: 422 on DAG failure, 500 on LLM timeout (retried once).
# END_MODULE_CONTRACT

# START_MODULE_MAP
# mapping:
#   - function: create_plan
#   - function: _call_architect_llm
#   - function: _slugify
#   - function: _extract_action
# END_MODULE_MAP

from __future__ import annotations

import asyncio
import json
import os
import re as _re
from datetime import datetime
from pathlib import Path

from fastapi import APIRouter

from grace_control.core.context_collector import ContextCollector
from grace_control.core.dag_validator import validate_dag
from grace_control.core.structured_logger import GraceLogger
from grace_control.db import get_db
from grace_control.db.schema import Feature, Packet, PacketState, Wave

router = APIRouter()
_log = GraceLogger("architect")

ARCHITECT_MODEL = "deepseek/deepseek-v4-pro"
ARCHITECT_TIMEOUT = int(os.environ.get("GRACE_ARCHITECT_TIMEOUT", "120"))


@router.post("/plan")
async def create_plan(request: dict) -> dict:
    spec = request["feature_spec"]
    title = spec.get("title", "")
    if not title:
        from fastapi import HTTPException
        raise HTTPException(status_code=400, detail="title is required")

    slug = _slugify(title)
    feature_id = f"FEAT-{slug.upper()}"
    has_waves = bool(spec.get("waves"))
    architect_generated = False

    # ── Context pre-warming ──────────────────────────────────────────────
    context = await _warm_context(spec, feature_id)

    # ── LLM path: business-TZ → generate waves/packets ───────────────────
    if not has_waves and not os.environ.get("GRACE_CONTEXT_DISABLED"):
        task_desc = spec.get("description", "") or title
        # Preserve metadata from original spec before LLM overwrites it
        _origin = spec.get("origin", "")
        _session_id = spec.get("session_id", "")
        _self_improvement = spec.get("self_improvement", False)
        try:
            spec = await _call_architect_llm(task_desc, context, slug,
                self_improvement=_self_improvement or _origin == "self_evolution")
            spec["title"] = title
            spec["description"] = spec.get("description", task_desc)
            spec["origin"] = _origin
            spec["session_id"] = _session_id
            spec["self_improvement"] = _self_improvement or _origin == "self_evolution"
            architect_generated = True
            _log.info("architect_generated", feature_id=feature_id,
                waves=len(spec.get("waves", [])))
        except Exception as e:
            _log.error("architect_failed", feature_id=feature_id, error=str(e)[:200])
            from fastapi import HTTPException
            raise HTTPException(status_code=500,
                detail=f"Architect LLM failed to generate plan: {str(e)[:200]}")

    # ── DAG validation ───────────────────────────────────────────────────
    dag_packets = []
    action_to_id: dict[str, str] = {}
    for i, wave_spec in enumerate(spec.get("waves", []), 1):
        for j, pkt_spec in enumerate(wave_spec.get("packets", []), 1):
            wave_slug = _slugify(wave_spec["title"])
            wave_id = f"{slug.upper()}-W{i:02d}"
            action = _extract_action(pkt_spec["title"])
            pid = f"{feature_id}-{wave_id}-P{j:02d}-{action}"
            action_to_id[action] = pid
            dag_packets.append({
                "id": pid,
                "depends_on": pkt_spec.get("depends_on", []),
                "scope": pkt_spec.get("scope", []),
            })

    for dp in dag_packets:
        resolved = []
        for dep in dp["depends_on"]:
            resolved.append(action_to_id.get(dep, dep))
        dp["depends_on"] = resolved

    dag_result = validate_dag(dag_packets)
    if not dag_result.valid:
        from fastapi import HTTPException
        raise HTTPException(status_code=422, detail={
            "errors": dag_result.errors,
            "cycles": dag_result.cycles,
            "conflicts": [[c.packet_a, c.packet_b, c.overlapping_files] for c in dag_result.conflicts],
        })

    # ── Persist ──────────────────────────────────────────────────────────
    packets_created = []
    with get_db() as db:
        existing_feature = db.query(Feature).filter_by(id=feature_id).first()
        if existing_feature:
            existing_waves = db.query(Wave).filter_by(feature_id=feature_id).order_by(Wave.order).all()
            existing_packets = db.query(Packet).filter_by(feature_id=feature_id).all()
            existing_context = {}
            if existing_packets:
                first = existing_packets[0]
                first_spec = first.spec_json or {}
                existing_context = first_spec.get("_context", {}) if isinstance(first_spec, dict) else {}
            return {
                "data": {
                    "feature_id": existing_feature.id,
                    "waves_count": len(existing_waves),
                    "packets_count": len(existing_packets),
                    "packets": [p.id for p in existing_packets],
                    "context": existing_context,
                },
                "timestamp": datetime.utcnow().isoformat() + "Z",
            }

        db.add(Feature(
            id=feature_id, slug=slug, title=title,
            description=spec.get("description", ""),
            spec_json=spec, status="NOT_STARTED",
        ))

        for i, wave_spec in enumerate(spec.get("waves", []), 1):
            wave_slug = _slugify(wave_spec["title"])
            wave_id = f"{slug.upper()}-W{i:02d}"
            is_first_wave = (i == 1)

            db.add(Wave(
                id=wave_id, feature_id=feature_id, slug=wave_slug,
                title=wave_spec["title"],
                description=wave_spec.get("description", ""),
                order=i, status="NOT_STARTED",
            ))

            for j, pkt_spec in enumerate(wave_spec.get("packets", []), 1):
                pkt_slug = _slugify(pkt_spec["title"])
                action = _extract_action(pkt_spec["title"])
                packet_id = f"{feature_id}-{wave_id}-P{j:02d}-{action}"

                target_state = PacketState.READY.value if is_first_wave else PacketState.DRAFT.value
                enriched_spec = dict(pkt_spec)
                enriched_spec["_context"] = context

                # Propagate root-level verification/constraints into each packet
                root_verification = spec.get("verification", [])
                root_constraints = spec.get("constraints", {})
                enriched_spec.setdefault("verification", root_verification)
                enriched_spec.setdefault("frozen_scope",
                    root_constraints.get("frozen_scope", ["src/prefect_grace/"]))

                if spec.get("self_improvement") or spec.get("origin") == "self_evolution":
                    enriched_spec.setdefault("origin", spec.get("origin", "self_evolution"))
                    enriched_spec.setdefault("session_id", spec.get("session_id", ""))
                    enriched_spec["self_improvement"] = True
                    enriched_spec["affected_subsystem"] = pkt_spec.get("affected_subsystem", "core")
                    enriched_spec["risk_level"] = pkt_spec.get("risk_level", "medium")

                db.add(Packet(
                    id=packet_id, feature_id=feature_id, wave_id=wave_id,
                    slug=pkt_slug, title=pkt_spec["title"],
                    description=pkt_spec.get("description", ""),
                    spec_json=enriched_spec,
                    state=target_state,
                    acceptance_profile=pkt_spec.get("acceptance_profile", "NORMAL"),
                ))
                packets_created.append(packet_id)

    return {
        "data": {
            "feature_id": feature_id,
            "waves_count": len(spec.get("waves", [])),
            "packets_count": len(packets_created),
            "packets": packets_created,
            "context": context,
            "generated": architect_generated,
        },
        "timestamp": datetime.utcnow().isoformat() + "Z",
    }


async def _warm_context(spec: dict, feature_id: str) -> dict:
    if os.environ.get("GRACE_CONTEXT_DISABLED"):
        return {"summary": "Context collection disabled", "disabled": True}

    task_desc = spec.get("description", "") or spec.get("title", "")
    scope_paths = set()
    for wave_spec in spec.get("waves", []):
        for pkt_spec in wave_spec.get("packets", []):
            for s in pkt_spec.get("scope", []):
                scope_paths.add(s)

    scene = sorted(scope_paths) if scope_paths else ["src/grace_control/"]
    try:
        collector = ContextCollector(cli="opencode", model="deepseek/deepseek-v4-flash")
        code_ctx = await collector.collect(task_description=task_desc, target_scope=scene)
        ctx = {
            "summary": code_ctx.summary,
            "estimated_scope": code_ctx.estimated_scope,
            "complexity_score": code_ctx.complexity_score,
            "file_count": len(code_ctx.files),
            "files": [{"path": f.path, "size_lines": f.size_lines, "exports": f.exports[:8],
                       "content_preview": f.content_preview, "relevant": f.relevant}
                      for f in code_ctx.files[:50]],
        }
        _log.info("context_collected", feature_id=feature_id,
            scope_count=len(scope_paths), complexity=code_ctx.complexity_score)
        return ctx
    except Exception as e:
        _log.warn("context_fallback", feature_id=feature_id, error=str(e)[:120])
        return {"summary": f"Fallback: {task_desc[:200]}", "fallback": True}


async def _call_architect_llm(task: str, context: dict, feature_slug: str,
                              self_improvement: bool = False) -> dict:
    all_files = context.get("files", [])
    all_paths = "\n".join(f.get("path", f.get("path", "?")) for f in all_files[:60])

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
CRITICAL: scope MUST contain paths from the file listing above."""


    if self_improvement:
        prompt += """SELF-IMPROVEMENT MODE: You are modifying the GRACE orchestrator itself.
For each packet, include these additional fields in the JSON:
  - "affected_subsystem": "ui" | "api" | "core" | "worker" | "tests"
  - "risk_level": "low" | "medium" | "high"
  - "required_gates": list of checks before merge (e.g. ["js_syntax", "api_contract", "playwright_smoke"])
  - "reload_required": true/false (true for Python/API changes, false for static HTML/JS/CSS)
  - "rollback_note": brief description of how to undo

After ALL waves complete:
  - Static files (HTML/JS/CSS): served immediately, no restart needed
  - Python files (api/core/worker): uvicorn needs reload via SIGUSR1 or restart
  - New test files: run pytest to verify they pass
"""

    prompt += """Rules:
1. Each wave is a logical phase. Wave 2 starts only after ALL Wave 1 packets are merged.
2. Each packet = one atomic code change (1-3 files max).
3. Scope MUST list actual file paths to write (relative to project root).
4. NO TWO packets may share the same file in their scope. If changes affect the same file, merge them into ONE packet.
5. Use acceptance_profile: FAST (simple), NORMAL (moderate), STRICT (needs review).
6. depends_on: optional list of packet titles that must complete first (within same wave).
7. Include `constraints` block with: frozen_scope (files NEVER to touch), forbidden_imports, python_version.
8. Include `verification` list with shell commands to run (pytest, ruff, mypy).
9. CRITICAL: Each packet MUST be small enough for a single agent run (~2-5 min, ~200 lines max). A task like "rebuild the entire dashboard" is TOO BIG. Split it into multiple small packets: "add status summary section", "add feature list column", "add packet detail tabs", "add artifact viewer", etc. Each packet touches 1-2 files, never the entire codebase.

Respond ONLY with valid JSON (no markdown, no backticks):

{{
  "waves": [
    {{
      "title": "Phase 1 name",
      "packets": [
        {{
          "title": "Add login endpoint",
          "scope": ["src/auth.py", "tests/test_auth.py"],
          "acceptance_profile": "NORMAL",
          "depends_on": [],
          "description": "what this packet does",
          "verification": {{
            "t0": [],
            "t1": ["python3 -m pytest tests/test_auth.py -q"],
            "t2": []
          }},
          "expected_evidence": [
            {{
              "id": "auth_test_green",
              "kind": "command",
              "required": true,
              "pattern": "tests/test_auth.py"
            }}
          ]
        }}
      ]
    }}
  ],
  "constraints": {{
    "frozen_scope": ["src/prefect_grace/"],
    "forbidden_imports": [],
    "python_version": ">= 3.12"
  }},
  "verification": {{
    "t0": [],
    "t1": [],
    "t2": []
  }}
}}"""

    for attempt in range(2):
        try:
            raw = await _run_opencode(prompt, ARCHITECT_MODEL)
            plan = json.loads(raw)
            if "waves" not in plan:
                plan["waves"] = []
            for w in plan.get("waves", []):
                if "packets" not in w:
                    w["packets"] = []
                for pkt in w["packets"]:
                    pkt.setdefault("scope", [])
                    pkt.setdefault("acceptance_profile", "NORMAL")
                    pkt.setdefault("depends_on", [])

            all_empty = all(not pkt.get("scope") for w in plan.get("waves", [])
                           for pkt in w.get("packets", []))
            any_packet = any(w.get("packets") for w in plan.get("waves", []))
            if any_packet and all_empty:
                file_paths = [f["path"] for f in context.get("files", [])]
                if file_paths:
                    for w in plan.get("waves", []):
                        for pkt in w.get("packets", []):
                            if not pkt.get("scope"):
                                pkt["scope"] = file_paths[:3]
                    _log.info("architect_scope_seeded", paths=len(file_paths))
                else:
                    raise RuntimeError("All packet scopes are empty — you must specify which files to modify")

            plan.setdefault("constraints", {"frozen_scope": ["src/prefect_grace/"]})
            plan.setdefault("verification", {"t0": [], "t1": [], "t2": []})
            return plan
        except Exception as e:
            if attempt == 1:
                raise RuntimeError(f"Architect LLM failed after 2 attempts: {e}")
            error = str(e)[:200]
            _log.warn("architect_retry", attempt=attempt + 1, error=error)
            prompt = prompt + f"\n\n[Previous attempt failed with invalid JSON: {error}. Ensure valid JSON output.]"

    raise RuntimeError("Architect LLM failed")


async def _run_opencode(prompt: str, model: str) -> str:
    from grace_control.core.llm_runner import run_llm
    raw = await run_llm(prompt, role="architect", model=model, cli="opencode")

    # Try direct JSON parse
    for line in raw.split("\n"):
        line = line.strip()
        if line.startswith("{") and line.endswith("}"):
            try:
                json.loads(line)
                return line
            except Exception:
                pass

    # Try extract JSON block
    m = _re.search(r"\{[\s\S]*\}", raw)
    if m:
        candidate = m.group(0)
        try:
            json.loads(candidate)
            return candidate
        except Exception:
            pass

    raise RuntimeError(f"Could not extract JSON from output (first 300): {raw[:300]}")


def _slugify(text: str) -> str:
    text = _re.sub(r'[^\w\s-]', '', text)
    return text.lower().strip().replace(" ", "-").replace("_", "-")


def _extract_action(title: str) -> str:
    words = title.split()
    if not words:
        return "ACTION"
    action = words[0].upper()
    rest = "-".join(words[1:3]).upper().replace(" ", "-") if len(words) > 1 else ""
    return f"{action}-{rest}" if rest else action
