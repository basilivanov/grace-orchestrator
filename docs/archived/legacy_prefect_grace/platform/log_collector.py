# ############################################################################
# AI_HEADER: log_collector
# ROLE: Bounded JSONL collector for GRACE structured execution traces.
# ############################################################################

# START_MODULE_CONTRACT
# purpose: Write bounded packet execution trace events to local JSONL artifacts.
# inputs: Artifact root, packet ID, event dictionaries, and max event limit.
# returns: LogCollector with collection counters and trace file path.
# side_effects: Creates artifact directories and appends JSONL trace entries.
# emitted_logs: structured execution_trace.jsonl entries when used by logger.
# error_behavior: Fail-safe; collection and flush errors are captured and never raised.
# END_MODULE_CONTRACT

# START_MODULE_MAP
# mapping:
#   - class: LogCollector
# END_MODULE_MAP

from __future__ import annotations

import json
from pathlib import Path
from typing import Any


DEFAULT_MAX_EVENTS = 10000


class LogCollector:
    """Bounded JSONL writer for one packet execution."""

    # START_FUNCTION_CONTRACT
    # name: __init__
    # purpose: Initialize collector for packet execution trace JSONL.
    # inputs: artifact_root (Path|str), packet_id (str), max_events (int).
    # returns: LogCollector instance.
    # side_effects: None until first collect call.
    # emitted_logs: None.
    # error_behavior: Stores initialization values; does not raise for filesystem until collect.
    # END_FUNCTION_CONTRACT
    def __init__(
        self,
        *,
        artifact_root: str | Path,
        packet_id: str,
        max_events: int = DEFAULT_MAX_EVENTS,
    ) -> None:
        self.artifact_root = Path(artifact_root)
        self.packet_id = packet_id
        self.max_events = max(0, int(max_events))
        self.event_count = 0
        self.dropped_count = 0
        self.failures: list[str] = []
        self.path = self.artifact_root / packet_id / "execution_trace.jsonl"

    # START_FUNCTION_CONTRACT
    # name: collect
    # purpose: Append one JSON-serializable event to execution_trace.jsonl.
    # inputs: log_entry (dict[str, Any]).
    # returns: bool indicating whether event was written.
    # side_effects: Creates packet artifact directory and appends one JSONL line.
    # emitted_logs: One JSON object per line until max_events is reached.
    # error_behavior: Returns False on limit or IO/serialization failure; never raises.
    # END_FUNCTION_CONTRACT
    def collect(self, log_entry: dict[str, Any]) -> bool:
        if self.event_count >= self.max_events:
            self.dropped_count += 1
            return False

        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            with self.path.open("a", encoding="utf-8") as handle:
                handle.write(json.dumps(log_entry, sort_keys=True, ensure_ascii=True))
                handle.write("\n")
            self.event_count += 1
            return True
        except Exception as exc:
            self.failures.append(str(exc))
            return False

    # START_FUNCTION_CONTRACT
    # name: flush
    # purpose: Flush collector state after trace context exit.
    # inputs: None.
    # returns: bool indicating flush success.
    # side_effects: None for append-only per-event writer.
    # emitted_logs: None.
    # error_behavior: Returns False on unexpected failure; never raises.
    # END_FUNCTION_CONTRACT
    def flush(self) -> bool:
        try:
            return True
        except Exception as exc:
            self.failures.append(str(exc))
            return False

    # START_FUNCTION_CONTRACT
    # name: to_dict
    # purpose: Serialize collector counters for tests and evidence.
    # inputs: None.
    # returns: dict[str, Any] with trace path and counters.
    # side_effects: None.
    # emitted_logs: None.
    # error_behavior: Never raises.
    # END_FUNCTION_CONTRACT
    def to_dict(self) -> dict[str, Any]:
        return {
            "path": str(self.path),
            "event_count": self.event_count,
            "dropped_count": self.dropped_count,
            "failures": list(self.failures),
            "max_events": self.max_events,
        }
