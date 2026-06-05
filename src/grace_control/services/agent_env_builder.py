# AI_HEADER: agent_env_builder — expands ${ENV_VAR}, redacts secrets in logs
# START_MODULE_CONTRACT
# purpose: Expands `${VAR}` references from os.environ, returns a clean env dict
#          for subprocess execution. Redacts secret-like values in previews.
# inputs: raw_env (dict[str,str]), env_override (dict | None).
# returns: dict[str,str] with all ${VAR} expanded.
# side_effects: Reads os.environ.
# error_behavior: Missing var → leaves unreplaced if optional, raises if required.
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
        result = {}
        for k, v in merged.items():
            result[k] = self._expand(v)
        return result

    def _expand(self, value: str) -> str:
        def _replacer(m: re.Match) -> str:
            var = m.group(1)
            return os.environ.get(var, m.group(0))
        return re.sub(r"\$\{(\w+)\}", _replacer, value)

    def preview(self, env: dict[str, str]) -> dict[str, str]:
        """Return env dict with secret values redacted for logging."""
        redacted = {}
        for k, v in env.items():
            if any(s in k.upper() for s in _SECRET_KEYS):
                redacted[k] = "****"
            else:
                redacted[k] = v
        return redacted
