# ############################################################################
# AI_HEADER: runtime_redaction
# ROLE: RuntimeRedactor — redact secrets from env/payload artifacts
# ############################################################################

from __future__ import annotations

import os
import re
from typing import Any

from grace_control.core.structured_logger import GraceLogger

_log = GraceLogger("runtime_redaction")

# Keys to always redact
_REDACT_KEYS: set[str] = {
    "*_API_KEY",
    "*_TOKEN",
    "*_SECRET",
    "PASSWORD",
    "COOKIE",
    "AUTH",
    "OPENAI_API_KEY",
    "ANTHROPIC_API_KEY",
    "GEMINI_API_KEY",
    "DEEPSEEK_API_KEY",
}


def _key_matches(key: str) -> bool:
    """Check if key matches any redact pattern."""
    upper = key.upper()
    for pattern in _REDACT_KEYS:
        if pattern.startswith("*_"):
            base = pattern[2:]
            if upper.endswith(base):
                return True
        elif upper == pattern:
            return True
    return False


class RuntimeRedactor:

    def redact_env(self, env: dict[str, str] | None) -> dict[str, Any]:
        """Return redacted version of env dict."""
        if not env:
            return {}

        result: dict[str, Any] = {}
        for key, value in env.items():
            if _key_matches(key):
                result[key] = {
                    "present": True,
                    "redacted": True,
                }
            else:
                result[key] = value
        return result

    def redact_payload(self, payload: dict[str, Any]) -> dict[str, Any]:
        """Recursively redact sensitive keys in a payload dict."""
        if not payload:
            return payload

        result: dict[str, Any] = {}
        for key, value in payload.items():
            if _key_matches(str(key)):
                result[key] = {
                    "present": True,
                    "redacted": True,
                }
            elif isinstance(value, dict):
                result[key] = self.redact_payload(value)
            elif isinstance(value, list):
                result[key] = [
                    self.redact_payload(item) if isinstance(item, dict) else item
                    for item in value
                ]
            else:
                result[key] = value
        return result

    def redact_string(self, content: str) -> str:
        """Replace known secret patterns in string content."""
        result = content
        # Redact common API key patterns
        result = re.sub(
            r'(sk-[A-Za-z0-9]{20,})',
            'sk-...REDACTED',
            result,
        )
        result = re.sub(
            r'(\b[A-Za-z0-9+/]{40,}\b)',
            '...REDACTED',
            result,
        )
        return result
