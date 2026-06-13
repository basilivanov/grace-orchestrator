# ############################################################################
# AI_HEADER: agent_session_adapter
# ROLE: Abstract adapter for OpenCode session resume/fallback.
# ############################################################################

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from grace_control.core.structured_logger import GraceLogger

_log = GraceLogger("agent_session_adapter")


@dataclass
class AgentSessionHandle:
    runner: str = "opencode"
    role: str = "architect"
    model: str | None = None
    session_id: str | None = None
    cwd: str | None = None
    stdout_path: str | None = None
    stderr_path: str | None = None
    metadata: dict = field(default_factory=dict)


@dataclass
class AgentRunRequest:
    prompt: str
    role: str = "architect"
    model: str | None = None
    executor_id: str | None = None
    session_handle: AgentSessionHandle | None = None
    cwd: Path | None = None
    timeout_s: int = 300


@dataclass
class AgentRunResult:
    accepted: bool
    output: str
    domain_status: str = ""
    stdout_path: str | None = None
    stderr_path: str | None = None
    session_handle: AgentSessionHandle | None = None
    duration_ms: int = 0
    error: str | None = None


class AgentSessionAdapter:
    """Abstract adapter for launching/resuming architect LLM sessions."""

    async def run_new(self, request: AgentRunRequest) -> AgentRunResult:
        raise NotImplementedError

    async def resume(self, handle: AgentSessionHandle, message: str) -> AgentRunResult:
        """Resume existing session or fall back to new run."""
        raise NotImplementedError


class OpenCodeSessionAdapter(AgentSessionAdapter):
    """Adapter for OpenCode-backed architect sessions with resume support."""

    def __init__(self, default_model: str = "deepseek/deepseek-v4-pro"):
        self.default_model = default_model

    async def run_new(self, request: AgentRunRequest) -> AgentRunResult:
        from grace_control.core.llm_runner import run_llm

        model = request.model or self.default_model
        executor_id = request.executor_id or "deepseek-v4-pro"

        try:
            raw = await run_llm(
                request.prompt,
                role=request.role,
                model=model,
                cli=executor_id,
            )
            handle = AgentSessionHandle(
                runner="opencode",
                role=request.role,
                model=model,
                session_id=None,
                metadata={"executor_id": executor_id},
            )
            return AgentRunResult(
                accepted=True,
                output=raw,
                domain_status="completed",
                session_handle=handle,
            )
        except Exception as e:
            return AgentRunResult(
                accepted=False,
                output="",
                domain_status="failed",
                error=str(e)[:500],
            )

    async def resume(
        self,
        handle: AgentSessionHandle,
        message: str,
    ) -> AgentRunResult:
        """Attempt resume if session_id available; otherwise run new."""
        if handle.session_id:
            _log.info("session_resume_attempted", role=handle.role,
                      session_id=handle.session_id)
            # Future: implement actual OpenCode session resume via CLI
            # Currently: fall back to new run since OpenCode resume is not
            # available via the CLI backend.

        _log.info("session_resume_fallback", role=handle.role,
                  reason="no_available_backend")
        request = AgentRunRequest(
            prompt=message,
            role=handle.role,
            model=handle.model or self.default_model,
        )
        return await self.run_new(request)
