# .gitignore guidance for projects using GRACE Orchestrator

This document describes files and directories that should be added to
**the target project's** `.gitignore` when GRACE is integrated. GRACE
itself does not write to the target repo, but it creates large ephemeral
directories under `.grace/` that should not be committed.

## What to add to .gitignore

```gitignore
# GRACE Orchestrator — ephemeral runtime data
.grace/worktrees/    # git worktree dirs (per-packet)
/.grace/sessions/    # opencode session metadata (if persisted here)
/.grace/logs/        # local orchestration logs
```

**Do NOT add** `.grace/state/` to `.gitignore` if you want to preserve
run artifacts in version control for evidence / audit. (Most projects
do not; see below.)

## Recommended layout

```
.grace/
├── worktrees/      # ephemeral — ALWAYS gitignore
│   └── <packet_id>/
├── state/          # optional — gitignore if disk is the source of truth
│   └── packets/
│       └── <packet_id>/
│           └── runs/
│               ├── R01/
│               ├── R02/
│               └── ...
└── sessions/       # ephemeral — ALWAYS gitignore
```

## Why gitignore `.grace/worktrees/`?

Per-packet worktrees contain the same files as the target repo, but in
a dirty state with uncommitted agent changes. Committing them would
pollute the repo history and duplicate the file tree.

Worktrees are cleaned up automatically when a packet reaches a terminal
state (REJECTED / FAILED / BLOCKED / MERGED) — see
`TZ_RETENTION_POLICY.md` Phase 1.

## Why gitignore `.grace/sessions/`?

This is where opencode session metadata lives while a packet is being
worked on. Sessions are short-lived and do not need version control.

## Why NOT gitignore `.grace/state/`?

`TZ_RETENTION_POLICY.md` Phase 2 declares that run artifacts
(`coder.log`, `verifier.log`, JSON evidence, output patches) are
**kept forever**. The cost trade-off favours disk retention over
re-running a packet.

You may still add `.grace/state/` to `.gitignore` for the following
reasons:
- The artifacts are large (KBs to MBs per run, GBs over time)
- They contain per-machine data (paths, timestamps) that may not
  reproduce in a different environment
- The git history would be polluted with binary blobs

In that case, ensure you have **out-of-band backup** for `.grace/state/`
(e.g. nightly tar to object storage) so the evidence survives a
machine failure.

## Cleanup policy

Branches of the form `agent/<packet_id>-attempt-<NNNN>` are created in
the **target repo** (not in `.grace/`) when GRACE runs a packet. These
branches are also ephemeral — they are deleted on terminal state.

The agent branches are NOT under `.grace/`, so they are governed by the
target repo's `.git/` and are visible via `git branch`. Use the
**Maintenance** tab in the admin UI to see and clean them up manually.

## Manual cleanup

The Maintenance tab at `/admin?view=maintenance` shows:
- Disk usage (worktrees + state + agent branch count)
- Worktrees (with per-row cleanup button)
- Branches (with per-row delete button)
- A "Clean up all stale" button for bulk cleanup

All cleanup is **manual** — there is no scheduler, no cron, no TTL.
