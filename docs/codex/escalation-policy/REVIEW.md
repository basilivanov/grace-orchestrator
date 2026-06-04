# Review: Escalation Policy Phase Specs

Review of `docs/codex/escalation-policy/` against `docs/codex/tz-017-feature-recovery-escalation-policy.md`.

Date: 2026-06-04

---

## Summary

| Aspect | Status |
|--------|--------|
| Phase coverage | ✅ 6/6 phases (all TZ-017 phases) |
| File count | 7 files (README + 1-per-phase + review) |
| Total specs | 6 phases × ~200 lines avg = ~1200 lines |
| Test requirements | 46 tests across all phases |
| Self-improvement ready | ⚠️ Waves 1-2 only, rest needs manual |
| Missing | `never_downgrade_strict` field in RecoveryPolicy |

---

## Per-phase review

### Phase 1/2 Baseline — ✅ 4/5

| Criterion | Status | Notes |
|-----------|--------|-------|
| Models documented | ✅ | All 5 models with defaults listed |
| Known gaps identified | ✅ | 4 gaps, 1 blocker (never_downgrade_strict) |
| "Must not change" clear | ✅ | 7 items |
| File map | ⚠️ | Missing `tests/grace_control/core/test_feature_recovery.py` path |
| Implementation baseline | ✅ | Accurate: 271 lines, 21 classify paths |

**Gap:** Lines 43-50 mention 4 gaps but don't say which are blockers for Phase 3. Only `never_downgrade_strict` (gap #1) is actually blocking — the rest are cosmetic.

### Phase 3 RecoveryController — ⚠️ 3/5

| Criterion | Status | Notes |
|-----------|--------|-------|
| `build_signal()` | ✅ | Full implementation from DB |
| `evaluate()` | ✅ | classify → decide → persist → apply |
| Apply actions | ✅ | 7 actions covered |
| `_next_executor_hint` usage | ⚠️ | Used in SWITCH_CODER but ladder is hardcoded value, not reference to existing `_next_executor_hint()` |
| Worker integration | ⚠️ | Shows worker code but doesn't specify WHERE exactly (line number) in worker.py |
| Executor selection | ⚠️ | `spec_json` access is fragile — `spec_json` may be string/dict at different points |

**Issues:**
1. Phase 3 uses `decision.next_executor_hint` but doesn't import from `feature_recovery._next_executor_hint`. Should use the existing function.
2. `packet.spec_json["recovery"]["requested_executor_id"]` — mutations on dict may not trigger SQLAlchemy dirty-check. Need explicit assignment.
3. `_apply_retry_verifier` and `_apply_retry_reviewer` only store metadata — no actual retry logic. Should clarify "metadata only" in spec.
4. Worker integration line numbers not specified — coder needs to know exact insertion point.

### Phase 4 Session Resume — ✅ 4/5

| Criterion | Status | Notes |
|-----------|--------|-------|
| Models defined | ✅ | 3 models with all fields |
| Stub functions | ✅ | 3 stub functions |
| No LLM calls | ✅ | Explicitly stated |
| Test requirements | ✅ | 9 tests listed |
| Integration | ⚠️ | Doesn't say WHERE in feature_recovery.py to add models |

**Issues:**
1. `build_session_snapshot` tries to access `packet_run.started_at` with `hasattr` check — but `PacketRun` always has `started_at` (nullable DateTime). The check is unnecessary.
2. `RecoverySessionSnapshot.session_id` defaults to `""` — no function populates it. Should say "reserved for future Phase 3+".
3. Phase 4 depends on Phase 3 (for recovery_decision_id) but TZ says "Phase 4 after Phase 3 is stable" — order is correct.

### Phase 5 Admin/Event — ⚠️ 3/5

| Criterion | Status | Notes |
|-----------|--------|-------|
| Dashboard HTML | ✅ | Inline HTML example |
| Dashboard API | ✅ | `dashboard_data()` extension |
| Event stream | ✅ | Filter by recovery_* prefix |
| WebSocket | ✅ | `recovery_update` event types |
| Tests | ⚠️ | Only 5 tests, some are integration-level |

**Issues:**
1. Dashboard HTML example uses template literal `${}` syntax — but the existing dashboard uses Python `str.format()` or string concatenation, not JS template literals. Spec is inconsistent with existing codebase style.
2. `test_recovery_section_renders_in_html` — this is an integration/test that requires an HTTP server. Spec says "no real API server" for recovery tests. Conflict.
3. `blocked_recovery_count` query uses `Packet.spec_json.contains(...)` — JSON column `contains` may not work on SQLite (depends on SQLAlchemy version). Need to verify with `sqlite://` DB.
4. Phase 5 files (dashboard.html, ws_broadcast.py, main.py) are NOT Python — self-improvement agent cannot handle HTML/JS/CSS changes well. Spec should note "manual implementation recommended for dashboard.html".

### Phase 6 Routing Wrapper — ✅ 5/5

| Criterion | Status | Notes |
|-----------|--------|-------|
| Thin wrapper | ✅ | Pure functions, no engine |
| No YAML | ✅ | Explicitly stated |
| Reuses classify/decide | ✅ | decorate_route wraps, not replaces |
| Session context modes | ✅ | 4 modes mapped to 9 actions |
| Stop guards | ✅ | Reads from RecoveryPolicy |
| Safety notes | ✅ | STRICT, block, escalation |

**Issues:** None critical. This is the cleanest phase spec. Small note: `_stop_guard_if_hit` instantiates `RecoveryPolicy()` to read limits — should accept `policy` as parameter to avoid re-instantiating.

---

## Cross-cutting issues

### 1. TZ-017d conflict prevention

All phases correctly avoid:
- YAML rules engine ❌ (not introduced)
- RouteContext with duplicate counters ❌
- Separate stop guards outside RecoveryPolicy ❌
- Session context before controller stable ❌

Phase 6 explicitly states: "Do NOT create a YAML rules engine."

### 2. `never_downgrade_strict` — uncorrected across all phases

Phase 1/2 gap #1 identifies this as missing. Phase 3 `_apply_switch_coder` and `_apply_retry_same_coder` don't check it. Phase 4 doesn't check it. Phase 5 doesn't display it. Phase 6 `_collect_safety_notes` mentions it as a note but doesn't actually enforce it.

**Fix:** Phase 3 must explicitly add `never_downgrade_strict` to `RecoveryPolicy` and enforce it in `decide_recovery()` or in controller apply methods.

### 3. Self-improvement feasibility

| Phase | Waves | Self-improvement? | Notes |
|-------|-------|-------------------|-------|
| Phase 1/2 | — | N/A | Already done |
| Phase 3 | 3 waves | 🟡 Possible with exact scopes | `recovery_controller.py` new file, `worker.py` small edit |
| Phase 4 | 1 wave | 🟢 Good | Only add models to `feature_recovery.py` |
| Phase 5 | 2 waves | 🔴 Not recommended | `dashboard.html` — agent is bad at HTML/JS |
| Phase 6 | 1 wave | 🟢 Good | Pure functions, no new files |

### 4. Test count vs TZ-017

TZ-017 §16 lists required tests by phase. Current specs list:

| Phase | TZ-017 tests | Spec tests | Match? |
|-------|-------------|------------|--------|
| Phase 1/2 | 12 classification + 6 decision + 5 safety | "25 tests pass" | ✅ |
| Phase 3 | 9 tests | 16 tests | ⚠️ Over-specified |
| Phase 4 | 3 tests | 9 tests | ⚠️ Over-specified |
| Phase 5 | — | 5 tests | ✅ |
| Phase 6 | — | 8 tests | ✅ |

Phase 3 and 4 specs list more tests than TZ-017 requires. This is OK for completeness but may lead to over-implementation.

---

## Recommendations

### 🔴 Must fix

1. Add `never_downgrade_strict: bool = True` to `RecoveryPolicy` in existing `feature_recovery.py` (Phase 1/2 gap #1)
2. Enforce it in Phase 3 `_apply_*` methods
3. Store `requested_executor_id` as a dedicated field, not in `spec_json["recovery"]` (SQLAlchemy dirty-check issue)

### 🟡 Should fix

4. Phase 3 worker integration — add exact line numbers for insertion
5. Phase 4 models — add a note that `session_id` is reserved for Phase 3+
6. Phase 5 — add note that dashboard.html should be implemented manually
7. Phase 5 — verify `Packet.spec_json.contains()` works on SQLite

### 🟢 Nice to have

8. Phase 6 `_stop_guard_if_hit` accepts `policy` parameter
9. Phase 3 executor selection uses `_next_executor_hint()` function, not hardcoded value
10. Remove `hasattr(packet_run, "started_at")` check in Phase 4 since `PacketRun` always has it

---

## Verdict

**85/100 — Solid phase specs, 3 must-fix items before implementation.**

The escalation policy specs properly decompose TZ-017 into implementable phases with clear file scopes, test requirements, and explicit "do not" rules. Phase 6 correctly avoids the TZ-017d rules engine trap. Phase 5 correctly limits frontend scope.

The missing `never_downgrade_strict` field and SQLAlchemy dirty-check concern are the only blockers before Phase 3 implementation.
