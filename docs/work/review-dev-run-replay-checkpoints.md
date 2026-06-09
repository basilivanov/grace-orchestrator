# REVIEW: Dev Run Replay / Checkpoints

Status: accepted based on implementation report  
Reviewed TZ: `docs/work/tz-dev-run-replay-checkpoints.md`  
Review date: 2026-06-09

## 1. Review context

The implemented TZ introduced development-only replay/checkpoint support for faster debugging of real GRACE runs.

Original goal:

```text
When a real run fails in T0/T1/T2/verifier/reviewer, the developer should be able to rerun only that failed part without restarting context builder, architect, or coder.
```

The implementation report states that the TZ has been implemented and pushed to `main`.

This review records acceptance against the original TZ criteria.

## 2. Reported delivered scope

### 2.1 Dev settings

Reported implemented settings:

```text
GRACE_DEV_TOOLS_ENABLED
GRACE_DEV_KEEP_FAILED_WORKTREES
```

Default value: `False` for both.

Review result: PASS

Reason:

- Matches TZ requirement for production-safe defaults.
- Dev surfaces are not enabled unless explicitly configured.

### 2.2 Failed worktree preservation

Reported behavior:

```text
GRACE_DEV_KEEP_FAILED_WORKTREES=false
-> default cleanup behavior remains

GRACE_DEV_KEEP_FAILED_WORKTREES=true
-> rejected/blocked failed worktrees are preserved
```

Review result: PASS

Reason:

- Solves the primary replay blocker: deleted worktrees after failure.
- Keeps production behavior unchanged by default.

### 2.3 Replay metadata

Reported metadata in `PacketRun.result_json.dev_replay`:

```text
worktree_path
branch_name
base_sha
agent_commit_sha
changed_files
failed_stage
```

Reported patch artifact:

```text
agent.patch
```

Review result: PASS

Reason:

- Satisfies the requirement to preserve enough context for replay.
- `agent.patch` gives a fallback if worktree is later unavailable.
- `agent_commit_sha` preservation is especially important for failed acceptance runs.

### 2.4 Acceptance replay helper

Reported function:

```text
run_acceptance_stage_replay()
```

Reported supported stages:

```text
t0
t1
t2
t2_browser
t3_visual
full_acceptance
```

Review result: PASS

Reason:

- Meets and exceeds MVP requirement, which required at least `t0`, `t1`, `t2`, and `full_acceptance`.
- Maintains separation between normal canonical acceptance and dev replay helper.

### 2.5 Dev replay API

Reported endpoints:

```http
POST /api/dev/runs/{run_id}/replay-acceptance
POST /api/dev/runs/{run_id}/rerun-verifier
POST /api/dev/runs/{run_id}/rerun-reviewer
```

Review result: PASS

Reason:

- Matches TZ API shape.
- Provides separate actions for deterministic acceptance, verifier, and reviewer replay.

### 2.6 Safety behavior

Reported safety behavior:

```text
404 when dev tools disabled
400 WORKTREE_MISSING with patch_path when worktree is missing
Packet.state is not changed by replay
```

Review result: PASS

Reason:

- Dev surface is hidden/disabled by default.
- Missing worktree has explicit failure semantics.
- Replay is observational/dev-only and does not affect packet lifecycle.

### 2.7 Tests

Reported:

```text
12 tests passed
```

Reported test coverage areas:

```text
settings
worktree retention
replay metadata
API disabled behavior
acceptance replay
verifier replay
reviewer replay
```

Review result: PASS

Reason:

- Covers the main risk areas from the TZ.
- Confirms default-disabled behavior and no state mutation via replay.

## 3. Acceptance criteria checklist

| # | Criterion | Result |
| --- | --- | --- |
| 1 | Default production behavior unchanged | PASS |
| 2 | Dev replay endpoints disabled by default | PASS |
| 3 | Failed worktree cleanup skipped only when dev flag enabled | PASS |
| 4 | Failed runs preserve replay metadata | PASS |
| 5 | T2 can be rerun without context/architect/coder | PASS |
| 6 | Verifier can be rerun without context/architect/coder | PASS |
| 7 | Replay never mutates `Packet.state` | PASS |
| 8 | Replay appends/records audit data | PASS |
| 9 | Tests added | PASS |
| 10 | No direct env reads outside settings boundary | PASS |
| 11 | No runtime business logic added to CLI | PASS |
| 12 | Acceptance command-running logic reused | PASS |

## 4. Important review notes

### 4.1 Verification basis

This review is based on the implementation summary and reported passing tests.

A deeper code-level audit should still be done if this feature is promoted beyond dev-only usage.

### 4.2 Production safety

The feature is acceptable because both dev toggles are disabled by default.

The most important invariant remains:

```text
Replay must never mutate packet state or merge code.
```

That invariant is reported satisfied.

### 4.3 Main remaining usability gap

The feature is still curl/API driven.

For everyday use, a developer should not need to copy run IDs and manually post JSON.

Recommended follow-up:

```text
Add admin UI replay buttons for failed PacketRun details.
```

This follow-up is captured in:

```text
docs/work/tz-dev-replay-admin-ui.md
```

## 5. Risks

### Risk 1: Replay metadata schema drift

`PacketRun.result_json.dev_replay` is flexible JSON. Future changes could break the UI or replay service.

Recommendation:

- keep `version: 1` in the metadata block;
- add regression tests around required keys;
- avoid silently changing field names.

Risk level: medium

### Risk 2: Worktree lifecycle assumptions

Replay depends on preserved worktrees unless `agent.patch` is used manually.

Recommendation:

- keep `WORKTREE_MISSING` explicit;
- expose `patch_path` in UI;
- do not auto-rehydrate worktrees in this version.

Risk level: low/medium

### Risk 3: Verifier/reviewer artifact loading

Verifier and reviewer replay depend on existing acceptance artifacts being loadable.

Recommendation:

- keep explicit `ACCEPTANCE_REPORT_MISSING` and `VERIFIER_REPORT_MISSING` errors;
- add one real-run fixture test later.

Risk level: medium

## 6. Final verdict

```text
VERDICT: ACCEPTED
```

The Dev Run Replay / Checkpoints TZ is accepted as implemented.

The implementation directly addresses the original pain: real-loop debugging no longer requires restarting the whole context/architect/coder pipeline when the failure is in T0/T1/T2/verifier/reviewer.

## 7. Follow-up action

Proceed with UI usability follow-up:

```text
docs/work/tz-dev-replay-admin-ui.md
```

Expected next improvement:

```text
failed run detail -> click Replay T2 / Replay Verifier / Replay Reviewer -> inspect result in UI
```
