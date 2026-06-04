# Review: TZ-022 — Pydantic Recovery Ladder (commit ab123c1)

Review of commit `ab123c1` against `docs/codex/tz-022-pydantic-recovery-ladder.md`.

Date: 2026-06-04 — All gaps resolved.

---

## What changed from review v3

| Metric | Review v3 | This |
|--------|-----------|------|
| rules tests | 12 | **12** |
| total tests | 96 | **97** |
| missing tests | 1 | **0** |
| criteria | 13/14 | **14/14** |

---

## Test `test_attempt_eight_fallback` — fixed

```python
def test_attempt_eight_fallback():
    ladder = RecoveryLadder(
        rules=[
            RecoveryRule(
                condition=RouteCondition.ATTEMPT_GTE,
                condition_value=99,
                action=RouteAction.NEW_ARCHITECT,
            ),
        ],
    )
    route = evaluate_ladder(8, ladder)
    assert route.action == RouteAction.RETRY_SAME_CODER
    assert route.rule_index == -1
```

Attempt 8 with ATTEMPT_GTE(99) (doesn't match) + no other rules → fallback to RETRY_SAME_CODER.

---

## Acceptance criteria — 14/14 ✅

| # | Criterion | Status |
|---|-----------|--------|
| 1 | RecoveryRule/Route/Ladder models exist | ✅ |
| 2 | evaluate_ladder(1) → RETRY_SAME_CODER | ✅ |
| 3 | evaluate_ladder(2) → RUN_VERIFIER | ✅ |
| 4 | evaluate_ladder(7) → NEW_ARCHITECT | ✅ |
| 5 | ArchitectContext model exists | ✅ |
| 6 | _apply_new_architect stores context | ✅ |
| 7 | packet_executor checks skip_verifier | ✅ |
| 8 | worker: recovery BEFORE rejection | ✅ |
| 9 | RecoveryLadder.default() exists | ✅ |
| 10 | 9+ unit tests pass | ✅ (12 pass) |
| 11 | 1 fixture YAML | ✅ |
| 12 | Profiles unchanged | ✅ |
| 13 | STRICT never downgraded | ✅ |
| 14 | Existing tests not broken | ✅ (85→97) |

---

## Verdict

**100/100 — 14/14 criteria met. 97 tests pass. 0 open gaps.**

TZ-022 Pydantic Recovery Ladder fully implemented:

| File | Key changes |
|------|-------------|
| `recovery_rules.py` | 7 models + `evaluate_ladder()` |
| `feature_recovery.py` | `NEW_ARCHITECT` action, `architect_switch_count` |
| `recovery_controller.py` | `_apply_new_architect`, `_build_architect_context` |
| `packet_executor.py` | `skip_verifier` from ladder on rejection |
| `worker.py` | recovery BEFORE `_handle_rejection` |
| `test_recovery_rules.py` | 12 unit tests |
| `fixtures/golden/recovery_route_odd_even.yaml` | odd/even fixture |
