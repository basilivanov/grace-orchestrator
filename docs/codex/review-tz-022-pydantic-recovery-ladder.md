# Review: TZ-022 — Pydantic Recovery Ladder (commit ab123c1)

Review of commit `ab123c1` against `docs/codex/tz-022-pydantic-recovery-ladder.md`.

Date: 2026-06-04

---

## What changed from review v2

| Metric | Review v2 (a885b7e) | This (ab123c1) |
|--------|--------------------|-----------------|
| rules tests | 11 | **12** |
| total tests | 96 | **97** |
| missing tests | 2 | **1** (test_attempt_eight_fallback) |
| criteria | 12/14 | **13/14** |

---

## New tests added

| Test | Status | Covers gap |
|------|--------|------------|
| `test_fallback_on_empty_ladder` | ✅ NEW | partial fallback coverage |
| `test_recovery_ladder_default` | ✅ NEW | default ladder creation |
| `test_route_model_creation` | ✅ NEW | RecoveryRoute model |
| `test_recovery_rule_default_on_verdict` | ✅ NEW | on_verdict defaults |
| `test_architect_context_model_creation` | ✅ NEW | **Review gap #2 fixed** |

---

## Acceptance criteria (final)

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

**13/14 criteria met.**

---

## ⚠️ Still missing

| # | Test | Priority |
|---|------|----------|
| 1 | `test_attempt_eight_fallback` — attempt=8 with ATTEMPT_GTE(99) ladder → falls back to default route | Low |
| 2 | Commit message says "91 total" but actual is 97 | Cosmetic |

---

## Discrepancies

| Claim | Actual |
|-------|--------|
| "12 rules tests" | ✅ 12 |
| "91 tests total" | ❌ 97 |
| "All 14/14 criteria met" | ❌ 13/14 (missing test_attempt_eight_fallback) |

---

## Verdict

**96/100 — 13/14 criteria met. 97 tests pass. 1 edge-case test missing.**

The edge case (attempt=8 with no matching rule) is handled by the fallback in `evaluate_ladder()` (line 142-148) which returns `RETRY_SAME_CODER` with `skip_verifier=false`. Safe behavior — just not explicitly tested.

### Remaining work

| # | What | Effort |
|---|------|--------|
| 1 | `test_attempt_eight_fallback` — 1 assert | 2 min |
| 2 | Fix commit stat to 97, not 91 | 1 min |
