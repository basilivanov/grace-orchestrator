# AI_HEADER: agent_profiles — W7 declarative agent profile loader
# START_MODULE_CONTRACT
# purpose: Load and validate agent profiles from agent_profiles.yaml.
#          Uses the top-level `agents:` key (W7 revised spec).
#          Rejects string command — requires list[str].
# inputs: None (reads agent_profiles.yaml from config dir).
# returns: dict[executor_id, AgentProfile].
# side_effects: Reads YAML, cached.
# error_behavior: Raises ValueError on validation errors.
# END_MODULE_CONTRACT
# START_MODULE_MAP
# mapping:   - class: AgentProfile   - function: load_agent_profiles   - function: get_agent_profile
# END_MODULE_MAP

from __future__ import annotations
from pathlib import Path
from typing import Any

import yaml

_PROFILES_PATH = Path(__file__).resolve().parent / "agent_profiles.yaml"
_cache: dict[str, dict] | None = None


class AgentProfile:
    def __init__(self, executor_id: str, raw: dict[str, Any]) -> None:
        self.executor_id = executor_id
        self.backend = raw.get("backend", "cli")
        self.command = raw.get("command", [])
        self.extras = raw.get("extras", [])
        self.model = raw.get("model", "")
        self.effort = raw.get("effort", "medium")
        self.cwd_template = str(raw.get("cwd", "{worktree_path}"))
        self.timeout_seconds = int(raw.get("timeout_seconds", 600))
        self.minimal_repo = bool(raw.get("minimal_repo", False))
        self.skip_context_builder = bool(raw.get("skip_context_builder", False))
        self.env = dict(raw.get("env", {}))
        self.input_mode = raw.get("input", {}).get("mode", "none") if isinstance(raw.get("input"), dict) else "none"
        self.input_template = raw.get("input", {}).get("template", "") if isinstance(raw.get("input"), dict) else ""
        self.resume_mode = raw.get("resume_mode", "never")
        self.resume_flag = raw.get("resume_flag", "")
        self.fork_flag = raw.get("fork_flag", "")
        self.inject_dir = raw.get("inject_dir", False)
        self.multimodal = raw.get("multimodal", False)
        # TZ §6: workspace / session safety knobs read by packet_executor
        # and agent_run_service. None = inherit from settings.
        self.workspace_mode = raw.get("workspace_mode")  # full_git_worktree | target_repo_worktree | scoped_copy
        self.resume_safe = bool(raw.get("resume_safe", False))
        self.validate_session_before_use = bool(raw.get("validate_session_before_use", True))
        # Per-profile override for scoped_copy verification safety.
        # "unsafe_allowed_for_fixture" lets the coder-opencode-fixture
        # run even with a scoped_copy workspace (it has no broad-repo
        # verification needs).
        self.workspace_scope_safety = raw.get("workspace_scope_safety", "default")
        self._validate()

    def _validate(self) -> None:
        if isinstance(self.command, str):
            raise ValueError(
                f"Agent '{self.executor_id}': `command` must be a list of strings, "
                f"got string '{self.command}'. Use `command: [\"{self.command}\"]` instead."
            )
        if not isinstance(self.command, list):
            raise ValueError(f"Agent '{self.executor_id}': `command` must be a list of strings")
        for i, part in enumerate(self.command):
            if not isinstance(part, str):
                raise ValueError(f"Agent '{self.executor_id}': command[{i}] must be a string, got {type(part).__name__}")
        if isinstance(self.extras, str):
            raise ValueError(
                f"Agent '{self.executor_id}': `extras` must be a list of strings, "
                f"got string '{self.extras}'."
            )
        if not isinstance(self.extras, list):
            raise ValueError(f"Agent '{self.executor_id}': `extras` must be a list of strings")
        for i, part in enumerate(self.extras):
            if not isinstance(part, str):
                raise ValueError(f"Agent '{self.executor_id}': extras[{i}] must be a string, got {type(part).__name__}")

    def to_dict(self) -> dict[str, Any]:
        return {
            "executor_id": self.executor_id,
            "backend": self.backend,
            "command": list(self.command),
            "extras": list(self.extras),
            "model": self.model,
            "effort": self.effort,
            "cwd": self.cwd_template,
            "timeout_seconds": self.timeout_seconds,
            "env": dict(self.env),
            "input_mode": self.input_mode,
            "input_template": self.input_template,
            "resume_mode": self.resume_mode,
            "resume_flag": self.resume_flag,
            "fork_flag": self.fork_flag,
            "inject_dir": self.inject_dir,
            "multimodal": self.multimodal,
            "minimal_repo": self.minimal_repo,
            "skip_context_builder": self.skip_context_builder,
            # TZ §6: workspace + session safety knobs read by packet_executor
            # and agent_run_service via dict access. Must be present in
            # to_dict() or they'll silently fall back to settings defaults.
            "workspace_mode": self.workspace_mode,
            "resume_safe": self.resume_safe,
            "validate_session_before_use": self.validate_session_before_use,
            "workspace_scope_safety": self.workspace_scope_safety,
        }


def load_agent_profiles() -> dict[str, AgentProfile]:
    global _cache
    if _cache is not None:
        return _cache
    if not _PROFILES_PATH.exists():
        _cache = {}
        return _cache
    raw = yaml.safe_load(_PROFILES_PATH.read_text()) or {}
    agents_raw = raw.get("agents", {})
    profiles: dict[str, AgentProfile] = {}
    for executor_id, agent_cfg in agents_raw.items():
        if isinstance(agent_cfg, dict):
            profiles[executor_id] = AgentProfile(executor_id, agent_cfg)
    _cache = profiles
    return profiles


def get_agent_profile(executor_id: str) -> AgentProfile | None:
    return load_agent_profiles().get(executor_id)


def reset_cache() -> None:
    global _cache
    _cache = None
