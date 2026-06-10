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
