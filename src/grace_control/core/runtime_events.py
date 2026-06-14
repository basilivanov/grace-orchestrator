# ############################################################################
# AI_HEADER: runtime_events
# ROLE: RuntimeEventLogger — emit structured events to GraceLogger + events.jsonl
# ############################################################################

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from grace_control.config.settings import settings
from grace_control.core.runtime_artifacts import RuntimeArtifactRef, RuntimeArtifactStore
from grace_control.core.runtime_trace import RuntimeTraceContext, get_current_trace
from grace_control.core.structured_logger import GraceLogger

_log = GraceLogger("runtime_events")


class RuntimeEventLogger:

    def __init__(self, store: RuntimeArtifactStore | None = None, disabled: bool | None = None):
        self._store = store or RuntimeArtifactStore()
        if disabled is not None:
            self._disabled = disabled
        else:
            self._disabled = not getattr(settings, "runtime_observability_enabled", True)

    def emit(
        self,
        *,
        trace: RuntimeTraceContext | None = None,
        level: str = "info",
        event: str,
        stage: str,
        component: str,
        status: str | None = None,
        message: str | None = None,
        duration_ms: int | None = None,
        artifact_refs: list[RuntimeArtifactRef] | None = None,
        payload: dict | None = None,
    ) -> None:
        if self._disabled:
            return

        resolved_trace = trace or get_current_trace()
        ts = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.") + f"{datetime.now(timezone.utc).microsecond:06d}Z"

        entry: dict[str, Any] = {
            "ts": ts,
            "level": level,
            "event": event,
            "stage": stage,
            "component": component,
        }

        if resolved_trace:
            entry["trace_id"] = resolved_trace.trace_id
            entry["feature_id"] = resolved_trace.feature_id
            entry["packet_id"] = resolved_trace.packet_id
            entry["wave_id"] = resolved_trace.wave_id
            entry["runtime_run_id"] = resolved_trace.runtime_run_id
        if status:
            entry["status"] = status
        if message:
            entry["message"] = message
        if duration_ms is not None:
            entry["duration_ms"] = duration_ms
        if artifact_refs:
            entry["artifact_refs"] = [r.model_dump() for r in artifact_refs]
        if payload:
            entry["payload"] = payload

        # Emit through existing GraceLogger
        log_level_map = {"debug": _log.debug, "info": _log.info, "warn": _log.warn, "error": _log.error}
        log_fn = log_level_map.get(level, _log.info)
        log_fn(event, trace_id=resolved_trace.trace_id if resolved_trace else None, stage=stage, status=status)

        # Append to events.jsonl
        try:
            feature_id = resolved_trace.feature_id if resolved_trace else None
            if feature_id:
                events_dir = self._store.feature_dir(feature_id)
                events_dir.mkdir(parents=True, exist_ok=True)
                events_path = events_dir / "events.jsonl"
                with open(str(events_path), "a", encoding="utf-8") as f:
                    f.write(json.dumps(entry, ensure_ascii=False, default=str) + "\n")
        except Exception as exc:
            _log.warn("events_jsonl_append_failed", error=str(exc)[:200])
