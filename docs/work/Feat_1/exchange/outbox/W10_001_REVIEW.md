---
feature_id: Feat_1
wave_id: W10
submission_attempt: 1
reviewer: active_reviewer_architect
decision: REWORK_REQUIRED
reviewed_commit: 2c167ab
created_at: 2026-06-16T00:00:00Z
---

# Review: W10 attempt 1

Decision: REWORK_REQUIRED

Reviewed submission: `docs/work/Feat_1/exchange/inbox/W10_001_SUBMISSION.md`
Reviewed commit: `2c167ab`

Good progress:

- Duplicate `opencode_server_url` setting was removed.
- Selected architect profile command text no longer lists legacy schema field names directly.
- Critical `except: pass` / `except Exception: pass` patterns in the packet executor path were replaced with logged observable failures.
- Required W10 tests were added.
- Prior-wave dangerous defaults are checked by regression tests.

Blocking issue:

1. `agent_runtime_selftest._real_shell()` is now broken for its current callers.

   W10 changed `_real_shell()` from `shell=True` to `shell=False`, but the function still accepts a string command:

   ```python
   ShellRunner = Callable[[str], tuple[int, str, str]]

   def _real_shell(cmd: str) -> tuple[int, str, str]:
       r = subprocess.run(
           cmd, shell=False, capture_output=True, text=True, timeout=30,
       )
   ```

   Existing selftest calls still pass shell-style strings, for example:

   ```python
   self._shell(f"git -C {_quote(git_check_root)} rev-parse --show-toplevel 2>/dev/null")
   self._shell(f"git -C {_quote(git_check_root)} status --porcelain 2>/dev/null")
   ```

   With `shell=False`, a string command is treated as the executable path itself, not parsed into argv. That means commands like `git -C /repo rev-parse ...` will fail as `FileNotFoundError` / `binary not found` instead of running git. The runtime selftest will report false failures for valid repos.

   This is not just a style issue: it makes an active runtime diagnostic path unreliable.

   Required fix:

   - Either convert `_real_shell()` to accept `list[str]` argv and update all call sites accordingly;
   - or split the command safely with `shlex.split()` before calling `subprocess.run(..., shell=False)`;
   - or replace this helper with the existing command runner/supervisor pattern that already models no-shell execution.

   Add regression coverage proving `_real_shell()` or the selftest can successfully run a simple git command with `shell=False`, for example by creating a temporary git repo and asserting `CHECK_GIT_ROOT_EQUALS_WORKTREE_ROOT` passes.

Non-blocking notes:

1. The W10 broad regex tests are useful, but they are still mostly static scans. Future hardening should add one runtime test that builds an executable packet and proves no broad default scope is injected.
2. `LEGACY_FIELD_MAP` remains for compatibility. This is acceptable for W10 if it is not selected/active prompt schema, but should be retired once all LLM outputs are canonical.
3. The release fencing test scans function chunks for fencing tokens. Future cleanup should add API-level tests for missing or stale lease fields, not only static token checks.

Required next submission:

`docs/work/Feat_1/exchange/inbox/W10_002_SUBMISSION.md`
