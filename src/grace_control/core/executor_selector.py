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

import os
from typing import Any

from grace_control.config.agent_profiles import AgentProfile, load_agent_profiles


def _profile_priority_key(profile: AgentProfile) -> tuple[int, int]:
    return (getattr(profile, "priority", 0), profile.timeout_seconds)


def _coder_ladder(profiles: list[AgentProfile]) -> list[AgentProfile]:
    """Return enabled mini-swe coders in configured fallback order."""
    mini_profiles = [
        profile for profile in profiles
        if isinstance(profile.command, list)
        and "grace_control.runtime.mini_swe_runner" in " ".join(profile.command)
    ]
    candidates = mini_profiles or profiles
    configured = [
        item.strip()
        for item in os.environ.get("GRACE_CODER_EXECUTOR_LADDER", "").split(",")
        if item.strip()
    ]
    if configured:
        by_id = {profile.executor_id: profile for profile in candidates}
        ordered = [by_id[executor_id] for executor_id in configured if executor_id in by_id]
        if ordered:
            return ordered
    return sorted(candidates, key=_profile_priority_key, reverse=True)


def select_executor(role: str, attempt: int = 1) -> dict[str, Any]:
    from grace_control.config.agent_profiles import get_agent_profile
    if role == "coder":
        live_profile = os.environ.get("GRACE_LIVE_EXECUTOR_PROFILE")
        if live_profile:
            match = get_agent_profile(live_profile)
            if match:
                # W09: Fail-closed — reject disabled profiles even via live override.
                if match.disabled:
                    raise ValueError(
                        f"GRACE_LIVE_EXECUTOR_PROFILE={live_profile!r} selects a "
                        f"disabled profile. Disabled profiles must not be used for "
                        f"execution. Either enable the profile in agent_profiles.yaml "
                        f"or choose a different live profile."
                    )
                return match.to_dict()

    profiles = list(load_agent_profiles().values())
    # W09: Skip disabled profiles — they must not be selected for execution.
    profiles = [p for p in profiles if not p.disabled]
    if not profiles:
        return {"executor_id": "default", "model": "gemini-3.5-flash",
                "command": ["agy", "run"], "effort": "medium", "cwd": "{worktree_path}",
                "env": {}, "extras": [], "input_mode": "none", "input_template": ""}

    matching = [p for p in profiles if _profile_matches_role(p.executor_id, role)]
    if not matching:
        return profiles[0].to_dict()

    if role == "coder":
        matching = _coder_ladder(matching)
    else:
        matching.sort(key=_profile_priority_key, reverse=True)
    index = (attempt - 1) % len(matching) if role == "coder" else min(attempt - 1, len(matching) - 1)
    return matching[index].to_dict()


def _profile_matches_role(executor_id: str, role: str) -> bool:
    """Heuristic: profile ID containing the role name matches.

    For context_collector role, prefer context-json-flash (internal
    JSON helper, strictly read-only) over context-collector-flash
    (which is the live Stage 0 bundle writer). context-json-flash
    must be selected first because it does NOT have coder-like
    permissions.
    """
    role_map = {
        "architect": ["architect", "premium"],
        "coder": ["coder", "opencode"],
        "verifier": ["verifier", "verify"],
        "reviewer": ["reviewer"],
        "context_collector": ["context-json-flash", "context-collector-flash", "context"],
    }
    keywords = role_map.get(role, [role])
    eid_lower = executor_id.lower()
    return any(kw in eid_lower for kw in keywords)


def get_escalation(role: str) -> list[dict[str, Any]]:
    profiles = list(load_agent_profiles().values())
    # W09: Skip disabled profiles
    profiles = [p for p in profiles if not p.disabled]
    matching = [p for p in profiles if _profile_matches_role(p.executor_id, role)]
    if role == "coder":
        matching = _coder_ladder(matching)
    else:
        matching.sort(key=_profile_priority_key, reverse=True)
    return [p.to_dict() for p in matching]


def resolve_model(role: str) -> dict[str, Any]:
    """Backward-compat: return model+command+kind+executor_id for a role.

    Callers (ContextCollector, ReviewerGate) need a string `command`
    (CLI binary name) and a `model` string. The `kind` field indicates
    which CLI to use (opencode/agy/...). The `executor_id` field
    identifies the exact agent profile for profile lookup in run_llm.
    """
    profiles = list(load_agent_profiles().values())
    # W09: Skip disabled profiles
    profiles = [p for p in profiles if not p.disabled]
    matching = [p for p in profiles if _profile_matches_role(p.executor_id, role)]
    if not matching:
        return {"model": "gemini-3.5-flash", "command": "opencode", "kind": "opencode", "executor_id": "opencode"}

    # For context_collector role, prefer context-json-flash (internal read-only
    # JSON helper) over context-collector-flash (live Stage 0 bundle writer).
    if role == "context_collector":
        for candidate in ("context-json-flash", "context-collector-flash"):
            for p in matching:
                if p.executor_id == candidate:
                    best = p
                    break
            else:
                continue
            break
        else:
            matching.sort(key=_profile_priority_key, reverse=True)
            best = matching[0]
    else:
        matching.sort(key=_profile_priority_key, reverse=True)
        best = matching[0]

    cmd = best.command
    cli_name = cmd[0] if isinstance(cmd, list) and cmd else "opencode"
    kind_map = {"opencode": "opencode", "agy": "agy", "python3": "mini-swe", "python": "mini-swe"}
    kind = "opencode"
    command_text = " ".join(cmd) if isinstance(cmd, list) else str(cmd)
    if "grace_control.runtime.mini_swe_runner" in command_text:
        kind = "mini-swe"
    else:
        for prefix, k in kind_map.items():
            if cli_name.startswith(prefix):
                kind = k
                break
    return {"model": best.model or "gemini-3.5-flash", "command": cli_name, "kind": kind, "executor_id": best.executor_id}
