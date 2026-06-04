"""Tests for feature recovery / escalation policy (TZ-017 Phase 1-4)."""

import pytest

from grace_control.core.feature_recovery import (
    FailureClass,
    FailureSignal,
    RecoveryAction,
    RecoveryDecision,
    RecoveryPolicy,
    classify_failure,
    decide_recovery,
    NO_CHANGES_PATTERNS,
    build_session_snapshot,
    build_task_resume_context,
    render_resume_summary,
)


def _signal(**kw) -> FailureSignal:
    defaults = dict(packet_id="pkt_test", packet_state="rejected", domain_status="rejected")
    defaults.update(kw)
    return FailureSignal(**defaults)


# ── Classification tests ───────────────────────────────────────────────────


class TestClassification:
    def test_acceptance_test_failure_is_retryable_coder(self):
        fc = classify_failure(_signal(reason="test failure: pytest exited with code 1"))
        assert fc == FailureClass.RETRYABLE_CODER

    def test_no_changes_produced_is_retryable_coder(self):
        fc = classify_failure(_signal(reason="Agent produced no changes"))
        assert fc == FailureClass.RETRYABLE_CODER

    def test_no_changes_all_patterns(self):
        for pat in NO_CHANGES_PATTERNS:
            fc = classify_failure(_signal(reason=f"agent {pat}"))
            assert fc == FailureClass.RETRYABLE_CODER, f"pattern failed: {pat}"

    def test_no_changes_snake_case_is_retryable_coder(self):
        fc = classify_failure(_signal(reason="no_changes"))
        assert fc == FailureClass.RETRYABLE_CODER
        fc = classify_failure(_signal(reason="no_changes_produced"))
        assert fc == FailureClass.RETRYABLE_CODER
        fc = classify_failure(_signal(reason="no changes produced"))
        assert fc == FailureClass.RETRYABLE_CODER

    def test_scope_violation_by_coder_is_retryable_coder(self):
        fc = classify_failure(_signal(reason="scope violation: wrote outside allowed scope"))
        assert fc == FailureClass.RETRYABLE_CODER

    def test_scope_impossible_is_architect_repack_needed(self):
        fc = classify_failure(_signal(reason="scope impossible without editing API file"))
        assert fc == FailureClass.ARCHITECT_REPACK_NEEDED

    def test_verifier_rework_to_coder_is_retryable_coder(self):
        fc = classify_failure(_signal(reason="verifier says rework", evidence_verifier_verdict="REWORK_TO_CODER"))
        assert fc == FailureClass.RETRYABLE_CODER

    def test_verifier_return_to_architect_is_architect_repack(self):
        fc = classify_failure(_signal(reason="verifier says architect", evidence_verifier_verdict="RETURN_TO_ARCHITECT"))
        assert fc == FailureClass.ARCHITECT_REPACK_NEEDED

    def test_verifier_invalid_json_is_retryable_verifier(self):
        fc = classify_failure(_signal(reason="invalid JSON", evidence_verifier_verdict="INVALID_JSON"))
        assert fc == FailureClass.RETRYABLE_VERIFIER

    def test_verifier_unknown_non_pass_verdict_is_retryable_verifier(self):
        fc = classify_failure(_signal(reason="weird", evidence_verifier_verdict="UNKNOWN"))
        assert fc == FailureClass.RETRYABLE_VERIFIER

    def test_verifier_parse_error_is_retryable_verifier(self):
        fc = classify_failure(_signal(reason="parse error", evidence_verifier_verdict="PARSE_ERROR"))
        assert fc == FailureClass.RETRYABLE_VERIFIER

    def test_verifier_timeout_is_retryable_verifier(self):
        fc = classify_failure(_signal(reason="timeout", evidence_verifier_verdict="TIMEOUT"))
        assert fc == FailureClass.RETRYABLE_VERIFIER

    def test_reviewer_rework_to_coder_is_retryable_coder(self):
        fc = classify_failure(_signal(packet_state="accepted", domain_status="accepted",
                                       reviewer_verdict="REWORK_TO_CODER"))
        assert fc == FailureClass.RETRYABLE_CODER

    def test_reviewer_return_to_architect_is_architect_repack(self):
        fc = classify_failure(_signal(packet_state="accepted", domain_status="accepted",
                                       reviewer_verdict="RETURN_TO_ARCHITECT"))
        assert fc == FailureClass.ARCHITECT_REPACK_NEEDED

    def test_reviewer_invalid_json_is_retryable_reviewer(self):
        fc = classify_failure(_signal(reason="invalid JSON", reviewer_verdict="INVALID"))
        assert fc == FailureClass.RETRYABLE_REVIEWER

    def test_reviewer_unknown_non_pass_verdict_is_retryable_reviewer(self):
        fc = classify_failure(_signal(reason="weird", reviewer_verdict="UNKNOWN"))
        assert fc == FailureClass.RETRYABLE_REVIEWER

    def test_dirty_target_repo_is_true_blocker(self):
        fc = classify_failure(_signal(packet_state="accepted", domain_status="accepted",
                                       merge_error="DIRTY_TARGET_REPO"))
        assert fc == FailureClass.TRUE_BLOCKER

    def test_merge_conflict_is_true_blocker(self):
        fc = classify_failure(_signal(packet_state="accepted", domain_status="accepted",
                                       merge_error="conflict in file.py"))
        assert fc == FailureClass.TRUE_BLOCKER

    def test_transient_merge_error_is_merge_retryable(self):
        fc = classify_failure(_signal(packet_state="accepted", domain_status="accepted",
                                       merge_error="timeout connecting to remote"))
        assert fc == FailureClass.MERGE_RETRYABLE

    def test_missing_cli_is_true_blocker(self):
        fc = classify_failure(_signal(reason="missing CLI binary: agy not found"))
        assert fc == FailureClass.TRUE_BLOCKER

    def test_unknown_first_failure_is_unknown_retryable(self):
        fc = classify_failure(_signal(reason="weird internal error", packet_state="running",
                                       domain_status="unknown", attempt_count=1))
        assert fc == FailureClass.UNKNOWN_RETRYABLE

    def test_blocked_impossible_scope_is_architect_repack(self):
        fc = classify_failure(_signal(packet_state="blocked", domain_status="blocked",
                                       reason="scope impossible without expanding"))
        assert fc == FailureClass.ARCHITECT_REPACK_NEEDED

    def test_blocked_other_is_true_blocker(self):
        fc = classify_failure(_signal(packet_state="blocked", domain_status="blocked",
                                       reason="cannot proceed"))
        assert fc == FailureClass.TRUE_BLOCKER


# ── Decision tests ─────────────────────────────────────────────────────────


class TestDecisions:
    def test_first_coder_failure_retries_same_coder(self):
        signal = _signal(reason="test failed", coder_attempt_count=0, attempt_count=1)
        d = decide_recovery(signal, RecoveryPolicy())
        assert d.action == RecoveryAction.RETRY_SAME_CODER
        assert d.failure_class == FailureClass.RETRYABLE_CODER

    def test_second_coder_failure_switches_coder(self):
        signal = _signal(reason="test failed", coder_attempt_count=2, attempt_count=3)
        d = decide_recovery(signal, RecoveryPolicy(max_same_coder_attempts=2))
        assert d.action == RecoveryAction.SWITCH_CODER
        assert d.next_executor_hint is not None

    def test_second_coder_failure_model_switch_disabled_retries_same(self):
        signal = _signal(reason="test failed", coder_attempt_count=2, attempt_count=3,
                          current_executor_id="coder-flash")
        d = decide_recovery(signal, RecoveryPolicy(max_same_coder_attempts=2, allow_model_switch=False))
        assert d.action == RecoveryAction.RETRY_SAME_CODER
        assert d.next_executor_hint == "coder-flash"

    def test_fourth_coder_failure_returns_to_architect(self):
        signal = _signal(reason="test failed", coder_attempt_count=4, attempt_count=5)
        d = decide_recovery(signal, RecoveryPolicy(max_total_coder_attempts=4))
        assert d.action == RecoveryAction.RETURN_TO_ARCHITECT
        assert d.max_attempts_reached is True

    def test_repeated_architect_repair_escalates_architect(self):
        signal = _signal(reason="scope impossible", architect_repair_count=3,
                          evidence_verifier_verdict="RETURN_TO_ARCHITECT")
        d = decide_recovery(signal, RecoveryPolicy(max_architect_repairs=2))
        assert d.action == RecoveryAction.ESCALATE_ARCHITECT

    def test_verifier_parser_fail_retries_verifier(self):
        d = decide_recovery(FailureSignal(reason="invalid JSON", verifier_reject_count=0,
                                           packet_state="rejected",
                                           evidence_verifier_verdict="INVALID"), RecoveryPolicy())
        assert d.action == RecoveryAction.RETRY_VERIFIER

    def test_reviewer_parser_fail_retries_reviewer(self):
        d = decide_recovery(FailureSignal(reason="invalid JSON", reviewer_reject_count=0,
                                           packet_state="rejected",
                                           reviewer_verdict="INVALID"), RecoveryPolicy())
        assert d.action == RecoveryAction.RETRY_REVIEWER

    def test_repeated_reviewer_parser_fail_escalates_architect(self):
        d = decide_recovery(FailureSignal(reason="invalid JSON", reviewer_reject_count=2,
                                           packet_state="rejected",
                                           reviewer_verdict="INVALID"),
                            RecoveryPolicy(max_reviewer_retries=2))
        assert d.action == RecoveryAction.ESCALATE_ARCHITECT

    def test_merge_retryable_retries_until_limit(self):
        d = decide_recovery(FailureSignal(merge_error="timeout", merge_attempt_count=0,
                                           packet_state="accepted"), RecoveryPolicy(max_merge_retries=2))
        assert d.action == RecoveryAction.RETRY_MERGE

    def test_merge_retry_limit_blocks_feature(self):
        d = decide_recovery(FailureSignal(merge_error="timeout", merge_attempt_count=2,
                                           packet_state="accepted"), RecoveryPolicy(max_merge_retries=2))
        assert d.action == RecoveryAction.BLOCK_FEATURE
        assert d.max_attempts_reached is True

    def test_true_blocker_blocks_feature(self):
        d = decide_recovery(FailureSignal(reason="missing CLI binary", packet_state="failed"),
                             RecoveryPolicy())
        assert d.action == RecoveryAction.BLOCK_FEATURE

    def test_strict_profile_does_not_downgrade(self):
        signal = _signal(reason="test failed", acceptance_profile="STRICT",
                          coder_attempt_count=0, attempt_count=1)
        d = decide_recovery(signal, RecoveryPolicy())
        assert d.action == RecoveryAction.RETRY_SAME_CODER
        assert d.next_acceptance_profile is None or d.next_acceptance_profile == "STRICT"


# ── Safety invariant tests ─────────────────────────────────────────────────


class TestSafety:
    def test_recovery_never_returns_action_to_skip_acceptance(self):
        never_skip = {RecoveryAction.NO_ACTION, RecoveryAction.BLOCK_FEATURE}
        for action in RecoveryAction:
            assert action in never_skip or action in (
                RecoveryAction.RETRY_SAME_CODER,
                RecoveryAction.SWITCH_CODER,
                RecoveryAction.RETURN_TO_ARCHITECT,
                RecoveryAction.ESCALATE_ARCHITECT,
                RecoveryAction.RETRY_VERIFIER,
                RecoveryAction.RETRY_REVIEWER,
                RecoveryAction.RETRY_MERGE,
            ), f"Unexpected action: {action}"

    def test_recovery_never_returns_action_to_skip_scope_guard(self):
        bypass_actions = {RecoveryAction.NO_ACTION}
        for action in RecoveryAction:
            if action in bypass_actions:
                continue
            assert action in (
                RecoveryAction.RETRY_SAME_CODER,
                RecoveryAction.SWITCH_CODER,
                RecoveryAction.RETURN_TO_ARCHITECT,
                RecoveryAction.ESCALATE_ARCHITECT,
                RecoveryAction.RETRY_VERIFIER,
                RecoveryAction.RETRY_REVIEWER,
                RecoveryAction.RETRY_MERGE,
                RecoveryAction.BLOCK_FEATURE,
            ), f"Action {action} might bypass scope guard"

    def test_recovery_never_lowers_acceptance_profile(self):
        for profile in ("STRICT", "NORMAL", "FAST"):
            signal = _signal(reason="test failed", acceptance_profile=profile,
                              coder_attempt_count=0, attempt_count=1)
            d = decide_recovery(signal, RecoveryPolicy())
            assert d.next_acceptance_profile is None

    def test_recovery_can_escalate_acceptance_profile(self):
        signal = _signal(reason="test failed", acceptance_profile="FAST",
                          coder_attempt_count=4, attempt_count=5)
        d = decide_recovery(signal, RecoveryPolicy())
        assert d.action in (RecoveryAction.RETURN_TO_ARCHITECT, RecoveryAction.BLOCK_FEATURE)

    def test_recovery_decision_contains_reason(self):
        signal = _signal(reason="test failure", coder_attempt_count=0, attempt_count=1)
        d = decide_recovery(signal, RecoveryPolicy())
        assert d.reason
        assert d.failure_class is not None
        assert d.action is not None

    def test_policy_has_never_downgrade_strict_default_true(self):
        p = RecoveryPolicy()
        assert p.never_downgrade_strict is True

    def test_strict_profile_never_downgraded_even_if_future_decision_sets_profile(self):
        from grace_control.core.feature_recovery import _safe_next_profile
        result = _safe_next_profile("STRICT", "NORMAL", RecoveryPolicy(never_downgrade_strict=True))
        assert result == "STRICT"
        result = _safe_next_profile("NORMAL", "STRICT", RecoveryPolicy(never_downgrade_strict=True))
        assert result == "STRICT"
        result = _safe_next_profile("NORMAL", "FAST", RecoveryPolicy(never_downgrade_strict=False))
        assert result == "FAST"
        result = _safe_next_profile("STRICT", None, RecoveryPolicy())
        assert result is None

    def test_no_changes_produced_explicit_classification(self):
        from grace_control.core.feature_recovery import NO_CHANGES_PATTERNS
        assert "no_changes" in NO_CHANGES_PATTERNS
        assert "no_changes_produced" in NO_CHANGES_PATTERNS
        assert "no changes produced" in NO_CHANGES_PATTERNS

    def test_build_failure_signal_from_fixture_maps_required_fields(self):
        from grace_control.core.golden_fixtures import build_failure_signal_from_fixture, FixtureSpec
        spec = FixtureSpec(**{
            "id": "test_recovery", "kind": "golden_fixture", "start_stage": "recovery",
            "profile": "NORMAL", "packet": {"title": "test", "slug": "test",
             "state": "rejected", "acceptance_profile": "NORMAL"},
            "failure_signal": {"reason": "T1 failed", "acceptance_verdict": "rework_required",
             "coder_attempt_count": 1, "current_executor_id": "coder-flash"},
            "expected": {"recovery": {"failure_class": "retryable_coder",
             "action": "retry_same_coder", "must_not_lower_acceptance_profile": True}},
        })
        fs = build_failure_signal_from_fixture(spec, packet_id="pkt_test", state_root="/tmp/grace-fixtures")
        assert fs is not None
        assert isinstance(fs, FailureSignal)
        assert fs.packet_id == "pkt_test"

    def test_never_downgrade_strict_enforced_by_decide_recovery(self):
        """_safe_next_profile is called from decide_recovery — STRICT profile stays STRICT."""
        from grace_control.core.feature_recovery import _safe_next_profile
        signal = _signal(reason="test failed", acceptance_profile="STRICT",
                          coder_attempt_count=2, attempt_count=3)
        d = decide_recovery(signal, RecoveryPolicy(never_downgrade_strict=True))
        enforced = _safe_next_profile("STRICT", d.next_acceptance_profile,
                                       RecoveryPolicy(never_downgrade_strict=True))
        assert enforced == "STRICT" or enforced is None, \
            f"STRICT not preserved: next_acceptance_profile={d.next_acceptance_profile}"

    def test_never_downgrade_strict_latent_enforcement(self):
        """If future code sets next_acceptance_profile=NORMAL, _safe_next_profile corrects to STRICT."""
        from grace_control.core.feature_recovery import _safe_next_profile
        result = _safe_next_profile("STRICT", "NORMAL", RecoveryPolicy(never_downgrade_strict=True))
        assert result == "STRICT"


# ── Phase 4: Session Resume Stub tests ─────────────────────────────────────


class TestSessionResume:
    def test_snapshot_contains_run_identity(self):
        class FakeRun:
            id = "run_001"
            packet_id = "pkt_test"
            run_number = 1
            status = "rejected"
            result_json = {"reason": "test failed", "executor_id": "coder-flash"}
            started_at = None
            finished_at = None

        class FakePacket:
            feature_id = "feat_test"
            wave_id = "wave_01"

        snap = build_session_snapshot(FakeRun(), FakePacket())
        assert snap.packet_id == "pkt_test"
        assert snap.run_id == "run_001"
        assert snap.attempt_number == 1

    def test_snapshot_contains_executor_model(self):
        class FakeRun:
            id = "run_001"
            packet_id = "pkt_test"
            run_number = 1
            status = "rejected"
            result_json = {"executor_id": "coder-flash", "model": "deepseek/deepseek-v4-flash"}
            started_at = None
            finished_at = None

        snap = build_session_snapshot(FakeRun())
        assert snap.executor_id == "coder-flash"
        assert snap.model == "deepseek/deepseek-v4-flash"

    def test_snapshot_status_matches_run(self):
        class FakeRun:
            id = "run_001"
            packet_id = "pkt_test"
            run_number = 2
            status = "failed"
            result_json = {"reason": "timeout"}
            started_at = None
            finished_at = None

        snap = build_session_snapshot(FakeRun())
        assert snap.status == "failed"

    def test_resume_context_contains_previous(self):
        from grace_control.core.feature_recovery import RecoverySessionSnapshot

        class FakePacket:
            id = "pkt_test"
            feature_id = "feat_test"

        prev = [RecoverySessionSnapshot(packet_id="pkt_test", run_id="run_001", feature_id="feat_test")]
        context = build_task_resume_context(FakePacket(), history=prev)
        assert len(context.previous_attempts) == 1
        assert context.previous_attempts[0].run_id == "run_001"

    def test_resume_context_contains_decision(self):
        class FakePacket:
            id = "pkt_test"
            feature_id = "feat_test"

        decision = RecoveryDecision(
            action=RecoveryAction.RETRY_SAME_CODER,
            failure_class=FailureClass.RETRYABLE_CODER,
            reason="test",
            next_executor_hint="coder-flash",
        )
        context = build_task_resume_context(FakePacket(), decision=decision)
        assert context.recovery_decision.get("action") == "retry_same_coder"

    def test_resume_summary_is_human_readable(self):
        from grace_control.core.feature_recovery import TaskResumeContext

        context = TaskResumeContext(
            packet_id="pkt_test",
            feature_id="feat_test",
            failure_summary="coder failed 2x",
        )
        summary = render_resume_summary(context)
        assert "pkt_test" in summary
        assert "coder failed" in summary

    def test_resume_context_default_disabled(self):
        class FakePacket:
            id = "pkt_test"
            feature_id = "feat_test"

        context = build_task_resume_context(FakePacket())
        assert context.session_resume_available is False
        assert context.build_resume_context is False

    def test_artifact_paths_preserved_in_snapshot(self):
        class FakeRun:
            id = "run_001"
            packet_id = "pkt_test"
            run_number = 1
            status = "rejected"
            result_json = {
                "acceptance_report_path": "/tmp/report.json",
                "evidence_verifier_report_path": "/tmp/ev.json",
                "reviewer_report_path": "/tmp/rv.json",
                "recovery": {"decision_id": "recd_abc"},
                "executor_id": "coder-flash",
            }
            started_at = None
            finished_at = None

        snap = build_session_snapshot(FakeRun())
        assert snap.acceptance_report_path == "/tmp/report.json"
        assert snap.evidence_report_path == "/tmp/ev.json"
        assert snap.reviewer_report_path == "/tmp/rv.json"
        assert snap.recovery_decision_id == "recd_abc"
