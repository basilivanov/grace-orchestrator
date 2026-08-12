# ############################################################################
# AI_HEADER: test_admin_read_models — characterization of bounded Admin reads
# ROLE: Locks the exact public dictionary shapes for the typed Admin read
#       models and their selected service helpers without changing API output.
# ############################################################################

# START_MODULE_CONTRACT
# purpose: Characterize and verify bounded typed Admin read-model contracts.
# inputs: Model values and small source-compatible helper inputs.
# returns: Pytest assertions; no application state is changed.
# side_effects: None beyond temporary in-memory test values.
# emitted_logs: None.
# error_behavior: Fails when a required key set or value-preserving boundary
#                 changes.
# END_MODULE_CONTRACT

# START_MODULE_MAP
# mapping:
#   - function: test_cross_project_coverage_shapes
#   - function: test_attention_item_shape
#   - function: test_project_health_shape
#   - function: test_admin_worker_shape
#   - function: test_packet_run_summary_shape
#   - function: test_pipeline_stage_shape
# END_MODULE_MAP

from __future__ import annotations

from datetime import UTC, datetime
from types import SimpleNamespace

from grace_control.services.admin_cross_project_helpers import (
    _attention_item,
    _coverage,
    _coverage_from_results,
)
from grace_control.services.admin_overview_read_service import (
    AdminOverviewReadService,
)
from grace_control.services.admin_packet_read_service import _packet_run_summary
from grace_control.services.admin_pipeline_read_service import _pipeline_stage
from grace_control.services.admin_read_models import (
    AttentionItem,
    CrossProjectCoverage,
    PacketRunSummary,
    PipelineStageView,
    ProjectHealthSnapshot,
    WorkerSnapshot,
)


# START_FUNCTION_CONTRACT
# name: test_cross_project_coverage_shapes
# purpose: Lock the full and reduced coverage dictionary contracts.
# inputs: None; uses representative in-memory rows.
# returns: None.
# side_effects: None.
# emitted_logs: None.
# error_behavior: Fails if either coverage shape changes.
# END_FUNCTION_CONTRACT
def test_cross_project_coverage_shapes():
    rows = [
        {"responded": True, "partial": False, "disabled": False},
        {"responded": False, "partial": True, "disabled": False},
        {"responded": False, "partial": False, "disabled": True},
    ]
    assert set(_coverage(rows, 3)) == {
        "projects_total", "projects_responded", "projects_failed",
        "projects_disabled", "projects_partial", "partial",
    }
    assert set(_coverage_from_results([], 0)) == {
        "projects_total", "projects_responded", "projects_failed",
    }
    model = CrossProjectCoverage(3, 1, 1, 1, 1, True)
    assert set(model.to_dict()) == set(_coverage(rows, 3))


# START_FUNCTION_CONTRACT
# name: test_attention_item_shape
# purpose: Lock the normalized ten-field attention row contract.
# inputs: None; uses a minimal project context stub.
# returns: None.
# side_effects: None.
# emitted_logs: None.
# error_behavior: Fails if attention keys or nullable values change.
# END_FUNCTION_CONTRACT
def test_attention_item_shape():
    context = SimpleNamespace(key="alpha", name="Alpha")
    item = _attention_item(
        context, "warning", "packet_state", "packet", "pkt-1",
        "Packet needs attention", "packet is blocked", None,
    )
    assert set(item) == {
        "severity", "project_key", "project_name", "kind", "entity_type",
        "entity_id", "title", "reason", "timestamp", "detail_url",
    }
    assert item["entity_id"] == "pkt-1"
    assert item["timestamp"] is None
    assert isinstance(AttentionItem(**item), AttentionItem)


# START_FUNCTION_CONTRACT
# name: test_project_health_shape
# purpose: Lock the six-field Admin system-health response.
# inputs: monkeypatch — pytest environment patcher for target metadata.
# returns: None.
# side_effects: Reads local git metadata through the service's existing reader.
# emitted_logs: None.
# error_behavior: Fails if health keys or defaults change.
# END_FUNCTION_CONTRACT
def test_project_health_shape(monkeypatch):
    monkeypatch.delenv("GRACE_TARGET_DIR", raising=False)
    health = AdminOverviewReadService().get_system_health()
    assert set(health) == {
        "supervisor_alive", "api_alive", "workers_alive", "db_ok", "code_sha", "version",
    }
    assert ProjectHealthSnapshot(**health).to_dict() == health


# START_FUNCTION_CONTRACT
# name: test_admin_worker_shape
# purpose: Lock the six-field Admin worker snapshot distinct from lifecycle.
# inputs: None; uses a minimal worker row stub.
# returns: None.
# side_effects: None.
# emitted_logs: None.
# error_behavior: Fails if worker keys or elapsed semantics change.
# END_FUNCTION_CONTRACT
def test_admin_worker_shape():
    now = datetime.now(UTC)
    worker = SimpleNamespace(
        id="worker-1",
        status="active",
        current_packet_id="pkt-1",
        last_heartbeat=now,
        started_at=now,
    )
    row = AdminOverviewReadService._worker_to_dict(worker)
    assert set(row) == {
        "id", "status", "current_packet_id", "last_heartbeat", "started_at",
        "current_elapsed",
    }
    assert row["id"] == "worker-1"
    assert WorkerSnapshot(**row).to_dict() == row


# START_FUNCTION_CONTRACT
# name: test_packet_run_summary_shape
# purpose: Lock the rich sixteen-field packet-run summary contract.
# inputs: None; uses a minimal persisted-run stub.
# returns: None.
# side_effects: None.
# emitted_logs: None.
# error_behavior: Fails if run fields, nulls or numeric coercion change.
# END_FUNCTION_CONTRACT
def test_packet_run_summary_shape():
    started = datetime(2026, 1, 1, 10, 0, 0)
    finished = datetime(2026, 1, 1, 10, 0, 5)
    run = SimpleNamespace(
        id="run-1",
        run_number=2,
        worker_id=None,
        executor_id=None,
        model=None,
        status="completed",
        duration_ms=None,
        started_at=started,
        finished_at=finished,
        tokens_in=12,
        tokens_out=34,
        cost_usd="0.25",
        base_sha="base-1",
        integration_base_sha=None,
    )
    row = _packet_run_summary(run)
    expected = {
        "run_id", "run_number", "worker_id", "executor_id", "model", "status",
        "duration_ms", "started_at", "finished_at", "elapsed_seconds", "is_running",
        "tokens_in", "tokens_out", "cost_usd", "base_sha", "integration_base_sha",
    }
    assert set(row) == expected
    assert row["worker_id"] == ""
    assert row["duration_ms"] == 0
    assert row["elapsed_seconds"] == 5
    assert row["cost_usd"] == 0.25
    assert PacketRunSummary(**row).to_dict() == row


# START_FUNCTION_CONTRACT
# name: test_pipeline_stage_shape
# purpose: Lock the canonical eight-field pipeline stage-card contract.
# inputs: None; uses representative operator-stage values.
# returns: None.
# side_effects: None.
# emitted_logs: None.
# error_behavior: Fails if the stable pipeline stage shape changes.
# END_FUNCTION_CONTRACT
def test_pipeline_stage_shape():
    row = _pipeline_stage(
        "coder_run", "Coder", "running", "2026-01-01T10:00:00Z", None,
        0, "worker-1", "runs",
    )
    assert set(row) == {
        "key", "label", "status", "started_at", "finished_at", "duration_ms",
        "meta", "target_tab",
    }
    assert PipelineStageView(**row).to_dict() == row
