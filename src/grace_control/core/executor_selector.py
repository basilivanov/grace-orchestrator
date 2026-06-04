# ############################################################################
# AI_HEADER: executor_selector
# ROLE: Select AI executor based on role, acceptance profile, and attempt — with escalation.
# ############################################################################

# START_MODULE_CONTRACT
# purpose: Load agent_profiles.yaml, select executor by role + attempt (cheap→medium→strong).
# inputs: role (architect/coder/verifier/reviewer), attempt number, acceptance_profile.
# returns: dict with executor_id, model, command.
# side_effects: Reads YAML file once, caches result.
# emitted_logs: None.
# error_behavior: Returns default executor on missing config.
# END_MODULE_CONTRACT

# START_MODULE_MAP
# mapping:
#   - function: load_profiles
#   - function: select_executor
#   - function: get_escalation
#   - function: resolve_model
# END_MODULE_MAP

from __future__ import annotations

from functools import lru_cache
from pathlib import Path

import yaml

DEFAULT_MODEL = "gemini-3.5-flash"
DEFAULT_EXECUTOR = {"executor_id": "default", "model": DEFAULT_MODEL, "command": "agy", "priority": 100}

_PROFILES_PATH = Path(__file__).parent.parent.parent / "prefect_grace" / "agent_profiles.yaml"


@lru_cache(maxsize=1)
def load_profiles() -> dict:
    if _PROFILES_PATH.exists():
        return yaml.safe_load(_PROFILES_PATH.read_text()) or {}
    return {}


def select_executor(role: str, attempt: int = 1) -> dict:
    profiles = load_profiles()
    executors = profiles.get("codex", {}).get("executors", [])

    matching = [e for e in executors if role in e.get("roles", [])]
    if not matching:
        return DEFAULT_EXECUTOR

    matching.sort(key=lambda e: e.get("priority", 0), reverse=True)

    # Escalation: attempt 1 → cheapest, attempt 2 → medium, attempt 3 → premium
    index = min(attempt - 1, len(matching) - 1)
    return matching[index]


def get_escalation(role: str) -> list[dict]:
    profiles = load_profiles()
    executors = profiles.get("codex", {}).get("executors", [])
    matching = [e for e in executors if role in e.get("roles", [])]
    matching.sort(key=lambda e: e.get("priority", 0), reverse=True)
    return matching


# START_FUNCTION_CONTRACT
# purpose: Resolve the highest priority executor for a given role.
# inputs: role (str)
# returns: dict with 'model', 'command', and 'kind'.
# side_effects: None.
# error_behavior: Returns default executor details if no match is found.
# END_FUNCTION_CONTRACT
def resolve_model(role: str) -> dict:
    profiles = load_profiles()
    executors = profiles.get("codex", {}).get("executors", [])
    matching = [e for e in executors if role in e.get("roles", [])]
    if not matching:
        return {
            "model": DEFAULT_MODEL,
            "command": DEFAULT_EXECUTOR.get("command", "agy"),
            "kind": "default"
        }
    
    matching.sort(key=lambda e: e.get("priority", 0), reverse=True)
    best = matching[0]
    
    return {
        "model": best.get("model", DEFAULT_MODEL),
        "command": best.get("command", DEFAULT_EXECUTOR.get("command", "agy")),
        "kind": best.get("kind", "default")
    }
