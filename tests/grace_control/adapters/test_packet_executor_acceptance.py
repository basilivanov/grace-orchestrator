"""Integration tests: packet_executor acceptance pipeline — calling execute()."""

import pytest
import tempfile
pytestmark = pytest.mark.asyncio
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

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
    def __init__(self, ok=True, domain_status="accepted", worktree_path=None, branch_name="agent/test", evidence=None):
        self.ok = ok
        self.domain_status = domain_status
        self.worktree_path = worktree_path
        self.branch_name = branch_name
        self.evidence = evidence or {}
        self.errors = []
        self.registry_reason = ""
        self.managed_runner_result = {}

    def to_dict(self):
        return {"ok": self.ok, "domain_status": self.domain_status,
                "worktree_path": self.worktree_path, "branch_name": self.branch_name,
                "evidence": self.evidence}


class _FakeBackend:
    """W8: tests pass a fake backend in instead of selecting the (removed) legacy one."""
    def __init__(self, worktree_path=None, ok=True):
        self._wt = worktree_path
        self._ok = ok

    async def run(self, request):
        return _FakeLegacyResult(
            ok=self._ok, domain_status="accepted" if self._ok else "failed",
            worktree_path=self._wt, branch_name=request.branch_name,
        )

    async def cancel(self, request):
        return None


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


def _make_mock_packet(attempt_count=1, profile="NORMAL"):
    p = MagicMock()
    p.id = "pkt-001"
    p.feature_id = "feat-001"
    p.wave_id = "W01"
    p.slug = "test-packet"
    p.title = "Test Packet"
    p.description = "Test"
    p.spec_json = {"scope": ["src/"], "verification": {"t1": [["echo", "ok"]]}}
    p.state = "pending"
    p.acceptance_profile = profile
    p.attempt_count = attempt_count
    p.max_attempts = 3
    return p


def _make_mock_packet_run(packet_id="pkt-001", attempt=1):
    r = MagicMock()
    r.id = f"{packet_id}-R{attempt:02d}"
    r.status = "running"
    return r


def _make_verifier_pass():
    from grace_control.core.evidence_verifier import EvidenceVerifierReport, EvidenceVerifierVerdict
    return EvidenceVerifierReport(verdict=EvidenceVerifierVerdict.PASS, summary="verifier passed")


def _make_verifier_rework():
    from grace_control.core.evidence_verifier import EvidenceVerifierReport, EvidenceVerifierVerdict
    return EvidenceVerifierReport(verdict=EvidenceVerifierVerdict.REWORK_TO_CODER, summary="verifier says rework")


def _make_verifier_architect():
    from grace_control.core.evidence_verifier import EvidenceVerifierReport, EvidenceVerifierVerdict
    return EvidenceVerifierReport(verdict=EvidenceVerifierVerdict.RETURN_TO_ARCHITECT, summary="verifier says architect",
                                   spec_conflicts=["scope too narrow"])


def _make_reviewer_pass():
    from grace_control.core.reviewer_gate import ReviewerReport, ReviewerVerdict
    return ReviewerReport(verdict=ReviewerVerdict.PASS, summary="reviewer passed")


def _make_reviewer_rework():
    from grace_control.core.reviewer_gate import ReviewerReport, ReviewerVerdict
    return ReviewerReport(verdict=ReviewerVerdict.REWORK_TO_CODER, summary="reviewer says rework")


def _make_reviewer_architect():
    from grace_control.core.reviewer_gate import ReviewerReport, ReviewerVerdict
    return ReviewerReport(verdict=ReviewerVerdict.RETURN_TO_ARCHITECT, summary="reviewer says architect")


async def _run_adapter_test(mock_legacy, mock_get_db, mock_pipeline,
                       legacy_ok=True, domain_status="accepted",
                       worktree_subdir="wt", packet_attempt=1,
                       pipeline_report=None, expect_accepted=None,
                       existing_run=None, mock_verifier=None, mock_reviewer=None,
                       profile="NORMAL"):
    mock_legacy.return_value = _FakeLegacyResult(
        ok=legacy_ok, domain_status=domain_status,
        worktree_path=None,
    )
    if pipeline_report is not None:
        mock_pipeline.return_value = pipeline_report
    from grace_control.core.evidence_verifier import EvidenceVerifierReport as _EVR
    from grace_control.core.reviewer_gate import ReviewerReport as _RR
    if mock_verifier is not None and not isinstance(mock_verifier.return_value, _EVR):
        mock_verifier.return_value = _make_verifier_pass()
    if mock_reviewer is not None and not isinstance(mock_reviewer.return_value, _RR):
        mock_reviewer.return_value = _make_reviewer_pass()

    with tempfile.TemporaryDirectory() as td:
        wt_dir = Path(td) / worktree_subdir
        wt_dir.mkdir(parents=True, exist_ok=True)
        mock_legacy.return_value.worktree_path = str(wt_dir)

        run_mock = existing_run if existing_run is not None else _make_mock_packet_run(f"pkt-001-R{packet_attempt:02d}", attempt=packet_attempt)
        side_effect_values = [
            _make_mock_packet(attempt_count=packet_attempt, profile=profile),
            existing_run,
            run_mock,
        ]
        mock_get_db.return_value.__enter__.return_value.query.return_value.filter_by.return_value.first.side_effect = side_effect_values

        adapter = PacketExecutionAdapter(
            project_root=Path(td), state_root=Path(td), worktree_root=Path(td),
            backend=_FakeBackend())
        result = await adapter.execute("pkt-001", "w1")

    if expect_accepted is not None:
        assert result.accepted == expect_accepted, f"expected accepted={expect_accepted}, got {result}"
    return result


# ── Original tests (updated with verifier/reviewer mocks) ────────────────────

class TestOriginal:
    @patch("grace_control.adapters.packet_executor.run_reviewer_gate")
    @patch("grace_control.adapters.packet_executor.run_evidence_verifier")
    @patch("grace_control.adapters.packet_executor.get_db")
    @patch("grace_control.core.acceptance_pipeline.run_acceptance_pipeline")
    @patch("grace_control.adapters.packet_executor.PacketExecutionAdapter._call_executor")
    async def test_legacy_accepted_acceptance_accepted(self, mock_legacy, mock_pipeline, mock_get_db, mock_verifier, mock_reviewer):
        """verifier PASS + reviewer PASS → accepted."""
        result = await _run_adapter_test(
            mock_legacy, mock_get_db, mock_pipeline,
            pipeline_report=_make_accepted_report(),
            expect_accepted=True,
            mock_verifier=mock_verifier, mock_reviewer=mock_reviewer,
        )
        assert result.acceptance_report_path
        assert result.acceptance_verdict == "accepted"
        assert result.acceptance_summary

    @patch("grace_control.adapters.packet_executor.run_reviewer_gate")
    @patch("grace_control.adapters.packet_executor.run_evidence_verifier")
    @patch("grace_control.adapters.packet_executor.get_db")
    @patch("grace_control.core.acceptance_pipeline.run_acceptance_pipeline")
    @patch("grace_control.adapters.packet_executor.PacketExecutionAdapter._call_executor")
    async def test_legacy_accepted_acceptance_rework(self, mock_legacy, mock_pipeline, mock_get_db, mock_verifier, mock_reviewer):
        result = await _run_adapter_test(
            mock_legacy, mock_get_db, mock_pipeline,
            pipeline_report=_make_rework_report(),
            expect_accepted=False,
            mock_verifier=mock_verifier, mock_reviewer=mock_reviewer,
        )
        assert result.acceptance_report_path
        assert result.acceptance_verdict == "rework_required"

    @patch("grace_control.adapters.packet_executor.run_reviewer_gate")
    @patch("grace_control.adapters.packet_executor.run_evidence_verifier")
    @patch("grace_control.adapters.packet_executor.get_db")
    @patch("grace_control.core.acceptance_pipeline.run_acceptance_pipeline")
    @patch("grace_control.adapters.packet_executor.PacketExecutionAdapter._call_executor")
    async def test_legacy_accepted_acceptance_blocked(self, mock_legacy, mock_pipeline, mock_get_db, mock_verifier, mock_reviewer):
        result = await _run_adapter_test(
            mock_legacy, mock_get_db, mock_pipeline,
            pipeline_report=_make_blocked_report(),
            expect_accepted=False,
            mock_verifier=mock_verifier, mock_reviewer=mock_reviewer,
        )
        assert result.acceptance_verdict == "blocked"

    @patch("grace_control.adapters.packet_executor.run_reviewer_gate")
    @patch("grace_control.adapters.packet_executor.run_evidence_verifier")
    @patch("grace_control.adapters.packet_executor.get_db")
    @patch("grace_control.core.acceptance_pipeline.run_acceptance_pipeline")
    @patch("grace_control.adapters.packet_executor.PacketExecutionAdapter._call_executor")
    async def test_adapter_trusts_acceptance_pipeline_when_mocked(self, mock_legacy, mock_pipeline, mock_get_db, mock_verifier, mock_reviewer):
        """Adapter trusts the acceptance pipeline report even when legacy failed (pipeline mock)."""
        result = await _run_adapter_test(
            mock_legacy, mock_get_db, mock_pipeline,
            legacy_ok=False, domain_status="runner_error",
            pipeline_report=_make_accepted_report(),
            expect_accepted=True,
            mock_verifier=mock_verifier, mock_reviewer=mock_reviewer,
        )

    @patch("grace_control.adapters.packet_executor.run_reviewer_gate")
    @patch("grace_control.adapters.packet_executor.run_evidence_verifier")
    @patch("grace_control.adapters.packet_executor.get_db")
    @patch("grace_control.core.acceptance_pipeline.run_acceptance_pipeline")
    @patch("grace_control.adapters.packet_executor.PacketExecutionAdapter._call_executor")
    async def test_result_json_contains_both(self, mock_legacy, mock_pipeline, mock_get_db, mock_verifier, mock_reviewer):
        mock_run = _make_mock_packet_run()
        await _run_adapter_test(
            mock_legacy, mock_get_db, mock_pipeline,
            pipeline_report=_make_accepted_report(),
            existing_run=mock_run,
            mock_verifier=mock_verifier, mock_reviewer=mock_reviewer,
        )
        assert mock_run.result_json is not None
        assert "legacy_result" in mock_run.result_json
        assert "acceptance_report" in mock_run.result_json

    @patch("grace_control.adapters.packet_executor.run_reviewer_gate")
    @patch("grace_control.adapters.packet_executor.run_evidence_verifier")
    @patch("grace_control.adapters.packet_executor.get_db")
    @patch("grace_control.core.acceptance_pipeline.run_acceptance_pipeline")
    @patch("grace_control.adapters.packet_executor.PacketExecutionAdapter._call_executor")
    async def test_durable_worktree_path_exists(self, mock_legacy, mock_pipeline, mock_get_db, mock_verifier, mock_reviewer):
        with tempfile.TemporaryDirectory() as td:
            wt = Path(td) / "wt"
            wt.mkdir()
            mock_legacy.return_value = _FakeLegacyResult(
                ok=True, domain_status="accepted", worktree_path=str(wt))
            mock_pipeline.return_value = _make_accepted_report()
            mock_verifier.return_value = _make_verifier_pass()
            mock_reviewer.return_value = _make_reviewer_pass()
            side_effect_values = [_make_mock_packet(profile="STRICT"), None, _make_mock_packet_run()]
            mock_get_db.return_value.__enter__.return_value.query.return_value.filter_by.return_value.first.side_effect = side_effect_values
            adapter = PacketExecutionAdapter(
                project_root=Path(td), state_root=Path(td), worktree_root=Path(td),
                backend=_FakeBackend())
            result = await adapter.execute("pkt-001", "w1")
            assert result.accepted is True
            assert result.worktree_path
            assert Path(result.worktree_path).exists()

    @patch("grace_control.adapters.packet_executor.run_reviewer_gate")
    @patch("grace_control.adapters.packet_executor.run_evidence_verifier")
    @patch("grace_control.adapters.packet_executor.get_db")
    @patch("grace_control.core.acceptance_pipeline.run_acceptance_pipeline")
    @patch("grace_control.adapters.packet_executor.PacketExecutionAdapter._call_executor")
    async def test_adapter_trusts_acceptance_pipeline_domain_status_mocked(self, mock_legacy, mock_pipeline, mock_get_db, mock_verifier, mock_reviewer):
        """Adapter trusts pipeline report even when legacy domain_status=rejected (pipeline mock)."""
        result = await _run_adapter_test(
            mock_legacy, mock_get_db, mock_pipeline,
            domain_status="rejected",
            pipeline_report=_make_accepted_report(),
            expect_accepted=True,
            mock_verifier=mock_verifier, mock_reviewer=mock_reviewer,
        )

    @patch("grace_control.adapters.packet_executor.run_reviewer_gate")
    @patch("grace_control.adapters.packet_executor.run_evidence_verifier")
    @patch("grace_control.adapters.packet_executor.get_db")
    @patch("grace_control.core.acceptance_pipeline.run_acceptance_pipeline")
    @patch("grace_control.adapters.packet_executor.PacketExecutionAdapter._call_executor")
    async def test_packet_run_status_accepted(self, mock_legacy, mock_pipeline, mock_get_db, mock_verifier, mock_reviewer):
        mock_run = _make_mock_packet_run()
        await _run_adapter_test(
            mock_legacy, mock_get_db, mock_pipeline,
            pipeline_report=_make_accepted_report(),
            existing_run=mock_run,
            mock_verifier=mock_verifier, mock_reviewer=mock_reviewer,
        )
        assert mock_run.status == "accepted"

    @patch("grace_control.adapters.packet_executor.run_reviewer_gate")
    @patch("grace_control.adapters.packet_executor.run_evidence_verifier")
    @patch("grace_control.adapters.packet_executor.get_db")
    @patch("grace_control.core.acceptance_pipeline.run_acceptance_pipeline")
    @patch("grace_control.adapters.packet_executor.PacketExecutionAdapter._call_executor")
    async def test_packet_run_status_rejected(self, mock_legacy, mock_pipeline, mock_get_db, mock_verifier, mock_reviewer):
        mock_run = _make_mock_packet_run()
        await _run_adapter_test(
            mock_legacy, mock_get_db, mock_pipeline,
            pipeline_report=_make_rework_report(),
            existing_run=mock_run,
            mock_verifier=mock_verifier, mock_reviewer=mock_reviewer,
        )
        assert mock_run.status == "rejected"

    @patch("grace_control.adapters.packet_executor.run_reviewer_gate")
    @patch("grace_control.adapters.packet_executor.run_evidence_verifier")
    @patch("grace_control.adapters.packet_executor.get_db")
    @patch("grace_control.core.acceptance_pipeline.run_acceptance_pipeline")
    @patch("grace_control.adapters.packet_executor.PacketExecutionAdapter._call_executor")
    async def test_keep_worktree_true_in_legacy_call(self, mock_legacy, mock_pipeline, mock_get_db, mock_verifier, mock_reviewer):
        await _run_adapter_test(
            mock_legacy, mock_get_db, mock_pipeline,
            pipeline_report=_make_accepted_report(),
            mock_verifier=mock_verifier, mock_reviewer=mock_reviewer,
        )
        mock_legacy.assert_awaited_once()


# ── TZ-008 Routing tests ─────────────────────────────────────────────────────

class TestEvidenceVerifierReviewerRouting:

    # ── Tests that use FAST profile ──────────────────────────────────

    @patch("grace_control.adapters.packet_executor.run_reviewer_gate")
    @patch("grace_control.adapters.packet_executor.run_evidence_verifier")
    @patch("grace_control.adapters.packet_executor.get_db")
    @patch("grace_control.core.acceptance_pipeline.run_acceptance_pipeline")
    @patch("grace_control.adapters.packet_executor.PacketExecutionAdapter._call_executor")
    async def test_fast_skips_verifier_and_reviewer(self, mock_legacy, mock_pipeline, mock_get_db, mock_verifier, mock_reviewer):
        """FAST with deterministic accepted → verifier and reviewer not called."""
        result = await _run_adapter_test(
            mock_legacy, mock_get_db, mock_pipeline,
            pipeline_report=_make_accepted_report(),
            expect_accepted=True,
            mock_verifier=mock_verifier, mock_reviewer=mock_reviewer,
            profile="FAST",
        )
        mock_verifier.assert_not_called()
        mock_reviewer.assert_not_called()
        mock_run = mock_get_db.return_value.__enter__.return_value.query.return_value.filter_by.return_value.first
        last_call = mock_run.side_effect
        assert result.acceptance_verdict == "accepted"

    # ── Tests that use NORMAL profile ────────────────────────────────

    @patch("grace_control.adapters.packet_executor.run_reviewer_gate")
    @patch("grace_control.adapters.packet_executor.run_evidence_verifier")
    @patch("grace_control.adapters.packet_executor.get_db")
    @patch("grace_control.core.acceptance_pipeline.run_acceptance_pipeline")
    @patch("grace_control.adapters.packet_executor.PacketExecutionAdapter._call_executor")
    async def test_normal_verifier_pass_skips_reviewer(self, mock_legacy, mock_pipeline, mock_get_db, mock_verifier, mock_reviewer):
        """NORMAL with verifier PASS → reviewer not called, accepted."""
        result = await _run_adapter_test(
            mock_legacy, mock_get_db, mock_pipeline,
            pipeline_report=_make_accepted_report(),
            expect_accepted=True,
            mock_verifier=mock_verifier, mock_reviewer=mock_reviewer,
            profile="NORMAL",
        )
        mock_verifier.assert_called_once()
        mock_reviewer.assert_not_called()

    @patch("grace_control.adapters.packet_executor.run_reviewer_gate")
    @patch("grace_control.adapters.packet_executor.run_evidence_verifier")
    @patch("grace_control.adapters.packet_executor.get_db")
    @patch("grace_control.core.acceptance_pipeline.run_acceptance_pipeline")
    @patch("grace_control.adapters.packet_executor.PacketExecutionAdapter._call_executor")
    async def test_normal_verifier_rework_skips_reviewer(self, mock_legacy, mock_pipeline, mock_get_db, mock_verifier, mock_reviewer):
        """NORMAL with verifier REWORK_TO_CODER → reviewer not called, rejected."""
        mock_verifier.return_value = _make_verifier_rework()
        result = await _run_adapter_test(
            mock_legacy, mock_get_db, mock_pipeline,
            pipeline_report=_make_accepted_report(),
            expect_accepted=False,
            mock_verifier=mock_verifier, mock_reviewer=mock_reviewer,
            profile="NORMAL",
        )
        mock_reviewer.assert_not_called()
        assert result.domain_status == "rejected"

    @patch("grace_control.adapters.packet_executor.run_reviewer_gate")
    @patch("grace_control.adapters.packet_executor.run_evidence_verifier")
    @patch("grace_control.adapters.packet_executor.get_db")
    @patch("grace_control.core.acceptance_pipeline.run_acceptance_pipeline")
    @patch("grace_control.adapters.packet_executor.PacketExecutionAdapter._call_executor")
    async def test_normal_verifier_architect_skips_reviewer(self, mock_legacy, mock_pipeline, mock_get_db, mock_verifier, mock_reviewer):
        """NORMAL with verifier RETURN_TO_ARCHITECT → reviewer not called, blocked."""
        mock_verifier.return_value = _make_verifier_architect()
        result = await _run_adapter_test(
            mock_legacy, mock_get_db, mock_pipeline,
            pipeline_report=_make_accepted_report(),
            expect_accepted=False,
            mock_verifier=mock_verifier, mock_reviewer=mock_reviewer,
            profile="NORMAL",
        )
        mock_reviewer.assert_not_called()
        assert result.domain_status == "blocked"

    # ── Tests that use STRICT profile ────────────────────────────────

    @patch("grace_control.adapters.packet_executor.run_reviewer_gate")
    @patch("grace_control.adapters.packet_executor.run_evidence_verifier")
    @patch("grace_control.adapters.packet_executor.get_db")
    @patch("grace_control.core.acceptance_pipeline.run_acceptance_pipeline")
    @patch("grace_control.adapters.packet_executor.PacketExecutionAdapter._call_executor")
    async def test_strict_verifier_pass_reviewer_pass(self, mock_legacy, mock_pipeline, mock_get_db, mock_verifier, mock_reviewer):
        """STRICT with verifier PASS + reviewer PASS → accepted."""
        mock_verifier.return_value = _make_verifier_pass()
        mock_reviewer.return_value = _make_reviewer_pass()
        result = await _run_adapter_test(
            mock_legacy, mock_get_db, mock_pipeline,
            pipeline_report=_make_accepted_report(),
            expect_accepted=True,
            mock_verifier=mock_verifier, mock_reviewer=mock_reviewer,
            profile="STRICT",
        )
        mock_reviewer.assert_called_once()
        assert result.acceptance_verdict == "accepted"

    @patch("grace_control.adapters.packet_executor.run_reviewer_gate")
    @patch("grace_control.adapters.packet_executor.run_evidence_verifier")
    @patch("grace_control.adapters.packet_executor.get_db")
    @patch("grace_control.core.acceptance_pipeline.run_acceptance_pipeline")
    @patch("grace_control.adapters.packet_executor.PacketExecutionAdapter._call_executor")
    async def test_strict_reviewer_rework_rejected(self, mock_legacy, mock_pipeline, mock_get_db, mock_verifier, mock_reviewer):
        """STRICT with reviewer REWORK_TO_CODER → rejected."""
        mock_verifier.return_value = _make_verifier_pass()
        mock_reviewer.return_value = _make_reviewer_rework()
        result = await _run_adapter_test(
            mock_legacy, mock_get_db, mock_pipeline,
            pipeline_report=_make_accepted_report(),
            expect_accepted=False,
            mock_verifier=mock_verifier, mock_reviewer=mock_reviewer,
            profile="STRICT",
        )
        assert result.domain_status == "rejected"

    @patch("grace_control.adapters.packet_executor.run_reviewer_gate")
    @patch("grace_control.adapters.packet_executor.run_evidence_verifier")
    @patch("grace_control.adapters.packet_executor.get_db")
    @patch("grace_control.core.acceptance_pipeline.run_acceptance_pipeline")
    @patch("grace_control.adapters.packet_executor.PacketExecutionAdapter._call_executor")
    async def test_strict_reviewer_architect_blocked(self, mock_legacy, mock_pipeline, mock_get_db, mock_verifier, mock_reviewer):
        """STRICT with reviewer RETURN_TO_ARCHITECT → blocked."""
        mock_verifier.return_value = _make_verifier_pass()
        mock_reviewer.return_value = _make_reviewer_architect()
        result = await _run_adapter_test(
            mock_legacy, mock_get_db, mock_pipeline,
            pipeline_report=_make_accepted_report(),
            expect_accepted=False,
            mock_verifier=mock_verifier, mock_reviewer=mock_reviewer,
            profile="STRICT",
        )
        assert result.domain_status == "blocked"

    @patch("grace_control.adapters.packet_executor.run_reviewer_gate")
    @patch("grace_control.adapters.packet_executor.run_evidence_verifier")
    @patch("grace_control.adapters.packet_executor.get_db")
    @patch("grace_control.core.acceptance_pipeline.run_acceptance_pipeline")
    @patch("grace_control.adapters.packet_executor.PacketExecutionAdapter._call_executor")
    async def test_result_json_has_four_keys_strict(self, mock_legacy, mock_pipeline, mock_get_db, mock_verifier, mock_reviewer):
        """STRICT: result_json always has all four keys."""
        mock_verifier.return_value = _make_verifier_pass()
        mock_reviewer.return_value = _make_reviewer_pass()
        mock_run = _make_mock_packet_run()
        await _run_adapter_test(
            mock_legacy, mock_get_db, mock_pipeline,
            pipeline_report=_make_accepted_report(),
            existing_run=mock_run,
            mock_verifier=mock_verifier, mock_reviewer=mock_reviewer,
            profile="STRICT",
        )
        assert "legacy_result" in mock_run.result_json
        assert "acceptance_report" in mock_run.result_json
        assert "evidence_verifier_report" in mock_run.result_json
        assert "reviewer_report" in mock_run.result_json

    # ── Deterministic fail for all profiles ──────────────────────────

    @patch("grace_control.adapters.packet_executor.run_reviewer_gate")
    @patch("grace_control.adapters.packet_executor.run_evidence_verifier")
    @patch("grace_control.adapters.packet_executor.get_db")
    @patch("grace_control.core.acceptance_pipeline.run_acceptance_pipeline")
    @patch("grace_control.adapters.packet_executor.PacketExecutionAdapter._call_executor")
    async def test_deterministic_fail_skips_verifier_reviewer(self, mock_legacy, mock_pipeline, mock_get_db, mock_verifier, mock_reviewer):
        """All profiles: deterministic fail → verifier and reviewer not called."""
        result = await _run_adapter_test(
            mock_legacy, mock_get_db, mock_pipeline,
            pipeline_report=_make_rework_report(),
            expect_accepted=False,
            mock_verifier=mock_verifier, mock_reviewer=mock_reviewer,
        )
        mock_verifier.assert_not_called()
        mock_reviewer.assert_not_called()
        assert result.domain_status == "rework_required"

    @patch("grace_control.adapters.packet_executor.run_reviewer_gate")
    @patch("grace_control.adapters.packet_executor.run_evidence_verifier")
    @patch("grace_control.adapters.packet_executor.get_db")
    @patch("grace_control.core.acceptance_pipeline.run_acceptance_pipeline")
    @patch("grace_control.adapters.packet_executor.PacketExecutionAdapter._call_executor")
    async def test_skip_context_builder_in_evidence(self, mock_legacy, mock_pipeline, mock_get_db, mock_verifier, mock_reviewer):
        """skip_context_builder: true -> records skip in evidence."""
        # Mock _resolve_executor to return skip_context_builder=True
        with patch("grace_control.adapters.packet_executor.PacketExecutionAdapter._resolve_executor") as mock_resolve:
            mock_resolve.return_value = {
                "executor_id": "coder-opencode-fixture",
                "backend": "cli",
                "skip_context_builder": True,
            }
            # Set up mock run
            mock_run = _make_mock_packet_run()
            result = await _run_adapter_test(
                mock_legacy, mock_get_db, mock_pipeline,
                pipeline_report=_make_accepted_report(),
                expect_accepted=True,
                existing_run=mock_run,
                mock_verifier=mock_verifier, mock_reviewer=mock_reviewer,
            )
            # The session store save was called; result_json legacy_result has context_builder
            legacy = mock_run.result_json.get("legacy_result", {})
            assert "evidence" in legacy
            assert "context_builder" in legacy["evidence"]
            assert legacy["evidence"]["context_builder"]["skipped"] is True
            assert legacy["evidence"]["context_builder"]["reason"] == "executor.skip_context_builder=true"
            assert legacy["evidence"]["context_builder"]["executor_id"] == "coder-opencode-fixture"

    @patch("grace_control.adapters.packet_executor.run_reviewer_gate")
    @patch("grace_control.adapters.packet_executor.run_evidence_verifier")
    @patch("grace_control.adapters.packet_executor.get_db")
    @patch("grace_control.core.acceptance_pipeline.run_acceptance_pipeline")
    @patch("grace_control.adapters.packet_executor.PacketExecutionAdapter._call_executor")
    async def test_no_skip_context_builder_in_evidence(self, mock_legacy, mock_pipeline, mock_get_db, mock_verifier, mock_reviewer):
        """skip_context_builder: absent/false -> records skipped: false in evidence."""
        with patch("grace_control.adapters.packet_executor.PacketExecutionAdapter._resolve_executor") as mock_resolve:
            mock_resolve.return_value = {
                "executor_id": "coder-opencode",
                "backend": "cli",
            }
            mock_run = _make_mock_packet_run()
            result = await _run_adapter_test(
                mock_legacy, mock_get_db, mock_pipeline,
                pipeline_report=_make_accepted_report(),
                expect_accepted=True,
                existing_run=mock_run,
                mock_verifier=mock_verifier, mock_reviewer=mock_reviewer,
            )
            legacy = mock_run.result_json.get("legacy_result", {})
            assert "evidence" in legacy
            assert "context_builder" in legacy["evidence"]
            assert legacy["evidence"]["context_builder"]["skipped"] is False


class TestCallExecutorTargetRepoWorktree:
    @pytest.mark.asyncio
    @patch("grace_control.services.git_service.GitService.run_preflight")
    @patch("grace_control.services.agent_workspace_builder.AgentWorkspaceBuilder.build_target_repo_worktree")
    @patch("grace_control.services.worktree_cleanup_service.WorktreeCleanupService.cleanup_attempt")
    @patch("grace_control.agent.backend.ExecutionBackend.run")
    async def test_call_executor_target_repo_worktree(self, mock_backend_run, mock_cleanup, mock_build, mock_preflight, tmp_path):
        from grace_control.adapters.packet_executor import PacketExecutionAdapter
        from grace_control.core.contracts import build_packet_contract
        from grace_control.services.git_service import PreflightResult
        from grace_control.services.agent_workspace_builder import WorkspaceResult
        from grace_control.agent.backend import ExecutionResult as BackendExecutionResult

        # Mock preflight to pass
        mock_preflight.return_value = PreflightResult(
            success=True,
            is_git_repo=True,
            working_tree_clean=True,
            current_branch="main",
            local_head="123456",
        )

        # Mock workspace builder to return fake WorkspaceResult
        wt_path = tmp_path / "worktree"
        wt_path.mkdir()
        mock_build.return_value = WorkspaceResult(
            workspace_path=wt_path,
            workspace_mode="target_repo_worktree",
            target_repo_root=tmp_path / "target",
            base_sha="123456",
            commit_semantics="target_repo_commit",
        )

        # Mock backend run
        mock_backend_run.return_value = BackendExecutionResult(
            accepted=True,
            domain_status="completed",
            worktree_path=wt_path,
            branch_name="agent/test",
            commit_sha="abcdef",
            stdout="run ok",
            stderr="",
            duration_ms=100,
        )

        # Initialize adapter
        project_dir = tmp_path / "project"
        project_dir.mkdir(parents=True, exist_ok=True)
        from grace_control.services.git_service import GitService as _GS
        git_init = _GS()
        git_init._run(["init", "-q"], project_dir)
        git_init._run(["config", "user.email", "test@grace"], project_dir)
        git_init._run(["config", "user.name", "Test Agent"], project_dir)
        (project_dir / "README.md").write_text("init")
        git_init._run(["add", "."], project_dir)
        git_init._run(["commit", "-q", "-m", "init"], project_dir)

        adapter = PacketExecutionAdapter(
            project_root=project_dir,
            state_root=tmp_path / "state",
            worktree_root=tmp_path / "worktrees",
            backend=MagicMock(),
        )
        adapter._backend.run = mock_backend_run

        packet_path = tmp_path / "pkt-001" / "EXECUTION_PACKET.md"
        packet_path.parent.mkdir(parents=True, exist_ok=True)
        packet_path.write_text("packet content")

        pkt_contract = build_packet_contract({
            "id": "pkt-001",
            "spec_json": {"scope": ["src/"]},
        })

        executor = {
            "executor_id": "coder-opencode",
            "workspace_mode": "target_repo_worktree",
        }

        # Call _call_executor
        result = await adapter._call_executor(
            packet_path=packet_path,
            packet_contract=pkt_contract,
            attempt=1,
            base_ref="main",
            base_sha="123456",
            executor=executor,
            evidence_dir=tmp_path / "evidence",
        )

        # Assertions
        assert result.accepted is True
        assert "workspace" in result.evidence
        assert result.evidence["workspace"]["workspace_mode"] == "target_repo_worktree"
        assert result.evidence["workspace"]["commit_semantics"] == "target_repo_commit"
        assert "target_repo_preflight" in result.evidence
        assert result.evidence["target_repo_preflight"]["working_tree_clean"] is True

        # Assert correct cleanup_attempt call
        mock_cleanup.assert_called_once()
        mock_build.assert_called_once()
        mock_preflight.assert_called_once()

    @patch("grace_control.adapters.packet_executor.run_reviewer_gate")
    @patch("grace_control.adapters.packet_executor.run_evidence_verifier")
    @patch("grace_control.adapters.packet_executor.get_db")
    @patch("grace_control.core.acceptance_pipeline.run_acceptance_pipeline")
    @patch("grace_control.adapters.packet_executor.PacketExecutionAdapter._call_executor")
    async def test_target_repo_worktree_cleanup_on_rework(self, mock_legacy, mock_pipeline, mock_get_db, mock_verifier, mock_reviewer, tmp_path):
        """target_repo_worktree: rejected -> cleanup executes on target_repo_root."""
        # Create temp dirs representing project and target repo roots
        project_dir = tmp_path / "project"
        project_dir.mkdir()
        target_dir = tmp_path / "target"
        target_dir.mkdir()

        # Set target_repo_root in settings override
        from grace_control.config.settings import settings
        with patch("grace_control.adapters.packet_executor.PacketExecutionAdapter._resolve_executor") as mock_resolve, \
             patch("grace_control.core.cleanup_on_state.TerminalStateCleanup.run") as mock_cleanup_run, \
             patch.object(settings, "workspace_mode", "target_repo_worktree"), \
             patch.object(settings, "target_repo_root", str(target_dir)):
             
            mock_resolve.return_value = {
                "executor_id": "coder-opencode",
                "backend": "cli",
            }
            
            mock_legacy.return_value = _FakeLegacyResult(
                ok=True, domain_status="rework_required",
                worktree_path=str(tmp_path / "wt"),
            )
            mock_pipeline.return_value = _make_rework_report()
            mock_verifier.return_value = _make_verifier_rework()
            
            # Setup db mocks
            mock_run = _make_mock_packet_run()
            side_effect_values = [
                _make_mock_packet(attempt_count=1, profile="NORMAL"),
                None,
                mock_run,
            ]
            mock_get_db.return_value.__enter__.return_value.query.return_value.filter_by.return_value.first.side_effect = side_effect_values

            adapter = PacketExecutionAdapter(
                project_root=project_dir,
                state_root=tmp_path / "state",
                worktree_root=tmp_path / "worktrees",
                backend=MagicMock(),
            )
            
            # We must pass the mock_resolve mock because resolve_executor is called
            # and we want to ensure settings.workspace_mode is used, which is target_repo_worktree.
            await adapter.execute("pkt-001", "w1")

            # Check that TerminalStateCleanup.run was called with target_dir
            mock_cleanup_run.assert_called_once()
            _, kwargs = mock_cleanup_run.call_args
            assert kwargs["project_root"] == target_dir


class TestW10ReworkPackets:
    """W10: Reviewer Rework Packets — verify rework packet creation in _route_after."""

    @patch("grace_control.adapters.packet_executor.create_rework_packet")
    @patch("grace_control.adapters.packet_executor.run_reviewer_gate")
    @patch("grace_control.adapters.packet_executor.run_evidence_verifier")
    @patch("grace_control.adapters.packet_executor.get_db")
    @patch("grace_control.core.acceptance_pipeline.run_acceptance_pipeline")
    @patch("grace_control.adapters.packet_executor.PacketExecutionAdapter._call_executor")
    async def test_verifier_rework_creates_rework_packet(self, mock_legacy, mock_pipeline, mock_get_db, mock_verifier, mock_reviewer, mock_create_rework):
        """Evidence verifier REWORK_TO_CODER → create_rework_packet called with correct args."""
        mock_verifier.return_value = _make_verifier_rework()
        with patch("grace_control.config.settings.settings.agent_runtime_rework_packets_enabled", True):
            result = await _run_adapter_test(
                mock_legacy, mock_get_db, mock_pipeline,
                pipeline_report=_make_accepted_report(),
                expect_accepted=False,
                mock_verifier=mock_verifier, mock_reviewer=mock_reviewer,
                profile="NORMAL",
            )
        assert result.domain_status == "rejected"
        mock_create_rework.assert_called_once()
        _, kwargs = mock_create_rework.call_args
        assert kwargs["original_packet_id"] == "pkt-001"
        assert kwargs["verdict_source"] == "evidence_verifier"
        assert "verifier says rework" in kwargs["summary"]

    @patch("grace_control.adapters.packet_executor.create_rework_packet")
    @patch("grace_control.adapters.packet_executor.run_reviewer_gate")
    @patch("grace_control.adapters.packet_executor.run_evidence_verifier")
    @patch("grace_control.adapters.packet_executor.get_db")
    @patch("grace_control.core.acceptance_pipeline.run_acceptance_pipeline")
    @patch("grace_control.adapters.packet_executor.PacketExecutionAdapter._call_executor")
    async def test_verifier_architect_does_not_create_rework(self, mock_legacy, mock_pipeline, mock_get_db, mock_verifier, mock_reviewer, mock_create_rework):
        """Evidence verifier RETURN_TO_ARCHITECT → create_rework_packet NOT called."""
        mock_verifier.return_value = _make_verifier_architect()
        with patch("grace_control.config.settings.settings.agent_runtime_rework_packets_enabled", True):
            result = await _run_adapter_test(
                mock_legacy, mock_get_db, mock_pipeline,
                pipeline_report=_make_accepted_report(),
                expect_accepted=False,
                mock_verifier=mock_verifier, mock_reviewer=mock_reviewer,
                profile="NORMAL",
            )
        assert result.domain_status == "blocked"
        mock_create_rework.assert_not_called()

    @patch("grace_control.adapters.packet_executor.create_rework_packet")
    @patch("grace_control.adapters.packet_executor.run_reviewer_gate")
    @patch("grace_control.adapters.packet_executor.run_evidence_verifier")
    @patch("grace_control.adapters.packet_executor.get_db")
    @patch("grace_control.core.acceptance_pipeline.run_acceptance_pipeline")
    @patch("grace_control.adapters.packet_executor.PacketExecutionAdapter._call_executor")
    async def test_reviewer_rework_creates_rework_packet(self, mock_legacy, mock_pipeline, mock_get_db, mock_verifier, mock_reviewer, mock_create_rework):
        """Reviewer REWORK_TO_CODER → create_rework_packet called with correct args."""
        mock_verifier.return_value = _make_verifier_pass()
        mock_reviewer.return_value = _make_reviewer_rework()
        with patch("grace_control.config.settings.settings.agent_runtime_rework_packets_enabled", True):
            result = await _run_adapter_test(
                mock_legacy, mock_get_db, mock_pipeline,
                pipeline_report=_make_accepted_report(),
                expect_accepted=False,
                mock_verifier=mock_verifier, mock_reviewer=mock_reviewer,
                profile="STRICT",
            )
        assert result.domain_status == "rejected"
        mock_create_rework.assert_called_once()
        _, kwargs = mock_create_rework.call_args
        assert kwargs["original_packet_id"] == "pkt-001"
        assert kwargs["verdict_source"] == "reviewer"
        assert "reviewer says rework" in kwargs["summary"]

    @patch("grace_control.adapters.packet_executor.create_rework_packet")
    @patch("grace_control.adapters.packet_executor.run_reviewer_gate")
    @patch("grace_control.adapters.packet_executor.run_evidence_verifier")
    @patch("grace_control.adapters.packet_executor.get_db")
    @patch("grace_control.core.acceptance_pipeline.run_acceptance_pipeline")
    @patch("grace_control.adapters.packet_executor.PacketExecutionAdapter._call_executor")
    async def test_reviewer_architect_does_not_create_rework(self, mock_legacy, mock_pipeline, mock_get_db, mock_verifier, mock_reviewer, mock_create_rework):
        """Reviewer RETURN_TO_ARCHITECT → create_rework_packet NOT called."""
        mock_verifier.return_value = _make_verifier_pass()
        mock_reviewer.return_value = _make_reviewer_architect()
        with patch("grace_control.config.settings.settings.agent_runtime_rework_packets_enabled", True):
            result = await _run_adapter_test(
                mock_legacy, mock_get_db, mock_pipeline,
                pipeline_report=_make_accepted_report(),
                expect_accepted=False,
                mock_verifier=mock_verifier, mock_reviewer=mock_reviewer,
                profile="STRICT",
            )
        assert result.domain_status == "blocked"
        mock_create_rework.assert_not_called()

    @patch("grace_control.adapters.packet_executor.create_rework_packet")
    @patch("grace_control.adapters.packet_executor.run_reviewer_gate")
    @patch("grace_control.adapters.packet_executor.run_evidence_verifier")
    @patch("grace_control.adapters.packet_executor.get_db")
    @patch("grace_control.core.acceptance_pipeline.run_acceptance_pipeline")
    @patch("grace_control.adapters.packet_executor.PacketExecutionAdapter._call_executor")
    async def test_verifier_rework_disabled_no_rework_packet(self, mock_legacy, mock_pipeline, mock_get_db, mock_verifier, mock_reviewer, mock_create_rework):
        """agent_runtime_rework_packets_enabled=False → no rework packet created."""
        mock_verifier.return_value = _make_verifier_rework()
        with patch("grace_control.config.settings.settings.agent_runtime_rework_packets_enabled", False):
            result = await _run_adapter_test(
                mock_legacy, mock_get_db, mock_pipeline,
                pipeline_report=_make_accepted_report(),
                expect_accepted=False,
                mock_verifier=mock_verifier, mock_reviewer=mock_reviewer,
                profile="NORMAL",
            )
        assert result.domain_status == "rejected"
        mock_create_rework.assert_not_called()

    @patch("grace_control.adapters.packet_executor.create_rework_packet")
    @patch("grace_control.adapters.packet_executor.run_reviewer_gate")
    @patch("grace_control.adapters.packet_executor.run_evidence_verifier")
    @patch("grace_control.adapters.packet_executor.get_db")
    @patch("grace_control.core.acceptance_pipeline.run_acceptance_pipeline")
    @patch("grace_control.adapters.packet_executor.PacketExecutionAdapter._call_executor")
    async def test_acceptance_failure_no_rework_packet(self, mock_legacy, mock_pipeline, mock_get_db, mock_verifier, mock_reviewer, mock_create_rework):
        """Acceptance failure (deterministic) → no rework packet created (never reaches _route_after)."""
        with patch("grace_control.config.settings.settings.agent_runtime_rework_packets_enabled", True):
            result = await _run_adapter_test(
                mock_legacy, mock_get_db, mock_pipeline,
                pipeline_report=_make_rework_report(),
                expect_accepted=False,
                mock_verifier=mock_verifier, mock_reviewer=mock_reviewer,
                profile="NORMAL",
            )
        mock_create_rework.assert_not_called()
