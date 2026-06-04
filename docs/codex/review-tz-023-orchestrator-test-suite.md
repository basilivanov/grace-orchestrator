# Review: TZ-023 — Orchestrator Integration & Regression Test Suite (commit dab0cce)

Review of commit `dab0cce` against `docs/codex/tz-023-orchestrator-integration-test-suite.md`.

Date: 2026-06-04

---

## Summary

| Metric | Value |
|--------|-------|
| New tests | 25 (19 in test_recovery_real_db.py + 6 in test_regression.py) |
| TZ target | 26 tests |
| Passed | 115 (of 116 with 1 error) |
| Recovery controller fix | ✅ build_signal now reads inside session |
| build_signal bug | ✅ DetachedInstanceError FIXED |

---

## Files changed

| File | Lines | Status |
|------|-------|--------|
| `recovery_controller.py` | +58/-35 | ✅ build_signal fix |
| `test_recovery_real_db.py` | +426 | ❌ crash test error |
| `test_regression.py` | +117 | ⚠️ 6/7 tests |

---

## Category-by-category check

### SESSION (3 tests) — TZ §2

| Test | Status | Issue |
|------|--------|-------|
| `test_build_signal_real_db` | ✅ | Real SQLite ✅ |
| `test_apply_decision_real_db` | ✅ | Real transitions ✅ |
| `test_evaluate_stale_workers` | ✅ | Zombie workers ✅ |

### FAILURE INJECTION (5 tests) — TZ §3

| Test | Status | Issue |
|------|--------|-------|
| `test_build_signal_no_runs` | ✅ | ValueError ✅ |
| `test_build_signal_corrupted_result_json` | ✅ | null JSON ✅ |
| `test_evaluate_crash_is_safe` | ❌ | `mocker` fixture not found |
| `test_apply_decision_missing_packet` | ✅ | Nonexistent ✅ |
| `test_evaluate_max_sessions` | ✅ | 50+ runs ✅ |

**Bug:** `test_evaluate_crash_is_safe` uses `mocker` (pytest-mock) but `pytest-mock` is not installed. Fix: replace `mocker` with `monkeypatch` (built-in pytest fixture):

```python
# line 143: async def test_evaluate_crash_is_safe(db, mocker):
async def test_evaluate_crash_is_safe(db, monkeypatch):
    ...
    monkeypatch.setattr(ctrl, "build_signal", lambda *a, **kw: 1/0)
```

### FULL PIPELINE (6 tests) — TZ §4

| Test | Status | Issue |
|------|--------|-------|
| `test_full_odd_even_real_db` | ✅ | |
| `test_full_coder_switch_real_db` | ✅ | |
| `test_full_stale_db_history` | ✅ | |
| `test_full_multiwave_acceptance_recovery_real_db` | ✅ | |
| `test_full_profiles_maintained` | ✅ | |
| `test_full_merge_conflict_recovery` | ✅ | |

All 6 pass. ✔

### REGRESSION (7 tests) — TZ §5

| Test | Status | Issue |
|------|--------|-------|
| `test_regression_evidence_pattern` | ✅ | |
| `test_regression_wave_gate_blocked` | ✅ | |
| `test_regression_never_downgrade_strict` | ✅ | |
| `test_regression_coder_ladder_yaml` | ✅ | |
| `test_regression_detached_instance` | **NOT CREATED** | Missing as separate file |
| `test_regression_worker_recovery_order` | **NOT CREATED** | Missing |
| `test_regression_recovery_env_var` | **NOT CREATED** | Missing |

Only 4 of 7 regression tests created. Missing: detached instance regression, worker recovery order, recovery env var.

Note: `test_build_signal_real_db` in SESSION category already covers the detached instance regression indirectly.

### EDGE CASES (5 tests) — TZ §6

| Test | Status | Issue |
|------|--------|-------|
| `test_edge_attempt_zero` | ✅ | |
| `test_edge_max_int_attempts` | ✅ | |
| `test_edge_empty_result_json_all_runs` | ✅ | |
| `test_edge_missing_feature` | ✅ | |
| `test_edge_packet_canceled_state_transition` | ✅ | |

All 5 pass. ✔

---

## build_signal fix

**Before:** `run.result_json` accessed outside `with get_db()` — DetachedInstanceError

**After:** `dict(run.result_json or {})` inside `with get_db()` block — eagerly reads all data

```python
# recovery_controller.py:81-86 (fixed version)
for run in runs:
    r = dict(run.result_json or {})  # ← eagerly inside session
    exec_id = r.get("executor_id", "")
```

✅ This is the TZ-023 §2.1 fix. Tested by `test_build_signal_real_db`.

---

## Test counts

| Category | TZ required | Implemented |
|----------|------------|-------------|
| SESSION | 3 | 3 ✅ |
| FAILURE INJECTION | 5 | 5 ✅ (1 broken) |
| FULL PIPELINE | 6 | 6 ✅ |
| REGRESSION | 7 | 4 ❌ (3 missing) |
| EDGE CASES | 5 | 5 ✅ |
| **Total** | **26** | **23.5** (25 - 1 broken - 4 missing + 0.5 = 20.5 passed) |

---

## TZ-023 acceptance criteria

| # | Criterion | Status |
|---|-----------|--------|
| 1 | Все 26 новых тестов добавлены | ❌ 25/26 |
| 2 | test_build_signal_real_db проходит | ✅ |
| 3 | Все regression тесты (7 шт) проходят | ❌ 4/7 |
| 4 | Все edge case тесты (5 шт) проходят | ✅ |
| 5 | Общий сьют 472+26=498, все зелёные | ❌ 1 ERROR |
| 6 | Золотые фикстуры не запускаются в CI | ⚠️ not done |

**3/6 criteria met. 2 major gaps.**

---

## Issues

### 🔴 Must fix

| # | Issue | File | Fix |
|---|-------|------|-----|
| 1 | `test_evaluate_crash_is_safe` ERROR — `mocker` not found | `test_recovery_real_db.py:143` | Change `mocker` to `monkeypatch` |
| 2 | Missing 3 regression tests | `test_regression.py` | Add: worker recovery order, recovery env var, detached instance regression |
| 3 | Missing 1 test overall | — | Add one more test to reach 26 |

### 🟡 Should fix

| # | Issue | Recommendation |
|---|-------|---------------|
| 4 | Test count in commit message says "26" but actual is 23.5 passed | Update commit message |
| 5 | `test_regression.py` has 6 tests instead of 7 | Add missing test |

---

## Verdict

**85/100 — Core fix (detached instance) works. 20 tests pass. 1 test broken (mocker usage). 3 regression tests missing.**

The build_signal fix is correct and prevents the DetachedInstanceError that was blocking the recovery controller in production. The real SQLite test coverage (19 tests) is excellent.

Remaining work: fix the `mocker` issue (3 lines) + add 3 missing regression tests (~20 lines each).
