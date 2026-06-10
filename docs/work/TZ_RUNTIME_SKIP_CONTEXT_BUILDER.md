# TZ: Runtime handling for `skip_context_builder`

Date: 2026-06-10
Status: ready for coder
Priority: P0 follow-up after scoped_copy smoke PASS
Scope: executor/profile runtime behavior
Related:
- `docs/work/TZ_MINIMAL_WORKTREE_AND_CONTEXT_BUILDER.md`
- `docs/work/TZ_LIVE_FIXTURE_SCOPED_COPY_SMOKE.md`
- `docs/work/REPORT_LIVE_FIXTURE_SCOPED_COPY_SMOKE.md`

## 1. Context

The scoped-copy live fixture smoke has passed.

We proved:

```text
coder-opencode-fixture uses scoped_copy workspace
workspace contains only fixture files
workspace report is persisted in result_json
no GRACE repo leakage
no kernel OOM
API stayed alive
packet reached accepted
```

The next gap is `skip_context_builder`.

The profile already contains:

```yaml
coder-opencode-fixture:
  minimal_repo: true
  skip_context_builder: true
```

But the runtime must explicitly honor this flag wherever context collection is invoked.

## 2. Goal

Make `skip_context_builder: true` a real runtime contract.

When an executor profile has:

```yaml
skip_context_builder: true
```

then GRACE must not run the context collector / context-builder stage for that packet attempt.

The run should go directly to packet materialization / executor run using the existing `packet_markdown` input.

## 3. Non-goals

Do not implement the full bounded `agent_context_builder` in this task.
Do not implement GRACE Canon digest in this task.
Do not implement Solar Sage support in this task.
Do not implement `target_repo_worktree` in this task.
Do not change `scoped_copy` apply-back semantics.
Do not turn `skip_context_builder` on for all profiles.
Do not remove the context collector profile.
Do not change the admin UI.

This task only makes the existing profile flag effective and observable.

## 4. Required behavior

### 4.1 Executor profile flag

Profiles may define:

```yaml
skip_context_builder: true
```

Default behavior:

```text
missing / false => existing behavior unchanged
true => skip context collection before execution
```

### 4.2 Runtime must honor the flag

Find the code path that invokes context collection before or during packet execution.

Likely areas to inspect:

```text
src/grace_control/adapters/packet_executor.py
src/grace_control/agent/universal_cli_backend.py
src/grace_control/services/agent_run_service.py
src/grace_control/services/packet_materializer.py
src/grace_control/config/agent_profiles.yaml
```

The implementation should be placed at the narrowest correct boundary:

- If context collection is part of packet materialization, skip it there.
- If it is part of executor selection/pre-run orchestration, skip it there.
- If it is part of a dedicated context service, skip it there.

Do not add broad hacks in unrelated layers.

### 4.3 Evidence must show the decision

Every run should record whether context builder was used or skipped.

For skipped runs, persist something like:

```json
{
  "context_builder": {
    "skipped": true,
    "reason": "executor.skip_context_builder=true",
    "executor_id": "coder-opencode-fixture"
  }
}
```

For non-skipped runs, if easy, persist:

```json
{
  "context_builder": {
    "skipped": false
  }
}
```

At minimum, skipped runs must be visible in result/evidence.

### 4.4 Logs must be explicit

Emit a structured log when context builder is skipped:

```text
context_builder_skipped packet_id=<...> executor_id=<...> reason=executor.skip_context_builder
```

This is important because otherwise the only proof is absence of a context-collector process.

### 4.5 No accidental behavior change for normal profiles

Normal profiles such as:

```text
coder-opencode
```

must preserve existing behavior unless they explicitly set `skip_context_builder: true`.

The fixture profile:

```text
coder-opencode-fixture
```

should skip context builder.

## 5. Acceptance criteria

Accepted when:

1. `skip_context_builder: true` is read from executor profile at runtime.
2. Context collector is not invoked for `coder-opencode-fixture`.
3. Normal profiles keep existing context behavior.
4. Evidence/result JSON records context builder skipped reason.
5. Structured log records skip decision.
6. Existing scoped_copy fixture smoke still passes.
7. Existing test suite passes.

## 6. Tests required

Add focused tests. Use existing test style and file locations.

### 6.1 Unit test: flag true skips context builder

Create a test that configures an executor with:

```python
{"executor_id": "coder-opencode-fixture", "skip_context_builder": True}
```

Assert that the context collector/context builder call is not made.

Mock/spy the context service call if needed.

### 6.2 Unit test: flag missing/false preserves behavior

Create a test with normal executor profile:

```python
{"executor_id": "coder-opencode"}
```

Assert existing context path is still called, or at least no skip evidence is recorded.

### 6.3 Evidence test

Assert run result/evidence contains:

```json
"context_builder": {
  "skipped": true,
  "reason": "executor.skip_context_builder=true"
}
```

for the fixture executor.

### 6.4 Profile test

Assert:

```text
coder-opencode-fixture skip_context_builder == true
coder-opencode skip_context_builder is absent/false
```

### 6.5 Live smoke regression

Re-run or update the live fixture smoke path to confirm:

```text
workspace_mode=scoped_copy
context_builder.skipped=true
no context collector process/session is created for fixture run
```

## 7. Manual verification command

After implementation, run the fixture smoke again with:

```bash
PYTHONPATH=.:tests_live/fixtures/apps \
GRACE_LIVE_AGENT_TESTS=1 \
GRACE_DEV_TOOLS_ENABLED=1 \
GRACE_DATABASE_URL="sqlite:////tmp/grace-live-test.db" \
GRACE_TARGET_REPO_ROOT="/tmp/grace-live-test" \
python3 -u tests_live/runner/wave_resume_runner.py \
  --scenario backend-1w \
  --agent-profile coder-opencode-fixture \
  --timeout 240
```

Expected report fields:

```text
workspace.workspace_mode=scoped_copy
workspace.commit_semantics=workspace_only
context_builder.skipped=true
context_builder.reason=executor.skip_context_builder=true
packet state=accepted
no OOM
API alive
```

## 8. Output report

After implementation and smoke, create/update a report:

```text
docs/work/REPORT_RUNTIME_SKIP_CONTEXT_BUILDER.md
```

Report must include:

```text
commit tested
profile used
packet/run id
whether context builder was invoked
evidence JSON snippet for context_builder
workspace JSON snippet
memory/OOM/API observation
pass/fail verdict
```

## 9. What remains after this task

After this task passes, the next planned work is:

```text
1. target_repo_worktree mode
2. first Solar Sage pilot using target_repo_worktree
3. bounded agent_context_builder
4. GRACE Canon digest / prompt minimization
5. scoped_copy apply-back for real repos
```

Do not mix those into this patch.
