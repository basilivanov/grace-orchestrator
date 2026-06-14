from __future__ import annotations

from enum import Enum

from pydantic import BaseModel


class OpenCodeServerStatus(str, Enum):
    STOPPED = "stopped"
    STARTING = "starting"
    RUNNING = "running"
    UNHEALTHY = "unhealthy"
    FAILED = "failed"


class OpenCodeServerState(BaseModel):
    status: OpenCodeServerStatus
    url: str = ""
    pid: int | None = None
    log_path: str = ""
    failure_code: str | None = None
    failure_summary: str | None = None


class OpenCodeServerHealth(BaseModel):
    ok: bool
    url: str
    pid: int | None = None
    latency_ms: int | None = None
    failure_code: str | None = None
    summary: str = ""
