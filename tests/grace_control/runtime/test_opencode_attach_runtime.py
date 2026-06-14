from __future__ import annotations

import asyncio
import json
import tempfile
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from grace_control.runtime.agent_runtime_contract import (
    AgentRuntimeContract,
    AgentRuntimeFailureCode,
)

pytestmark = pytest.mark.asyncio


def _contract(agent_name="test-agent", model="deepseek-v4-flash", **overrides) -> AgentRuntimeContract:
    kwargs = dict(
        runtime_run_id="r1", feature_id="feat_w5", packet_id="pkt_w5",
        role="coder", adapter="opencode",
        target_repo_root="/tmp/target", orchestrator_repo_root="/tmp/orch",
        worktree_root="/tmp/worktree", cwd="/tmp/worktree",
        agent_name=agent_name, model=model,
        runtime_artifacts_dir="/tmp/artifacts", timeout_seconds=600,
    )
    kwargs.update(overrides)
    return AgentRuntimeContract(**kwargs)


class FakeProcess:
    def __init__(self, stdout_lines=None, stderr_lines=None, exit_code=0, pid=99999, hang=False):
        self._stdout_lines = stdout_lines or []
        self._stderr_lines = stderr_lines or []
        self._exit_code = exit_code
        self._killed = False
        self._terminated = False
        self._pid = pid
        self._hang = hang

    @property
    def pid(self):
        return self._pid

    @property
    def returncode(self):
        return None if self._hang else self._exit_code

    @returncode.setter
    def returncode(self, val):
        pass

    @property
    def stdout(self):
        class _Stream:
            def __init__(self, lines, hang):
                self._lines = lines
                self._hang = hang
                self._idx = 0
            async def readline(self):
                if self._hang:
                    await asyncio.sleep(9999)
                    return b""
                if self._idx < len(self._lines):
                    line = self._lines[self._idx]
                    self._idx += 1
                    return line.encode("utf-8") if isinstance(line, str) else line
                return b""
        return _Stream(self._stdout_lines, self._hang)

    @property
    def stderr(self):
        class _Stream:
            def __init__(self, lines, hang):
                self._lines = lines
                self._hang = hang
                self._idx = 0
            async def readline(self):
                if self._hang:
                    await asyncio.sleep(9999)
                    return b""
                if self._idx < len(self._lines):
                    line = self._lines[self._idx]
                    self._idx += 1
                    return line.encode("utf-8") if isinstance(line, str) else line
                return b""
        return _Stream(self._stderr_lines, self._hang)

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
        if self._hang:
            await asyncio.sleep(9999)
        return self._exit_code

    def kill(self):
        self._killed = True

    def terminate(self):
        self._terminated = True


class TrackedProcess(FakeProcess):
    """FakeProcess that records whether it was killed/terminated."""
    def __init__(self, hang=False, pid=99999):
        super().__init__(stdout_lines=[], stderr_lines=[], exit_code=1, pid=pid, hang=hang)
        self.was_killed = False
        self.was_terminated = False

    def kill(self):
        self.was_killed = True
        super().kill()

    def terminate(self):
        self.was_terminated = True
        super().terminate()


def _fake_runner(stdout_lines=None, stderr_lines=None, exit_code=0, hang=False, pid=99999):
    async def _run(*args, **kwargs):
        return FakeProcess(
            stdout_lines=stdout_lines or [],
            stderr_lines=stderr_lines or [],
            exit_code=exit_code,
            hang=hang,
            pid=pid,
        )
    return _run


def _ok_health(host, port, timeout=5):
    return True, "tcp_ok", 5


class TestAttachRuntimeMode:

    async def test_serve_attach_mode_uses_attach_command(self):
        from grace_control.runtime.opencode_runtime_adapter import OpenCodeRuntimeAdapter
        from grace_control.runtime.opencode_server_manager import OpenCodeServerManager

        with tempfile.TemporaryDirectory() as td:
            td_path = Path(td)
            from grace_control.config.settings import settings as _s
            _s.opencode_runtime_mode = "serve_attach"
            _s.opencode_server_pid_path = str(td_path / "opencode-server.pid")
            _s.opencode_server_log_path = str(td_path / "opencode-server.log")
            _s.opencode_server_start_timeout_seconds = 1

            mgr = OpenCodeServerManager(
                process_runner=_fake_runner(),
                health_runner=_ok_health,
            )
            adapter = OpenCodeRuntimeAdapter(
                server_manager=mgr,
                process_runner=_fake_runner(stdout_lines=[], exit_code=0),
            )
            result = await adapter.run(_contract(), "test prompt")
            assert "--attach" in result.command
            assert "--dir" in result.command

    async def test_direct_mode_does_not_start_server(self):
        from grace_control.runtime.opencode_runtime_adapter import OpenCodeRuntimeAdapter

        from grace_control.config.settings import settings as _s
        _s.opencode_runtime_mode = "direct"

        adapter = OpenCodeRuntimeAdapter(
            process_runner=_fake_runner(stdout_lines=[], exit_code=0),
        )
        result = await adapter.run(_contract(), "test prompt")
        assert "--attach" not in result.command
        assert result.command[1] == "run"

    async def test_packet_run_timeout_kills_hanging_process(self):
        """Packet timeout must kill hanging packet process, not server."""
        from grace_control.runtime.opencode_runtime_adapter import OpenCodeRuntimeAdapter

        hanging_proc = TrackedProcess(hang=True, pid=10001)
        server_proc = TrackedProcess(hang=False, pid=10002)

        server_started = False

        async def _server_runner(*args, **kwargs):
            nonlocal server_started
            server_started = True
            return server_proc

        async def _packet_runner(*args, **kwargs):
            return hanging_proc

        from grace_control.config.settings import settings as _s
        _s.opencode_direct_timeout_seconds = 0  # immediate timeout
        _s.opencode_runtime_mode = "direct"
        _s.opencode_process_kill_grace_seconds = 0

        adapter = OpenCodeRuntimeAdapter(
            process_runner=_packet_runner,
        )
        result = await adapter.run(_contract(), "test prompt")
        assert not result.ok
        assert hanging_proc.was_killed or hanging_proc.was_terminated, \
            "hanging packet process must be killed on timeout"

    async def test_packet_timeout_does_not_kill_server(self):
        """Packet timeout must kill the hanging packet process only,
        not the warm server process."""
        from grace_control.runtime.opencode_runtime_adapter import (
            OpenCodeRuntimeAdapter,
            OpenCodeExecutionBackend,
        )
        from grace_control.runtime.opencode_server_manager import OpenCodeServerManager
        from grace_control.agent.backend import ExecutionRequest

        server_proc = TrackedProcess(hang=False, pid=20001)
        packet_hang_proc = TrackedProcess(hang=True, pid=20002)

        async def _server_runner(*args, **kwargs):
            return server_proc

        async def _packet_runner(*args, **kwargs):
            return packet_hang_proc

        with tempfile.TemporaryDirectory() as td:
            td_path = Path(td)
            from grace_control.config.settings import settings as _s
            _s.opencode_runtime_mode = "serve_attach"
            _s.opencode_server_pid_path = str(td_path / "opencode-server.pid")
            _s.opencode_server_log_path = str(td_path / "opencode-server.log")
            _s.opencode_server_start_timeout_seconds = 1
            _s.opencode_direct_timeout_seconds = 0  # immediate timeout
            _s.opencode_process_kill_grace_seconds = 0

            mgr = OpenCodeServerManager(
                process_runner=_server_runner,
                health_runner=_ok_health,
            )
            adapter = OpenCodeRuntimeAdapter(
                server_manager=mgr,
                process_runner=_packet_runner,
            )
            backend = OpenCodeExecutionBackend(adapter=adapter)

            req = ExecutionRequest(
                packet_id="pkt_w5", spec={},
                worktree_path=td_path / "wt",
                branch_name="", scope_paths=[],
                executor={"agent_name": "test-agent", "model": "deepseek-v4-flash"},
                timeout_s=600,
            )
            result = await backend.run(req)
            assert not result.accepted, "hanging packet must time out"
            assert packet_hang_proc.was_killed or packet_hang_proc.was_terminated, \
                "hanging packet process must be killed"
            assert not server_proc.was_killed, "server must NOT be killed by packet timeout"

    async def test_attach_failure_classified(self):
        from grace_control.runtime.opencode_runtime_adapter import OpenCodeRuntimeAdapter
        from grace_control.runtime.opencode_server_manager import OpenCodeServerManager

        with tempfile.TemporaryDirectory() as td:
            td_path = Path(td)
            from grace_control.config.settings import settings as _s
            _s.opencode_runtime_mode = "serve_attach"
            _s.opencode_server_pid_path = str(td_path / "opencode-server.pid")
            _s.opencode_server_log_path = str(td_path / "opencode-server.log")
            _s.opencode_server_start_timeout_seconds = 1

            mgr = OpenCodeServerManager(
                process_runner=_fake_runner(),
                health_runner=_ok_health,
            )
            adapter = OpenCodeRuntimeAdapter(
                server_manager=mgr,
                process_runner=_fake_runner(stdout_lines=["failed\n"], exit_code=1),
            )
            result = await adapter.run(_contract(), "test prompt")
            assert not result.ok
            assert result.failure_code is not None
