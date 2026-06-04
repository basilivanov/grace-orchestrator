"""Tests for TZ-022 Pydantic Recovery Ladder."""

from __future__ import annotations

from grace_control.core.recovery_rules import (
    ArchitectContext,
    RecoveryLadder,
    RecoveryRoute,
    RecoveryRule,
    RouteAction,
    RouteCondition,
    evaluate_ladder,
)


def test_odd_attempt_retry_same_coder():
    route = evaluate_ladder(1)
    assert route.action == RouteAction.RETRY_SAME_CODER
    assert route.skip_verifier is True


def test_odd_attempt_3_same_behavior():
    route = evaluate_ladder(3)
    assert route.action == RouteAction.RETRY_SAME_CODER
    assert route.skip_verifier is True


def test_even_attempt_run_verifier():
    route = evaluate_ladder(2)
    assert route.action == RouteAction.RUN_VERIFIER
    assert route.skip_verifier is False


def test_even_attempt_on_verdict_mapping():
    route = evaluate_ladder(2)
    assert route.on_verdict["REWORK_TO_CODER"] == RouteAction.SWITCH_CODER.value
    assert route.on_verdict["RETURN_TO_ARCHITECT"] == RouteAction.ARCHITECT_REPACK.value


def test_default_ladder_rule_order():
    ladder = RecoveryLadder.default()
    assert ladder.rules[0].condition == RouteCondition.ATTEMPT_GTE
    assert ladder.rules[1].condition == RouteCondition.EVEN_ATTEMPT
    assert ladder.rules[2].condition == RouteCondition.ODD_ATTEMPT


def test_attempt_gte_seven_new_architect():
    route = evaluate_ladder(7)
    assert route.action == RouteAction.NEW_ARCHITECT
    assert route.skip_verifier is True
    assert route.rule_index == 0


def test_attempt_eight_fallback():
    route = evaluate_ladder(9)
    assert route.action == RouteAction.NEW_ARCHITECT
    assert route.rule_index == 0


def test_fallback_on_empty_ladder():
    empty = RecoveryLadder(rules=[])
    route = evaluate_ladder(5, empty)
    assert route.action == RouteAction.RETRY_SAME_CODER
    assert route.rule_index == -1


def test_recovery_ladder_default():
    ladder = RecoveryLadder.default()
    assert len(ladder.rules) == 3
    assert ladder.rules[0].condition == RouteCondition.ATTEMPT_GTE
    assert ladder.rules[0].condition_value == 7
    assert ladder.rules[1].condition == RouteCondition.EVEN_ATTEMPT
    assert ladder.rules[2].condition == RouteCondition.ODD_ATTEMPT


def test_route_model_creation():
    route = RecoveryRoute(
        rule_index=0,
        condition=RouteCondition.ODD_ATTEMPT,
        action=RouteAction.RETRY_SAME_CODER,
        skip_verifier=True,
        max_coders=3,
    )
    assert route.rule_index == 0
    assert route.action == RouteAction.RETRY_SAME_CODER
    assert route.skip_verifier is True


def test_recovery_rule_default_on_verdict():
    rule = RecoveryRule(
        condition=RouteCondition.ODD_ATTEMPT,
        action=RouteAction.RETRY_SAME_CODER,
    )
    assert rule.on_verdict["REWORK_TO_CODER"] == RouteAction.SWITCH_CODER.value
    assert rule.on_verdict["RETURN_TO_ARCHITECT"] == RouteAction.ARCHITECT_REPACK.value
