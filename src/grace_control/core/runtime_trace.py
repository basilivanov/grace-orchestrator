# ############################################################################
# AI_HEADER: runtime_trace
# ROLE: RuntimeTraceContext — trace_id propagation for observability spine
# ############################################################################

from __future__ import annotations

import hashlib
import threading
import uuid
from datetime import datetime, timezone

from pydantic import BaseModel

_trace_local = threading.local()


class RuntimeTraceContext(BaseModel):
    trace_id: str
    feature_id: str | None = None
    packet_id: str | None = None
    wave_id: str | None = None
    runtime_run_id: str | None = None
    stage: str | None = None
    role: str | None = None


def generate_trace_id() -> str:
    """Generate a unique trace_id."""
    raw = f"{uuid.uuid4().hex}-{datetime.now(timezone.utc).isoformat()}"
    return hashlib.sha256(raw.encode()).hexdigest()[:16]


def set_current_trace(trace: RuntimeTraceContext) -> None:
    _trace_local.current = trace


def get_current_trace() -> RuntimeTraceContext | None:
    return getattr(_trace_local, "current", None)


def clear_current_trace() -> None:
    _trace_local.current = None
