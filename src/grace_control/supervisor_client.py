# AI_HEADER: supervisor_client — HTTP-over-UDS client for the supervisor control socket
# START_MODULE_CONTRACT
# purpose: Typed internal client for the supervisor's FastAPI control app.
#          Used by lifecycle integration and tests over the private UDS without
#          exposing a second operator-facing command surface.
# inputs: socket_path (Path) or env var GRACE_SUPERVISOR_SOCK.
# returns: dict responses from the supervisor.
# side_effects: Opens a unix-socket HTTP connection.
# emitted_logs: connection_failed, timeout.
# error_behavior: SupervisorConnectionError on missing socket; underlying
#                 httpx errors propagate.
# END_MODULE_CONTRACT
# START_MODULE_MAP
# mapping:
#   - class: SupervisorClient
#   - class: SupervisorConnectionError
# END_MODULE_MAP

from __future__ import annotations

import asyncio
import os
from pathlib import Path
from typing import Any

import httpx


class SupervisorConnectionError(RuntimeError):
    """Raised when the supervisor control socket is not reachable."""


class SupervisorClient:
    """Async client over unix-socket transport.

    Usage:
        client = SupervisorClient.from_env()
        await client.status()
        await client.restart("workers")
    """

    DEFAULT_SOCK = "supervisor.sock"
    DEFAULT_TIMEOUT = 10.0

    def __init__(self, socket_path: Path, timeout: float = DEFAULT_TIMEOUT) -> None:
        self._socket_path = socket_path
        self._timeout = timeout

    @classmethod
    def from_env(cls) -> SupervisorClient:
        sock = os.environ.get("GRACE_SUPERVISOR_SOCK")
        if not sock:
            raise SupervisorConnectionError(
                "GRACE_SUPERVISOR_SOCK is not set; start the supervisor first"
            )
        return cls(Path(sock))

    @property
    def socket_path(self) -> Path:
        return self._socket_path

    def _transport(self) -> httpx.AsyncHTTPTransport:
        return httpx.AsyncHTTPTransport(uds=str(self._socket_path))

    async def _request(self, method: str, path: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
        if not self._socket_path.exists():
            raise SupervisorConnectionError(
                f"supervisor socket not found: {self._socket_path}"
            )
        async with httpx.AsyncClient(transport=self._transport(), timeout=self._timeout) as client:
            r = await client.request(method, f"http://localhost{path}", params=params or {})
            r.raise_for_status()
            return r.json()

    async def status(self) -> dict[str, Any]:
        return await self._request("GET", "/control/status")

    async def restart(self, target: str) -> dict[str, Any]:
        if target not in {"api", "workers", "all"}:
            raise ValueError(f"target must be api|workers|all, got {target!r}")
        return await self._request("POST", f"/control/restart/{target}")

    async def stop(self) -> dict[str, Any]:
        return await self._request("POST", "/control/stop")

    async def cleanup(
        self,
        *,
        worktrees: bool = True,
        state_files: bool = True,
        stale_leases: bool = True,
        stale_lease_minutes: int = 30,
        stale_state_days: int = 7,
    ) -> dict[str, Any]:
        return await self._request(
            "POST",
            "/control/cleanup",
            params={
                "worktrees": str(worktrees).lower(),
                "state_files": str(state_files).lower(),
                "stale_leases": str(stale_leases).lower(),
                "stale_lease_minutes": stale_lease_minutes,
                "stale_state_days": stale_state_days,
            },
        )

    async def reload(self) -> dict[str, Any]:
        return await self._request("POST", "/control/reload")

    # ── sync wrappers for non-async integration contexts ───────────────

    def status_sync(self) -> dict[str, Any]:
        return asyncio.run(self.status())

    def restart_sync(self, target: str) -> dict[str, Any]:
        return asyncio.run(self.restart(target))

    def stop_sync(self) -> dict[str, Any]:
        return asyncio.run(self.stop())

    def cleanup_sync(self, **kwargs: Any) -> dict[str, Any]:
        return asyncio.run(self.cleanup(**kwargs))

    def reload_sync(self) -> dict[str, Any]:
        return asyncio.run(self.reload())
