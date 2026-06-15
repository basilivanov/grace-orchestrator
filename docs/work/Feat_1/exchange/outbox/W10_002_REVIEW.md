---
feature_id: Feat_1
wave_id: W10
submission_attempt: 2
reviewer: active_reviewer_architect
decision: APPROVED
reviewed_commit: 66346ee
created_at: 2026-06-16T00:00:00Z
---

# Review: W10 attempt 2

Decision: APPROVED

Reviewed submission: `docs/work/Feat_1/exchange/inbox/W10_002_SUBMISSION.md`
Reviewed commit: `66346ee`

The W10 rework closes the blocker from `W10_001_REVIEW.md`.

Verified:

- `_real_shell()` now preserves the string-based selftest API while safely executing with `shell=False` by converting the command string to argv using `shlex.split()`.
- Empty commands, missing binaries, timeouts, and malformed shell-like input now produce explicit return codes/messages.
- Git selftest call sites now use `shlex.quote(...)` and no longer rely on shell redirection syntax.
- OpenCode binary detection now uses `which opencode` instead of shell builtin `command -v`.
- Regression tests prove `_real_shell()` can run real git commands with `shell=False`.
- Regression tests cover repository paths containing spaces.
- Regression tests run `AgentRuntimeSelftest()` with the production `_real_shell` against a real temporary git repo and assert `CHECK_GIT_ROOT_EQUALS_WORKTREE_ROOT` passes.
- Attempt 1 W10 behavior remains intact: duplicate settings cleanup, selected architect profile legacy schema cleanup, observable exception logging, static guards against broad executable scope defaults, and lease-fencing regression checks.

Non-blocking notes carried forward:

1. `LEGACY_FIELD_MAP` remains for compatibility with old LLM outputs. This is acceptable for W10 but should be removed once all outputs are confirmed canonical.
2. Some W10 guards are still static regex scans. Later hardening should add runtime packet-build/API tests for broad default scope and stale/missing lease release behavior.
3. `which` is acceptable for current Linux/CI environments, but a future cleanup could use `shutil.which()` to remove one external dependency from the selftest.

W10 is approved. Proceed to W11.
