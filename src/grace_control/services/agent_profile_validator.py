# AI_HEADER: agent_profile_validator — validate and dry-run agent profiles (W14.3)
# START_MODULE_CONTRACT
# purpose: Validate agent profiles: command shape, placeholder resolution, env vars,
#          input mode, timeout, and optional executable check. Dry-run renders
#          command/env/cwd without spawning.
# inputs: AgentProfile or executor dict.
# returns: dict with ok, errors, rendered_command, cwd, env_preview, input_mode.
# side_effects: None (dry-run does not spawn).
# error_behavior: Never raises; errors returned in result dict.
# END_MODULE_CONTRACT
# START_MODULE_MAP
# mapping:   - class: AgentProfileValidator
# END_MODULE_MAP

from __future__ import annotations
import os
import re
import shutil
import sys
from pathlib import Path
from typing import Any
from grace_control.services.agent_env_builder import AgentEnvBuilder
from grace_control.services.command_template_renderer import CommandTemplateRenderer
from grace_control.config.agent_profiles import AgentProfile


class AgentProfileValidator:
    def __init__(self) -> None:
        self._renderer = CommandTemplateRenderer()
        self._env_builder = AgentEnvBuilder()

    def validate(self, profile: AgentProfile, check_executable: bool = False,
                 worktree_path: str | None = None) -> dict[str, Any]:
        errors: list[str] = []
        warnings: list[str] = []

        if isinstance(profile.command, str):
            errors.append("command must be a list of strings, got string")
        elif not isinstance(profile.command, list):
            errors.append("command must be a list")
        elif not profile.command:
            errors.append("command list is empty")

        if profile.timeout_seconds <= 0:
            errors.append("timeout_seconds must be > 0")

        valid_modes = {"stdin", "file", "none"}
        if profile.input_mode not in valid_modes:
            errors.append(f"input_mode must be one of {valid_modes}, got '{profile.input_mode}'")

        ctx = {
            "packet_id": "test",
            "model": profile.model or "test-model",
            "effort": profile.effort or "medium",
            "role": "coder",
            "worktree_path": worktree_path or "/tmp/grace-worktree",
            "state_root": "/tmp/grace-state",
            "attempt": "1",
            "packet_markdown": "test prompt",
            "packet_path": "/tmp/grace-worktree/EXECUTION_PACKET.md",
            "python_executable": sys.executable,
        }

        rendered_command = []
        try:
            rendered_command = self._renderer.render(profile.command, ctx)
        except ValueError as e:
            errors.append(str(e))

        for part in rendered_command:
            if re.search(r"(?<!\$)\{[a-z_]+\}", part):
                errors.append(f"unresolved placeholder in command: '{part[:40]}...'")

        if check_executable and rendered_command:
            exe = shutil.which(rendered_command[0])
            if not exe:
                warnings.append(f"executable '{rendered_command[0]}' not found on PATH")

        try:
            cwd_raw = self._renderer.render([profile.cwd_template], ctx)[0]
        except Exception:
            cwd_raw = profile.cwd_template

        raw_env = profile.env
        try:
            env = self._env_builder.build(raw_env)
        except Exception as e:
            errors.append(f"env build: {e}")

        env_preview = self._env_builder.preview(env) if not errors else {}

        return {
            "ok": len(errors) == 0,
            "executor_id": profile.executor_id,
            "errors": errors,
            "warnings": warnings,
            "rendered_command": rendered_command,
            "cwd": cwd_raw,
            "input_mode": profile.input_mode,
            "env_preview": env_preview,
            "would_execute": False,
        }

    def dry_run(self, profile: AgentProfile, worktree_path: str | None = None) -> dict[str, Any]:
        return self.validate(profile, check_executable=False, worktree_path=worktree_path)
