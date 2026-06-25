from __future__ import annotations

import json

from grace_control.core.structured_logger import GraceLogger

_log = GraceLogger("opencode_event_collector")


class OpenCodeEventCollector:
    """Read opencode stdout line-by-line, separate JSON events from plain text."""

    def __init__(self, require_json_events: bool = True):
        self._require_json = require_json_events
        self._raw_events: list[dict] = []
        self._plain_lines: list[str] = []

    def feed_line(self, line: str) -> None:
        stripped = line.strip()
        if not stripped:
            self._plain_lines.append(line)
            return
        if stripped.startswith("{"):
            try:
                parsed = json.loads(stripped)
                self._raw_events.append(parsed)
                return
            except json.JSONDecodeError:
                pass
        self._plain_lines.append(line)

    @property
    def raw_events(self) -> list[dict]:
        return list(self._raw_events)

    @property
    def plain_text(self) -> str:
        return "".join(self._plain_lines)

    def has_meaningful_output(self) -> bool:
        if self._require_json:
            return len(self._raw_events) > 0
        return bool(self._raw_events) or bool(self.plain_text.strip())

    def reset(self) -> None:
        self._raw_events.clear()
        self._plain_lines.clear()

    @property
    def tokens_in(self) -> int:
        tokens = 0
        for ev in self._raw_events:
            if not isinstance(ev, dict):
                continue
            for usage_key in ("usage", "llm_usage"):
                usage_val = ev.get(usage_key)
                if isinstance(usage_val, dict):
                    tokens += usage_val.get("input_tokens") or usage_val.get("prompt_tokens") or 0
        return tokens

    @property
    def tokens_out(self) -> int:
        tokens = 0
        for ev in self._raw_events:
            if not isinstance(ev, dict):
                continue
            for usage_key in ("usage", "llm_usage"):
                usage_val = ev.get(usage_key)
                if isinstance(usage_val, dict):
                    tokens += usage_val.get("output_tokens") or usage_val.get("completion_tokens") or 0
        return tokens
