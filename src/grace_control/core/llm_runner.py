# AI_HEADER: llm_runner — thin adapter: call sites → AgentRunService via profiles (W13).
# START_MODULE_CONTRACT
# purpose: Single entry point for LLM calls (architect, verifier, reviewer,
#          context_collector). Resolves profile by executor_id via
#          get_agent_profile(), delegates to UniversalCliAgentBackend.
#          No hardcoded CLI names, no subprocess, no os.environ.
# inputs: prompt, role, model, cli (executor_id for profile lookup).
# returns: stdout as string.
# side_effects: Spawns agent via ProcessSupervisor/AgentRunService.
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
from grace_control.config.agent_profiles import get_agent_profile
from grace_control.core.structured_logger import GraceLogger

_log = GraceLogger("llm_runner")


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
    executor_id = cli or f"llm_{role}"
    profile = get_agent_profile(executor_id)
    if not profile:
        raise ValueError(f"no agent profile for executor_id={executor_id!r}; check agent_profiles.yaml `agents:` section")

    executor = profile.to_dict()
    if model:
        executor["model"] = model

    req = ExecutionRequest(
        packet_id=f"llm_{role}_{uuid.uuid4().hex[:6]}",
        spec={"packet_markdown": prompt},
        worktree_path=project_root,
        branch_name="",
        executor=executor,
        timeout_s=profile.timeout_seconds,
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
