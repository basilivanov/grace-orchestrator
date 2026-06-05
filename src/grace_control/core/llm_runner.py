# AI_HEADER: llm_runner — thin adapter: call sites → AgentRunService (W13).
# START_MODULE_CONTRACT
# purpose: Single entry point for LLM calls (architect, verifier, reviewer,
#          context_collector). Delegates to AgentRunService via on-the-fly
#          profiles. No hardcoded CLI names.
# inputs: prompt, role, model, cli (executor_id for profile lookup).
# returns: stdout as string.
# side_effects: Writes prompt to .grace/llm_prompts/, spawns agent via
#               UniversalCliAgentBackend/ProcessSupervisor.
# emitted_logs: llm_started, llm_completed, llm_failed.
# error_behavior: Raises RuntimeError on empty output or non-zero exit.
# END_MODULE_CONTRACT
# START_MODULE_MAP
# mapping:   - function: run_llm
# END_MODULE_MAP

from __future__ import annotations

import uuid
from pathlib import Path

from grace_control.agent.backend import ExecutionRequest
from grace_control.agent.universal_cli_backend import UniversalCliAgentBackend
from grace_control.core.structured_logger import GraceLogger
from grace_control.services.command_template_renderer import CommandTemplateRenderer

_log = GraceLogger("llm_runner")
_renderer = CommandTemplateRenderer()


async def run_llm(
    prompt: str,
    *,
    role: str,
    model: str,
    cli: str = "",
    cwd: Path | None = None,
    session_dir: Path | None = None,
    extract_json: bool = True,
) -> str:
    project_root = cwd or Path.cwd()
    prompt_dir = project_root / ".grace" / "llm_prompts"
    prompt_dir.mkdir(parents=True, exist_ok=True)
    prompt_file = prompt_dir / f"{role}_{uuid.uuid4().hex[:8]}.txt"
    prompt_file.write_text(prompt)

    executor = {
        "executor_id": f"llm_{role}",
        "command": [cli, "run", "--model", model, "Read the task from {packet_path}. Respond ONLY with valid JSON."],
        "model": model,
        "effort": "high",
        "cwd": "{worktree_path}",
        "timeout_seconds": 600,
        "input_mode": "file",
    }

    req = ExecutionRequest(
        packet_id=f"llm_{role}_{uuid.uuid4().hex[:6]}",
        spec={"packet_markdown": prompt},
        worktree_path=project_root,
        branch_name="",
        executor=executor,
        timeout_s=600,
        session_dir=session_dir,
    )

    backend = UniversalCliAgentBackend()
    result = await backend.run(req)

    out = result.stdout.strip() if result.stdout else ""
    if not out:
        err = result.stderr[:300] if result.stderr else "empty output"
        _log.warn("llm_failed", role=role, stderr=err)
        raise RuntimeError(f"{role}: {err}")

    if extract_json:
        out = _extract_json_block(out)

    _log.info("llm_completed", role=role, output_len=len(out))
    return out


def _extract_json_block(text: str) -> str:
    import json, re
    m = re.search(r"```(?:json)?\s*\n?([\s\S]*?)\n?```", text)
    if m:
        candidate = m.group(1).strip()
        try:
            json.loads(candidate)
            return candidate
        except Exception:
            pass
    for line in text.split("\n"):
        line = line.strip()
        if line.startswith("{") and line.endswith("}"):
            try:
                json.loads(line)
                return line
            except Exception:
                pass
    for line in text.split("\n"):
        line = line.strip()
        if line.startswith("[") and line.endswith("]"):
            try:
                json.loads(line)
                return line
            except Exception:
                pass
    m = re.search(r"\{[\s\S]*\}", text)
    if m:
        try:
            json.loads(m.group(0))
            return m.group(0)
        except Exception:
            pass
    return text
