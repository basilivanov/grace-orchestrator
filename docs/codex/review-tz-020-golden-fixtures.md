# Review: TZ 020 — Staged Golden Fixtures

Review of commit range `ca29f8a..8b07ca7` against `/docs/codex/tz-020-golden-fixtures-staged-scenarios.md`.

Date: 2026-06-04

---

## Summary

| Area | Status | Notes |
|------|--------|-------|
| Fixture YAMLs | ✅ 32/32 present | 1 extra (merge_already_applied, merge_conflict beyond TZ 6) |
| Stage runners | ✅ 4/4 (merge, acceptance, verifier, reviewer) | |
| Safety guards | ✅ env + flag + /tmp | |
| Git state | ✅ init, branch, worktree, commit, detach | |
| DB seed | ✅ Feature/Wave/Packet/PacketRun | |
| Artifacts | ✅ files + report JSON | |
| CLI | ✅ `grace golden fixture run-one` | |
| Tests | ⚠️ 14/30+ TZ-required | Missing merge, verifier/reviewer, recovery tests |
| Recovery fixtures | ❌ NOT IMPLEMENTED | TZ §7, §15-21 |
| Live golden path | ✅ unchanged | |

---

## Acceptance Criteria Check (TZ §23)

### ✅ PASS (13/18)

| # | Criterion | Evidence |
|---|-----------|----------|
| 1 | Fixtures under `fixtures/golden/` | 32 YAML files |
| 2 | CLI can run `merge_clean_success` | Live-tested, PASSED |
| 3 | `--golden-fixture` + `GRACE_GOLDEN_FIXTURE=1` | `assert_golden_fixture_allowed()` + tests |
| 4 | Refuses non-`/tmp` repos | Safety guard test `test_requires_tmp_base_dir` |
| 5 | Creates real git repo, branch, worktree, commit | `init_target_repo()` + `create_fixture_git_state()` |
| 6 | Real Feature/Wave/Packet/PacketRun | `seed_db_fixture()` + 4 tests |
| 7 | Artifact files + report JSON | `create_fixture_artifacts()` + `run_fixture()` report |
| 8 | merge_clean_success → merged no architect/coder | Live-tested, PASSED in ~1s |
| 9 | merge_dirty_target_repo → fail closed | Live-tested, DIRTY_TARGET_REPO |
| 10 | merge_missing_worktree → fail clear | Live-tested, "does not exist" |
| 11 | merge_missing_branch → fail clear | Live-tested, "does not exist" |
| 12 | feat_/wave_/pkt_ UID model | `uid.py` + `test_fixture_generated_ids_use_uid_prefixes` |
| 14 | Expected outcome validation | `validate_expected()` + tests |
| 17 | Tests don't run real LLMs | 14 unit tests, zero opencode/agy/architect calls |
| 18 | Live golden path unchanged | All 7 golden tests still pass |

### ⚠️ PARTIAL (2/18)

| # | Criterion | Status |
|---|-----------|--------|
| 13 | scope/frozen_scope enforced in acceptance fixtures | ✅ for 2 acceptance fixtures (scope_clean, scope_violation). ⚠️ T1/T2 failure fixtures not tested live (YAML exists, not executed). |
| 16 | Recovery seed can create FailureSignal payloads | ❌ `FailureSignal` not seeded. `feature_recovery.py` exists but NOT wired into fixture seeder. No `seed_recovery_fixture()` or `build_failure_signal_from_fixture()`. |

### ❌ FAILING (3/18)

| # | Criterion | Status |
|---|-----------|--------|
| 15 | Recovery fixture specs exist for 13 scenarios | 0/13 recovery fixtures created. TZ §15-21 requires: coder retry, architect repack, verifier/reviewer routing, merge blocker, blocked retry, unknown failure, strict no-downgrade. **None implemented.** |

---

## Tests Gap Analysis (TZ §22)

| TZ File | Required | Implemented |
|---------|----------|-------------|
| `test_fixture_safety_guards.py` | 6 tests | ✅ 4 tests in `test_fixture_safety.py` |
| `test_fixture_seed_models.py` | 5 tests | ✅ 4 tests (missing: acceptance_report_artifact, preflight_missing_*) |
| `test_fixture_git_state.py` | 4 tests | ✅ 3 tests in `test_fixture_safety.py:TestGitState` |
| `test_fixture_merge_scenarios.py` | 5 tests | ❌ NOT CREATED |
| `test_fixture_artifacts.py` | — | ✅ 3 tests |
| `test_fixture_recovery_scenarios.py` | 13 tests | ❌ NOT CREATED |

### Missing tests details

| Test | Priority | Notes |
|------|----------|-------|
| `test_fixture_does_not_allow_production_repo` | Low | Safety guard checks `/tmp` prefix, not explicit production paths |
| `test_fixture_report_marks_fixture_mode` | Low | Report has `status` field but no explicit `fixture_mode` flag |
| `test_fixture_creates_acceptance_report_artifact` | Medium | Artifacts work (tested) but acceptance_report specifically not tested |
| `test_merge_clean_success_fixture_merges` | High | Live-tested manually but **no automated test** |
| `test_merge_dirty_target_fixture_fails_closed` | High | Live-tested but **no automated test** |
| `test_verifier_rework_fixture_routes_to_coder` | Medium | Fixture runner uses `expected.final_packet_state` to set verdict, not real routing |
| `test_recovery_coder_fail_twice_switch_model` | High | Recovery fixtures NOT IMPLEMENTED at all |

---

## Code Quality Findings

### 1. `create_fixture_git_state()` — if/else dead code (lines 176-186, FIXED)

```python
if git_cfg.no_commit_diff:
    # same git add + commit as below
    ...
else:
    # duplicate git add + commit
    ...
```

**Verdict:** ✅ Fixed in `798a931`. Now single block with conditional `agent_commit_sha`.

### 2. `seed_db_fixture()` — identical timestamps (line 250, FIXED)

```python
started_at=datetime.utcnow(), finished_at=datetime.utcnow()
```

**Verdict:** ✅ Fixed in `798a931`. Now `started = datetime.utcnow() - timedelta(seconds=30)`.

### 3. `datetime.utcnow()` deprecated (line 249, 254)

Python 3.12 deprecation. Use `datetime.now(datetime.UTC)`.

**Verdict:** ⚠️ 14 warnings in test output. Not a blocker but should be addressed.

### 4. Verifier/reviewer routing — stub logic (lines 377-443)

```python
# Uses expected.final_packet_state to decide PASS/REWORK/ARCHITECT
# Does NOT call real agy/opencode LLM
```

**Verdict:** ✅ Per TZ §17 "tests do not run real LLMs".

### 5. `run_fixture()` — no `--resume` or `--from` reuse (line 341)

Each run creates fresh IDs and state. No mechanism to reuse existing fixture state.

**Verdict:** ⚠️ TZ §19 "Golden replay/resume" integration not implemented.

---

## Recovery Fixtures Gap (TZ §7, §15-21)

The TZ requires:

```text
§7:  Recovery fixture YAML with failure_signal block
§15: Category: retryable_coder (fail once/retry, fail twice/switch, fail 4x/architect)
§16: Category: true_blocker (merge dirty, missing CLI, missing API key, security risk)
§17: Category: blocked_retry_denied
§18: Category: rejected_retry_allowed
§19: Category: return_to_architect_sets_blocked
§20: Category: retryable_merge (transient, retry limit)
§21: Category: unknown_failure_first_retryable
```

**None of these are implemented.** The `feature_recovery.py` file exists in the codebase (from TZ-017) but is NOT wired into the golden fixtures seeder. No `seed_recovery_fixture()`, no `build_failure_signal_from_fixture()`, no recovery YAMLs.

---

## Recommendations

### MUST DO (for TZ §23 compliance)

1. Create 13 recovery fixture YAMLs under `fixtures/golden/recovery_*.yaml`
2. Add `seed_recovery_fixture()` and `build_failure_signal_from_fixture()` to `golden_fixtures.py`
3. Wire `feature_recovery.py` into fixture runner (validate `FailureSignal` → `classify_failure()` → expected decision)

### SHOULD DO (for test coverage)

4. Create `tests/golden_fixtures/test_fixture_merge_scenarios.py` — 5 automated merge tests
5. Create `tests/golden_fixtures/test_fixture_recovery_scenarios.py` — at least 3 seed-only recovery tests
6. Fix `datetime.utcnow()` deprecation

### NICE TO HAVE

7. Add `test_fixture_creates_acceptance_report_artifact`
8. Add `test_fixture_preflight_fails_missing_worktree`
9. Add `--fixture-mode` flag to report JSON
10. Acceptable production repo check in safety guard

---

## Overall Verdict

**TZ 020 is 85% complete.** The core fixture infrastructure (safety, git, DB, artifacts, CLI, 4 stage runners) is solid and well-tested. The 5 merge scenarios work correctly end-to-end via the CLI. The model uses proper UIDs and validates expected outcomes.

The remaining 15% is the **recovery fixture subsystem** (TZ §7, §15-21) — none of the 13 recovery scenarios, the `FailureSignal` integration, or the recovery fixture tests have been implemented. These are explicitly required by acceptance criteria #15 and #16.

The TZ itself (§25 step 10) says "Add recovery fixture schema extension and seed-only recovery fixtures" — this was planned but not executed.

**Score: 85/100 — Passes MVP, needs recovery fixtures for full compliance.**
