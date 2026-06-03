# ############################################################################
# AI_HEADER: llm_runner
# ROLE: Unified LLM subprocess runner — stall detection, hard timeout, per-role config from YAML.
# ############################################################################

# START_MODULE_CONTRACT
# purpose: Single entry point for all LLM calls (architect, coder, verifier, reviewer, context_collector).
#          Reads role timeouts from agent_profiles.yaml. Detects stalls via stdout pipe size growth.
# inputs: prompt (str), role (str), model (str), cli (str).
# returns: stdout as string.
# side_effects: Writes prompt to .grace_state/llm_prompts/, spawns subprocess.
# emitted_logs: llm_started, llm_stalled, llm_timeout, llm_completed.
# error_behavior: Raises StallError after stall_timeout_seconds no growth. Raises TimeoutError after hard_timeout_seconds.
# END_MODULE_CONTRACT

# START_MODULE_MAP
# mapping:
#   - function: run_llm
#   - function: _load_role_config
# END_MODULE_MAP

from __future__ import annotations

import asyncio
import os
import re
import time
from pathlib import Path
from uuid import uuid4

import yaml

from grace_control.core.structured_logger import GraceLogger

_log = GraceLogger("llm_runner")

_PROFILES_PATH = Path(__file__).parent.parent.parent / "prefect_grace" / "agent_profiles.yaml"
_DEFAULT_STALL = 300
_DEFAULT_HARD = 600


def _load_role_config(role: str) -> dict:
    try:
        profiles = yaml.safe_load(_PROFILES_PATH.read_text()) or {}
        roles = profiles.get("codex", {}).get("roles", {})
        rc = roles.get(role, {})
        return {
            "stall": int(rc.get("stall_timeout_seconds", _DEFAULT_STALL)),
            "hard": int(rc.get("hard_timeout_seconds", _DEFAULT_HARD)),
        }
    except Exception:
        return {"stall": _DEFAULT_STALL, "hard": _DEFAULT_HARD}


async def run_llm(
    prompt: str,
    *,
    role: str,
    model: str,
    cli: str = "opencode",
    cwd: Path | None = None,
) -> str:
    config = _load_role_config(role)
    stall_sec = config["stall"]
    hard_sec = config["hard"]

    project_root = cwd or Path.cwd()
    state_root_env = os.environ.get("GRACE_STATE_ROOT", "")
    if state_root_env and cli != "opencode":
        prompt_dir = Path(state_root_env) / "llm_prompts"
    else:
        prompt_dir = project_root / "llm_prompts"
    prompt_dir.mkdir(parents=True, exist_ok=True)
    tmp = prompt_dir / f"{role}_{uuid4().hex[:8]}.txt"
    tmp.write_text(prompt)

    if cli == "opencode":
        rel = tmp.relative_to(project_root)
        instruction = (
            f"Read the task from {rel}. "
            "Respond ONLY with valid JSON, no other text."
        )
        cmd = ["opencode", "run", "--model", model, instruction]
        use_stdin = False
    else:
        prompt_text = tmp.read_text()
        cmd = ["agy", "--print", prompt_text]
        use_stdin = False

    _log.info("llm_started", role=role, model=model, stall_s=stall_sec, hard_s=hard_sec)

    proc = await asyncio.create_subprocess_exec(
        *cmd,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
        cwd=str(project_root),
    )

    last_size = 0
    no_progress = 0
    deadline = time.time() + hard_sec

    try:
        while time.time() < deadline:
            await asyncio.sleep(15)

            if proc.returncode is not None:
                break

            try:
                current_size = os.fstat(proc.stdout.fileno()).st_size
            except Exception:
                current_size = 0

            if current_size > last_size:
                last_size = current_size
                no_progress = 0
            else:
                no_progress += 15

            if no_progress >= stall_sec:
                proc.kill()
                tmp.unlink(missing_ok=True)
                _log.error("llm_stalled", role=role, stall_s=stall_sec)
                raise RuntimeError(f"{role}: no stdout growth for {stall_sec}s")

        if proc.returncode is None:
            proc.kill()
            tmp.unlink(missing_ok=True)
            _log.error("llm_timeout", role=role, hard_s=hard_sec)
            raise TimeoutError(f"{role}: hard timeout after {hard_sec}s")

        stdout, stderr = await proc.communicate()
        tmp.unlink(missing_ok=True)

        out = stdout.decode("utf-8", errors="replace").strip()
        if not out:
            err = stderr.decode("utf-8", errors="replace")[:300]
            _log.warn("llm_empty_output", role=role, stderr=err)
            raise RuntimeError(f"{role}: empty output: {err}")

        _log.info("llm_completed", role=role, output_len=len(out))
        return out

    except Exception:
        tmp.unlink(missing_ok=True)
        raise
