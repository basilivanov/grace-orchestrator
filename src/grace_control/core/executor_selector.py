# AI_HEADER: executor_selector — select executor from `agents:` profiles by role + escalation
# START_MODULE_CONTRACT
# purpose: Load agent profiles from `agents:` section, select executor by role + attempt.
#          Uses AgentProfile.to_dict() for standardized output format (list command, extras, etc.).
#          Legacy `codex.executors` section is ignored; all selection is from `agents:`.
# inputs: role (architect/coder/verifier/reviewer), attempt number.
# returns: dict with executor_id, command (list), model, effort, env, extras, input_mode, input_template, cwd.
# side_effects: Reads YAML once (cached via AgentProfile cache).
# emitted_logs: None.
# error_behavior: Returns minimal default executor on missing profiles.
# END_MODULE_CONTRACT

from __future__ import annotations

from typing import Any

from grace_control.config.agent_profiles import AgentProfile, load_agent_profiles


def select_executor(role: str, attempt: int = 1) -> dict[str, Any]:
    import os
    from grace_control.config.agent_profiles import get_agent_profile
    if role == "coder":
        live_profile = os.environ.get("GRACE_LIVE_EXECUTOR_PROFILE")
        if live_profile:
            match = get_agent_profile(live_profile)
            if match:
                return match.to_dict()

    profiles = list(load_agent_profiles().values())
    if not profiles:
        return {"executor_id": "default", "model": "gemini-3.5-flash",
                "command": ["agy", "run"], "effort": "medium", "cwd": "{worktree_path}",
                "env": {}, "extras": [], "input_mode": "none", "input_template": ""}

    matching = [p for p in profiles if _profile_matches_role(p.executor_id, role)]
    if not matching:
        return profiles[0].to_dict()

    matching.sort(key=lambda p: p.timeout_seconds, reverse=True)
    index = min(attempt - 1, len(matching) - 1)
    return matching[index].to_dict()


def _profile_matches_role(executor_id: str, role: str) -> bool:
    """Heuristic: profile ID containing the role name matches."""
    role_map = {
        "architect": ["architect", "premium"],
        "coder": ["coder", "opencode"],
        "verifier": ["verifier", "verify"],
        "reviewer": ["reviewer"],
        "context_collector": ["context"],
    }
    keywords = role_map.get(role, [role])
    eid_lower = executor_id.lower()
    return any(kw in eid_lower for kw in keywords)


def get_escalation(role: str) -> list[dict[str, Any]]:
    profiles = list(load_agent_profiles().values())
    matching = [p for p in profiles if _profile_matches_role(p.executor_id, role)]
    matching.sort(key=lambda p: p.timeout_seconds, reverse=False)
    return [p.to_dict() for p in matching]


def resolve_model(role: str) -> dict[str, Any]:
    """Backward-compat: return model+command+kind for a role.

    Callers (ContextCollector, ReviewerGate) need a string `command`
    (CLI binary name) and a `model` string. The `kind` field indicates
    which CLI to use (opencode/agy/...).
    """
    profiles = list(load_agent_profiles().values())
    matching = [p for p in profiles if _profile_matches_role(p.executor_id, role)]
    if not matching:
        return {"model": "gemini-3.5-flash", "command": "opencode", "kind": "opencode"}
    best = matching[0]
    # Derive CLI binary name from the first element of the command list
    cmd = best.command
    cli_name = cmd[0] if isinstance(cmd, list) and cmd else "opencode"
    kind_map = {"opencode": "opencode", "agy": "agy"}
    kind = "opencode"
    for prefix, k in kind_map.items():
        if cli_name.startswith(prefix):
            kind = k
            break
    return {"model": best.model or "gemini-3.5-flash", "command": cli_name, "kind": kind}
