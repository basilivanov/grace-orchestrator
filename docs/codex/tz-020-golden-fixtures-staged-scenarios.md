# TZ 020 — Staged Golden Fixtures: fast realistic scenario testing for merge/verifier/reviewer/recovery

Audience: Flash coder / literal executor.

Goal: add a fast golden fixture system that can prepare realistic control-plane state, git worktrees, branches, commits, PacketRuns, artifacts, and reports so we can test specific late pipeline stages without rerunning slow architect/coder/agent steps every time.

This is a test/debug infrastructure task. It must not bypass production safety gates and must not change normal feature execution behavior.

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
```

The fixture must be realistic enough to catch DB/git/worktree/branch/commit/report mismatches, especially merge bugs.

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

Never disable acceptance, scope guard, merge validation, dirty repo checks, or reviewer rules.

---

## 3. Terminology

```text
Fixture scenario
  A YAML/JSON description of the desired starting state and expected outcome.

Fixture seed
  Code that creates DB rows, git repo/worktree/branch/commit, artifacts, reports.

Start stage
  The stage where the test begins: acceptance/verifier/reviewer/merge/release/retry.

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

src/grace_control/core/golden_fixtures.py
src/grace_control/cli/golden_fixtures.py  # or integrate into existing CLI
scripts/golden_fixtures/README.md         # optional run examples

tests/golden_fixtures/
  test_fixture_seed_models.py
  test_fixture_merge_scenarios.py
  test_fixture_verifier_reviewer_scenarios.py
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

## 7. Fixture report schema

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

This report must make debugging possible without searching logs.

---

## 8. Realistic DB state requirements

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

The goal is to match production contract, not fake around it.

---

## 9. Realistic git state requirements

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

## 10. Artifact fixture requirements

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

## 11. Start stage behavior

Fixture runner should support starting from:

```text
acceptance
verifier
reviewer
merge
release
retry
blocked
```

MVP required stages:

```text
merge
verifier
reviewer
acceptance
```

### 11.1 Start from acceptance

Create:

```text
Feature/Wave/Packet in running or accepted-precheck state
worktree/branch/files present
legacy_result-like data present if required
```

Run deterministic acceptance only and then continue according to profile if requested.

### 11.2 Start from verifier

Create:

```text
accepted acceptance_report
worktree/branch/commit/artifacts present
PacketRun result_json contains acceptance report
```

Run Evidence Verifier only or verifier + subsequent flow depending command.

### 11.3 Start from reviewer

Create:

```text
acceptance_report accepted
verifier_report PASS or skipped according to profile
STRICT profile if reviewer is required
```

Run reviewer and verify output routing.

### 11.4 Start from merge

Create:

```text
packet accepted or reviewer-passed
worktree/branch/commit present
merge payload complete
```

Call merge path and verify result.

---

## 12. Required scenario set

Implement fixture specs for at least these scenarios.

### 12.1 Merge scenarios

```text
merge_clean_success
merge_dirty_target_repo
merge_missing_worktree
merge_missing_branch
merge_no_changes
merge_conflict
merge_already_merged_or_already_applied
```

### 12.2 Acceptance scenarios

```text
acceptance_scope_clean_success
acceptance_scope_violation
acceptance_frozen_scope_violation
acceptance_t1_failure
acceptance_t2_failure
acceptance_output_files_present
```

### 12.3 Verifier scenarios

```text
verifier_pass
verifier_rework_to_coder
verifier_return_to_architect
verifier_invalid_json_retryable
verifier_missing_evidence
```

### 12.4 Reviewer scenarios

```text
reviewer_pass_strict
reviewer_rework_to_coder
reviewer_return_to_architect
reviewer_invalid_json_retryable
reviewer_blocks_unsafe_self_improvement
```

### 12.5 Routing/blocking scenarios

```text
blocked_release_no_retry
retry_rejected_packet_allowed
retry_blocked_packet_denied
release_missing_inputs_fail_closed
return_to_architect_sets_blocked_or_architect_state
```

### 12.6 Self-improvement scenarios

```text
self_improvement_strict_gate_pass
self_improvement_fast_profile_rejected_or_escalated
self_improvement_missing_required_gate
self_improvement_reviewer_required
```

MVP may implement only merge scenarios first, but file structure and models should allow all.

---

## 13. Expected result validation

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
```

Fixture runner must validate expected results and fail with clear diff.

---

## 14. Integration with golden replay/resume

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

## 15. Integration with Feature Recovery TZ

This TZ also supports `TZ 017 — Feature Recovery / Escalation Policy`.

Recovery policy tests can use fixture states later:

```text
coder failed twice → switch coder
verifier returned RETURN_TO_ARCHITECT → architect repack
merge dirty target → true blocker
blocked packet retry denied
```

Do not implement recovery policy here. Only prepare fixtures that can later test it.

---

## 16. UID model requirements

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

## 17. Scope/frozen scope requirements

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

## 18. API/DB seeding design

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
```

If preflight fails, fixture should fail as `fixture_setup_failed`, not as pipeline failure.

---

## 19. Test-only generated repos

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

## 20. Commands should be deterministic

Avoid randomness in expected contents. UIDs can be random, but reports should capture them.

Use fixed timestamps only in tests if needed.

Allow `--seed` optionally for deterministic NanoID in tests, but not required in MVP.

Do not rely on wall-clock delays.

---

## 21. Tests required

Create tests:

```text
tests/golden_fixtures/test_fixture_safety_guards.py
tests/golden_fixtures/test_fixture_seed_models.py
tests/golden_fixtures/test_fixture_git_state.py
tests/golden_fixtures/test_fixture_merge_scenarios.py
tests/golden_fixtures/test_fixture_artifacts.py
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

MVP may initially add only safety + seed + merge tests, but leave TODO fixtures for verifier/reviewer.

---

## 22. Acceptance criteria

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
15. tests do not run real LLMs, opencode, agy, or architect.
16. normal live golden path remains unchanged.
```

---

## 23. Do not do in this task

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
```

---

## 24. Suggested implementation order

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
10. Add placeholder fixture specs for acceptance/verifier/reviewer/self-improvement.
```

---

## 25. Example MVP command set

```bash
export GRACE_GOLDEN_FIXTURE=1

grace golden fixture run-one fixtures/golden/merge_clean_success.yaml \
  --base-dir /tmp/grace-fixtures/merge-clean-success \
  --from merge \
  --golden-fixture

cat /tmp/grace-fixtures/merge-clean-success/reports/run-report.json
```

Expected runtime should be seconds, not minutes.

---

## 26. Final coder report format

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
Verifier/reviewer fixture placeholders added: yes/no
Tests added
Tests run
Remaining blockers
```
