# ############################################################################
# AI_HEADER: structured_logger
# ROLE: Structured JSONL logging with trace_id propagation for GRACE Control Plane.
# ############################################################################

# START_MODULE_CONTRACT
# purpose: Provide GraceLogger for structured JSONL output and trace_context for request tracing.
# inputs: Log messages with key=value context.
# returns: None (writes to stderr).
# side_effects: Writes JSON lines to stderr.
# emitted_logs: None (self-logging minimal).
# error_behavior: Never raises — logging failures are silent.
# END_MODULE_CONTRACT

# START_MODULE_MAP
# mapping:
#   - class: GraceLogger
#   - function: log_event
#   - function: trace_context
#   - function: get_trace_id
# END_MODULE_MAP

from __future__ import annotations

import json
import sys
import threading
from contextlib import contextmanager
from datetime import datetime, timezone
from typing import Any

_trace_local = threading.local()

#START_BLOCK_LOGGER
class GraceLogger:
    def __init__(self, component: str):
        self._component = component

    def _emit(self, level: str, message: str, **kwargs: Any) -> None:
        trace_id = getattr(_trace_local, "trace_id", None)
        entry: dict[str, Any] = {
            "ts": datetime.now(timezone.utc).isoformat() + "Z",
            "level": level,
            "component": self._component,
            "msg": message,
        }
        if trace_id:
            entry["trace_id"] = trace_id
        if kwargs:
            entry["ctx"] = kwargs
        try:
            print(json.dumps(entry, default=str), file=sys.stderr)
        except Exception:
            pass

    def info(self, message: str, **kwargs: Any) -> None:
        self._emit("INFO", message, **kwargs)

    def warn(self, message: str, **kwargs: Any) -> None:
        self._emit("WARN", message, **kwargs)

    def error(self, message: str, **kwargs: Any) -> None:
        self._emit("ERROR", message, **kwargs)

    def debug(self, message: str, **kwargs: Any) -> None:
        self._emit("DEBUG", message, **kwargs)

#END_BLOCK_LOGGER

#START_BLOCK_HELPERS
def log_event(level: str, message: str, **kwargs: Any) -> None:
    trace_id = getattr(_trace_local, "trace_id", None)
    entry: dict[str, Any] = {
        "ts": datetime.now(timezone.utc).isoformat() + "Z",
        "level": level,
        "msg": message,
    }
    if trace_id:
        entry["trace_id"] = trace_id
    if kwargs:
        entry["ctx"] = kwargs
    try:
        print(json.dumps(entry, default=str), file=sys.stderr)
    except Exception:
        pass


@contextmanager
def trace_context(trace_id: str):
    old = getattr(_trace_local, "trace_id", None)
    _trace_local.trace_id = trace_id
    try:
        yield
    finally:
        _trace_local.trace_id = old


def get_trace_id() -> str | None:
    return getattr(_trace_local, "trace_id", None)

#END_BLOCK_HELPERS
