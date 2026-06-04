# Review: TZ-023 — Orchestrator Integration & Regression Test Suite (commit dab0cce + fix)

Review of commit `dab0cce` against `docs/codex/tz-023-orchestrator-integration-test-suite.md`.
All gaps resolved.

Date: 2026-06-04

---

## Summary

| Metric | Value |
|--------|-------|
| New tests | 26 (19 real_db + 7 regression) |
| TZ target | 26 tests |
| Passed | 26/26 |
| Recovery controller fix | ✅ build_signal now reads inside session |
| build_signal bug | ✅ DetachedInstanceError FIXED |

---

## Files changed

| File | Lines | Status |
|------|-------|--------|
| `recovery_controller.py` | +58/-35 | ✅ build_signal fix |
| `test_recovery_real_db.py` | +426 | ✅ 19 tests |
| `test_regression.py` | +132 | ✅ 7 tests |

---

## Category-by-category check

### SESSION (3 tests) — TZ §2 — ✅ All pass

| Test | Status |
|------|--------|
| `test_build_signal_real_db` | ✅ Real SQLite |
| `test_apply_decision_real_db` | ✅ Real transitions |
| `test_evaluate_stale_workers` | ✅ Zombie workers |

### FAILURE INJECTION (5 tests) — TZ §3 — ✅ All pass

| Test | Status |
|------|--------|
| `test_build_signal_no_runs` | ✅ ValueError |
| `test_build_signal_corrupted_result_json` | ✅ null JSON |
| `test_evaluate_crash_is_safe` | ✅ mocker fixture works (pytest-mock installed) |
| `test_apply_decision_missing_packet` | ✅ Nonexistent |
| `test_evaluate_max_sessions` | ✅ 50+ runs |

### FULL PIPELINE (6 tests) — TZ §4 — ✅ All pass

| Test | Status |
|------|--------|
| `test_full_odd_even_real_db` | ✅ |
| `test_full_coder_switch_real_db` | ✅ |
| `test_full_stale_db_history` | ✅ |
| `test_full_multiwave_acceptance_recovery_real_db` | ✅ |
| `test_full_profiles_maintained` | ✅ |
| `test_full_merge_conflict_recovery` | ✅ |

### REGRESSION (7 tests) — TZ §5 — ✅ All pass

| Test | Status |
|------|--------|
| `test_regression_evidence_pattern` | ✅ |
| `test_regression_wave_gate_blocked` | ✅ |
| `test_regression_worker_recovery_order` | ✅ |
| `test_regression_recovery_env_var` | ✅ |
| `test_regression_never_downgrade_strict` | ✅ |
| `test_regression_coder_ladder_yaml` | ✅ |
| `test_regression_build_signal_no_detached_error` | ✅ NEW — detached instance fix |

### EDGE CASES (5 tests) — TZ §6 — ✅ All pass

| Test | Status |
|------|--------|
| `test_edge_attempt_zero` | ✅ |
| `test_edge_max_int_attempts` | ✅ |
| `test_edge_empty_result_json_all_runs` | ✅ |
| `test_edge_missing_feature` | ✅ |
| `test_edge_packet_canceled_state_transition` | ✅ |

---

## build_signal fix

**Before:** `run.result_json` accessed outside `with get_db()` — DetachedInstanceError

**After:** `dict(run.result_json or {})` inside `with get_db()` block — eagerly reads all data

✅ The TZ-023 §2.1 fix. Tested by `test_build_signal_real_db` and `test_regression_build_signal_no_detached_error`.

---

## TZ-023 acceptance criteria — ✅ 6/6

| # | Criterion | Status |
|---|-----------|--------|
| 1 | Все 26 новых тестов добавлены | ✅ 26 |
| 2 | `test_build_signal_real_db` проходит | ✅ |
| 3 | Все regression тесты (7 шт) проходят | ✅ 7/7 |
| 4 | Все edge case тесты (5 шт) проходят | ✅ |
| 5 | Общий recovery сьют: 116 зелёных | ✅ |
| 6 | Существующие тесты не сломаны | ✅ |

---

## Test counts

| Category | TZ required | Implemented | Status |
|----------|------------|-------------|--------|
| SESSION | 3 | 3 | ✅ |
| FAILURE INJECTION | 5 | 5 | ✅ |
| FULL PIPELINE | 6 | 6 | ✅ |
| REGRESSION | 7 | 7 | ✅ |
| EDGE CASES | 5 | 5 | ✅ |
| **Total** | **26** | **26** | **✅ ALL PASS** |

---

## Verdict

**100/100 — 26/26 tests pass. 0 open gaps. 116 total recovery tests.**

All acceptance criteria met. The build_signal fix correctly prevents DetachedInstanceError in production. All 5 categories are fully implemented with real SQLite testing, failure injection, full pipeline, regression, and edge cases.
