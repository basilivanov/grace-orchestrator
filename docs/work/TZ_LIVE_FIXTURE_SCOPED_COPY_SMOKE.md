# TZ: Live fixture smoke for scoped_copy minimal workspace

Date: 2026-06-10
Status: ready for operator/coder
Priority: P0 validation before next architecture work
Scope: live fixture validation only
Related:
- `docs/work/TZ_MINIMAL_WORKTREE_AND_CONTEXT_BUILDER.md`
- `docs/work/TZ_MINIMAL_WORKTREE_SAFETY_POLISH.md`
- `docs/work/REVIEW_MINIMAL_WORKTREE_EC47E41.md`

## 1. Goal

Validate the real runtime behavior of the new minimal workspace path.

We are not adding more architecture in this task. We are proving that the fixture live run now uses a small `scoped_copy` workspace instead of handing the full GRACE repository to `opencode`.

The run must prove:

```text
agent receives scoped_copy workspace
workspace does not include the full GRACE repo
workspace report is persisted in evidence
opencode does not OOM / freeze the host
packet proceeds through coder → acceptance/evidence path
admin UI can show/inspect the workspace result
```

## 2. Non-goals

Do not implement Solar Sage support in this task.
Do not implement `target_repo_worktree` in this task.
Do not implement apply-back from `scoped_copy` to real target repo.
Do not implement bounded `agent_context_builder` in this task.
Do not turn on `minimal_repo` for the default `coder-opencode` profile.
Do not change watchdog/health/admin UI in this task.

This is a live validation task, not a feature expansion task.

## 3. Required setup

Use the fixture/minimal app as the target repo, not the GRACE orchestrator root.

The executor profile must be:

```text
coder-opencode-fixture
```

Do not use the normal profile:

```text
coder-opencode
```

because normal `coder-opencode` should remain safe and non-minimal by default.

Required profile behavior:

```yaml
coder-opencode-fixture:
  minimal_repo: true
  skip_context_builder: true
```

## 4. Required implementation check before running

Before live run, verify the scenario/runner actually selects `coder-opencode-fixture`.

If current scenario configuration does not allow selecting the executor profile, add the smallest possible fixture-only override.

Acceptable options:

1. Scenario fixture config uses `executor_id: coder-opencode-fixture`.
2. Live runner accepts an env var/CLI flag like:

```text
GRACE_LIVE_EXECUTOR_PROFILE=coder-opencode-fixture
```

3. Test-only scenario code maps the fixture coder to `coder-opencode-fixture`.

Rejected options:

- Do not change default `coder-opencode` to minimal.
- Do not hardcode all coder runs globally to minimal.
- Do not make Solar Sage use `scoped_copy` yet.

## 5. Suggested live command

Baseline command shape:

```bash
cd /tmp/grace-orchestrator-export

rm -f /tmp/grace-live-test.db
fuser -k 8042/tcp 2>/dev/null || true
sleep 1

setsid env \
  GRACE_DATABASE_URL="sqlite:////tmp/grace-live-test.db" \
  GRACE_DEV_TOOLS_ENABLED=1 \
  GRACE_FAST_FAIL=1 \
  GRACE_TARGET_REPO_ROOT="/tmp/grace-live-test/backend_fastapi_todo" \
  python3 scripts/api_watchdog.py > /tmp/grace-watchdog.log 2>&1 &

sleep 3
curl -s http://127.0.0.1:8042/health
curl -s http://127.0.0.1:8042/health/liveness

PYTHONPATH=. \
GRACE_LIVE_AGENT_TESTS=1 \
GRACE_DEV_TOOLS_ENABLED=1 \
GRACE_FAST_FAIL=1 \
GRACE_TARGET_REPO_ROOT="/tmp/grace-live-test/backend_fastapi_todo" \
GRACE_LIVE_EXECUTOR_PROFILE="coder-opencode-fixture" \
python3 -u tests_live/runner/wave_resume_runner.py \
  --scenario backend-1w \
  --api-url http://127.0.0.1:8042 \
  --source-dir . \
  --target-dir /tmp/grace-live-test \
  --timeout 900 \
  --keep-artifacts
```

If `GRACE_LIVE_EXECUTOR_PROFILE` does not exist yet, the coder must add a fixture-only equivalent before running.

## 6. Required evidence checks

After the run, inspect the run result/evidence JSON.

It must contain something equivalent to:

```json
{
  "workspace": {
    "workspace_mode": "scoped_copy",
    "workspace_path": "...",
    "target_repo_root": "/tmp/grace-live-test/backend_fastapi_todo",
    "copied_files": [
      {"original": "...", "workspace": "..."}
    ],
    "omitted_files": [],
    "base_sha": "...",
    "commit_semantics": "workspace_only"
  }
}
```

Acceptance:

- `workspace_mode` is `scoped_copy`.
- `commit_semantics` is `workspace_only`.
- `target_repo_root` points to the fixture app, not the GRACE orchestrator repo.
- `workspace_path` is under configured worktree root.
- `copied_files` are target-relative paths.
- no `grace_control`, `packet_executor`, `.git` from the full GRACE repo are present as copied project files.

## 7. Required filesystem checks

After run, inspect the workspace path from evidence.

Run:

```bash
WORKSPACE="<workspace_path_from_evidence>"
find "$WORKSPACE" -maxdepth 4 -type f | sort | sed "s#$WORKSPACE/##" | head -200
```

Expected:

```text
only fixture/task files
minimal config allowlist files such as pyproject.toml if applicable
.git for the minimal repo itself is okay
no full GRACE source tree
no src/grace_control unless the fixture itself intentionally has that path
```

Reject if workspace contains broad GRACE repo files such as:

```text
src/grace_control/...
docs/work/...
tests/grace_control/...
scripts/api_watchdog.py
```

## 8. Required process / memory checks

During and after run, collect:

```bash
tail -200 /tmp/grace-watchdog.log
journalctl -k --since "30 min ago" | grep -Ei 'oom|out of memory|killed process' || true
ps -eo pid,ppid,pgid,sid,user,rss,etime,cmd --sort=-rss | head -60
```

Acceptance:

- no kernel OOM event;
- API stays alive;
- watchdog does not repeatedly restart API;
- opencode/agent process memory is materially lower than the previous full-GRACE-worktree run;
- no system-wide freeze.

## 9. Required admin UI checks

Open:

```text
http://127.0.0.1:8042/admin
```

Verify:

- packet is visible;
- pipeline stage cards are readable;
- current run shows expected timing;
- evidence/result includes workspace report or is inspectable from run details/dev replay.

If admin does not surface workspace report yet, it is acceptable for this smoke if the raw run result JSON contains it. A later admin polish can expose it more clearly.

## 10. Pass criteria

The live smoke passes only if all are true:

1. Fixture run uses `coder-opencode-fixture`.
2. Agent worktree is `scoped_copy`, not a full GRACE worktree.
3. Evidence contains workspace report.
4. Workspace copied files preserve relative paths.
5. Workspace excludes full GRACE repo.
6. Agent process does not OOM/freeze host.
7. API remains alive.
8. Packet reaches at least coder completion + acceptance/evidence path.
9. Admin remains usable.
10. Full test suite still passes after any small runner/scenario changes.

## 11. Fail criteria

Fail immediately if:

- default `coder-opencode` is changed to `minimal_repo: true`;
- workspace contains full GRACE repo;
- evidence has no workspace report;
- `target_repo_root` points to the orchestrator repo for fixture task;
- scoped-copy commit is treated as target repo merge commit;
- API restarts repeatedly during the run;
- OOM appears in kernel logs.

## 12. Expected output from coder/operator

After running, provide a short report in `docs/work`, for example:

```text
docs/work/REPORT_LIVE_FIXTURE_SCOPED_COPY_SMOKE.md
```

Report must include:

```text
commit tested
command used
executor profile used
packet id / run id
workspace_path
workspace copied_files count
omitted_files
whether GRACE repo leaked into workspace
memory/process observation
kernel OOM check result
admin screenshot/description
pass/fail verdict
next recommended step
```

## 13. Next step after pass

If this smoke passes, the next TZ should be:

```text
runtime handling for skip_context_builder
```

Then:

```text
target_repo_worktree mode for first Solar Sage pilot
```

Do not jump straight to Solar Sage `scoped_copy` until apply-back/patch semantics are designed.
