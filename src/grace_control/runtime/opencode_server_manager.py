from __future__ import annotations

import asyncio
import os
import socket
import time
from pathlib import Path
from typing import Callable

from grace_control.config.settings import settings
from grace_control.core.runtime_artifacts import RuntimeArtifactRef, RuntimeArtifactStore
from grace_control.core.runtime_events import RuntimeEventLogger
from grace_control.core.runtime_redaction import RuntimeRedactor
from grace_control.core.runtime_trace import RuntimeTraceContext
from grace_control.core.structured_logger import GraceLogger
from grace_control.runtime.agent_runtime_contract import AgentRuntimeFailureCode
from grace_control.runtime.opencode_server_state import (
    OpenCodeServerHealth,
    OpenCodeServerState,
    OpenCodeServerStatus,
)

_log = GraceLogger("opencode_server_manager")

ProcessRunner = Callable[..., asyncio.subprocess.Process]
HealthRunner = Callable[[str, int], tuple[bool, str, int | None]]


def _real_process_runner(*args, **kwargs) -> asyncio.subprocess.Process:
    return asyncio.create_subprocess_exec(*args, **kwargs)


def _tcp_healthcheck(host: str, port: int) -> tuple[bool, str, int | None]:
    try:
        start = time.monotonic()
        s = socket.create_connection((host, port), timeout=5)
        elapsed = int((time.monotonic() - start) * 1000)
        s.close()
        return True, "tcp_ok", elapsed
    except socket.timeout:
        return False, "tcp_timeout", None
    except ConnectionRefusedError:
        return False, "connection_refused", None
    except OSError as e:
        return False, f"tcp_error: {e}", None


class OpenCodeServerManager:

    def __init__(
        self,
        process_runner: ProcessRunner | None = None,
        health_runner: HealthRunner | None = None,
        store: RuntimeArtifactStore | None = None,
        redactor: RuntimeRedactor | None = None,
    ):
        self._process_runner = process_runner or _real_process_runner
        self._healthcheck = health_runner or _tcp_healthcheck
        self._store = store or RuntimeArtifactStore()
        self._redactor = redactor or RuntimeRedactor()
        self._server_proc: asyncio.subprocess.Process | None = None

    # ── Public API ────────────────────────────────────────────────────

    async def ensure_running(self) -> OpenCodeServerState:
        state = self._load_state()
        if state.status == OpenCodeServerStatus.RUNNING:
            health = await self.healthcheck()
            if health.ok:
                _log.info("server_reused", url=state.url, pid=state.pid)
                return state
            if getattr(settings, "opencode_server_restart_on_unhealthy", True):
                _log.warn("server_unhealthy_restarting", url=state.url,
                          reason=health.failure_code or health.summary)
                return await self.restart()
            return OpenCodeServerState(
                status=OpenCodeServerStatus.UNHEALTHY,
                url=state.url,
                failure_code=AgentRuntimeFailureCode.AGENT_OPENCODE_SERVER_UNHEALTHY,
                failure_summary=health.summary or "server unhealthy",
            )
        return await self.start()

    async def healthcheck(self) -> OpenCodeServerHealth:
        host = getattr(settings, "opencode_server_host", "127.0.0.1")
        port = getattr(settings, "opencode_server_port", 4096)
        url = getattr(settings, "opencode_server_url", "") or f"http://{host}:{port}"
        pid = self._read_pid()
        ok, summary, latency = self._healthcheck(host, port)
        if ok:
            return OpenCodeServerHealth(ok=True, url=url, pid=pid, latency_ms=latency, summary=summary)
        return OpenCodeServerHealth(
            ok=False, url=url, pid=pid, latency_ms=latency,
            failure_code=AgentRuntimeFailureCode.AGENT_OPENCODE_SERVER_UNHEALTHY,
            summary=summary,
        )

    async def start(self) -> OpenCodeServerState:
        host = getattr(settings, "opencode_server_host", "127.0.0.1")
        port = getattr(settings, "opencode_server_port", 4096)
        url = getattr(settings, "opencode_server_url", "") or f"http://{host}:{port}"
        binary = getattr(settings, "opencode_binary", "opencode")
        log_path = Path(getattr(settings, "opencode_server_log_path", ".grace/opencode-server.log"))
        pid_path = Path(getattr(settings, "opencode_server_pid_path", ".grace/opencode-server.pid"))

        self._clean_stale_pid()

        log_path.parent.mkdir(parents=True, exist_ok=True)
        pid_path.parent.mkdir(parents=True, exist_ok=True)

        try:
            proc = await self._process_runner(
                binary, "serve", "--hostname", host, "--port", str(port),
                stdout=open(log_path, "a"),
                stderr=asyncio.subprocess.STDOUT,
            )
            self._server_proc = proc
        except FileNotFoundError:
            return OpenCodeServerState(
                status=OpenCodeServerStatus.FAILED, url=url,
                failure_code=AgentRuntimeFailureCode.AGENT_ENV_MISSING_CONFIG,
                failure_summary=f"binary not found: {binary}",
                log_path=str(log_path),
            )

        timeout_s = getattr(settings, "opencode_server_start_timeout_seconds", 20)
        deadline = time.monotonic() + timeout_s
        last_health = None
        while time.monotonic() < deadline:
            await asyncio.sleep(0.3)
            health = await self.healthcheck()
            last_health = health
            if health.ok:
                pid = proc.pid
                self._write_pid(pid)
                _log.info("server_started", url=url, pid=pid, log_path=str(log_path))
                return OpenCodeServerState(
                    status=OpenCodeServerStatus.RUNNING, url=url, pid=pid, log_path=str(log_path),
                )

        _log.error("server_start_timeout", url=url, timeout=timeout_s,
                   last_health=last_health.summary if last_health else "no_healthcheck")
        return OpenCodeServerState(
            status=OpenCodeServerStatus.FAILED, url=url,
            failure_code=AgentRuntimeFailureCode.AGENT_OPENCODE_SERVER_TIMEOUT,
            failure_summary=f"server did not start within {timeout_s}s",
            log_path=str(log_path),
        )

    async def stop(self) -> None:
        proc = self._server_proc
        if proc and proc.returncode is None:
            try:
                proc.terminate()
                await asyncio.wait_for(proc.wait(), timeout=5)
            except asyncio.TimeoutError:
                try:
                    proc.kill()
                    await asyncio.wait_for(proc.wait(), timeout=3)
                except Exception:
                    pass
            except Exception:
                pass
        self._server_proc = None
        self._clear_pid()

    async def restart(self) -> OpenCodeServerState:
        await self.stop()
        return await self.start()

    # ── Internal helpers ──────────────────────────────────────────────

    def _load_state(self) -> OpenCodeServerState:
        host = getattr(settings, "opencode_server_host", "127.0.0.1")
        port = getattr(settings, "opencode_server_port", 4096)
        url = getattr(settings, "opencode_server_url", "") or f"http://{host}:{port}"
        log_path = str(Path(getattr(settings, "opencode_server_log_path", ".grace/opencode-server.log")))
        pid = self._read_pid()
        if pid is not None:
            if self._pid_alive(pid):
                return OpenCodeServerState(
                    status=OpenCodeServerStatus.RUNNING, url=url, pid=pid, log_path=log_path,
                )
            self._clear_pid()
        return OpenCodeServerState(status=OpenCodeServerStatus.STOPPED, url=url, log_path=log_path)

    def _read_pid(self) -> int | None:
        pid_path = Path(getattr(settings, "opencode_server_pid_path", ".grace/opencode-server.pid"))
        try:
            if pid_path.exists():
                raw = pid_path.read_text().strip()
                if raw:
                    return int(raw)
        except (OSError, ValueError):
            pass
        return None

    def _write_pid(self, pid: int) -> None:
        pid_path = Path(getattr(settings, "opencode_server_pid_path", ".grace/opencode-server.pid"))
        try:
            pid_path.parent.mkdir(parents=True, exist_ok=True)
            pid_path.write_text(str(pid))
        except OSError:
            pass

    def _clear_pid(self) -> None:
        pid_path = Path(getattr(settings, "opencode_server_pid_path", ".grace/opencode-server.pid"))
        try:
            if pid_path.exists():
                pid_path.unlink()
        except OSError:
            pass

    def _clean_stale_pid(self) -> None:
        pid = self._read_pid()
        if pid is not None and not self._pid_alive(pid):
            self._clear_pid()

    def _pid_alive(self, pid: int) -> bool:
        try:
            os.kill(pid, 0)
            return True
        except (OSError, PermissionError):
            return False

    def _redact_url(self, url: str) -> str:
        return self._redactor.redact_string(url) if self._redactor else url
