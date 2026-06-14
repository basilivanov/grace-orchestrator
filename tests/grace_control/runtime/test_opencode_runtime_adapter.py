from __future__ import annotations

import asyncio
import json
import os
import tempfile
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from grace_control.runtime.agent_runtime_contract import (
    AgentRuntimeContract,
    AgentRuntimeFailureCode,
)

# ── Helpers ──────────────────────────────────────────────────────────────

pytestmark = pytest.mark.asyncio


def _contract(agent_name="test-agent", model="deepseek-v4-flash", **overrides) -> AgentRuntimeContract:
    kwargs = dict(
        runtime_run_id="r1",
        feature_id="feat_w4",
        packet_id="pkt_w4",
        role="coder",
        adapter="opencode",
        target_repo_root="/tmp/target",
        orchestrator_repo_root="/tmp/orch",
        worktree_root="/tmp/worktree",
        cwd="/tmp/worktree",
        agent_name=agent_name,
        model=model,
        runtime_artifacts_dir="/tmp/artifacts",
        timeout_seconds=600,
    )
    kwargs.update(overrides)
    return AgentRuntimeContract(**kwargs)


class FakeProcess:
    """Mimics asyncio.subprocess.Process for testing."""

    def __init__(self, stdout_lines=None, stderr_lines=None, exit_code=0):
        self._stdout_lines = stdout_lines or []
        self._stderr_lines = stderr_lines or []
        self._exit_code = exit_code
        self._stdin_written = b""
        self._stdin_closed = False
        self._killed = False

    @property
    def stdout(self):
        async def _reader():
            for line in self._stdout_lines:
                yield line.encode("utf-8")

        class _Stream:
            def __init__(self, lines):
                self._lines = lines
                self._idx = 0

            async def readline(self):
                if self._idx < len(self._lines):
                    line = self._lines[self._idx]
                    self._idx += 1
                    return line.encode("utf-8") if isinstance(line, str) else line
                return b""

        return _Stream(self._stdout_lines)

    @property
    def stderr(self):
        class _Stream:
            def __init__(self, lines):
                self._lines = lines
                self._idx = 0

            async def readline(self):
                if self._idx < len(self._lines):
                    line = self._lines[self._idx]
                    self._idx += 1
                    return line.encode("utf-8") if isinstance(line, str) else line
                return b""

        return _Stream(self._stderr_lines)

    @property
    def stdin(self):
        class _Stdin:
            def __init__(self):
                self._data = b""

            def write(self, data: bytes):
                self._data += data

            async def drain(self):
                pass

            def close(self):
                pass

        return _Stdin()

    async def wait(self):
        return self._exit_code

    def kill(self):
        self._killed = True


def _fake_runner(stdout_lines=None, stderr_lines=None, exit_code=0):
    """Return a ProcessRunner that creates FakeProcess with given output."""

    async def _run(*args, **kwargs):
        return FakeProcess(
            stdout_lines=stdout_lines or [],
            stderr_lines=stderr_lines or [],
            exit_code=exit_code,
        )

    return _run


# ── Tests ────────────────────────────────────────────────────────────────


class TestCommandBuilding:

    async def test_command_includes_dir_agent_model_json(self):
        from grace_control.runtime.opencode_runtime_adapter import OpenCodeRuntimeAdapter

        adapter = OpenCodeRuntimeAdapter(
            process_runner=_fake_runner(stdout_lines=[], exit_code=0),
        )
        contract = _contract()
        result = await adapter.run(contract, "test prompt")
        assert result.command[0] == "opencode"
        assert result.command[1] == "run"
        assert result.command[result.command.index("--dir") + 1] == "/tmp/worktree"
        assert result.command[result.command.index("--agent") + 1] == "test-agent"
        assert result.command[result.command.index("--model") + 1] == "deepseek-v4-flash"
        assert result.command[result.command.index("--format") + 1] == "json"

    async def test_command_does_not_include_attach_in_w4(self):
        from grace_control.runtime.opencode_runtime_adapter import OpenCodeRuntimeAdapter

        adapter = OpenCodeRuntimeAdapter(
            process_runner=_fake_runner(stdout_lines=[], exit_code=0),
        )
        result = await adapter.run(_contract(), "prompt")
        assert "--attach" not in result.command
        assert "serve" not in result.command

    async def test_fails_without_model(self):
        from grace_control.runtime.opencode_runtime_adapter import OpenCodeRuntimeAdapter

        adapter = OpenCodeRuntimeAdapter(
            process_runner=_fake_runner(stdout_lines=[], exit_code=0),
        )
        result = await adapter.run(_contract(model=""), "prompt")
        assert not result.ok
        assert result.failure_code == "AGENT_RUNTIME_CONTRACT_INVALID"

    async def test_fails_without_agent(self):
        from grace_control.runtime.opencode_runtime_adapter import OpenCodeRuntimeAdapter

        adapter = OpenCodeRuntimeAdapter(
            process_runner=_fake_runner(stdout_lines=[], exit_code=0),
        )
        result = await adapter.run(_contract(agent_name=""), "prompt")
        assert not result.ok
        assert result.failure_code == "AGENT_RUNTIME_CONTRACT_INVALID"

    async def test_cwd_equals_worktree(self):
        from grace_control.runtime.opencode_runtime_adapter import OpenCodeRuntimeAdapter

        adapter = OpenCodeRuntimeAdapter(
            process_runner=_fake_runner(stdout_lines=[], exit_code=0),
        )
        result = await adapter.run(_contract(worktree_root="/tmp/wt", cwd="/tmp/wt"), "prompt")
        assert result.cwd == "/tmp/wt"


class TestJsonEventParsing:

    async def test_parses_json_events(self):
        from grace_control.runtime.opencode_runtime_adapter import OpenCodeRuntimeAdapter

        ev = json.dumps({"event": "agent_started", "data": "hello"})
        adapter = OpenCodeRuntimeAdapter(
            process_runner=_fake_runner(stdout_lines=[ev + "\n"], exit_code=0),
        )
        result = await adapter.run(_contract(), "prompt")
        assert len(result.raw_events) == 1
        assert result.raw_events[0]["event"] == "agent_started"

    async def test_preserves_unparseable_stdout(self):
        from grace_control.runtime.opencode_runtime_adapter import OpenCodeRuntimeAdapter

        adapter = OpenCodeRuntimeAdapter(
            process_runner=_fake_runner(
                stdout_lines=["plain line 1\n", "plain line 2\n"],
                exit_code=0,
            ),
        )
        result = await adapter.run(_contract(), "prompt")
        assert result.stdout
        assert "plain line 1" in result.stdout
        assert "plain line 2" in result.stdout
        assert result.raw_events == []

    async def test_mixed_json_and_plain(self):
        from grace_control.runtime.opencode_runtime_adapter import OpenCodeRuntimeAdapter

        ev = json.dumps({"event": "step"})
        adapter = OpenCodeRuntimeAdapter(
            process_runner=_fake_runner(
                stdout_lines=["progress\n", ev + "\n", "done\n"],
                exit_code=0,
            ),
        )
        result = await adapter.run(_contract(), "prompt")
        assert len(result.raw_events) == 1
        assert result.raw_events[0]["event"] == "step"
        assert "progress" in result.stdout
        assert "done" in result.stdout


class TestFailureClassification:

    async def test_fails_on_no_event_output_when_required(self):
        from grace_control.runtime.opencode_runtime_adapter import OpenCodeRuntimeAdapter

        adapter = OpenCodeRuntimeAdapter(
            process_runner=_fake_runner(stdout_lines=["plain\n"], exit_code=0),
        )
        result = await adapter.run(_contract(), "prompt")
        assert not result.ok
        assert result.failure_code == AgentRuntimeFailureCode.AGENT_NO_EVENT_OUTPUT

    async def test_allows_plain_stdout_when_json_not_required(self):
        from grace_control.runtime.opencode_runtime_adapter import OpenCodeRuntimeAdapter
        from grace_control.config.settings import settings

        original = settings.opencode_json_events_required
        try:
            settings.opencode_json_events_required = False
            adapter = OpenCodeRuntimeAdapter(
                process_runner=_fake_runner(stdout_lines=["plain\n"], exit_code=0),
            )
            result = await adapter.run(_contract(), "prompt")
            assert result.ok
        finally:
            settings.opencode_json_events_required = original

    async def test_classifies_missing_auth(self):
        from grace_control.runtime.opencode_runtime_adapter import OpenCodeRuntimeAdapter

        adapter = OpenCodeRuntimeAdapter(
            process_runner=_fake_runner(
                stderr_lines=["401 Unauthorized\n"],
                exit_code=1,
            ),
        )
        result = await adapter.run(_contract(), "prompt")
        assert not result.ok
        assert result.failure_code == AgentRuntimeFailureCode.AGENT_ENV_MISSING_AUTH

    async def test_classifies_model_unavailable(self):
        from grace_control.runtime.opencode_runtime_adapter import OpenCodeRuntimeAdapter

        adapter = OpenCodeRuntimeAdapter(
            process_runner=_fake_runner(
                stderr_lines=["model 'x' is unavailable\n"],
                exit_code=1,
            ),
        )
        result = await adapter.run(_contract(), "prompt")
        assert not result.ok
        assert result.failure_code == AgentRuntimeFailureCode.AGENT_MODEL_UNAVAILABLE

    async def test_classifies_permission_blocked(self):
        from grace_control.runtime.opencode_runtime_adapter import OpenCodeRuntimeAdapter

        adapter = OpenCodeRuntimeAdapter(
            process_runner=_fake_runner(
                stderr_lines=["permission denied\n"],
                exit_code=1,
            ),
        )
        result = await adapter.run(_contract(), "prompt")
        assert not result.ok
        assert result.failure_code == AgentRuntimeFailureCode.AGENT_PERMISSION_BLOCKED

    async def test_classifies_process_crashed(self):
        from grace_control.runtime.opencode_runtime_adapter import OpenCodeRuntimeAdapter

        adapter = OpenCodeRuntimeAdapter(
            process_runner=_fake_runner(
                stderr_lines=["segfault\n"],
                exit_code=139,
                stdout_lines=[],
            ),
        )
        result = await adapter.run(_contract(), "prompt")
        assert not result.ok
        assert result.failure_code == AgentRuntimeFailureCode.AGENT_PROCESS_CRASHED

    async def test_classifies_nonexistent_binary(self):
        from grace_control.runtime.opencode_runtime_adapter import OpenCodeRuntimeAdapter

        adapter = OpenCodeRuntimeAdapter(
            process_runner=_fake_runner(
                stderr_lines=["opencode: command not found\n"],
                exit_code=127,
            ),
        )
        result = await adapter.run(_contract(), "prompt")
        assert not result.ok
        assert result.failure_code == AgentRuntimeFailureCode.AGENT_ENV_MISSING_CONFIG


class TestArtifacts:

    async def test_writes_artifacts(self):
        from grace_control.runtime.opencode_runtime_adapter import OpenCodeRuntimeAdapter
        from grace_control.core.runtime_trace import RuntimeTraceContext, generate_trace_id

        trace = RuntimeTraceContext(
            trace_id=generate_trace_id(),
            feature_id="feat_w4",
            packet_id="pkt_w4",
            wave_id="wave_w4",
            runtime_run_id="r1",
        )
        ev = json.dumps({"event": "step"})
        adapter = OpenCodeRuntimeAdapter(
            process_runner=_fake_runner(stdout_lines=[ev + "\n", "plain\n"], exit_code=0),
        )
        with tempfile.TemporaryDirectory() as td:
            from grace_control.config.settings import settings as _s
            _s.runtime_artifacts_root = str(Path(td) / ".grace" / "runs")
            result, refs = await adapter.run_with_artifacts(
                _contract(),
                "test prompt content",
                trace,
                "pkt_w4",
            )
            assert refs
            names = {r.kind for r in refs}
            expected = {"opencode_command", "opencode_prompt", "opencode_stdout",
                        "opencode_events", "opencode_result"}
            missing = expected - names
            assert not missing, f"missing artifacts: {missing}"
            assert result.ok


class TestExecutionBackend:

    async def test_backend_maps_result(self):
        from grace_control.runtime.opencode_runtime_adapter import OpenCodeExecutionBackend
        from grace_control.agent.backend import ExecutionRequest

        adapter = OpenCodeExecutionBackend(
            adapter=_make_fake_adapter(
                ok=True,
                accepted=True,
                stdout="done\n",
            )
        )

        req = ExecutionRequest(
            packet_id="pkt_w4",
            spec={"allowed_write_scope": ["src/"]},
            worktree_path=Path("/tmp/wt"),
            branch_name="agent/test",
            scope_paths=["src/"],
            executor={"agent_name": "test-agent", "model": "deepseek-v4-flash"},
            timeout_s=600,
        )
        result = await adapter.run(req)
        assert result.accepted
        assert "done" in result.stdout

    async def test_backend_cancel_noop(self):
        from grace_control.runtime.opencode_runtime_adapter import OpenCodeExecutionBackend
        from grace_control.agent.backend import ExecutionRequest

        adapter = OpenCodeExecutionBackend()
        await adapter.cancel(ExecutionRequest(
            packet_id="x", spec={}, worktree_path=Path("/tmp"),
            branch_name="", scope_paths=[], executor={},
        ))


def _make_fake_adapter(ok=True, accepted=True, stdout="", stderr="", exit_code=0,
                       raw_events=None, failure_code=None, failure_summary=None):
    """Create a minimal OpenCodeRuntimeAdapter stand-in."""
    from grace_control.runtime.agent_execution_adapter import AgentExecutionAdapterResult

    class _FakeAdapter:
        async def run(self, contract, prompt):
            return AgentExecutionAdapterResult(
                ok=ok,
                accepted=accepted,
                adapter="opencode",
                command=["opencode", "run", "--dir", contract.worktree_root,
                         "--agent", contract.agent_name or "",
                         "--model", contract.model or "",
                         "--format", "json"],
                cwd=contract.worktree_root,
                stdout=stdout,
                stderr=stderr,
                raw_events=raw_events or [],
                exit_code=exit_code,
                duration_ms=100,
                failure_code=failure_code,
                failure_stage="opencode_run" if failure_code else None,
                failure_summary=failure_summary,
                model=contract.model,
                agent_name=contract.agent_name,
            )

        async def run_with_artifacts(self, contract, prompt, trace, packet_id):
            r = await self.run(contract, prompt)
            return r, []

    return _FakeAdapter()
