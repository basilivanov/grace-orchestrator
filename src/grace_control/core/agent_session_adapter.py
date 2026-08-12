# ############################################################################
# AI_HEADER: agent_session_adapter
# ROLE: Abstract adapter for profile-backed session resume/fallback.
# ############################################################################

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, Field

from grace_control.core.structured_logger import GraceLogger

_log = GraceLogger("agent_session_adapter")


class AgentSessionHandle(BaseModel):
    runner: str = "profile"
    role: str = "architect"
    model: str | None = None
    session_id: str | None = None
    cwd: str | None = None
    stdout_path: str | None = None
    stderr_path: str | None = None
    metadata: dict = Field(default_factory=dict)


class AgentRunResult(BaseModel):
    accepted: bool
    output: str
    domain_status: str = ""
    stdout_path: str | None = None
    stderr_path: str | None = None
    session_handle: AgentSessionHandle | None = None
    session_mode: Literal[
        "actual_resume",
        "fallback_new_session",
        "new_session",
        "no_session_handle",
    ] = "new_session"
    duration_ms: int = 0
    error: str | None = None


@dataclass
class AgentRunRequest:
    prompt: str
    role: str = "architect"
    model: str | None = None
    executor_id: str | None = None
    session_handle: AgentSessionHandle | None = None
    cwd: Path | None = None
    timeout_s: int = 300


class AgentSessionAdapter:
    """Abstract adapter for launching/resuming architect LLM sessions."""

    async def run_new(self, request: AgentRunRequest) -> AgentRunResult:
        raise NotImplementedError

    async def resume(self, handle: AgentSessionHandle, message: str) -> AgentRunResult:
        """Resume existing session or fall back to new run."""
        raise NotImplementedError


class AgentProfileSessionAdapter(AgentSessionAdapter):
    """Profile-backed architect adapter using the canonical LLM runner."""

    def __init__(
        self,
        default_model: str = "openai/gpt-5.5",
        default_executor_id: str = "architect-mini-swe",
        runner_name: str = "mini-swe",
    ):
        self.default_model = default_model
        self.default_executor_id = default_executor_id
        self.runner_name = runner_name

    async def run_new(self, request: AgentRunRequest) -> AgentRunResult:
        from grace_control.core.llm_runner import run_llm

        model = request.model or self.default_model
        executor_id = request.executor_id or self.default_executor_id

        try:
            raw = await run_llm(
                request.prompt,
                role=request.role,
                model=model,
                cli=executor_id,
                cwd=request.cwd,
            )
            handle = AgentSessionHandle(
                runner=self.runner_name,
                role=request.role,
                model=model,
                session_id=None,
                cwd=str(request.cwd) if request.cwd else None,
                metadata={"executor_id": executor_id},
            )
            return AgentRunResult(
                accepted=True,
                output=raw,
                domain_status="completed",
                session_handle=handle,
                session_mode="new_session",
            )
        except Exception as e:
            return AgentRunResult(
                accepted=False,
                output="",
                domain_status="failed",
                session_mode="new_session",
                error=str(e)[:500],
            )

    async def resume(
        self,
        handle: AgentSessionHandle,
        message: str,
    ) -> AgentRunResult:
        """Attempt resume if session_id available; otherwise fallback to new run."""
        if handle.session_id:
            _log.info("session_resume_not_implemented",
                      role=handle.role, session_id=handle.session_id,
                      fallback="new_session")
            # Actual resume is not available for this profile adapter yet;
            # fall back to a fresh run while retaining the repair context.

        _log.info("repair_session_mode",
                  role=handle.role if handle else "unknown",
                  session_mode="fallback_new_session",
                  reason="no_actual_resume_backend")
        request = AgentRunRequest(
            prompt=message,
            role=handle.role,
            model=handle.model or self.default_model,
            executor_id=str(handle.metadata.get("executor_id") or self.default_executor_id),
            cwd=Path(handle.cwd) if handle.cwd else None,
        )
        result = await self.run_new(request)
        result.session_mode = "fallback_new_session"
        return result
