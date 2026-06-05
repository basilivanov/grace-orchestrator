# ############################################################################
# AI_HEADER: agent_gateway_service
# ROLE: Provider-agnostic agent gateway — picks the right provider, builds the
#       request, applies timeout + retry, normalizes the response, and
#       persists artifacts. W7 of
#       source/codex/tz-api-first-cleanup-waves-w0-w11.md.
# ############################################################################

# START_MODULE_CONTRACT
# purpose: Single service that owns provider/model/prompt/timeout/retry
#          concerns. ApiAgentBackend delegates to this; nothing else should
#          import the underlying provider SDKs directly.
# inputs: provider, model, role, packet_id, packet_markdown, worktree_path,
#         timeout_seconds, max_retries.
# returns: dict with stdout, stderr, messages, changed_files, duration_ms.
# side_effects: Writes .agent_gateway.log + per-attempt logs to worktree.
# emitted_logs: agent_gateway_dispatch, agent_gateway_attempt_failed,
#               agent_gateway_timeout, agent_gateway_done.
# error_behavior: Never raises; returns dict(reason=...) on failure.
# END_MODULE_CONTRACT

# START_MODULE_MAP
# mapping:
#   - class: AgentGatewayService
#     methods:
#       - dispatch
#       - _call_provider
#       - _persist_artifacts
# END_MODULE_MAP

from __future__ import annotations

import time
from pathlib import Path
from typing import Any

from grace_control.core.structured_logger import GraceLogger

_log = GraceLogger("agent_gateway")

VALID_PROVIDERS = {"openai", "anthropic", "deepseek", "gemini", "cliproxy", "mock"}


# START_FUNCTION_CONTRACT
# name: _call_provider
# purpose: Call the provider-specific client. MVP implementation:
#          - `mock` always succeeds with a deterministic echo.
#          - any other provider returns an unsupported_provider error
#            (the real provider adapters are out of scope for W7; the
#            architecture is in place to add them later).
# inputs: provider, model, prompt, timeout_seconds.
# returns: dict(stdout, stderr, messages, changed_files).
# side_effects: None.
# emitted_logs: agent_gateway_provider_unsupported.
# error_behavior: Never raises.
# END_FUNCTION_CONTRACT
def _call_provider(provider: str, model: str, prompt: str, timeout_seconds: int) -> dict[str, Any]:
    if provider == "mock":
        return {
            "stdout": f"[mock:{model}] {prompt[:200]}",
            "stderr": "",
            "messages": [{"role": "assistant", "content": f"echo: {prompt[:200]}"}],
            "changed_files": [],
        }
    # Real provider adapters are out of scope for W7's MVP. The contract is in
    # place; one real provider can be wired in a follow-up without changing
    # ApiAgentBackend or the gateway.
    _log.warn("agent_gateway_provider_unsupported", provider=provider, model=model)
    return {
        "stdout": "",
        "stderr": f"provider {provider!r} not yet implemented",
        "messages": [],
        "changed_files": [],
    }


class AgentGatewayService:
    """Provider-agnostic agent invocation."""

    # START_FUNCTION_CONTRACT
    # name: __init__
    # purpose: Initialize gateway with a callable provider hook (testable).
    # inputs: provider_hook (callable) — defaults to _call_provider.
    # returns: None.
    # side_effects: None.
    # emitted_logs: None.
    # error_behavior: None.
    # END_FUNCTION_CONTRACT
    def __init__(self, provider_hook=None) -> None:
        self._call = provider_hook or _call_provider

    # START_FUNCTION_CONTRACT
    # name: dispatch
    # purpose: Run the agent gateway end-to-end: validate → retry loop →
    #          persist artifacts → return normalized dict.
    # inputs: provider (str), model (str), role (str), packet_id (str),
    #         packet_markdown (str), worktree_path (str | Path),
    #         timeout_seconds (int), max_retries (int).
    # returns: dict(packet_id, provider, model, role, accepted, stdout,
    #               stderr, messages, changed_files, duration_ms, reason,
    #               attempts).
    # side_effects: Writes .agent_gateway.log + per-attempt logs to worktree.
    # emitted_logs: agent_gateway_dispatch, agent_gateway_attempt_failed,
    #               agent_gateway_timeout, agent_gateway_done.
    # error_behavior: Never raises; failures returned as reason=...
    # END_FUNCTION_CONTRACT
    def dispatch(
        self,
        *,
        provider: str,
        model: str,
        role: str,
        packet_id: str,
        packet_markdown: str,
        worktree_path: str | Path,
        timeout_seconds: int = 600,
        max_retries: int = 0,
    ) -> dict[str, Any]:
        t0 = time.time()
        if provider not in VALID_PROVIDERS:
            return {
                "packet_id": packet_id, "provider": provider, "model": model, "role": role,
                "accepted": False,
                "reason": f"unknown provider: {provider!r}; expected one of {sorted(VALID_PROVIDERS)}",
                "stdout": "", "stderr": "", "messages": [], "changed_files": [],
                "duration_ms": int((time.time() - t0) * 1000), "attempts": 0,
            }
        _log.info("agent_gateway_dispatch", packet_id=packet_id,
            provider=provider, model=model, role=role, timeout_s=timeout_seconds)

        attempts = 0
        last_error = ""
        stdout = stderr = ""
        messages: list[dict] = []
        changed_files: list[str] = []

        while attempts <= max_retries:
            attempts += 1
            try:
                result = self._call(provider, model, packet_markdown, timeout_seconds)
                stdout = result.get("stdout", "")
                stderr = result.get("stderr", "")
                messages = list(result.get("messages") or [])
                changed_files = list(result.get("changed_files") or [])
                if stderr.startswith("provider") and "not yet implemented" in stderr:
                    last_error = stderr
                    break
                last_error = ""
                break
            except Exception as e:
                last_error = str(e)[:200]
                _log.warn("agent_gateway_attempt_failed", packet_id=packet_id,
                    attempt=attempts, error=last_error)

        duration_ms = int((time.time() - t0) * 1000)
        accepted = not last_error and not stderr

        if not accepted and not last_error:
            last_error = stderr or "agent gateway returned no output"

        self._persist_artifacts(
            worktree_path=worktree_path, packet_id=packet_id,
            provider=provider, model=model, role=role, attempts=attempts,
            duration_ms=duration_ms, stdout=stdout, stderr=stderr,
            last_error=last_error,
        )

        _log.info("agent_gateway_done", packet_id=packet_id,
            accepted=accepted, attempts=attempts, duration_ms=duration_ms,
            reason=last_error[:200] if last_error else "")

        return {
            "packet_id": packet_id, "provider": provider, "model": model, "role": role,
            "accepted": accepted, "stdout": stdout, "stderr": stderr,
            "messages": messages, "changed_files": changed_files,
            "duration_ms": duration_ms, "reason": last_error, "attempts": attempts,
        }

    # START_FUNCTION_CONTRACT
    # name: _persist_artifacts
    # purpose: Save the gateway's per-run log to the worktree.
    # inputs: worktree_path, packet_id, provider, model, role, attempts,
    #         duration_ms, stdout, stderr, last_error.
    # returns: None.
    # side_effects: Writes .agent_gateway.log to worktree_path.
    # emitted_logs: None.
    # error_behavior: Never raises (worktree may be read-only).
    # END_FUNCTION_CONTRACT
    def _persist_artifacts(
        self, *, worktree_path, packet_id, provider, model, role,
        attempts, duration_ms, stdout, stderr, last_error,
    ) -> None:
        try:
            wt = Path(worktree_path)
            wt.mkdir(parents=True, exist_ok=True)
            log = (
                f"packet_id={packet_id}\nprovider={provider}\nmodel={model}\n"
                f"role={role}\nattempts={attempts}\nduration_ms={duration_ms}\n"
                f"---\nstdout:\n{stdout}\n---\nstderr:\n{stderr}\n"
                f"---\nreason={last_error}\n"
            )
            (wt / ".agent_gateway.log").write_text(log)
        except Exception:
            pass
