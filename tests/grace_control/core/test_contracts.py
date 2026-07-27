"""Tests for acceptance pipeline contracts."""

import pytest
from grace_control.core.contracts import (
    AcceptanceProfile,
    AcceptanceReport,
    CommandResult,
    ExecutionPacketContract,
    FinalVerdict,
    PacketVerdict,
    ScopeViolation,
    StageName,
    StageResult,
    StageStatus,
    build_packet_contract,
    validate_acceptance_report,
    validate_packet_contract,
    validate_stage_result,
)


class TestCommandResult:
    def test_passed_true_for_zero_exit(self):
        cr = CommandResult(command="echo", cwd="/tmp", exit_code=0)
        assert cr.passed is True

    def test_passed_false_for_nonzero(self):
        cr = CommandResult(command="false", cwd="/tmp", exit_code=1)
        assert cr.passed is False

    def test_passed_false_for_127(self):
        cr = CommandResult(command="nonexist", cwd="/tmp", exit_code=127)
        assert cr.passed is False


class TestAcceptanceReport:
    def test_is_accepted_true_for_accepted(self):
        r = AcceptanceReport(packet_id="p1", final_verdict=FinalVerdict.ACCEPTED, profile=AcceptanceProfile.NORMAL, stages=[])
        assert r.is_accepted is True

    def test_is_accepted_false_for_rework(self):
        r = AcceptanceReport(packet_id="p1", final_verdict=FinalVerdict.REWORK_REQUIRED, profile=AcceptanceProfile.NORMAL, stages=[])
        assert r.is_accepted is False

    def test_is_accepted_false_for_blocked(self):
        r = AcceptanceReport(packet_id="p1", final_verdict=FinalVerdict.BLOCKED, profile=AcceptanceProfile.NORMAL, stages=[])
        assert r.is_accepted is False

    def test_to_dict_serializes(self):
        r = AcceptanceReport(packet_id="p1", final_verdict=FinalVerdict.ACCEPTED,
                            profile=AcceptanceProfile.NORMAL, stages=[], summary="ok")
        d = r.to_dict()
        assert d["packet_id"] == "p1"
        assert d["final_verdict"] == "accepted"
        assert d["summary"] == "ok"


class TestPacketContract:
    def test_semantic_review_contract_survives_compilation(self):
        packet = build_packet_contract({
            "id": "p1",
            "title": "Semantic review",
            "acceptance_profile": "NORMAL",
            "spec_json": {
                "scope": ["docs/requirements.md"],
                "verification": {"t0": [], "t1": ["true"], "t2": []},
                "acceptance_criteria": ["Every requirement is mapped."],
                "coder_instructions": ["Keep open decisions open."],
                "blocking_issues": ["Remove invented evidence."],
                "rework_summary": "Documentation remains incomplete.",
            },
        })

        assert packet.metadata["acceptance_criteria"] == [
            "Every requirement is mapped."
        ]
        assert packet.metadata["coder_instructions"] == [
            "Keep open decisions open."
        ]
        assert packet.metadata["blocking_issues"] == [
            "Remove invented evidence."
        ]
        assert packet.metadata["rework_summary"] == "Documentation remains incomplete."

    def test_coder_evidence_patterns_extend_effective_write_scope(self):
        packet = build_packet_contract({
            "id": "p1",
            "title": "Evidence scope",
            "acceptance_profile": "NORMAL",
            "spec_json": {
                "scope": ["docs/requirements.md"],
                "verification": {"t0": [], "t1": ["true"], "t2": []},
                "expected_evidence": [{
                    "id": "EV-VERIFY",
                    "kind": "test",
                    "stage": "t1",
                    "owner": "coder",
                    "producer": "cli",
                    "artifact_patterns": ["verification-output/W00*.log"],
                }],
            },
        })

        assert packet.allowed_write_scope == [
            "docs/requirements.md",
            "verification-output/W00*.log",
        ]

    def test_valid_normal(self):
        p = ExecutionPacketContract(packet_id="p1", title="t",
            allowed_write_scope=["src/"], frozen_scope=["legacy/"],
            acceptance_profile=AcceptanceProfile.NORMAL,
            verification={"t1": [["pytest"]]})
        assert validate_packet_contract(p) == []

    def test_valid_fast_without_commands(self):
        p = ExecutionPacketContract(packet_id="p1", title="t",
            allowed_write_scope=["src/"], frozen_scope=["legacy/"],
            acceptance_profile=AcceptanceProfile.FAST,
            verification={})
        assert validate_packet_contract(p) == []

    def test_empty_packet_id(self):
        p = ExecutionPacketContract(packet_id="", title="t",
            allowed_write_scope=["src/"], frozen_scope=["legacy/"],
            acceptance_profile=AcceptanceProfile.FAST)
        assert "packet_id is empty" in validate_packet_contract(p)

    def test_empty_scope(self):
        p = ExecutionPacketContract(packet_id="p1", title="t",
            allowed_write_scope=[], frozen_scope=[],
            acceptance_profile=AcceptanceProfile.FAST)
        assert "allowed_write_scope is empty" in validate_packet_contract(p)

    def test_absolute_path_in_scope(self):
        p = ExecutionPacketContract(packet_id="p1", title="t",
            allowed_write_scope=["/absolute/path"], frozen_scope=[],
            acceptance_profile=AcceptanceProfile.FAST)
        assert "path invalid" in " ".join(validate_packet_contract(p))

    def test_parent_traversal_in_scope(self):
        p = ExecutionPacketContract(packet_id="p1", title="t",
            allowed_write_scope=["../secret.py"], frozen_scope=[],
            acceptance_profile=AcceptanceProfile.FAST)
        assert "path invalid" in " ".join(validate_packet_contract(p))

    def test_normal_allows_gate_resolver_verification_defaults(self):
        p = ExecutionPacketContract(packet_id="p1", title="t",
            allowed_write_scope=["src/"], frozen_scope=[],
            acceptance_profile=AcceptanceProfile.NORMAL,
            verification={})
        assert validate_packet_contract(p) == []

    def test_strict_allows_gate_resolver_verification_defaults(self):
        p = ExecutionPacketContract(packet_id="p1", title="t",
            allowed_write_scope=["src/"], frozen_scope=[],
            acceptance_profile=AcceptanceProfile.STRICT,
            verification={})
        assert validate_packet_contract(p) == []


class TestStageResult:
    def test_failed_requires_issue(self):
        errs = validate_stage_result(StageResult(
            name=StageName.T0_SCOPE_AND_LINT, status=StageStatus.FAILED, summary=""))
        assert len(errs) >= 1

    def test_failed_with_blocking_issue_passes(self):
        errs = validate_stage_result(StageResult(
            name=StageName.T0_SCOPE_AND_LINT, status=StageStatus.FAILED, summary="",
            blocking_issues=["reason"]))
        assert errs == []

    def test_failed_with_failed_command_passes(self):
        errs = validate_stage_result(StageResult(
            name=StageName.T0_SCOPE_AND_LINT, status=StageStatus.FAILED, summary="",
            commands=[CommandResult(command="x", cwd="/", exit_code=1)]))
        assert errs == []

    def test_skipped_requires_reason(self):
        errs = validate_stage_result(StageResult(
            name=StageName.T1_TARGETED_TESTS, status=StageStatus.SKIPPED, summary=""))
        assert len(errs) >= 1

    def test_skipped_with_reason_passes(self):
        errs = validate_stage_result(StageResult(
            name=StageName.T1_TARGETED_TESTS, status=StageStatus.SKIPPED, summary="",
            skipped_reason="FAST profile"))
        assert errs == []

    def test_passed_with_blocking_issues_fails(self):
        errs = validate_stage_result(StageResult(
            name=StageName.T0_SCOPE_AND_LINT, status=StageStatus.PASSED, summary="",
            blocking_issues=["should not be here"]))
        assert len(errs) >= 1


class TestAcceptanceReportValidation:
    def test_accepted_requires_no_violations(self):
        r = AcceptanceReport(packet_id="p1", final_verdict=FinalVerdict.ACCEPTED,
                            profile=AcceptanceProfile.NORMAL, stages=[],
                            scope_violations=["x: out of scope"])
        assert "must not have scope violations" in " ".join(validate_acceptance_report(r))

    def test_non_accepted_requires_summary(self):
        r = AcceptanceReport(packet_id="p1", final_verdict=FinalVerdict.REWORK_REQUIRED,
                            profile=AcceptanceProfile.NORMAL, stages=[], summary="")
        assert "must have summary" in " ".join(validate_acceptance_report(r))

    def test_accepted_report_with_summary_passes(self):
        r = AcceptanceReport(packet_id="p1", final_verdict=FinalVerdict.REWORK_REQUIRED,
                            profile=AcceptanceProfile.NORMAL, stages=[], summary="T0 failed")
        assert "must have summary" not in " ".join(validate_acceptance_report(r))
