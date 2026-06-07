# Final Review: `1db1c9c` Retention + Session Resume follow-up

Date: 2026-06-07
Reviewer: ChatGPT
Commit reviewed: `1db1c9c3ad3b462d0235255c152e9aea8ba5e4d5`
Previous follow-up: `docs/work/review-retention-session-resume-followup-c23970b-2026-06-07.md`

## Verdict

**ACCEPT.**

The remaining follow-up items from the previous review are sufficiently addressed in production code. I would not block the work now.

There is one minor test-quality note: the new tests include useful coverage, but they do not fully integration-test the `backend=cli -> command[0] -> extraction backend` path, and two placeholder test classes are present. This is not a blocker for acceptance, but should be cleaned up later.

## Follow-up items checked

### 1. AGY / opencode session extraction kind

Status: **Fixed.**

`AgentRunService.run()` now keeps `backend = executor.get("backend", "cli")`, but if `backend == "cli"`, it derives the actual session extraction kind from `executor["command"][0]` when the command is `agy`, `opencode`, or `codex`.

This resolves the earlier issue where `coder_agy` had `backend: cli`, so `Conversation ID: ...` would not match the generic `cli` extractor.

### 2. Session resume audit trail

Status: **Fixed by alternative design.**

The previous review allowed two valid approaches:

1. populate `RecoveryDecision.resume_session_id/fork_session`, or
2. persist the actual resolved session separately after execution.

The implementation chose option 2: after session resolution and backend execution, `PacketExecutionAdapter._call_executor()` now writes:

```python
result.evidence["session_resume"] = {
    "resume_session_id": resume_session_id,
    "fork": fork,
    "prev_internal_id": prev_internal_id,
}
```

Because `ExecutionResult.to_dict()` includes `evidence`, this should appear in the stored `PacketRun.result_json["legacy_result"]` path used by the run evidence/audit flow.

Remaining non-blocking cleanup: consider removing or documenting the still-inert `RecoveryDecision.resume_session_id` / `fork_session` fields to avoid future confusion.

### 3. Targeted regression tests

Status: **Partially fixed, acceptable.**

New file added:

- `tests/grace_control/services/test_session_resume_followup.py`

It covers:

- agent profile resume fields;
- verifier/context collector never-resume policy;
- AGY direct `Conversation ID` extraction;
- opencode JSON/text session extraction;
- CLI JSON fallback;
- maintenance stale detection from `pkt_xxx-attempt-NNNN` slug;
- active/unknown worktrees not marked stale;
- multiple terminal states marked stale.

Minor gaps:

- no full `AgentRunService.run()` integration test proving `backend=cli` + `command[0] == "agy"` actually selects the `agy` extractor;
- no real test for `session_resume` being present in persisted `PacketRun.result_json`;
- two placeholder test classes remain:
  - `TestTerminalStateCleanup`
  - `TestRecoveryDecisionAudit`

These are test polish issues, not acceptance blockers.

## Final notes

The earlier BLOCKER/MAJOR issues are now resolved enough for merge/acceptance:

- resume fields are propagated from profiles;
- stale maintenance detection works by packet id;
- maintenance paths come from settings;
- fast reject triggers terminal cleanup;
- manual cleanup uses `git worktree remove` + prune;
- session `run_id` uses full `PacketRun.id`;
- fork parent uses internal session id;
- session table detection is SQLAlchemy-based;
- admin sessions path delegates to `SessionStore`;
- AGY session extraction is handled despite `backend: cli`;
- actual resume/fork audit data is persisted in result evidence.

## Non-blocking follow-up suggestion

In a later cleanup commit, replace placeholder tests with either real tests or remove the empty classes, and add one integration test for:

```text
executor = {backend: "cli", command: ["agy", ...]}
stdout = "Conversation ID: conv_123"
=> result.evidence["session_id"] == "conv_123"
```
