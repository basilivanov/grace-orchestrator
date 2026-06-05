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
import json
import os
import re
import time
from pathlib import Path
from uuid import uuid4

import yaml

from grace_control.core.structured_logger import GraceLogger

_log = GraceLogger("llm_runner")

_PROFILES_PATH = Path(__file__).parent.parent / "config" / "agent_profiles.yaml"
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
    session_dir: Path | None = None,
    extract_json: bool = True,
) -> str:
    config = _load_role_config(role)
    stall_sec = config["stall"]
    hard_sec = config["hard"]

    project_root = cwd or Path.cwd()
    session_root = session_dir or Path(os.environ.get("GRACE_SESSION_DIR", ""))
    if session_root and session_root.exists():
        prompt_dir = session_root / "llm_prompts"
    elif os.environ.get("GRACE_STATE_ROOT") and cli != "opencode":
        prompt_dir = Path(os.environ["GRACE_STATE_ROOT"]) / "llm_prompts"
    else:
        prompt_dir = project_root / "llm_prompts"
    prompt_dir.mkdir(parents=True, exist_ok=True)
    tmp = prompt_dir / f"{role}_{uuid4().hex[:8]}.txt"
    tmp.write_text(prompt)

    if cli == "opencode":
        try:
            task_path = str(tmp.relative_to(project_root))
        except ValueError:
            task_path = str(tmp)
        instruction = (
            f"Read the task from {task_path}. "
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
                _log.error("llm_stalled", role=role, stall_s=stall_sec)
                raise RuntimeError(f"{role}: no stdout growth for {stall_sec}s")

        if proc.returncode is None:
            proc.kill()
            _log.error("llm_timeout", role=role, hard_s=hard_sec)
            raise TimeoutError(f"{role}: hard timeout after {hard_sec}s")

        stdout, stderr = await proc.communicate()

        out = stdout.decode("utf-8", errors="replace").strip()
        if not out:
            err = stderr.decode("utf-8", errors="replace")[:300]
            _log.warn("llm_empty_output", role=role, stderr=err)
            raise RuntimeError(f"{role}: empty output: {err}")

        if extract_json:
            out = _extract_json_block(out)

        _log.info("llm_completed", role=role, output_len=len(out))
        return out

    finally:
        tmp.unlink(missing_ok=True)


def _extract_json_block(text: str) -> str:
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
        candidate = m.group(0)
        try:
            json.loads(candidate)
            return candidate
        except Exception:
            pass

    return text
