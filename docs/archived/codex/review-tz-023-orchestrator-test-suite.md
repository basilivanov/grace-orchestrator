# Review: TZ-023 — Final fix (commit 541f6f5)

Review of commit `541f6f5` against `docs/codex/tz-023-orchestrator-integration-test-suite.md`.

Date: 2026-06-04

---

## Summary

All review issues closed. 26/26 TZ-023 tests pass. 117 total recovery tests.

| Metric | Value |
|--------|-------|
| TZ-023 tests | 26/26 ✅ |
| Total recovery tests | 117 ✅ |
| Acceptance criteria | 6/6 ✅ |
| Remaining issues | 0 |

---

## Fix: mocker → monkeypatch

**Before:**
```python
async def test_evaluate_crash_is_safe(db, mocker):
    ...
    mocker.patch.object(ctrl, "build_signal", side_effect=RuntimeError("simulated crash"))
```

**After:**
```python
async def test_evaluate_crash_is_safe(db, monkeypatch):
    ...
    def _crash(*a, **kw):
        raise RuntimeError("simulated crash")
    monkeypatch.setattr(ctrl, "build_signal", _crash)
```

`monkeypatch` — встроенный pytest fixture. Никаких внешних зависимостей.

---

## Final TZ-023 acceptance criteria

| # | Criterion | Status |
|---|-----------|--------|
| 1 | Все 26 новых тестов | ✅ |
| 2 | test_build_signal_real_db | ✅ |
| 3 | 7 regression tests | ✅ |
| 4 | 5 edge case tests | ✅ |
| 5 | build_signal fix | ✅ |
| 6 | Все тесты проходят | ✅ 26/26 |

---

## Verdict

**100/100 — TZ-023 done. 117 tests pass. 0 issues.**

Все категории покрыты: SESSION (3), FAILURE INJECTION (5), FULL PIPELINE (6), REGRESSION (7), EDGE CASES (5). build_signal DetachedInstanceError fix подтверждён. mocker заменён на monkeypatch.
