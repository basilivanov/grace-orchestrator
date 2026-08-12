# ############################################################################
# AI_HEADER: test_supervisor_control_service — typed supervisor control tests
# ROLE: Proves state gating, target validation, one-shot delegation, and typed
#      transport/remote error preservation for lifecycle mutations.
# ############################################################################

# START_MODULE_CONTRACT
# purpose: Verify SupervisorControlService behavior without a real UDS server.
# inputs: Temporary state/socket paths and explicit fake SupervisorClient ports.
# returns: Pytest assertions.
# side_effects: Creates temporary state/socket marker files only.
# emitted_logs: None.
# error_behavior: Fails when domain error mapping or no-retry behavior regresses.
# END_MODULE_CONTRACT

# START_MODULE_MAP
# mapping:
#   - class: _FakeClient
#   - function: test_missing_state_is_typed
#   - function: test_missing_socket_is_typed
#   - function: test_invalid_target_is_rejected
#   - function: test_restart_reload_delegate_once
#   - function: test_remote_status_and_detail_are_preserved
#   - function: test_transport_failure_is_not_retried
# END_MODULE_MAP

from __future__ import annotations

from pathlib import Path
from typing import Any

import httpx
import pytest

from grace_control.core.structured_logger import GraceLogger
from grace_control.services.runtime_state_store import RuntimeStateStore
from grace_control.services.supervisor_control_service import (
    SupervisorControlService,
    SupervisorNotRunningError,
    SupervisorRemoteError,
    SupervisorUnavailableError,
)
from grace_control.supervisor_client import SupervisorConnectionError

_log = GraceLogger("test_supervisor_control_service")


# START_BLOCK_SUPERVISOR_CONTROL_TESTS
class _FakeClient:
    # START_FUNCTION_CONTRACT
    # name: __init__
    # purpose: Configure a fake explicit supervisor client port.
    # inputs: socket_path — socket marker path; restart_result/reload_result —
    #          successful response mappings.
    # returns: None.
    # side_effects: Initializes call counters.
    # emitted_logs: None.
    # error_behavior: Optional failures are raised by the operation methods.
    # END_FUNCTION_CONTRACT
    def __init__(self, socket_path: Path, *, restart_result: dict[str, Any] | None = None) -> None:
        self.socket_path = socket_path
        self.restart_result = restart_result or {"ok": True, "target": "workers"}
        self.restart_calls = 0
        self.reload_calls = 0
        self.restart_error: Exception | None = None
        self.reload_error: Exception | None = None

    # START_FUNCTION_CONTRACT
    # name: restart
    # purpose: Return or raise the configured fake restart outcome.
    # inputs: target — requested supervisor restart target.
    # returns: Fake supervisor response.
    # side_effects: Increments restart call count.
    # emitted_logs: None.
    # error_behavior: Raises configured restart_error.
    # END_FUNCTION_CONTRACT
    async def restart(self, target: str) -> dict[str, Any]:
        self.restart_calls += 1
        if self.restart_error:
            raise self.restart_error
        return {**self.restart_result, "target": target}

    # START_FUNCTION_CONTRACT
    # name: reload
    # purpose: Return or raise the configured fake reload outcome.
    # inputs: None.
    # returns: Fake supervisor response.
    # side_effects: Increments reload call count.
    # emitted_logs: None.
    # error_behavior: Raises configured reload_error.
    # END_FUNCTION_CONTRACT
    async def reload(self) -> dict[str, Any]:
        self.reload_calls += 1
        if self.reload_error:
            raise self.reload_error
        return {"ok": True, "watcher_primed": False}


# START_FUNCTION_CONTRACT
# name: _running_service
# purpose: Build a service with physically present state and socket markers.
# inputs: tmp_path — pytest temporary target directory.
# returns: Tuple of service, fake client, and state store.
# side_effects: Writes temporary state/socket marker files.
# emitted_logs: None.
# error_behavior: None beyond filesystem failures.
# END_FUNCTION_CONTRACT
def _running_service(tmp_path: Path) -> tuple[SupervisorControlService, _FakeClient, RuntimeStateStore]:
    (tmp_path / "supervisor.json").write_text("{}")
    socket = tmp_path / "supervisor.sock"
    socket.touch()
    store = RuntimeStateStore(tmp_path)
    client = _FakeClient(socket)
    return SupervisorControlService(store, client), client, store


# START_FUNCTION_CONTRACT
# name: test_missing_state_is_typed
# purpose: Verify missing state blocks mutation as a not-running error.
# inputs: tmp_path — empty target directory.
# returns: None.
# side_effects: None.
# emitted_logs: None.
# error_behavior: AssertionError when missing state reaches the client.
# END_FUNCTION_CONTRACT
@pytest.mark.asyncio
async def test_missing_state_is_typed(tmp_path: Path) -> None:
    client = _FakeClient(tmp_path / "supervisor.sock")
    service = SupervisorControlService(RuntimeStateStore(tmp_path), client)
    with pytest.raises(SupervisorNotRunningError):
        await service.restart("workers")
    assert client.restart_calls == 0


# START_FUNCTION_CONTRACT
# name: test_missing_socket_is_typed
# purpose: Verify present state with unavailable socket becomes 502-domain
#          unavailable without calling the client.
# inputs: tmp_path — target with state but no socket.
# returns: None.
# side_effects: Writes temporary supervisor.json.
# emitted_logs: None.
# error_behavior: AssertionError when unavailable state is not typed.
# END_FUNCTION_CONTRACT
@pytest.mark.asyncio
async def test_missing_socket_is_typed(tmp_path: Path) -> None:
    (tmp_path / "supervisor.json").write_text("{}")
    client = _FakeClient(tmp_path / "supervisor.sock")
    service = SupervisorControlService(RuntimeStateStore(tmp_path), client)
    with pytest.raises(SupervisorUnavailableError):
        await service.reload()
    assert client.reload_calls == 0


# START_FUNCTION_CONTRACT
# name: test_invalid_target_is_rejected
# purpose: Verify restart target validation precedes state/transport work.
# inputs: tmp_path — empty target directory.
# returns: None.
# side_effects: None.
# emitted_logs: None.
# error_behavior: AssertionError when invalid target reaches a domain port.
# END_FUNCTION_CONTRACT
@pytest.mark.asyncio
async def test_invalid_target_is_rejected(tmp_path: Path) -> None:
    service, client, _store = _running_service(tmp_path)
    with pytest.raises(ValueError, match=r"api\|workers\|all"):
        await service.restart("bogus")
    assert client.restart_calls == 0


# START_FUNCTION_CONTRACT
# name: test_restart_reload_delegate_once
# purpose: Verify successful restart and reload each delegate exactly once.
# inputs: tmp_path — running target markers.
# returns: None.
# side_effects: Calls fake control methods.
# emitted_logs: None.
# error_behavior: AssertionError when delegation or response changes.
# END_FUNCTION_CONTRACT
@pytest.mark.asyncio
async def test_restart_reload_delegate_once(tmp_path: Path) -> None:
    service, client, _store = _running_service(tmp_path)
    assert await service.restart("workers") == {"ok": True, "target": "workers"}
    assert await service.reload() == {"ok": True, "watcher_primed": False}
    assert client.restart_calls == 1
    assert client.reload_calls == 1


# START_FUNCTION_CONTRACT
# name: test_remote_status_and_detail_are_preserved
# purpose: Verify HTTPStatusError becomes a typed exception with remote status
#          and response text intact.
# inputs: tmp_path — running target markers.
# returns: None.
# side_effects: Calls fake control method once.
# emitted_logs: None.
# error_behavior: AssertionError when remote detail is discarded.
# END_FUNCTION_CONTRACT
@pytest.mark.asyncio
async def test_remote_status_and_detail_are_preserved(tmp_path: Path) -> None:
    service, client, _store = _running_service(tmp_path)
    request = httpx.Request("POST", "http://localhost/control/reload")
    response = httpx.Response(409, text="reload conflict", request=request)
    client.reload_error = httpx.HTTPStatusError("conflict", request=request, response=response)
    with pytest.raises(SupervisorRemoteError) as caught:
        await service.reload()
    assert caught.value.status_code == 409
    assert caught.value.detail == "reload conflict"
    assert client.reload_calls == 1


# START_FUNCTION_CONTRACT
# name: test_transport_failure_is_not_retried
# purpose: Verify ambiguous transport failure results in one client attempt.
# inputs: tmp_path — running target markers.
# returns: None.
# side_effects: Calls fake control method once.
# emitted_logs: None.
# error_behavior: AssertionError when a mutation is retried.
# END_FUNCTION_CONTRACT
@pytest.mark.asyncio
async def test_transport_failure_is_not_retried(tmp_path: Path) -> None:
    service, client, _store = _running_service(tmp_path)
    client.restart_error = SupervisorConnectionError("socket down")
    with pytest.raises(SupervisorUnavailableError):
        await service.restart("all")
    assert client.restart_calls == 1


# END_BLOCK_SUPERVISOR_CONTROL_TESTS
