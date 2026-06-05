# TZ 020 — Staged Golden Fixtures: fast realistic scenario testing for merge/verifier/reviewer/recovery

Audience: Flash coder / literal executor.

Goal: add a fast golden fixture system that can prepare realistic control-plane state, git worktrees, branches, commits, PacketRuns, artifacts, and reports so we can test specific late pipeline stages without rerunning slow architect/coder/agent steps every time.

This is a test/debug infrastructure task. It must not bypass production safety gates and must not change normal feature execution behavior.

Related specs:

```text
docs/codex/tz-016-golden-replay-resume-mode.md
docs/codex/tz-017-feature-recovery-escalation-policy.md
```

---

## 0. Why this is needed

Live golden tests are valuable because they validate the full end-to-end path:

```text
YAML → architect plan → worker claim → coder/agent → worktree writes → acceptance → verifier/reviewer → merge
```

But when a bug is near the end of the pipeline, rerunning the whole chain is too slow.

Example pain:

```text
agent already wrote files
acceptance already passed
merge fails
fix merge code
rerun takes 5–7+ minutes just to reach merge again
```

We need staged golden fixtures that can start from a prepared realistic stage:

```text
acceptance fixture → start at acceptance
verifier fixture   → start at verifier
reviewer fixture   → start at reviewer
merge fixture      → start at merge
blocked fixture    → start at release/retry/block handling
recovery fixture   → start at recovery decision / escalation policy
```

The fixture must be realistic enough to catch DB/git/worktree/branch/commit/report mismatches, especially merge bugs and feature-recovery routing bugs.

---

## 1. Conceptual model

There are three test layers:

```text
1. Live Golden
   Slow, full end-to-end, uses real architect/coder/agent.

2. Staged Golden Fixtures
   Medium-fast, creates realistic DB + git + artifacts state and starts at selected stage.

3. Unit/Integration tests
   Fast, isolated functions/classes, usually mocks git/API/LLM.
```

Do not replace live golden tests. Add staged fixtures to debug and regression-test specific layers quickly.

For feature reliability, staged fixtures must let us test the future `TZ 017` recovery policy with realistic states:

```text
rejected packet with one failed coder attempt
rejected packet with two failed coder attempts
verifier returned REWORK_TO_CODER
verifier returned RETURN_TO_ARCHITECT
reviewer returned REWORK_TO_CODER
merge failed with dirty target repo
blocked packet retry denied
architect repair attempts exhausted
```

---

## 2. Hard safety rules

Staged golden fixtures are test-only.

Allowed only when all are true:

```text
1. CLI flag --golden-fixture is present
2. env GRACE_GOLDEN_FIXTURE=1 is set
3. state_root/worktree_root/target_repo_root are under /tmp/grace-fixtures/ or another explicitly allowed test root
4. fixture file is under fixtures/golden/ or grace/features/golden-fixtures/
5. target repo is a generated fixture repo or explicitly marked test-only
```

If any condition is false:

```text
fail closed with clear error
```

Never run fixture seeding against a production repo or normal self-improvement repo.

Never disable acceptance, scope guard, merge validation, dirty repo checks, reviewer rules, or recovery safety blockers.

---

## 3. Terminology

```text
Fixture scenario
  A YAML/JSON description of the desired starting state and expected outcome.

Fixture seed
  Code that creates DB rows, git repo/worktree/branch/commit, artifacts, reports.

Start stage
  The stage where the test begins: acceptance/verifier/reviewer/merge/release/retry/recovery.

Generated target repo
  A temporary git repository created under /tmp for fixture testing.

Fixture report
  JSON report describing created IDs, paths, commits, start stage, outcome.
```

---

## 4. Suggested file layout

Add:

```text
fixtures/golden/
  merge_clean_success.yaml
  merge_dirty_target_repo.yaml
  merge_missing_worktree.yaml
  merge_missing_branch.yaml
  merge_no_changes.yaml
  acceptance_scope_violation.yaml
  acceptance_frozen_scope_violation.yaml
  verifier_rework_to_coder.yaml
  verifier_return_to_architect.yaml
  reviewer_rework_to_coder.yaml
  reviewer_return_to_architect.yaml
  blocked_release.yaml
  retry_blocked_packet.yaml
  self_improvement_strict_gate.yaml

  # Recovery/stability fixtures for TZ-017
  recovery_coder_fail_once_retry_same.yaml
  recovery_coder_fail_twice_switch_model.yaml
  recovery_coder_fail_four_times_return_architect.yaml
  recovery_architect_repair_exhausted_escalate.yaml
  recovery_verifier_rework_to_coder.yaml
  recovery_verifier_return_to_architect.yaml
  recovery_reviewer_rework_to_coder.yaml
  recovery_reviewer_return_to_architect.yaml
  recovery_merge_dirty_target_true_blocker.yaml
  recovery_merge_transient_retry.yaml
  recovery_blocked_retry_denied.yaml
  recovery_unknown_first_retryable.yaml

src/grace_control/core/golden_fixtures.py
src/grace_control/cli/golden_fixtures.py  # or integrate into existing CLI
scripts/golden_fixtures/README.md         # optional run examples

tests/golden_fixtures/
  test_fixture_seed_models.py
  test_fixture_merge_scenarios.py
  test_fixture_verifier_reviewer_scenarios.py
  test_fixture_recovery_scenarios.py
  test_fixture_safety_guards.py
```

If current CLI organization prefers one `cli/main.py`, implement there but keep fixture logic in `core/golden_fixtures.py`.

---

## 5. CLI commands

Add commands or subcommands under existing `grace` CLI.

Preferred shape:

```bash
grace golden fixture create fixtures/golden/merge_clean_success.yaml \
  --run-id merge-clean-001 \
  --state-root /tmp/grace-fixtures/merge-clean-001/state \
  --worktree-root /tmp/grace-fixtures/merge-clean-001/worktrees \
  --target-repo-root /tmp/grace-fixtures/merge-clean-001/target-repo \
  --report /tmp/grace-fixtures/merge-clean-001/fixture-report.json \
  --golden-fixture
```

Run from prepared stage:

```bash
grace golden fixture run fixtures/golden/merge_clean_success.yaml \
  --run-id merge-clean-001 \
  --from merge \
  --state-root /tmp/grace-fixtures/merge-clean-001/state \
  --worktree-root /tmp/grace-fixtures/merge-clean-001/worktrees \
  --target-repo-root /tmp/grace-fixtures/merge-clean-001/target-repo \
  --report /tmp/grace-fixtures/merge-clean-001/run-report.json \
  --golden-fixture
```

Convenience one-shot:

```bash
grace golden fixture run-one fixtures/golden/merge_clean_success.yaml \
  --run-id merge-clean-001 \
  --from merge \
  --base-dir /tmp/grace-fixtures/merge-clean-001 \
  --golden-fixture
```

Recovery fixture example:

```bash
export GRACE_GOLDEN_FIXTURE=1

grace golden fixture run-one fixtures/golden/recovery_coder_fail_twice_switch_model.yaml \
  --base-dir /tmp/grace-fixtures/recovery-coder-switch \
  --from recovery \
  --golden-fixture
```

MVP can implement only `run-one` if simpler:

```text
run-one = create fixture state + execute from selected stage + produce report
```

---

## 6. Fixture YAML schema

Create a Pydantic model for fixture specs.

Example:

```yaml
id: merge_clean_success
kind: golden_fixture
start_stage: merge
profile: FAST

feature:
  title: Merge clean success
  slug: merge-clean-success
  self_improvement: false

wave:
  title: Merge wave
  order: 1

packet:
  title: Add fixture file
  slug: add-fixture-file
  state: accepted
  acceptance_profile: FAST
  scope:
    - sandbox/golden/merge_clean_success/
  frozen_scope:
    - src/grace_control/core/acceptance_pipeline.py
  verification:
    t0: []
    t1: ["python3 -m pytest sandbox/golden/merge_clean_success/test_fixture_file.py -q"]
    t2: []

git:
  init_target_repo: true
  base_branch: main
  create_worktree: true
  create_branch: true
  branch_name: agent/default/pkt_fixture/attempt-0001
  commit_message: fixture agent commit
  changed_files:
    - path: sandbox/golden/merge_clean_success/fixture_file.py
      content: |
        def answer():
            return 42
    - path: sandbox/golden/merge_clean_success/test_fixture_file.py
      content: |
        from fixture_file import answer
        def test_answer():
            assert answer() == 42

runs:
  - attempt: 1
    status: accepted
    domain_status: accepted
    acceptance_report:
      final_verdict: accepted
      summary: fixture acceptance passed
    artifacts:
      - name: stdout.log
        type: log
        content: "pytest passed\n"
      - name: acceptance_report.json
        type: json
        content_json:
          final_verdict: accepted
          summary: fixture acceptance passed

expected:
  final_packet_state: merged
  merge_should_succeed: true
  expected_files_in_target:
    - sandbox/golden/merge_clean_success/fixture_file.py
```

Do not require users to provide generated UIDs in fixture YAML. Fixture seeder should generate:

```text
feature_id = feat_...
wave_id = wave_...
packet_id = pkt_...
run_id = run_... or canonical PacketRun format
```

YAML should use title/slug for readability, UID for generated state only.

---

## 7. Recovery fixture YAML extension

Recovery/stability fixtures support `start_stage: recovery` and must create the exact failure history that `TZ 017` needs.

Example:

```yaml
id: recovery_coder_fail_twice_switch_model
kind: golden_fixture
start_stage: recovery
profile: NORMAL

feature:
  title: Recovery coder switch
  slug: recovery-coder-switch

wave:
  title: Recovery wave
  order: 1

packet:
  title: Fix small API bug
  slug: fix-small-api-bug
  state: rejected
  acceptance_profile: NORMAL
  scope:
    - sandbox/golden/recovery_coder_switch/
  verification:
    t0: []
    t1: ["python3 -m pytest sandbox/golden/recovery_coder_switch/test_api.py -q"]
    t2: []

failure_signal:
  failure_class_hint: retryable_coder
  reason: "T1 failed twice"
  acceptance_verdict: rework_required
  coder_attempt_count: 2
  attempt_count: 2
  current_executor_id: coder-flash
  previous_executor_ids:
    - coder-flash
    - coder-flash

runs:
  - attempt: 1
    status: rejected
    executor_id: coder-flash
    result_json:
      acceptance_report:
        final_verdict: rework_required
        summary: T1 failed
  - attempt: 2
    status: rejected
    executor_id: coder-flash
    result_json:
      acceptance_report:
        final_verdict: rework_required
        summary: T1 failed again

expected:
  recovery:
    failure_class: retryable_coder
    action: switch_coder
    next_executor_hint_any_of:
      - coder-agy-flash
      - coder-agy-sonnet
    must_not_block_feature: true
    must_not_lower_acceptance_profile: true
```

The fixture runner does not need to implement recovery policy itself unless `TZ 017` is already implemented. It must at least be able to seed these states and later call `decide_recovery(...)` when available.

If `feature_recovery.py` is not implemented yet, recovery fixtures can be validated as seed/preflight fixtures only and marked pending for execution.

---

## 8. Fixture report schema

Every fixture run writes a JSON report:

```json
{
  "fixture_id": "merge_clean_success",
  "run_id": "merge-clean-001",
  "start_stage": "merge",
  "feature_id": "feat_...",
  "wave_id": "wave_...",
  "packet_id": "pkt_...",
  "target_repo_root": "/tmp/grace-fixtures/.../target-repo",
  "worktree_path": "/tmp/grace-fixtures/.../worktrees/pkt_...",
  "branch_name": "agent/default/pkt_.../attempt-0001",
  "base_sha": "...",
  "agent_commit_sha": "...",
  "artifact_dir": "...",
  "expected": {},
  "actual": {},
  "status": "passed"
}
```

Recovery fixture report adds:

```json
{
  "recovery": {
    "failure_signal": {},
    "expected_decision": {},
    "actual_decision": {},
    "status": "passed"
  }
}
```

This report must make debugging possible without searching logs.

---

## 9. Realistic DB state requirements

Seeder must create real DB rows using existing SQLAlchemy models or repository helpers, not raw ad hoc SQL unless there is no alternative.

Required rows for most scenarios:

```text
Feature
Wave
Packet
PacketRun or run equivalent
Event rows if event model exists
Artifact metadata rows if artifact model exists
```

Minimum required logical fields:

```text
Feature.id = feat_...
Feature.slug/title/status
Wave.id = wave_...
Wave.feature_id = feat_...
Packet.id = pkt_...
Packet.feature_id/wave_id
Packet.state
Packet.acceptance_profile
Packet.spec_json with scope/frozen_scope/verification
PacketRun.status/result_json/attempt_number
```

For merge scenarios, `PacketRun.result_json` or equivalent must include whatever merge endpoint actually needs:

```text
worktree_path
branch_name
agent_commit_sha / commit_sha
acceptance_report_path
acceptance_verdict
acceptance_summary
target_repo_root if required
```

For recovery scenarios, Packet/PacketRun/result_json must include enough data to build `FailureSignal` from `TZ 017`:

```text
feature_id
packet_id
packet_state
domain_status
reason
acceptance_verdict
evidence_verifier_verdict
reviewer_verdict
merge_error
blocked_reason
acceptance_profile
attempt_count
coder_attempt_count
architect_repair_count
reviewer_reject_count
verifier_reject_count
merge_attempt_count
current_executor_id
previous_executor_ids
changed_files
```

The goal is to match production contract, not fake around it.

---

## 10. Realistic git state requirements

Merge fixtures must create real git state:

```text
initialized target repo under /tmp
base branch
base commit
agent branch
worktree path
changed files on agent branch
agent commit sha
clean/dirty target repo state depending scenario
```

Do not simulate merge with only DB rows.

For merge success scenario:

```text
target repo clean
branch exists
worktree exists
commit exists
changed files are committed
merge endpoint should merge branch into target repo
```

For dirty target scenario:

```text
target repo has uncommitted change
merge endpoint should fail closed with DIRTY_TARGET_REPO or equivalent
```

For missing branch:

```text
DB references branch_name
branch does not exist
merge endpoint should fail clearly
```

For missing worktree:

```text
DB references worktree_path
path missing
merge endpoint should fail clearly
```

For no changes:

```text
agent branch has no diff from base
merge should reject no_changes or equivalent
```

---

## 11. Artifact fixture requirements

Artifacts should be real files under fixture state root.

Example layout:

```text
/tmp/grace-fixtures/<run-id>/state/artifacts/<packet_id>/attempt-0001/
  stdout.log
  stderr.log
  acceptance_report.json
  evidence.json
  diff.patch
  screenshot.png
```

Artifact metadata should match current artifact API expectations.

If artifact API expects `run_id = R01` or `packet_id-R01`, fixture must create data that exercises both if compatibility is supported.

Add regression scenario:

```text
artifact_run_id_double_prefix_regression
```

Expected: endpoint must not look for `packet_id-packet_id-R01`.

---

## 12. Start stage behavior

Fixture runner should support starting from:

```text
acceptance
verifier
reviewer
merge
release
retry
blocked
recovery
```

MVP required stages:

```text
merge
verifier
reviewer
acceptance
recovery-seed-only
```

### 12.1 Start from acceptance

Create:

```text
Feature/Wave/Packet in running or accepted-precheck state
worktree/branch/files present
legacy_result-like data present if required
```

Run deterministic acceptance only and then continue according to profile if requested.

### 12.2 Start from verifier

Create:

```text
accepted acceptance_report
worktree/branch/commit/artifacts present
PacketRun result_json contains acceptance report
```

Run Evidence Verifier only or verifier + subsequent flow depending command.

### 12.3 Start from reviewer

Create:

```text
acceptance_report accepted
verifier_report PASS or skipped according to profile
STRICT profile if reviewer is required
```

Run reviewer and verify output routing.

### 12.4 Start from merge

Create:

```text
packet accepted or reviewer-passed
worktree/branch/commit present
merge payload complete
```

Call merge path and verify result.

### 12.5 Start from recovery

Create:

```text
Feature/Wave/Packet/PacketRun history representing a known failure pattern
failure_signal fixture payload
optional worktree/artifacts if failure depends on git/acceptance reports
```

If `feature_recovery.py` exists:

```text
build FailureSignal from seeded state
call classify_failure(...)
call decide_recovery(...)
validate expected recovery decision
```

If `feature_recovery.py` is not yet implemented:

```text
validate seeded DB/result_json/failure_signal only
mark execution as pending_recovery_policy
```

---

## 13. Required scenario set

Implement fixture specs for at least these scenarios.

### 13.1 Merge scenarios

```text
merge_clean_success
merge_dirty_target_repo
merge_missing_worktree
merge_missing_branch
merge_no_changes
merge_conflict
merge_already_merged_or_already_applied
```

### 13.2 Acceptance scenarios

```text
acceptance_scope_clean_success
acceptance_scope_violation
acceptance_frozen_scope_violation
acceptance_t1_failure
acceptance_t2_failure
acceptance_output_files_present
```

### 13.3 Verifier scenarios

```text
verifier_pass
verifier_rework_to_coder
verifier_return_to_architect
verifier_invalid_json_retryable
verifier_missing_evidence
```

### 13.4 Reviewer scenarios

```text
reviewer_pass_strict
reviewer_rework_to_coder
reviewer_return_to_architect
reviewer_invalid_json_retryable
reviewer_blocks_unsafe_self_improvement
```

### 13.5 Routing/blocking scenarios

```text
blocked_release_no_retry
retry_rejected_packet_allowed
retry_blocked_packet_denied
release_missing_inputs_fail_closed
return_to_architect_sets_blocked_or_architect_state
```

### 13.6 Self-improvement scenarios

```text
self_improvement_strict_gate_pass
self_improvement_fast_profile_rejected_or_escalated
self_improvement_missing_required_gate
self_improvement_reviewer_required
```

### 13.7 Feature recovery / stability scenarios for TZ-017

These fixtures directly test the future Feature Recovery / Escalation Policy from `docs/codex/tz-017-feature-recovery-escalation-policy.md`.

Coder retry/model-switch fixtures:

```text
recovery_coder_fail_once_retry_same
  state: one rejected attempt, retryable coder failure
  expected: RETRY_SAME_CODER

recovery_coder_fail_twice_switch_model
  state: two rejected attempts by coder-flash
  expected: SWITCH_CODER, next_executor_hint not coder-flash

recovery_coder_fail_four_times_return_architect
  state: four coder failures, deterministic acceptance still failing
  expected: RETURN_TO_ARCHITECT

recovery_no_changes_retryable_then_switch
  state: repeated no_changes_produced failures
  expected: first retry coder, then switch coder/model
```

Architect escalation fixtures:

```text
recovery_scope_impossible_return_architect
  state: verifier/reviewer indicates scope impossible without expanding allowed scope
  expected: RETURN_TO_ARCHITECT

recovery_architect_repair_once_retry_packet
  state: one architect repair already happened, new corrected packet exists
  expected: continue/retry packet, not true blocker

recovery_architect_repair_exhausted_escalate
  state: architect_repair_count >= 2 and packet still impossible
  expected: ESCALATE_ARCHITECT
```

Verifier fixtures:

```text
recovery_verifier_rework_to_coder
  state: evidence_verifier_verdict=REWORK_TO_CODER
  expected: RETRYABLE_CODER → coder ladder

recovery_verifier_return_to_architect
  state: evidence_verifier_verdict=RETURN_TO_ARCHITECT
  expected: ARCHITECT_REPACK_NEEDED → RETURN_TO_ARCHITECT

recovery_verifier_invalid_json_retry
  state: verifier parser/invalid JSON failure, verifier_reject_count=1
  expected: RETRY_VERIFIER

recovery_verifier_invalid_json_escalate
  state: repeated verifier parser failures
  expected: ESCALATE_ARCHITECT or switch verifier if registry supports it
```

Reviewer fixtures:

```text
recovery_reviewer_rework_to_coder
  state: reviewer_verdict=REWORK_TO_CODER
  expected: RETRYABLE_CODER → coder ladder

recovery_reviewer_return_to_architect
  state: reviewer_verdict=RETURN_TO_ARCHITECT
  expected: ARCHITECT_REPACK_NEEDED → RETURN_TO_ARCHITECT

recovery_reviewer_invalid_json_retry
  state: reviewer parser/invalid JSON failure, reviewer_reject_count=1
  expected: RETRY_REVIEWER

recovery_reviewer_invalid_json_escalate
  state: repeated reviewer parser failures
  expected: ESCALATE_ARCHITECT
```

Merge recovery fixtures:

```text
recovery_merge_dirty_target_true_blocker
  state: merge_error=DIRTY_TARGET_REPO
  expected: TRUE_BLOCKER → BLOCK_FEATURE

recovery_merge_conflict_true_blocker
  state: merge conflict
  expected: TRUE_BLOCKER → BLOCK_FEATURE

recovery_merge_transient_retry
  state: transient merge/API error, merge_attempt_count < limit
  expected: MERGE_RETRYABLE → RETRY_MERGE

recovery_merge_retry_limit_blocks
  state: transient merge/API error, merge_attempt_count >= max_merge_retries
  expected: BLOCK_FEATURE

recovery_missing_branch_retry_then_block
  state: missing branch first time vs repeated
  expected: MERGE_RETRYABLE first, then BLOCK_FEATURE
```

True blocker fixtures:

```text
recovery_missing_cli_true_blocker
  state: missing opencode/agy/codex CLI
  expected: TRUE_BLOCKER → BLOCK_FEATURE

recovery_missing_api_key_true_blocker
  state: auth/key missing
  expected: TRUE_BLOCKER → BLOCK_FEATURE

recovery_user_decision_required_blocker
  state: blocked_reason=user decision required
  expected: TRUE_BLOCKER → BLOCK_FEATURE

recovery_security_risk_requires_approval
  state: auth/security/data-loss risk without approval
  expected: TRUE_BLOCKER or STRICT/human approval path, never silent retry
```

Blocked/retry fixtures:

```text
recovery_blocked_retry_denied
  state: packet BLOCKED
  expected: retry denied, BLOCK_FEATURE or NO_ACTION according to policy

recovery_rejected_retry_allowed
  state: packet REJECTED with retryable coder failure
  expected: retry/switch according to coder ladder

recovery_return_to_architect_sets_blocked_or_architect_state
  state: verifier/reviewer return_to_architect
  expected: packet exits normal coder retry loop and routes to architect
```

Unknown failure fixtures:

```text
recovery_unknown_first_retryable
  state: unknown failure first occurrence
  expected: UNKNOWN_RETRYABLE and retry once

recovery_unknown_repeated_escalates
  state: repeated unknown failure
  expected: ESCALATE_ARCHITECT or TRUE_BLOCKER depending safety
```

Acceptance profile safety fixtures:

```text
recovery_strict_profile_never_downgraded
  state: STRICT packet failure
  expected: next_acceptance_profile is STRICT or stricter-equivalent, never NORMAL/FAST

recovery_profile_escalates_to_strict_for_core_git_merge
  state: NORMAL packet touches worker/git/merge/core safety path
  expected: next_acceptance_profile STRICT if policy supports escalation
```

MVP for recovery fixtures:

```text
1. Seed-only fixtures for all recovery scenario classes.
2. Executable `decide_recovery(...)` validation only after TZ-017 implementation lands.
3. At minimum, implement executable tests for:
   - recovery_coder_fail_once_retry_same
   - recovery_coder_fail_twice_switch_model
   - recovery_coder_fail_four_times_return_architect
   - recovery_merge_dirty_target_true_blocker
   - recovery_blocked_retry_denied
```

MVP may implement only merge scenarios first, but file structure and models must allow all recovery fixtures.

---

## 14. Expected result validation

Each fixture YAML has an `expected` section.

Supported checks:

```yaml
expected:
  final_packet_state: merged
  final_feature_state: running
  merge_should_succeed: true
  expected_error_contains: null
  expected_events:
    - packet_merged
  forbidden_events:
    - packet_retried
  expected_files_in_target:
    - sandbox/golden/merge_clean_success/fixture_file.py
  forbidden_files_in_target:
    - src/grace_control/core/acceptance_pipeline.py
  expected_report_fields:
    acceptance_verdict: accepted
  recovery:
    failure_class: retryable_coder
    action: switch_coder
    next_executor_hint_any_of:
      - coder-agy-flash
      - coder-agy-sonnet
    must_not_block_feature: true
    must_not_lower_acceptance_profile: true
```

Fixture runner must validate expected results and fail with clear diff.

---

## 15. Integration with golden replay/resume

This TZ complements `TZ 016 — Golden-only replay/resume mode`.

Difference:

```text
Golden replay/resume:
  reuses checkpoints from a previous real run.

Staged golden fixtures:
  creates known state from a fixture spec without waiting for previous real run.
```

They can share helpers:

```text
fingerprint validation
checkpoint writing
state_root layout
safety guard env/flag checks
report format
```

But fixture seeding must be explicit and test-only.

---

## 16. Integration with Feature Recovery TZ

This TZ directly supports `TZ 017 — Feature Recovery / Escalation Policy`.

Recovery policy tests should use fixture states to validate:

```text
coder failed once → retry same coder
coder failed twice → switch coder/model
coder failed four times → return to architect
verifier returned RETURN_TO_ARCHITECT → architect repack
reviewer returned REWORK_TO_CODER → coder ladder
merge dirty target → true blocker
merge transient error → retry merge
blocked packet retry denied
unknown failure first time → retryable once
repeated unknown failure → escalate/block
STRICT packet → never downgrade acceptance profile
```

Do not implement recovery policy here. Only prepare fixtures that can test it once `feature_recovery.py` exists.

The fixture layer must expose a helper usable by recovery tests:

```python
def seed_recovery_fixture(spec, db, base_dir) -> SeededFixture:
    ...

def build_failure_signal_from_fixture(seeded: SeededFixture) -> FailureSignal:
    ...
```

If `FailureSignal` is not importable yet, keep fixture failure-signal payload as plain dict and document the intended mapping.

---

## 17. UID model requirements

Use current UID model:

```text
Feature.id = feat_<nanoid>
Wave.id = wave_<nanoid>
Packet.id = pkt_<nanoid>
```

Fixture YAML should not hardcode generated IDs.

Reports should print generated UIDs.

Do not parse title/slug/order into IDs.
Do not create old `FEAT-...-W01-P01...` IDs.

Add tests:

```text
test_fixture_generated_ids_use_uid_prefixes
test_fixture_yaml_does_not_require_ids
test_fixture_runner_does_not_parse_w01_p01_from_ids
```

---

## 18. Scope/frozen scope requirements

Even in fixture worktrees:

```text
agent/generated changes may only be inside packet scope
frozen_scope must still block writes
```

Fixtures must include both clean and violating scenarios.

For clean scenario:

```text
changed files all inside scope
no files inside frozen_scope
```

For scope violation:

```text
changed file outside allowed scope
acceptance must reject
```

For frozen scope violation:

```text
changed file matches frozen_scope
acceptance must reject/block according to current policy
```

Do not weaken scope guard for fixtures.

---

## 19. API/DB seeding design

Do not blindly insert partial rows.

Preferred implementation order:

```text
1. Create pure fixture models from YAML.
2. Create generated target repo and git state.
3. Create DB rows using existing models/session helpers.
4. Create PacketRun/result_json/artifact files.
5. Validate fixture state before running stage.
6. Run selected stage.
7. Validate expected outcome.
8. Write fixture report.
```

Add preflight validation:

```text
DB row exists for feature/wave/packet
packet_id in DB matches report
worktree_path exists if required
branch exists if required
commit_sha exists if required
artifact paths exist if required
target repo clean/dirty as scenario requires
recovery failure_signal can be built from seeded state if start_stage=recovery
```

If preflight fails, fixture should fail as `fixture_setup_failed`, not as pipeline failure.

---

## 20. Test-only generated repos

Generated repo layout:

```text
/tmp/grace-fixtures/<run-id>/
  target-repo/
  state/
  worktrees/
  reports/
```

The target repo should be initialized with minimal files:

```text
README.md
pyproject.toml or pytest-compatible minimal config if needed
sandbox/golden/.gitkeep
```

When scenario needs tests, write minimal test files into branch/worktree.

Do not use the real control-plane repo as target for staged fixtures unless an explicit `--allow-current-repo-fixture` flag is added later. For MVP, do not add that flag.

---

## 21. Commands should be deterministic

Avoid randomness in expected contents. UIDs can be random, but reports should capture them.

Use fixed timestamps only in tests if needed.

Allow `--seed` optionally for deterministic NanoID in tests, but not required in MVP.

Do not rely on wall-clock delays.

---

## 22. Tests required

Create tests:

```text
tests/golden_fixtures/test_fixture_safety_guards.py
tests/golden_fixtures/test_fixture_seed_models.py
tests/golden_fixtures/test_fixture_git_state.py
tests/golden_fixtures/test_fixture_merge_scenarios.py
tests/golden_fixtures/test_fixture_artifacts.py
tests/golden_fixtures/test_fixture_recovery_scenarios.py
```

### Safety tests

```text
test_fixture_requires_env_flag
test_fixture_requires_cli_flag
test_fixture_rejects_non_tmp_target_repo
test_fixture_rejects_non_fixture_path
test_fixture_does_not_allow_production_repo
test_fixture_report_marks_fixture_mode
```

### Seed/model tests

```text
test_fixture_creates_feature_wave_packet_with_uid_ids
test_fixture_creates_packet_run_with_result_json
test_fixture_creates_acceptance_report_artifact
test_fixture_preflight_fails_missing_worktree
test_fixture_preflight_fails_missing_branch
test_fixture_creates_recovery_failure_signal_payload
```

### Git state tests

```text
test_fixture_initializes_target_repo
test_fixture_creates_branch_and_commit
test_fixture_clean_merge_has_diff_from_base
test_fixture_dirty_target_repo_is_dirty
test_fixture_no_changes_has_no_diff
```

### Merge scenario tests

```text
test_merge_clean_success_fixture_merges
test_merge_dirty_target_fixture_fails_closed
test_merge_missing_worktree_fixture_fails_clear
test_merge_missing_branch_fixture_fails_clear
test_merge_no_changes_fixture_rejects
```

### Verifier/reviewer scenario tests

```text
test_verifier_rework_fixture_routes_to_coder
test_verifier_return_architect_fixture_routes_to_architect
test_reviewer_rework_fixture_routes_to_coder
test_reviewer_return_architect_fixture_routes_to_architect
test_self_improvement_strict_fixture_requires_reviewer
```

### Feature recovery fixture tests

If `feature_recovery.py` exists:

```text
test_recovery_coder_fail_once_retry_same
test_recovery_coder_fail_twice_switch_model
test_recovery_coder_fail_four_times_return_architect
test_recovery_architect_repair_exhausted_escalate
test_recovery_verifier_rework_to_coder
test_recovery_verifier_return_to_architect
test_recovery_reviewer_rework_to_coder
test_recovery_reviewer_return_to_architect
test_recovery_merge_dirty_target_true_blocker
test_recovery_merge_transient_retry
test_recovery_blocked_retry_denied
test_recovery_unknown_first_retryable
test_recovery_strict_profile_never_downgraded
```

If `feature_recovery.py` does not exist yet:

```text
test_recovery_fixture_seed_coder_fail_twice_switch_model
test_recovery_fixture_seed_merge_dirty_target_true_blocker
test_recovery_fixture_seed_blocked_retry_denied
```

MVP may initially add only safety + seed + merge tests, but must leave fixture specs/TODOs for verifier/reviewer/recovery.

---

## 23. Acceptance criteria

Done only if:

```text
1. Fixture specs live under fixtures/golden/.
2. CLI can create/run at least merge_clean_success fixture.
3. CLI requires both --golden-fixture and GRACE_GOLDEN_FIXTURE=1.
4. Fixture runner refuses non-/tmp target repos.
5. Fixture runner creates real target git repo, branch, worktree, commit.
6. Fixture runner creates real Feature/Wave/Packet/PacketRun state.
7. Fixture runner creates artifact files and report JSON.
8. merge_clean_success starts at merge and succeeds without architect/coder.
9. merge_dirty_target_repo starts at merge and fails closed.
10. merge_missing_worktree fails with clear setup/merge error.
11. merge_missing_branch fails with clear setup/merge error.
12. generated IDs use feat_/wave_/pkt_ UID model.
13. scope/frozen_scope are still enforced in acceptance fixtures.
14. expected outcome validation is implemented.
15. recovery fixture specs exist for coder retry/model-switch, architect repack/escalation, verifier/reviewer routing, merge true blocker/retryable, blocked retry denied, unknown failure, and strict profile no-downgrade.
16. recovery seed/preflight can create FailureSignal-compatible payloads.
17. tests do not run real LLMs, opencode, agy, or architect.
18. normal live golden path remains unchanged.
```

---

## 24. Do not do in this task

```text
Do not replace live golden tests.
Do not run real architect/coder/LLM in staged fixtures.
Do not seed production DB or production repo.
Do not bypass acceptance/scope/merge/reviewer validation.
Do not use old deterministic FEAT/W/P IDs.
Do not require generated UIDs in fixture YAML.
Do not implement recovery policy here.
Do not auto-resolve merge conflicts.
Do not add manual mark-stage-passed override.
Do not make recovery fixtures lower acceptance_profile.
Do not treat true blockers as retryable just to keep tests moving.
```

---

## 25. Suggested implementation order

```text
1. Add fixture Pydantic models.
2. Add safety guard assert_golden_fixture_allowed(...).
3. Add generated target repo helper.
4. Add DB seed helper for Feature/Wave/Packet/PacketRun.
5. Add artifact/report helper.
6. Add preflight validation.
7. Add run-one CLI for merge_clean_success.
8. Add merge dirty/missing/no_changes fixtures.
9. Add tests for safety/seed/git/merge.
10. Add recovery fixture schema extension and seed-only recovery fixtures.
11. Add placeholder fixture specs for acceptance/verifier/reviewer/self-improvement.
12. After TZ-017 lands, wire recovery fixtures to `classify_failure(...)` and `decide_recovery(...)`.
```

---

## 26. Example MVP command set

```bash
export GRACE_GOLDEN_FIXTURE=1

grace golden fixture run-one fixtures/golden/merge_clean_success.yaml \
  --base-dir /tmp/grace-fixtures/merge-clean-success \
  --from merge \
  --golden-fixture

cat /tmp/grace-fixtures/merge-clean-success/reports/run-report.json
```

Recovery seed-only example:

```bash
export GRACE_GOLDEN_FIXTURE=1

grace golden fixture run-one fixtures/golden/recovery_coder_fail_twice_switch_model.yaml \
  --base-dir /tmp/grace-fixtures/recovery-coder-switch \
  --from recovery \
  --golden-fixture

cat /tmp/grace-fixtures/recovery-coder-switch/reports/run-report.json
```

Expected runtime should be seconds, not minutes.

---

## 27. Final coder report format

Coder must report:

```text
Files changed
Fixture models added: yes/no
Safety guards added: yes/no
Generated target repo helper added: yes/no
DB seed helper added: yes/no
Artifact/report helper added: yes/no
Preflight validation added: yes/no
CLI run-one added: yes/no
Merge clean fixture added: yes/no
Merge failure fixtures added: yes/no
Recovery fixture schema added: yes/no
Recovery seed fixtures added: yes/no
Verifier/reviewer fixture placeholders added: yes/no
Tests added
Tests run
Remaining blockers
```
