"""Tests for evidence collector."""

from grace_control.core.contracts import (
    AcceptanceProfile,
    CommandResult,
    StageName,
    StageResult,
    StageStatus,
)
from grace_control.core.evidence import EvidenceCollector


class TestEvidenceCollector:
    def _collector(self):
        return EvidenceCollector()

    def test_collect_from_passed_stage(self):
        ec = self._collector()
        stage = StageResult(name=StageName.T1_TARGETED_TESTS, status=StageStatus.PASSED,
                           summary="ok",
                           commands=[CommandResult(command=["pytest"], cwd="/", exit_code=0)])
        evidence = ec.collect_from_stage(stage)
        assert "command:pytest" in evidence
        assert "exit_code:0" in evidence

    def test_collect_from_failed_stage(self):
        ec = self._collector()
        stage = StageResult(name=StageName.T1_TARGETED_TESTS, status=StageStatus.FAILED,
                           summary="fail",
                           commands=[CommandResult(command=["pytest"], cwd="/", exit_code=1)],
                           blocking_issues=["reason"])
        evidence = ec.collect_from_stage(stage)
        assert "exit_code:1" in evidence

    def test_normal_requires_passed_evidence(self):
        ec = self._collector()
        assert ec.has_required_evidence(
            expected_evidence=["tests passed"],
            collected_evidence=["exit_code:0"],
            acceptance_profile=AcceptanceProfile.NORMAL,
        ) is True

    def test_normal_no_passed_fails(self):
        ec = self._collector()
        assert ec.has_required_evidence(
            expected_evidence=["tests passed"],
            collected_evidence=["exit_code:1"],
            acceptance_profile=AcceptanceProfile.NORMAL,
        ) is False

    def test_fast_always_true(self):
        ec = self._collector()
        assert ec.has_required_evidence(
            expected_evidence=[],
            collected_evidence=[],
            acceptance_profile=AcceptanceProfile.FAST,
        ) is True

    def test_no_expected_evidence_fails_normal(self):
        ec = self._collector()
        assert ec.has_required_evidence(
            expected_evidence=[],
            collected_evidence=["exit_code:0"],
            acceptance_profile=AcceptanceProfile.NORMAL,
        ) is False

    def test_failed_command_evidence_does_not_satisfy(self):
        ec = self._collector()
        assert ec.has_required_evidence(
            expected_evidence=["tests"],
            collected_evidence=["exit_code:1"],
            acceptance_profile=AcceptanceProfile.NORMAL,
        ) is False
