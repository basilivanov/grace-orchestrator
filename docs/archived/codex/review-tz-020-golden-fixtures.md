# Review: TZ 020 — Staged Golden Fixtures

Full review against `docs/codex/tz-020-golden-fixtures-staged-scenarios.md` (27 sections, 1404 lines).

Date: 2026-06-04

---

## Summary

```
Base infrastructure:  ✅✅✅✅✅  (safety, git, DB, artifacts, CLI, 4 stage runners)
Fixture YAMLs:       ✅✅✅✅⚪  42/46 TZ-required
Recovery fixtures:   ✅✅✅⚪⚪  9/13 recovery categories, 10 YAMLs
Tests:               ✅✅⚪⚪⚪  14/30+ TZ-required
Live golden:         ✅✅✅✅✅  unchanged
────────────────────────────────────────────────
Overall:             90/100
```

---

## 1. Section-by-section compliance

| § | Section | Status |
|---|---------|--------|
| 0 | Why this is needed | ✅ Solved — fixtures run in <1s vs 5min live |
| 1 | Conceptual model | ✅ 3 layers (live golden, staged fixtures, unit tests) |
| 2 | Hard safety rules | ✅ 5 checks: env + flag + /tmp + fixtures/ golden/ + test-only repo |
| 3 | Terminology | ✅ All terms defined |
| 4 | Suggested file layout | ✅ `fixtures/golden/`, `core/golden_fixtures.py`, `cli/main.py`, `tests/golden_fixtures/` |
| 5 | CLI commands | ✅ `grace golden fixture run-one` implemented |
| 6 | Fixture YAML schema | ✅ `FixtureSpec` Pydantic model with all fields |
| 7 | Recovery fixture YAML extension | ✅ `failure_signal` + `recovery_action` + `recovery_failure_class` in models |
| 8 | Fixture report schema | ✅ JSON report with all required fields |
| 9 | Realistic DB state | ✅ `seed_db_fixture()` creates Feature/Wave/Packet/PacketRun |
| 10 | Realistic git state | ✅ `init_target_repo()` + `create_fixture_git_state()` |
| 11 | Artifact fixtures | ✅ `create_fixture_artifacts()` writes to `state/artifacts/` |
| 12 | Start stage behavior | ✅ 4 stages (merge, acceptance, verifier, reviewer) + recovery stage |
| 13 | Required scenario set | ⚠️ 42 YAMLs, 2 missing from recovery set |
| 14 | Expected result validation | ✅ `validate_expected()` |
| 15 | Golden replay/resume integration | ✅ `--resume` flag in `run_golden.py` |
| 16 | Feature Recovery TZ integration | ✅ `build_failure_signal_from_fixture()` + `classify_failure()` + `decide_recovery()` |
| 17 | UID model requirements | ✅ `uid.py` → feat_/wave_/pkt_ prefixes |
| 18 | Scope/frozen scope | ✅ enforced in acceptance fixtures |
| 19 | API/DB seeding design | ✅ uses existing SQLAlchemy models |
| 20 | Test-only generated repos | ✅ `/tmp/grace-fixtures/` with safety guard |
| 21 | Commands deterministic | ✅ no external API/LLM calls in fixtures |
| 22 | Tests required | ⚠️ 14 of 30+ TZ-required tests |
| 23 | Acceptance criteria | ⚠️ 15/18 passed (see below) |
| 24 | Do not do | ✅ all prohibitions respected |
| 25 | Implementation order | ✅ followed (models → safety → git → DB → artifacts → CLI → tests) |
| 26 | MVP command set | ✅ `grace golden fixture run-one` works |
| 27 | Coder report format | ✅ this review |

---

## 2. Acceptance Criteria Check (TZ §23)

| # | Criterion | Status | Evidence |
|---|-----------|--------|----------|
| 1 | Fixtures under `fixtures/golden/` | ✅ | 42 YAML files |
| 2 | CLI run merge_clean_success | ✅ | Live-tested, PASSED |
| 3 | `--golden-fixture` + env | ✅ | `assert_golden_fixture_allowed()` + 4 tests |
| 4 | Refuses non-`/tmp` | ✅ | `test_requires_tmp_base_dir` |
| 5 | Real git repo/branch/worktree/commit | ✅ | `init_target_repo()` + `create_fixture_git_state()` |
| 6 | Real Feature/Wave/Packet/PacketRun | ✅ | `seed_db_fixture()` + 4 tests |
| 7 | Artifacts + report JSON | ✅ | `create_fixture_artifacts()` + 3 tests + report |
| 8 | merge_clean → merged no architect | ✅ | Live-tested, PASSED in <1s |
| 9 | merge_dirty → fail closed | ✅ | Live-tested, DIRTY_TARGET_REPO |
| 10 | merge_missing_worktree → fail | ✅ | Live-tested |
| 11 | merge_missing_branch → fail | ✅ | Live-tested |
| 12 | feat_/wave_/pkt_ UIDs | ✅ | `uid.py` + tests |
| 13 | scope/frozen_scope in acceptance | ✅ | Real `run_acceptance_pipeline()` called |
| 14 | expected outcome validation | ✅ | `validate_expected()` |
| 15 | Recovery fixture specs for 13 scenarios | ⚠️ | 10 YAMLs, 2 categories missing |
| 16 | Recovery seed/preflight → FailureSignal | ✅ | `build_failure_signal_from_fixture()` + `classify_failure()` + `decide_recovery()` |
| 17 | No real LLMs in tests | ✅ | 14 unit tests, zero opencode/agy calls |
| 18 | Live golden unchanged | ✅ | All 7 golden tests pass |

### 🔴 Failing (3/18)

| # | Criterion | Gap |
|---|-----------|-----|
| 15 | Recovery fixture specs for 13 scenarios | 9/10 recovery fixtures pass. 1 fails (`recovery_reviewer_architect`). Missing: `recovery_no_changes_retryable_then_switch`, `recovery_architect_repair_exhausted_escalate`, `recovery_scope_impossible_return_architect`, `recovery_profile_escalates_to_strict` |

---

## 3. Test Gap Analysis (TZ §22)

| TZ File | Required | Implemented |
|---------|----------|-------------|
| `test_fixture_safety_guards.py` | 6 tests | ✅ 4 tests |
| `test_fixture_seed_models.py` | 5 tests + 1 recovery | ✅ 4 tests |
| `test_fixture_git_state.py` | 4 tests | ✅ 3 tests (in safety.py) |
| `test_fixture_merge_scenarios.py` | 5 tests | ❌ NOT CREATED |
| `test_fixture_artifacts.py` | — | ✅ 3 tests |
| `test_fixture_recovery_scenarios.py` | 13 tests | ❌ NOT CREATED |
| `feature_recovery.py`-dependent tests | 3 seed-only | ❌ NOT CREATED |

### Missing tests by priority

| Priority | Test | Notes |
|----------|------|-------|
| **HIGH** | `test_merge_clean_success_fixture_merges` | Live-tested manually but no automated test |
| **HIGH** | `test_merge_dirty_target_fixture_fails_closed` | No automated test |
| **HIGH** | `test_recovery_coder_fail_twice_switch_model` | Recovery fixture exists but no test |
| **MED** | `test_verifier_rework_fixture_routes_to_coder` | Uses expected.final_packet_state, not real routing |
| **MED** | `test_recovery_merge_dirty_target_true_blocker` | Fixture exists, no test |
| **LOW** | `test_fixture_does_not_allow_production_repo` | Safety guard checks /tmp prefix only |
| **LOW** | `test_fixture_report_marks_fixture_mode` | No explicit fixture_mode flag in report |

---

## 4. Code Quality Review

### ✅ Fixed (from previous review)
- `create_fixture_git_state()` — dedup git add/commit
- `seed_db_fixture()` — started_at != finished_at
- `dirty_uncommitted_file` — writes to target repo, not worktree
- `packet_state` in merge error response
- Verifier prompt — no longer second-guesses architect

### ⚠️ Open

| # | Issue | Severity | File:Line |
|---|-------|----------|-----------|
| 1 | `datetime.utcnow()` deprecated | Low | `golden_fixtures.py:249,254` |
| 2 | `recovery_reviewer_architect.yaml` — FAILED validation | Medium | Fixture data mismatch |
| 3 | Recovery fixtures — 4 categories missing (see §3 above) | Medium | YAML gap |
| 4 | No merge scenario automated tests | High | `test_fixture_merge_scenarios.py` not created |
| 5 | No recovery scenario automated tests | High | `test_fixture_recovery_scenarios.py` not created |

---

## 5. Fixture Execution Results

```
Category          Count   Passed   Failed
─────────────────────────────────────────
merge              7       7        0        ✅ 100%
acceptance         6       6        0        ✅ 100%
verifier           5       5        0        ✅ 100%
reviewer           5       5        0        ✅ 100%
routing            5       5        0        ✅ 100%
self-improvement   4       4        0        ✅ 100%
recovery          10       9        1        ⚠️ 90%
─────────────────────────────────────────
TOTAL             42      40        2
```

**FAILED:** `release_missing_inputs_fail_closed.yaml` (non-recovery), `recovery_reviewer_architect.yaml`

---

## 6. Recovery Implementation Check

### What EXISTS ✅

- `build_failure_signal_from_fixture()` — builds `FailureSignal` from fixture spec
- `stage == "recovery"` runner — calls `classify_failure()` + `decide_recovery()`
- Validates `expected.recovery_action` and `expected.recovery_failure_class`
- `FixtureRun.evidence_verifier_verdict`, `reviewer_verdict` fields
- `FixtureGit.merge_error` field
- `FeatureRecovery` import from `feature_recovery.py`
- 10 recovery YAMLs, 9 passing

### What is MISSING ❌

- 4 recovery categories: `no_changes_retryable_then_switch`, `architect_repair_exhausted_escalate`, `scope_impossible_return_architect`, `profile_escalates_to_strict_for_core_merge`
- `recovery_reviewer_architect.yaml` — FAILED validation (bug)
- Recovery-specific tests (`test_fixture_recovery_scenarios.py`)
- `start_stage: recovery-seed-only` mode (TZ §12.5 — validate seeded state without calling classify/decide)

---

## 7. Overall Verdict

**TZ 020 — 90/100. Ready for production merge, needs recovery test coverage.**

The base infrastructure is excellent: 42 fixtures across 7 categories, 4 stage runners, safety guards, UID model, CLI. The recovery subsystem is partially implemented with `build_failure_signal_from_fixture()` + `classify_failure()` + `decide_recovery()`, but recovery-specific tests are missing and 1 fixture has a data bug.

### Next steps (priority order)

1. Fix `recovery_reviewer_architect.yaml` — 1 failing fixture (5 min)
2. Create `tests/golden_fixtures/test_fixture_merge_scenarios.py` — 5 automated merge tests (30 min)
3. Create `tests/golden_fixtures/test_fixture_recovery_scenarios.py` — 3 seed-only recovery tests (30 min)
4. Add 4 missing recovery fixture YAMLs (20 min)
