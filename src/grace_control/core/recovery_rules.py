# ############################################################################
# AI_HEADER: recovery_rules
# ROLE: Pydantic recovery ladder — evaluate state → route decision.
# TZ-022: Pydantic Recovery Ladder.
# ############################################################################

# START_MODULE_CONTRACT
# purpose: Define Pydantic recovery ladder models + evaluate_ladder().
#          Routes packet recovery decisions based on attempt number and state.
# inputs: attempt number, optional RecoveryLadder.
# returns: RecoveryRoute with action, skip_verifier, on_verdict mapping.
# side_effects: None (pure functions).
# emitted_logs: None.
# error_behavior: Falls back to default ladder on missing config.
# END_MODULE_CONTRACT

# START_MODULE_MAP
# mapping:
#   - enum: RouteCondition
#   - enum: RouteAction
#   - class: RecoveryRule
#   - class: RecoveryLadder
#   - class: RecoveryRoute
#   - class: ArchitectContext
#   - function: evaluate_ladder
# END_MODULE_MAP

from __future__ import annotations

from enum import Enum
from typing import Any

from pydantic import BaseModel, Field


class RouteCondition(str, Enum):
    ODD_ATTEMPT = "odd_attempt"
    EVEN_ATTEMPT = "even_attempt"
    ATTEMPT_GTE = "attempt_gte"


class RouteAction(str, Enum):
    RETRY_SAME_CODER = "RETRY_SAME_CODER"
    RUN_VERIFIER = "RUN_VERIFIER"
    SWITCH_CODER = "SWITCH_CODER"
    ARCHITECT_REPACK = "ARCHITECT_REPACK"
    NEW_ARCHITECT = "NEW_ARCHITECT"
    BLOCK_FEATURE = "BLOCK_FEATURE"
    NO_ACTION = "NO_ACTION"


class RecoveryRule(BaseModel):
    condition: RouteCondition
    condition_value: int | None = None
    action: RouteAction
    skip_verifier: bool = False
    on_verdict: dict[str, str] = Field(default_factory=lambda: {
        "REWORK_TO_CODER": RouteAction.SWITCH_CODER.value,
        "RETURN_TO_ARCHITECT": RouteAction.ARCHITECT_REPACK.value,
    })


class RecoveryLadder(BaseModel):
    rules: list[RecoveryRule]
    max_coders: int = 3
    switch_architect_on_attempt: int = 7

    @classmethod
    def default(cls) -> "RecoveryLadder":
        return cls(
            max_coders=3,
            switch_architect_on_attempt=7,
            rules=[
                RecoveryRule(
                    condition=RouteCondition.ATTEMPT_GTE,
                    condition_value=7,
                    action=RouteAction.NEW_ARCHITECT,
                    skip_verifier=True,
                ),
                RecoveryRule(
                    condition=RouteCondition.EVEN_ATTEMPT,
                    action=RouteAction.RUN_VERIFIER,
                    skip_verifier=False,
                    on_verdict={
                        "REWORK_TO_CODER": RouteAction.SWITCH_CODER.value,
                        "RETURN_TO_ARCHITECT": RouteAction.ARCHITECT_REPACK.value,
                    },
                ),
                RecoveryRule(
                    condition=RouteCondition.ODD_ATTEMPT,
                    action=RouteAction.RETRY_SAME_CODER,
                    skip_verifier=True,
                ),
            ],
        )


class RecoveryRoute(BaseModel):
    rule_index: int
    condition: RouteCondition
    action: RouteAction
    skip_verifier: bool = False
    max_coders: int = 3
    on_verdict: dict[str, str] = Field(default_factory=dict)


class ArchitectContext(BaseModel):
    original_spec: dict[str, Any] = Field(default_factory=dict)
    attempts: list[dict[str, Any]] = Field(default_factory=list)
    acceptance_reports: list[dict[str, Any]] = Field(default_factory=list)
    verifier_reports: list[dict[str, Any]] = Field(default_factory=list)
    executor_ids: list[str] = Field(default_factory=list)
    changed_files: list[str] = Field(default_factory=list)
    summary: str = ""


def evaluate_ladder(
    attempt: int,
    ladder: RecoveryLadder | None = None,
) -> RecoveryRoute:
    ladder = ladder or RecoveryLadder.default()

    for idx, rule in enumerate(ladder.rules):
        match = False
        if rule.condition == RouteCondition.ODD_ATTEMPT and attempt % 2 == 1:
            match = True
        elif rule.condition == RouteCondition.EVEN_ATTEMPT and attempt % 2 == 0:
            match = True
        elif rule.condition == RouteCondition.ATTEMPT_GTE and attempt >= (rule.condition_value or 7):
            match = True

        if match:
            return RecoveryRoute(
                rule_index=idx,
                condition=rule.condition,
                action=rule.action,
                skip_verifier=rule.skip_verifier,
                max_coders=ladder.max_coders,
                on_verdict=rule.on_verdict,
            )

    return RecoveryRoute(
        rule_index=-1,
        condition=RouteCondition.ODD_ATTEMPT,
        action=RouteAction.RETRY_SAME_CODER,
        skip_verifier=False,
        max_coders=ladder.max_coders,
    )
