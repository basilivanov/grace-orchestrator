# ############################################################################
# AI_HEADER: test_lifecycle_service — lifecycle snapshot and delegation tests
# ROLE: Proves exact read DTOs, degraded health issue rules, and control
#      delegation for LifecycleService using explicit in-memory ports.
# ############################################################################

# START_MODULE_CONTRACT
# purpose: Verify LifecycleService composition without filesystem, DB, Git, or
#          FastAPI dependencies.
# inputs: Explicit fake state, supervisor, worker, and version collaborators.
# returns: Pytest assertions for lifecycle read/control contracts.
# side_effects: Calls only in-memory fake collaborators.
# emitted_logs: None.
# error_behavior: Fails when DTO shapes, issue matrix, or delegation changes.
# END_MODULE_CONTRACT

# START_MODULE_MAP
# mapping:
#   - class: _State
#   - class: _Supervisor
#   - class: _Workers
#   - class: _Version
#   - function: _service
#   - function: test_status_exact_shape
#   - function: test_status_missing_state
#   - function: test_versions_recommendation
#   - function: test_health_issue_matrix
#   - function: test_controls_delegate
# END_MODULE_MAP

from __future__ import annotations

from typing import Any

import pytest

from grace_control.core.structured_logger import GraceLogger
from grace_control.services import lifecycle_service
from grace_control.services.lifecycle_service import LifecycleService, LifecycleStateMissingError

_log = GraceLogger("test_lifecycle_service")


# START_BLOCK_LIFECYCLE_SERVICE_TESTS
class _State:
    # START_FUNCTION_CONTRACT
    # name: __init__
    # purpose: Store one fake lifecycle state mapping.
    # inputs: value — mapping or None.
    # returns: None.
    # side_effects: None.
    # emitted_logs: None.
    # error_behavior: None.
    # END_FUNCTION_CONTRACT
    def __init__(self, value: dict[str, Any] | None) -> None:
        self.value = value

    # START_FUNCTION_CONTRACT
    # name: read
    # purpose: Return the configured fake lifecycle state.
    # inputs: None.
    # returns: Mapping or None.
    # side_effects: None.
    # emitted_logs: None.
    # error_behavior: None.
    # END_FUNCTION_CONTRACT
    def read(self) -> dict[str, Any] | None:
        return self.value


class _Supervisor:
    # START_FUNCTION_CONTRACT
    # name: __init__
    # purpose: Initialize fake control call tracking.
    # inputs: None.
    # returns: None.
    # side_effects: None.
    # emitted_logs: None.
    # error_behavior: None.
    # END_FUNCTION_CONTRACT
    def __init__(self) -> None:
        self.restart_targets: list[str] = []
        self.reload_calls = 0

    # START_FUNCTION_CONTRACT
    # name: restart
    # purpose: Record and return a fake restart delegation.
    # inputs: target — lifecycle target.
    # returns: Response mapping.
    # side_effects: Appends target to in-memory calls.
    # emitted_logs: None.
    # error_behavior: None.
    # END_FUNCTION_CONTRACT
    async def restart(self, target: str) -> dict[str, Any]:
        self.restart_targets.append(target)
        return {"target": target}

    # START_FUNCTION_CONTRACT
    # name: reload
    # purpose: Record and return a fake reload delegation.
    # inputs: None.
    # returns: Response mapping.
    # side_effects: Increments in-memory call count.
    # emitted_logs: None.
    # error_behavior: None.
    # END_FUNCTION_CONTRACT
    async def reload(self) -> dict[str, Any]:
        self.reload_calls += 1
        return {"reloaded": True}


class _Workers:
    # START_FUNCTION_CONTRACT
    # name: __init__
    # purpose: Store fake DB worker snapshot rows.
    # inputs: rows — worker projection list.
    # returns: None.
    # side_effects: None.
    # emitted_logs: None.
    # error_behavior: None.
    # END_FUNCTION_CONTRACT
    def __init__(self, rows: list[dict[str, Any]]) -> None:
        self.rows = rows

    # START_FUNCTION_CONTRACT
    # name: snapshot
    # purpose: Return fake DB worker rows.
    # inputs: None.
    # returns: Worker projection list.
    # side_effects: None.
    # emitted_logs: None.
    # error_behavior: None.
    # END_FUNCTION_CONTRACT
    def snapshot(self) -> list[dict[str, Any]]:
        return self.rows


class _Version:
    # START_FUNCTION_CONTRACT
    # name: current_sha
    # purpose: Return a fixed fake code SHA.
    # inputs: None.
    # returns: Short SHA.
    # side_effects: None.
    # emitted_logs: None.
    # error_behavior: None.
    # END_FUNCTION_CONTRACT
    def current_sha(self) -> str:
        return "abc123"


# START_FUNCTION_CONTRACT
# name: _service
# purpose: Construct LifecycleService with explicit fake collaborators.
# inputs: state — fake runtime mapping or None; workers — DB projection rows.
# returns: Tuple of service and fake supervisor.
# side_effects: None.
# emitted_logs: None.
# error_behavior: None.
# END_FUNCTION_CONTRACT
def _service(state: dict[str, Any] | None, workers: list[dict[str, Any]]) -> tuple[LifecycleService, _Supervisor]:
    supervisor = _Supervisor()
    service = LifecycleService(_State(state), supervisor, _Workers(workers), _Version())
    return service, supervisor


# START_FUNCTION_CONTRACT
# name: test_status_exact_shape
# purpose: Verify status returns the historical fields and values.
# inputs: monkeypatch — fixed timestamp; no external dependencies.
# returns: None.
# side_effects: Calls in-memory fake ports.
# emitted_logs: None.
# error_behavior: AssertionError when status DTO drifts.
# END_FUNCTION_CONTRACT
def test_status_exact_shape(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(lifecycle_service, "_now_iso", lambda: "nowZ")
    service, _supervisor = _service({"api": {"pid": 1}, "workers": []}, [])
    assert service.status() == {
        "supervisor_state": {"api": {"pid": 1}, "workers": []},
        "db_workers": [],
        "code_sha": "abc123",
        "fetched_at": "nowZ",
    }


# START_FUNCTION_CONTRACT
# name: test_status_missing_state
# purpose: Verify required status state raises the typed service error.
# inputs: None.
# returns: None.
# side_effects: Calls fake state port.
# emitted_logs: None.
# error_behavior: AssertionError when missing state becomes a fake DTO.
# END_FUNCTION_CONTRACT
def test_status_missing_state() -> None:
    service, _supervisor = _service(None, [])
    with pytest.raises(LifecycleStateMissingError, match="supervisor state not found"):
        service.status()


# START_FUNCTION_CONTRACT
# name: test_versions_recommendation
# purpose: Verify worker projection and recommendation semantics for versions.
# inputs: None.
# returns: None.
# side_effects: Calls fake state/version ports.
# emitted_logs: None.
# error_behavior: AssertionError when recommendation or child projection drifts.
# END_FUNCTION_CONTRACT
def test_versions_recommendation() -> None:
    service, _supervisor = _service(
        {"api": {"pid": 8}, "workers": [{"pid": 9, "started_at": "later"}]},
        [],
    )
    assert service.versions() == {
        "current_sha": "abc123",
        "api": {"pid": 8, "in_sync": True},
        "workers": [{"pid": 9, "started_at": "later"}],
        "recommendation": "POST /api/admin/lifecycle/restart/workers to bring children in sync",
    }


# START_FUNCTION_CONTRACT
# name: test_health_issue_matrix
# purpose: Verify degraded issue list and healthy boolean for missing and
#          complete runtime state.
# inputs: monkeypatch — fixed timestamp; no external dependencies.
# returns: None.
# side_effects: Calls in-memory fake ports.
# emitted_logs: None.
# error_behavior: AssertionError when health issue rules drift.
# END_FUNCTION_CONTRACT
def test_health_issue_matrix(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(lifecycle_service, "_now_iso", lambda: "nowZ")
    degraded, _supervisor = _service(None, [])
    degraded_body = degraded.health_full()
    assert degraded_body["healthy"] is False
    assert degraded_body["issues"] == ["supervisor state missing", "no workers registered in DB"]
    healthy, _supervisor = _service(
        {"api": {"pid": 1}, "workers": [{"pid": 2}]},
        [{"worker_id": "db-1"}],
    )
    healthy_body = healthy.health_full()
    assert healthy_body["healthy"] is True
    assert healthy_body["issues"] == []
    assert healthy_body["workers_alive"] == 1
    assert healthy_body["db_workers"] == 1


# START_FUNCTION_CONTRACT
# name: test_controls_delegate
# purpose: Verify LifecycleService delegates restart and reload without owning
#          control transport logic.
# inputs: None.
# returns: None.
# side_effects: Calls in-memory fake supervisor port.
# emitted_logs: None.
# error_behavior: AssertionError when delegation changes.
# END_FUNCTION_CONTRACT
@pytest.mark.asyncio
async def test_controls_delegate() -> None:
    service, supervisor = _service({}, [])
    assert await service.restart("all") == {"target": "all"}
    assert await service.reload() == {"reloaded": True}
    assert supervisor.restart_targets == ["all"]
    assert supervisor.reload_calls == 1


# END_BLOCK_LIFECYCLE_SERVICE_TESTS
