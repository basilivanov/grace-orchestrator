# AI_HEADER: agent_env_builder — expands ${ENV_VAR}, inherits parent env, redacts secrets
# START_MODULE_CONTRACT
# purpose: Build subprocess env dict starting from os.environ.copy(),
#          overlaying profile env vars with ${VAR} expansion.
# inputs: raw_env (dict[str,str]), env_override (dict | None).
# returns: dict[str,str] inheriting PATH/HOME/etc. + expanded profile env.
# side_effects: Reads os.environ.
# error_behavior: Missing var → leaves unreplaced.
# END_MODULE_CONTRACT
# START_MODULE_MAP
# mapping:   - class: AgentEnvBuilder
# END_MODULE_MAP

from __future__ import annotations
import os
import re

_SECRET_KEYS = {"API_KEY", "TOKEN", "SECRET", "PASSWORD", "CREDENTIAL"}


class AgentEnvBuilder:
    def build(self, raw_env: dict[str, str], env_override: dict[str, str] | None = None) -> dict[str, str]:
        merged = dict(raw_env)
        if env_override:
            merged.update(env_override)
        expanded = {}
        for k, v in merged.items():
            expanded[k] = self._expand(v)
        env = os.environ.copy()
        # Strip leaked OPENCODE runtime vars from parent shell.
        # OPENCODE_SERVER_PASSWORD without OPENCODE_SERVER_URL causes
        # `opencode run` to look up a non-existent server session and
        # exit with "Session not found". OPENCODE=1, OPENCODE_PID, etc.
        # mark the current shell as already inside an opencode run.
        for k in [k for k in list(env) if k == "OPENCODE" or k.startswith("OPENCODE_") and k not in expanded]:
            del env[k]
        env.update(expanded)
        return env

    def resolve(self, value: str, env: dict[str, str] | None = None) -> str:
        """Expand ${VAR} references in a single value against *env* (or os.environ).

        When *env* is provided, lookups use *env* first, then fall back to
        os.environ. This lets extras resolve against the final subprocess env
        (which may contain vars injected by the backend, not just os.environ).
        """
        return self._expand(value, env)

    def _expand(self, value: str, env: dict[str, str] | None = None) -> str:
        def _replacer(m: re.Match) -> str:
            var = m.group(1)
            if env is not None and var in env:
                return env[var]
            return os.environ.get(var, m.group(0))
        return re.sub(r"\$\{(\w+)\}", _replacer, value)

    def preview(self, env: dict[str, str]) -> dict[str, str]:
        redacted = {}
        for k, v in env.items():
            if any(s in k.upper() for s in _SECRET_KEYS):
                redacted[k] = "****"
            else:
                redacted[k] = v
        return redacted
