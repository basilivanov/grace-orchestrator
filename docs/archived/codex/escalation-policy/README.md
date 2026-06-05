# Escalation Policy — Implementation Index

Per TZ-017: Feature Recovery / Escalation Policy.

## Phase map

| Phase | Spec | Description | Status |
|-------|------|-------------|--------|
| 1/2 | `phase-1-2-baseline.md` | Deterministic policy core + recovery fixtures | ✅ DONE |
| 3 | `phase-3-recovery-controller.md` | Live RecoveryController + API + worker integration | ⬜ Next |
| 4 | `phase-4-session-resume-stubs.md` | Session resume data models + stubs | ⬜ After Phase 3 |
| 5 | `phase-5-admin-event-integration.md` | Admin dashboard recovery display + event stream | ⬜ After Phase 3 |
| 6 | `phase-6-routing-wrapper.md` | Thin routing metadata wrapper (no YAML engine) | ⬜ Last |

## File map

```
src/grace_control/core/
  feature_recovery.py          ← Phase 1/2 models + classify/decide (exists)
  recovery_controller.py       ← Phase 3 RecoveryController (new)
src/grace_control/api/routers/
  recovery.py                  ← Phase 3 API endpoints (new)
src/grace_control/worker/
  worker.py                    ← Phase 3 worker integration (modify)
src/grace_control/adapters/
  packet_executor.py           ← Phase 3 SWITCH_CODER executor (modify)
src/grace_control/ui/templates/
  dashboard.html               ← Phase 5 recovery display (modify)
src/grace_control/api/
  main.py                      ← Phase 5 dashboard_data() (modify)
  ws_broadcast.py              ← Phase 5 recovery events (modify)
src/grace_control/core/
  event_recorder.py            ← Phase 3/5 recovery events (modify)

tests/grace_control/core/
  test_recovery_controller.py  ← Phase 3 tests (new)
  test_recovery_session.py     ← Phase 4 tests (new)

fixtures/golden/
  recovery_*.yaml              ← Phase 2 fixtures (exist)
```

## Dependencies

```
Phase 1/2 (baseline)
  └─ Phase 3 (RecoveryController)
       ├─ Phase 4 (session resume stubs)
       └─ Phase 5 (admin/event integration)
```

## Safety invariants (all phases)

- Do NOT bypass scope guard
- Do NOT bypass deterministic acceptance
- Do NOT bypass reviewer for STRICT packets
- Do NOT force-merge dirty target repo
- Do NOT auto-resolve merge conflicts
- Do NOT lower STRICT to NORMAL/FAST
- Do NOT let recovery loops run forever
- Do NOT add a competing routing engine
- Do NOT replace `classify_failure` / `decide_recovery` with YAML logic
- Do NOT run real LLMs/git/opencode/agy in tests

## Feature flags

```
GRACE_RECOVERY_CONTROLLER_ENABLED=true|false  (Phase 3)
```

## Reference

- TZ-017: `docs/codex/tz-017-feature-recovery-escalation-policy.md`
- TZ-017b: `docs/codex/tz-017b-feature-recovery-controller-live-wiring.md`
- TZ-017c: `docs/codex/tz-017c-recovery-config-and-fixture-yaml-requirements.md`
