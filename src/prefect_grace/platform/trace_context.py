# ############################################################################
# AI_HEADER: trace_context
# ROLE: Thread-local GRACE trace context lifecycle management.
# ############################################################################

# START_MODULE_CONTRACT
# purpose: Create and manage nested thread-local structured logging trace contexts.
# inputs: Packet ID, attempt, scenario ID, optional artifact root and event limit.
# returns: TraceContext values and context manager helpers.
# side_effects: Pushes/pops thread-local context and flushes collector on exit.
# emitted_logs: structured logs through attached StructuredLogger.
# error_behavior: Fail-safe; context exit flush failures are captured and never raised.
# END_MODULE_CONTRACT

# START_MODULE_MAP
# mapping:
#   - dataclass: TraceContext
#   - class: trace_scope
#   - function: create_trace_context
#   - function: current_trace_context
# END_MODULE_MAP

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
import threading
from typing import Any

from prefect_grace.platform.log_collector import DEFAULT_MAX_EVENTS, LogCollector
from prefect_grace.platform.structured_logger import StructuredLogger


_LOCAL = threading.local()


@dataclass
class TraceContext:
    """Structured logging trace context for one packet attempt."""

    trace_id: str
    scenario_id: str
    packet_id: str
    attempt: int
    logger: StructuredLogger | None = None
    collector: LogCollector | None = None
    failures: list[str] = field(default_factory=list)

    # START_FUNCTION_CONTRACT
    # name: flush
    # purpose: Flush attached collector on context exit.
    # inputs: None.
    # returns: bool indicating flush success.
    # side_effects: Flushes collector if present.
    # emitted_logs: None.
    # error_behavior: Returns False and records failure; never raises.
    # END_FUNCTION_CONTRACT
    def flush(self) -> bool:
        try:
            if self.collector is None:
                return True
            return self.collector.flush()
        except Exception as exc:
            self.failures.append(str(exc))
            return False


# START_FUNCTION_CONTRACT
# name: create_trace_context
# purpose: Create TraceContext with canonical trace and scenario identifiers.
# inputs: packet_id, attempt, scenario_id, artifact_root, max_events.
# returns: TraceContext.
# side_effects: None until context is used for logging.
# emitted_logs: None.
# error_behavior: Falls back to logger without collector if collector construction fails.
# END_FUNCTION_CONTRACT
def create_trace_context(
    *,
    packet_id: str,
    attempt: int,
    scenario_id: str | None = None,
    artifact_root: str | Path | None = None,
    max_events: int = DEFAULT_MAX_EVENTS,
) -> TraceContext:
    trace_id = f"TRACE-{packet_id}-ATTEMPT-{int(attempt):03d}"
    normalized_scenario_id = _normalize_scenario_id(scenario_id)
    collector = None
    failures: list[str] = []
    if artifact_root is not None:
        try:
            collector = LogCollector(
                artifact_root=artifact_root,
                packet_id=packet_id,
                max_events=max_events,
            )
        except Exception as exc:
            failures.append(str(exc))

    logger = StructuredLogger(
        trace_id=trace_id,
        scenario_id=normalized_scenario_id,
        packet_id=packet_id,
        attempt=attempt,
        collector=collector,
    )
    return TraceContext(
        trace_id=trace_id,
        scenario_id=normalized_scenario_id,
        packet_id=packet_id,
        attempt=int(attempt),
        logger=logger,
        collector=collector,
        failures=failures,
    )


class trace_scope:
    """Context manager that pushes a TraceContext to thread-local storage."""

    # START_FUNCTION_CONTRACT
    # name: __init__
    # purpose: Store TraceContext for lifecycle management.
    # inputs: trace_context.
    # returns: trace_scope instance.
    # side_effects: None.
    # emitted_logs: None.
    # error_behavior: Never raises for normal inputs.
    # END_FUNCTION_CONTRACT
    def __init__(self, trace_context: TraceContext):
        self.trace_context = trace_context

    # START_FUNCTION_CONTRACT
    # name: __enter__
    # purpose: Push context to thread-local stack.
    # inputs: None.
    # returns: TraceContext.
    # side_effects: Updates thread-local context stack.
    # emitted_logs: None.
    # error_behavior: Propagates only unexpected thread-local errors.
    # END_FUNCTION_CONTRACT
    def __enter__(self) -> TraceContext:
        stack = _context_stack()
        stack.append(self.trace_context)
        return self.trace_context

    # START_FUNCTION_CONTRACT
    # name: __exit__
    # purpose: Pop context from thread-local stack and flush collector.
    # inputs: exc_type, exc, tb.
    # returns: False to preserve caller exceptions.
    # side_effects: Updates thread-local context stack and flushes collector.
    # emitted_logs: None.
    # error_behavior: Captures flush/pop failures and never suppresses caller exception.
    # END_FUNCTION_CONTRACT
    def __exit__(self, exc_type: Any, exc: Any, tb: Any) -> bool:
        try:
            stack = _context_stack()
            if stack and stack[-1] is self.trace_context:
                stack.pop()
            elif self.trace_context in stack:
                stack.remove(self.trace_context)
        except Exception as pop_exc:
            self.trace_context.failures.append(str(pop_exc))
        self.trace_context.flush()
        return False


# START_FUNCTION_CONTRACT
# name: current_trace_context
# purpose: Return current thread-local TraceContext if present.
# inputs: None.
# returns: TraceContext or None.
# side_effects: None.
# emitted_logs: None.
# error_behavior: Returns None on missing stack.
# END_FUNCTION_CONTRACT
def current_trace_context() -> TraceContext | None:
    stack = getattr(_LOCAL, "stack", None)
    if not stack:
        return None
    return stack[-1]


def _context_stack() -> list[TraceContext]:
    stack = getattr(_LOCAL, "stack", None)
    if stack is None:
        stack = []
        _LOCAL.stack = stack
    return stack


def _normalize_scenario_id(scenario_id: str | None) -> str:
    if not scenario_id:
        return "SCN-DEFAULT"
    value = scenario_id.strip()
    if value.startswith("SCN-"):
        return value
    return "SCN-" + value.upper().replace("_", "-").replace(" ", "-")
