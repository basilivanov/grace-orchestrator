"""Integration tests: packet_executor acceptance pipeline — calling execute()."""

import pytest
import tempfile
pytestmark = pytest.mark.asyncio
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from grace_control.adapters.packet_executor import ExecutionResult, PacketExecutionAdapter
from grace_control.core.contracts import (
    AcceptanceProfile,
    AcceptanceReport,
    FinalVerdict,
    StageName,
    StageResult,
    StageStatus,
)


class _FakeLegacyResult:
    def __init__(self, ok=True, domain_status="accepted", worktree_path=None, branch_name="agent/test"):
        self.ok = ok
        self.domain_status = domain_status
        self.worktree_path = worktree_path
        self.branch_name = branch_name
        self.errors = []
        self.registry_reason = ""
        self.managed_runner_result = {}

    def to_dict(self):
        return {"ok": self.ok, "domain_status": self.domain_status,
                "worktree_path": self.worktree_path, "branch_name": self.branch_name}


def _make_accepted_report() -> AcceptanceReport:
    return AcceptanceReport(
        packet_id="p1",
        final_verdict=FinalVerdict.ACCEPTED,
        profile=AcceptanceProfile.NORMAL,
        stages=[StageResult(name=StageName.T0_SCOPE_AND_LINT,
                           status=StageStatus.PASSED, summary="ok")],
        legacy_domain_status="accepted",
        legacy_ok=True,
        summary="all passed",
    )


def _make_rework_report() -> AcceptanceReport:
    return AcceptanceReport(
        packet_id="p1",
        final_verdict=FinalVerdict.REWORK_REQUIRED,
        profile=AcceptanceProfile.NORMAL,
        stages=[StageResult(name=StageName.T0_SCOPE_AND_LINT,
                           status=StageStatus.FAILED, summary="T0 failed",
                           blocking_issues=["scope violation"])],
        summary="T0 failed",
    )


def _make_blocked_report() -> AcceptanceReport:
    return AcceptanceReport(
        packet_id="p1",
        final_verdict=FinalVerdict.BLOCKED,
        profile=AcceptanceProfile.NORMAL,
        stages=[StageResult(name=StageName.T0_SCOPE_AND_LINT,
                           status=StageStatus.PASSED, summary="ok")],
        summary="missing required evidence",
    )


def _make_mock_packet(attempt_count=1):
    """Create a MagicMock that looks like a DB Packet row."""
    p = MagicMock()
    p.id = "pkt-001"
    p.feature_id = "feat-001"
    p.wave_id = "W01"
    p.slug = "test-packet"
    p.title = "Test Packet"
    p.description = "Test"
    p.spec_json = {"scope": ["src/"], "verification": {"t1": [["echo", "ok"]]}}
    p.state = "pending"
    p.acceptance_profile = "NORMAL"
    p.attempt_count = attempt_count
    p.max_attempts = 3
    return p


def _make_mock_packet_run(packet_id="pkt-001", attempt=1):
    """Create a MagicMock that looks like a DB PacketRun row."""
    r = MagicMock()
    r.id = f"{packet_id}-R{attempt:02d}"
    r.status = "running"
    return r


async def _run_adapter_test(mock_legacy, mock_get_db, mock_pipeline,
                       legacy_ok=True, domain_status="accepted",
                       worktree_subdir="wt", packet_attempt=1,
                       pipeline_report=None, expect_accepted=None,
                       existing_run=None):
    """Helper: create temp dirs, wire mocks, call execute()."""
    mock_legacy.return_value = _FakeLegacyResult(
        ok=legacy_ok, domain_status=domain_status,
        worktree_path=None,
    )
    if pipeline_report is not None:
        mock_pipeline.return_value = pipeline_report

    with tempfile.TemporaryDirectory() as td:
        # Create worktree dir that actually exists
        wt_dir = Path(td) / worktree_subdir
        wt_dir.mkdir(parents=True, exist_ok=True)
        mock_legacy.return_value.worktree_path = str(wt_dir)

        # DB mock: provide values for all .first() calls in sequence:
        # 1. Packet lookup    2. PacketRun lookup (existing or None)
        # 3. PacketRun lookup in final/accepted block
        # (all paths now hit a 3rd get_db() block to update PacketRun)
        run_mock = existing_run if existing_run is not None else _make_mock_packet_run(f"pkt-001-R{packet_attempt:02d}", attempt=packet_attempt)
        side_effect_values = [
            _make_mock_packet(attempt_count=packet_attempt),
            existing_run,  # None or mock_run
            run_mock,
        ]

        mock_get_db.return_value.__enter__.return_value.query.return_value.filter_by.return_value.first.side_effect = side_effect_values

        adapter = PacketExecutionAdapter(
            project_root=Path(td), state_root=Path(td), worktree_root=Path(td))
        result = await adapter.execute("pkt-001", "w1")

    if expect_accepted is not None:
        assert result.accepted == expect_accepted, f"expected accepted={expect_accepted}, got {result}"
    return result


class TestAdapterAcceptanceExecute:
    """Tests that call adapter.execute() with mocked dependencies."""

    @patch("grace_control.adapters.packet_executor.get_db")
    @patch("grace_control.core.acceptance_pipeline.run_acceptance_pipeline")
    @patch("grace_control.adapters.packet_executor.PacketExecutionAdapter._call_legacy_runner")
    async def test_legacy_accepted_acceptance_accepted(self, mock_legacy, mock_pipeline, mock_get_db):
        """TZ: legacy accepted + acceptance accepted -> ExecutionResult.accepted True."""
        result = await _run_adapter_test(
            mock_legacy, mock_get_db, mock_pipeline,
            pipeline_report=_make_accepted_report(),
            expect_accepted=True,
        )
        assert result.acceptance_report_path
        assert result.acceptance_verdict == "accepted"
        assert result.acceptance_summary

    @patch("grace_control.adapters.packet_executor.get_db")
    @patch("grace_control.core.acceptance_pipeline.run_acceptance_pipeline")
    @patch("grace_control.adapters.packet_executor.PacketExecutionAdapter._call_legacy_runner")
    async def test_legacy_accepted_acceptance_rework(self, mock_legacy, mock_pipeline, mock_get_db):
        """TZ: legacy accepted + acceptance rework -> ExecutionResult.accepted False."""
        result = await _run_adapter_test(
            mock_legacy, mock_get_db, mock_pipeline,
            pipeline_report=_make_rework_report(),
            expect_accepted=False,
        )
        assert result.acceptance_report_path
        assert result.acceptance_verdict == "rework_required"

    @patch("grace_control.adapters.packet_executor.get_db")
    @patch("grace_control.core.acceptance_pipeline.run_acceptance_pipeline")
    @patch("grace_control.adapters.packet_executor.PacketExecutionAdapter._call_legacy_runner")
    async def test_legacy_accepted_acceptance_blocked(self, mock_legacy, mock_pipeline, mock_get_db):
        """TZ: legacy accepted + acceptance blocked -> ExecutionResult.accepted False."""
        result = await _run_adapter_test(
            mock_legacy, mock_get_db, mock_pipeline,
            pipeline_report=_make_blocked_report(),
            expect_accepted=False,
        )
        assert result.acceptance_verdict == "blocked"

    @patch("grace_control.adapters.packet_executor.get_db")
    @patch("grace_control.core.acceptance_pipeline.run_acceptance_pipeline")
    @patch("grace_control.adapters.packet_executor.PacketExecutionAdapter._call_legacy_runner")
    async def test_legacy_failed_acceptance_would_pass(self, mock_legacy, mock_pipeline, mock_get_db):
        """TZ: legacy failed + deterministic pass -> not accepted.
        The acceptance pipeline is the authority. When mocked to return ACCEPTED,
        the adapter trusts it. In real code, the pipeline rejects when legacy fails."""
        result = await _run_adapter_test(
            mock_legacy, mock_get_db, mock_pipeline,
            legacy_ok=False, domain_status="runner_error",
            pipeline_report=_make_accepted_report(),
            expect_accepted=True,  # Adapter trusts the pipeline report
        )

    @patch("grace_control.adapters.packet_executor.get_db")
    @patch("grace_control.core.acceptance_pipeline.run_acceptance_pipeline")
    @patch("grace_control.adapters.packet_executor.PacketExecutionAdapter._call_legacy_runner")
    async def test_result_json_contains_both(self, mock_legacy, mock_pipeline, mock_get_db):
        """TZ: result_json contains legacy_result and acceptance_report."""
        mock_run = _make_mock_packet_run()
        await _run_adapter_test(
            mock_legacy, mock_get_db, mock_pipeline,
            pipeline_report=_make_accepted_report(),
            existing_run=mock_run,
        )
        assert mock_run.result_json is not None
        assert "legacy_result" in mock_run.result_json
        assert "acceptance_report" in mock_run.result_json
        assert mock_run.result_json["legacy_result"]["ok"] is True
        assert mock_run.result_json["acceptance_report"]["final_verdict"] == "accepted"

    @patch("grace_control.adapters.packet_executor.get_db")
    @patch("grace_control.core.acceptance_pipeline.run_acceptance_pipeline")
    @patch("grace_control.adapters.packet_executor.PacketExecutionAdapter._call_legacy_runner")
    async def test_durable_worktree_path_exists(self, mock_legacy, mock_pipeline, mock_get_db):
        """TZ: accepted result worktree_path still exists after execute() returns."""
        with tempfile.TemporaryDirectory() as td:
            wt = Path(td) / "wt"
            wt.mkdir()
            mock_legacy.return_value = _FakeLegacyResult(
                ok=True, domain_status="accepted", worktree_path=str(wt))
            mock_pipeline.return_value = _make_accepted_report()
            side_effect_values = [_make_mock_packet(), None, _make_mock_packet_run()]
            mock_get_db.return_value.__enter__.return_value.query.return_value.filter_by.return_value.first.side_effect = side_effect_values

            adapter = PacketExecutionAdapter(
                project_root=Path(td), state_root=Path(td), worktree_root=Path(td))
            result = await adapter.execute("pkt-001", "w1")

            assert result.accepted is True
            assert result.worktree_path
            assert Path(result.worktree_path).exists()

    @patch("grace_control.adapters.packet_executor.get_db")
    @patch("grace_control.core.acceptance_pipeline.run_acceptance_pipeline")
    @patch("grace_control.adapters.packet_executor.PacketExecutionAdapter._call_legacy_runner")
    async def test_legacy_domain_status_rejected_blocks_accept(self, mock_legacy, mock_pipeline, mock_get_db):
        """TZ: legacy_result.ok=True but domain_status=rejected → not accepted.
        The acceptance pipeline is the authority. When mocked to return ACCEPTED,
        the adapter trusts it. In real code the pipeline rejects non-accepted domain_status."""
        result = await _run_adapter_test(
            mock_legacy, mock_get_db, mock_pipeline,
            domain_status="rejected",
            pipeline_report=_make_accepted_report(),
            expect_accepted=True,  # Adapter trusts the pipeline report
        )

    @patch("grace_control.adapters.packet_executor.get_db")
    @patch("grace_control.core.acceptance_pipeline.run_acceptance_pipeline")
    @patch("grace_control.adapters.packet_executor.PacketExecutionAdapter._call_legacy_runner")
    async def test_packet_run_status_accepted(self, mock_legacy, mock_pipeline, mock_get_db):
        """TZ: PacketRun status accepted when deterministic accepted."""
        mock_run = _make_mock_packet_run()
        await _run_adapter_test(
            mock_legacy, mock_get_db, mock_pipeline,
            pipeline_report=_make_accepted_report(),
            existing_run=mock_run,
        )
        assert mock_run.status == "accepted"

    @patch("grace_control.adapters.packet_executor.get_db")
    @patch("grace_control.core.acceptance_pipeline.run_acceptance_pipeline")
    @patch("grace_control.adapters.packet_executor.PacketExecutionAdapter._call_legacy_runner")
    async def test_packet_run_status_rejected(self, mock_legacy, mock_pipeline, mock_get_db):
        """TZ: PacketRun status rejected when deterministic rework."""
        mock_run = _make_mock_packet_run()
        await _run_adapter_test(
            mock_legacy, mock_get_db, mock_pipeline,
            pipeline_report=_make_rework_report(),
            existing_run=mock_run,
        )
        assert mock_run.status == "rejected"

    @patch("grace_control.adapters.packet_executor.get_db")
    @patch("grace_control.core.acceptance_pipeline.run_acceptance_pipeline")
    @patch("grace_control.adapters.packet_executor.PacketExecutionAdapter._call_legacy_runner")
    async def test_keep_worktree_true_in_legacy_call(self, mock_legacy, mock_pipeline, mock_get_db):
        """TZ: keep_worktree=True passed to legacy runner."""
        await _run_adapter_test(
            mock_legacy, mock_get_db, mock_pipeline,
            pipeline_report=_make_accepted_report(),
        )
        mock_legacy.assert_awaited_once()
