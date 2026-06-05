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
        self.model = raw.get("model", "")
        self.effort = raw.get("effort", "medium")
        self.cwd_template = str(raw.get("cwd", "{worktree_path}"))
        self.timeout_seconds = int(raw.get("timeout_seconds", 600))
        self.env = dict(raw.get("env", {}))
        self.input_mode = raw.get("input", {}).get("mode", "none") if isinstance(raw.get("input"), dict) else "none"
        self.input_template = raw.get("input", {}).get("template", "") if isinstance(raw.get("input"), dict) else ""
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

    def to_dict(self) -> dict[str, Any]:
        return {
            "executor_id": self.executor_id,
            "command": list(self.command),
            "model": self.model,
            "effort": self.effort,
            "cwd": self.cwd_template,
            "timeout_seconds": self.timeout_seconds,
            "env": dict(self.env),
            "input_mode": self.input_mode,
            "input_template": self.input_template,
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
