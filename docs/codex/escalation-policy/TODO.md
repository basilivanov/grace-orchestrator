# Escalation Policy — TODO

Remaining work after commit `5c5e834` / review `REVIEW-CODE-FIX.md`.

---

## 🔴 Must do (blockers for Phase 3 live testing)

| # | What | File | Effort |
|---|------|------|--------|
| 1 | Create `test_recovery_session.py` — Phase 4 session stubs | `tests/grace_control/core/test_recovery_session.py` | 30 min |
| 2 | Fix test count: claimed 79, actual 76. Missing 3 tests. | Verify all test files exist | 10 min |

## 🟡 Should do (before enabling recovery in prod)

| # | What | File | Effort |
|---|------|------|--------|
| 3 | Run self-improvement golden test with `GRACE_RECOVERY_CONTROLLER_ENABLED=true` | `grace/features/self-evolve-tz-021.yaml` | 5 min |
| 4 | Verify recovery API endpoint returns valid JSON | `curl /api/recovery/evaluate/{packet_id}` | 2 min |
| 5 | Verify `dashboard.html` recovery section renders in browser | open `http://localhost:8042` | 2 min |

## 🟢 Nice to have (out of scope for current TZ)

| # | What | Phase | Effort |
|---|------|-------|--------|
| 6 | Phase 6 routing wrapper — `decorate_route()` | 6 | 1 hour |
| 7 | Phase 6 tests — `test_decorate_route_*` | 6 | 30 min |
| 8 | Admin UI polish — recovery timeline chart | 5 | 2 hours |
| 9 | Session resume live wiring (not stubs) | Future | TBD |

---

## Quick fix commands

```bash
# Run recovery test suite
.venv/bin/python -m pytest \
  tests/grace_control/core/test_feature_recovery.py \
  tests/grace_control/core/test_recovery_controller.py \
  tests/golden_fixtures/test_fixture_recovery_scenarios.py \
  -v

# Test recovery API (requires API running with controller enabled)
curl -X POST http://localhost:8042/api/recovery/evaluate/pkt_xxx -d '{"apply":false}'

# Run self-improvement golden with recovery
GRACE_RECOVERY_CONTROLLER_ENABLED=true \
  .venv/bin/grace golden fixture run-one \
  fixtures/golden/recovery_coder_fail_twice.yaml --golden-fixture
```

---

## Status summary

```
Phase 1/2:  ✅ DONE (core policy + fixtures, 46 pass)
Phase 3:    ✅ DONE (RecoveryController, API, worker, 16 tests)
Phase 4:    ⚠️ MISSING TEST FILE (stubs done, tests not done)
Phase 5:    ✅ DONE (dashboard recovery HTML, events, WS)
Phase 6:    ⏳ OUT OF SCOPE (after Phase 3/4 stable)

Total: 76 tests pass. Missing: test_recovery_session.py (~9 tests).
```
