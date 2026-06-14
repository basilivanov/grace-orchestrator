from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any, Protocol

from pydantic import BaseModel

from grace_control.runtime.agent_runtime_contract import AgentRuntimeContract


class AgentExecutionAdapterResult(BaseModel):
    ok: bool
    accepted: bool = False
    adapter: str
    command: list[str]
    cwd: str
    stdout: str = ""
    stderr: str = ""
    raw_events: list[dict] = []
    exit_code: int | None = None
    duration_ms: int = 0
    failure_code: str | None = None
    failure_stage: str | None = None
    failure_summary: str | None = None
    session_id: str | None = None
    model: str | None = None
    agent_name: str | None = None
    prompt_sha256: str | None = None


class AgentExecutionAdapter(ABC):

    @abstractmethod
    async def run(self, contract: AgentRuntimeContract, prompt: str) -> AgentExecutionAdapterResult:
        ...
