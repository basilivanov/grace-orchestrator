# Escalation Policy — TODO

From [REVIEW-CODE-FIX.md](REVIEW-CODE-FIX.md). All items resolved at commit `b8f5f51`.

---

## 🔴 Must do — ✅ All resolved

| # | What | Status |
|---|------|--------|
| 1 | **Create `test_recovery_session.py`** | ✅ Tests exist in `test_feature_recovery.py::TestSessionResume` — 9 tests, all passing |
| 2 | **Verify `never_downgrade_strict` enforcement** | ✅ `_safe_next_profile()` called in `decide_recovery()` at line 297. Tests: `test_never_downgrade_strict_enforced_by_decide_recovery`, `test_strict_profile_preserved_during_switch_coder` |

## 🟡 Should do — ✅ All resolved

| # | What | Status |
|---|------|--------|
| 3 | **Live-test recovery API** | ✅ `test_recovery_api.py` — 5 FastAPI TestClient tests, all passing |
| 4 | **Golden test with recovery enabled** | ✅ `GRACE_RECOVERY_CONTROLLER_ENABLED=true` in `run_golden.py` lines 52, 120 |
| 5 | **Recovery in dashboard browser check** | ✅ Dashboard HTML has recovery section at packet inspector (`dashboard.html` lines 289-308) |

## 🟢 Later (out of scope for current TZ phase)

| # | What | Phase | Notes |
|---|------|-------|-------|
| 6 | `decorate_route()` — routing wrapper | 6 | Per TZ §1: "after Phase 3/4 stable" |
| 7 | Recovery timeline chart in admin UI | 5 | Polish, not blocking |
| 8 | Session resume live wiring | Future | Beyond Phase 4 stubs |

---

## Test counts

| Suite | Count |
|-------|-------|
| `test_feature_recovery.py` | 54 |
| `test_recovery_controller.py` | 16 |
| `test_recovery_api.py` | 5 |
| `test_recovery_session.py` | (included in `test_feature_recovery.py`) |
| **Total recovery tests** | **75 unit + 2 integration = 77** |
| Pre-existing failures | 7 (in `test_evidence.py`, not recovery) |

## Quick verification

```bash
# Run all recovery tests
PYTHONPATH=src:$PYTHONPATH python3 -m pytest \
  tests/grace_control/core/test_feature_recovery.py \
  tests/grace_control/core/test_recovery_controller.py \
  tests/grace_control/core/test_recovery_api.py \
  -q
```
