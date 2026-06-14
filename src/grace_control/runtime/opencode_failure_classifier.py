from __future__ import annotations

import os

from grace_control.runtime.agent_runtime_contract import AgentRuntimeFailureCode


class OpenCodeFailureClassifier:

    @staticmethod
    def classify(
        exit_code: int | None,
        stdout: str,
        stderr: str,
        duration_ms: int,
        timeout_seconds: int,
        event_count: int,
        no_event_bypassed: bool = False,
    ) -> tuple[str | None, str | None]:
        """Return (failure_code, failure_summary) or (None, None) on success."""
        timeout_ms = timeout_seconds * 1000

        if exit_code is None and duration_ms >= timeout_ms:
            return (AgentRuntimeFailureCode.AGENT_COMMAND_TIMEOUT,
                    f"process timed out after {duration_ms}ms (limit {timeout_seconds}s)")

        if exit_code is not None and exit_code < 0:
            return (AgentRuntimeFailureCode.AGENT_PROCESS_CRASHED,
                    f"process crashed with signal {abs(exit_code)}")

        blob = ((stdout or "") + "\n" + (stderr or "")).lower()

        if exit_code in (1, 127) and ("not found" in blob or "no such file" in blob):
            return (AgentRuntimeFailureCode.AGENT_ENV_MISSING_CONFIG,
                    "opencode binary not found on PATH")

        if exit_code is not None and exit_code != 0:
            if "auth" in blob or "401" in blob or "403" in blob or "unauthorized" in blob:
                return (AgentRuntimeFailureCode.AGENT_ENV_MISSING_AUTH,
                        "authentication error detected in output")
            if "model" in blob and ("unavailable" in blob or "not found" in blob or "rate limit" in blob):
                return (AgentRuntimeFailureCode.AGENT_MODEL_UNAVAILABLE,
                        "model/provider unavailable")
            if "permission" in blob or "denied" in blob or "blocked" in blob or "EACCES" in blob:
                return (AgentRuntimeFailureCode.AGENT_PERMISSION_BLOCKED,
                        "permission denied / tool blocked")
            if "timeout" in blob or "timed out" in blob:
                return (AgentRuntimeFailureCode.AGENT_COMMAND_TIMEOUT,
                        "process reported timeout in output")

            return (AgentRuntimeFailureCode.AGENT_PROCESS_CRASHED,
                    f"process exited with code {exit_code}")

        if exit_code == 0 and event_count == 0:
            if no_event_bypassed:
                return (None, None)
            if stdout or stderr:
                return (AgentRuntimeFailureCode.AGENT_NO_EVENT_OUTPUT,
                        "zero exit but no JSON events in output")
            return (AgentRuntimeFailureCode.AGENT_NO_EVENT_OUTPUT,
                    "zero exit but completely empty output")

        return (None, None)
