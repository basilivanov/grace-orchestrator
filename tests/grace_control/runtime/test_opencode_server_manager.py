from __future__ import annotations

import asyncio
import os
import tempfile
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from grace_control.runtime.opencode_server_state import (
    OpenCodeServerHealth,
    OpenCodeServerState,
    OpenCodeServerStatus,
)

pytestmark = pytest.mark.asyncio

FAKE_PID = 12345


def _ok_health(host: str, port: int, timeout: int = 5) -> tuple[bool, str, int | None]:
    return True, "tcp_ok", 5


def _fail_health(host: str, port: int, timeout: int = 5) -> tuple[bool, str, int | None]:
    return False, "connection_refused", None


class FakeProcess:
    def __init__(self, pid=FAKE_PID):
        self._pid = pid
        self.returncode = None

    @property
    def pid(self):
        return self._pid

    async def wait(self):
        self.returncode = 0
        return 0

    def terminate(self):
        self.returncode = -15

    def kill(self):
        self.returncode = -9


async def _fake_process_runner(*args, **kwargs):
    return FakeProcess(pid=FAKE_PID)


class TestServerManagerStart:

    async def test_starts_when_not_running(self):
        from grace_control.runtime.opencode_server_manager import OpenCodeServerManager

        with tempfile.TemporaryDirectory() as td:
            td_path = Path(td)
            from grace_control.config.settings import settings as _s
            _s.opencode_server_pid_path = str(td_path / "opencode-server.pid")
            _s.opencode_server_log_path = str(td_path / "opencode-server.log")
            _s.opencode_server_start_timeout_seconds = 1

            mgr = OpenCodeServerManager(
                process_runner=_fake_process_runner,
                health_runner=_ok_health,
            )
            state = await mgr.start()
            assert state.status == OpenCodeServerStatus.RUNNING
            assert state.pid == FAKE_PID
            assert "127.0.0.1" in state.url

    async def test_returns_state_on_start_failure(self):
        from grace_control.runtime.opencode_server_manager import OpenCodeServerManager

        with tempfile.TemporaryDirectory() as td:
            td_path = Path(td)
            from grace_control.config.settings import settings as _s
            _s.opencode_server_pid_path = str(td_path / "opencode-server.pid")
            _s.opencode_server_log_path = str(td_path / "opencode-server.log")
            _s.opencode_server_start_timeout_seconds = 1

            mgr = OpenCodeServerManager(
                process_runner=_fake_process_runner,
                health_runner=_fail_health,
            )
            state = await mgr.start()
            assert state.status == OpenCodeServerStatus.FAILED

    async def test_writes_pid_file(self):
        from grace_control.runtime.opencode_server_manager import OpenCodeServerManager

        with tempfile.TemporaryDirectory() as td:
            td_path = Path(td)
            pid_path = td_path / "opencode-server.pid"
            from grace_control.config.settings import settings as _s
            _s.opencode_server_pid_path = str(pid_path)
            _s.opencode_server_log_path = str(td_path / "opencode-server.log")
            _s.opencode_server_start_timeout_seconds = 1

            mgr = OpenCodeServerManager(
                process_runner=_fake_process_runner,
                health_runner=_ok_health,
            )
            await mgr.start()
            assert pid_path.exists()
            assert pid_path.read_text().strip() == str(FAKE_PID)

    async def test_reuses_healthy_server(self):
        from grace_control.runtime.opencode_server_manager import OpenCodeServerManager

        with tempfile.TemporaryDirectory() as td:
            td_path = Path(td)
            pid_path = td_path / "opencode-server.pid"
            from grace_control.config.settings import settings as _s
            _s.opencode_server_pid_path = str(pid_path)
            _s.opencode_server_log_path = str(td_path / "opencode-server.log")
            _s.opencode_server_start_timeout_seconds = 1
            _s.opencode_server_host = "127.0.0.1"
            _s.opencode_server_port = 4096

            pid_path.write_text(str(os.getpid()))
            # Write matching state file so PID is trusted
            state_path = td_path / "opencode-server-state.json"
            import json
            state_path.write_text(json.dumps({
                "pid": os.getpid(),
                "host": "127.0.0.1",
                "port": 4096,
                "binary": "opencode",
            }))
            mgr = OpenCodeServerManager(health_runner=_ok_health)
            state = await mgr.ensure_running()
            assert state.status == OpenCodeServerStatus.RUNNING

    async def test_cleans_stale_pid(self):
        from grace_control.runtime.opencode_server_manager import OpenCodeServerManager

        with tempfile.TemporaryDirectory() as td:
            td_path = Path(td)
            pid_path = td_path / "opencode-server.pid"
            from grace_control.config.settings import settings as _s
            _s.opencode_server_pid_path = str(pid_path)
            _s.opencode_server_log_path = str(td_path / "opencode-server.log")
            _s.opencode_server_start_timeout_seconds = 1

            pid_path.write_text("99999999")
            mgr = OpenCodeServerManager(
                process_runner=_fake_process_runner,
                health_runner=_ok_health,
            )
            await mgr.ensure_running()
            assert pid_path.exists()
            assert pid_path.read_text().strip() == str(FAKE_PID)


class TestServerHealthcheck:

    async def test_healthcheck_tcp_success(self):
        from grace_control.runtime.opencode_server_manager import OpenCodeServerManager

        mgr = OpenCodeServerManager(health_runner=_ok_health)
        health = await mgr.healthcheck()
        assert health.ok

    async def test_healthcheck_failure_classified(self):
        from grace_control.runtime.opencode_server_manager import OpenCodeServerManager

        mgr = OpenCodeServerManager(health_runner=_fail_health)
        health = await mgr.healthcheck()
        assert not health.ok
        assert health.failure_code == "AGENT_OPENCODE_SERVER_UNHEALTHY"


class TestServerStop:

    async def test_stops_running_process(self):
        from grace_control.runtime.opencode_server_manager import OpenCodeServerManager

        with tempfile.TemporaryDirectory() as td:
            pid_path = Path(td) / "opencode-server.pid"
            from grace_control.config.settings import settings as _s
            _s.opencode_server_pid_path = str(pid_path)
            _s.opencode_server_log_path = str(Path(td) / "opencode-server.log")
            _s.opencode_server_start_timeout_seconds = 1

            mgr = OpenCodeServerManager(
                process_runner=_fake_process_runner,
                health_runner=_ok_health,
            )
            await mgr.start()
            assert pid_path.exists()

            await mgr.stop()
            assert not pid_path.exists()


class TestEnsureRunning:

    async def test_ensure_running_starts_if_not_running(self):
        from grace_control.runtime.opencode_server_manager import OpenCodeServerManager

        with tempfile.TemporaryDirectory() as td:
            td_path = Path(td)
            from grace_control.config.settings import settings as _s
            _s.opencode_server_pid_path = str(td_path / "opencode-server.pid")
            _s.opencode_server_log_path = str(td_path / "opencode-server.log")
            _s.opencode_server_start_timeout_seconds = 1

            mgr = OpenCodeServerManager(
                process_runner=_fake_process_runner,
                health_runner=_ok_health,
            )
            state = await mgr.ensure_running()
            assert state.status == OpenCodeServerStatus.RUNNING

    async def test_restarts_unhealthy_when_enabled(self):
        from grace_control.runtime.opencode_server_manager import OpenCodeServerManager

        with tempfile.TemporaryDirectory() as td:
            td_path = Path(td)
            pid_path = td_path / "opencode-server.pid"
            from grace_control.config.settings import settings as _s
            _s.opencode_server_pid_path = str(pid_path)
            _s.opencode_server_log_path = str(td_path / "opencode-server.log")
            _s.opencode_server_start_timeout_seconds = 1
            _s.opencode_server_restart_on_unhealthy = True

            pid_path.write_text(str(os.getpid()))
            mgr = OpenCodeServerManager(
                process_runner=_fake_process_runner,
                health_runner=_fail_health,
            )
            state = await mgr.ensure_running()
            assert state.status == OpenCodeServerStatus.FAILED

    async def test_fails_unhealthy_when_restart_disabled(self):
        from grace_control.runtime.opencode_server_manager import OpenCodeServerManager

        with tempfile.TemporaryDirectory() as td:
            td_path = Path(td)
            pid_path = td_path / "opencode-server.pid"
            from grace_control.config.settings import settings as _s
            _s.opencode_server_pid_path = str(pid_path)
            _s.opencode_server_log_path = str(td_path / "opencode-server.log")
            _s.opencode_server_restart_on_unhealthy = False
            _s.opencode_server_host = "127.0.0.1"
            _s.opencode_server_port = 4096

            pid_path.write_text(str(os.getpid()))
            import json
            (td_path / "opencode-server-state.json").write_text(json.dumps({
                "pid": os.getpid(),
                "host": "127.0.0.1",
                "port": 4096,
                "binary": "opencode",
            }))
            mgr = OpenCodeServerManager(health_runner=_fail_health)
            state = await mgr.ensure_running()
            assert state.status == OpenCodeServerStatus.UNHEALTHY
