# ############################################################################
# AI_HEADER: structured_logger
# ROLE: Fail-safe GRACE structured log envelope builder.
# ############################################################################

# START_MODULE_CONTRACT
# purpose: Build GRACE Canon structured log envelopes and send them to a collector.
# inputs: Trace identifiers, packet metadata, event fields, and bounded extras.
# returns: StructuredLogger with fail-safe log_event API.
# side_effects: Writes JSONL through configured LogCollector.
# emitted_logs: structured JSONL envelopes with module, fn, block, event, result, trace_id, scenario_id, timestamp.
# error_behavior: Fail-safe; logging failures are captured and never raised to callers.
# END_MODULE_CONTRACT

# START_MODULE_MAP
# mapping:
#   - class: StructuredLogger
#   - function: utc_timestamp
#   - function: log_event
# END_MODULE_MAP

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any


REQUIRED_ENVELOPE_FIELDS = {
    "module",
    "fn",
    "block",
    "event",
    "result",
    "trace_id",
    "scenario_id",
    "timestamp",
}
CORE_EXTRA_FIELDS = {"packet_id", "attempt"}
MAX_EXTRA_FIELDS = 32
MAX_EXTRA_STRING_LENGTH = 4096


# START_FUNCTION_CONTRACT
# name: utc_timestamp
# purpose: Generate ISO-8601 UTC timestamp with trailing Z.
# inputs: None.
# returns: Timestamp string.
# side_effects: None.
# emitted_logs: None.
# error_behavior: Never raises under normal runtime.
# END_FUNCTION_CONTRACT
def utc_timestamp() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


class StructuredLogger:
    """Fail-safe structured logger for one trace context."""

    # START_FUNCTION_CONTRACT
    # name: __init__
    # purpose: Initialize logger with trace metadata and optional collector.
    # inputs: trace_id, scenario_id, packet_id, attempt, collector.
    # returns: StructuredLogger instance.
    # side_effects: None.
    # emitted_logs: None.
    # error_behavior: Never raises for missing collector.
    # END_FUNCTION_CONTRACT
    def __init__(
        self,
        *,
        trace_id: str,
        scenario_id: str,
        packet_id: str,
        attempt: int,
        collector: Any | None = None,
    ) -> None:
        self.trace_id = trace_id
        self.scenario_id = scenario_id
        self.packet_id = packet_id
        self.attempt = int(attempt)
        self.collector = collector
        self.failures: list[str] = []

    # START_FUNCTION_CONTRACT
    # name: log_event
    # purpose: Build and collect one GRACE log envelope.
    # inputs: module, fn, block, event, result, and optional bounded extra fields.
    # returns: dict[str, Any] envelope, or None when logging failed.
    # side_effects: Sends envelope to collector if present.
    # emitted_logs: One structured JSONL envelope.
    # error_behavior: Captures failures and returns None; never raises.
    # END_FUNCTION_CONTRACT
    def log_event(
        self,
        *,
        module: str,
        fn: str,
        block: str,
        event: str,
        result: str,
        **extra: Any,
    ) -> dict[str, Any] | None:
        try:
            envelope: dict[str, Any] = {
                "module": module,
                "fn": fn,
                "block": block,
                "event": event,
                "result": result,
                "trace_id": self.trace_id,
                "scenario_id": self.scenario_id,
                "timestamp": utc_timestamp(),
                "packet_id": self.packet_id,
                "attempt": self.attempt,
            }
            envelope.update(_bounded_extra(extra))
            if self.collector is not None:
                self.collector.collect(envelope)
            return envelope
        except Exception as exc:
            self.failures.append(str(exc))
            return None


# START_FUNCTION_CONTRACT
# name: log_event
# purpose: Fail-safe helper to log through an optional TraceContext-like object.
# inputs: trace_context plus event envelope fields and extras.
# returns: dict[str, Any] envelope, or None.
# side_effects: Writes through trace_context.logger when available.
# emitted_logs: One structured JSONL envelope when trace_context has logger.
# error_behavior: Returns None on missing logger or failure; never raises.
# END_FUNCTION_CONTRACT
def log_event(
    trace_context: Any | None,
    *,
    module: str,
    fn: str,
    block: str,
    event: str,
    result: str,
    **extra: Any,
) -> dict[str, Any] | None:
    try:
        logger = getattr(trace_context, "logger", None)
        if logger is None:
            return None
        return logger.log_event(
            module=module,
            fn=fn,
            block=block,
            event=event,
            result=result,
            **extra,
        )
    except Exception:
        return None


def _bounded_extra(extra: dict[str, Any]) -> dict[str, Any]:
    bounded: dict[str, Any] = {}
    for index, key in enumerate(sorted(extra.keys())):
        if index >= MAX_EXTRA_FIELDS:
            bounded["extra_fields_truncated"] = True
            break
        if key in REQUIRED_ENVELOPE_FIELDS or key in CORE_EXTRA_FIELDS:
            continue
        bounded[key] = _json_safe(extra[key])
    return bounded


def _json_safe(value: Any) -> Any:
    if value is None or isinstance(value, (bool, int, float)):
        return value
    if isinstance(value, str):
        if len(value) > MAX_EXTRA_STRING_LENGTH:
            return value[:MAX_EXTRA_STRING_LENGTH] + "...[truncated]"
        return value
    if isinstance(value, (list, tuple)):
        return [_json_safe(item) for item in list(value)[:100]]
    if isinstance(value, dict):
        safe: dict[str, Any] = {}
        for index, key in enumerate(sorted(value.keys(), key=str)):
            if index >= 100:
                safe["items_truncated"] = True
                break
            safe[str(key)] = _json_safe(value[key])
        return safe
    return str(value)
