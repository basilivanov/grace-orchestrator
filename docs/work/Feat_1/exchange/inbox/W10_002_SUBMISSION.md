---
feature_id: Feat_1
wave_id: W10
submission_attempt: 2
status: READY_FOR_REVIEW
created_at: 2026-06-16T18:00:00Z
---

# W10 Submission (attempt 2): Fix _real_shell() for shell=False

## Rework Summary

The reviewer identified that W10 attempt 1 changed `_real_shell()` from `shell=True` to `shell=False` without properly handling the string-to-argv conversion. With `shell=False`, a string command is treated as the executable path itself, causing all selftest git commands to fail as `FileNotFoundError` instead of executing correctly.

## Fix Applied

### 1. `_real_shell()` now uses `shlex.split()` to convert string commands to argv lists

**File:** `src/grace_control/runtime/agent_runtime_selftest.py`

The `_real_shell()` function now splits the command string using `shlex.split()` before passing the resulting argv list to `subprocess.run(shell=False)`. This preserves the existing string-based call API that callers and test mocks depend on, while correctly executing commands without a shell.

```python
def _real_shell(cmd: str) -> tuple[int, str, str]:
    """Run a command string without a shell.

    The command string is split via shlex.split() into an argv list
    before being passed to subprocess.run(shell=False).  This avoids
    shell injection while preserving the string-based call API that
    existing callers (and test mocks) rely on.
    """
    try:
        argv = shlex.split(cmd)
        if not argv:
            return 1, "", "empty command"
        r = subprocess.run(
            argv, shell=False, capture_output=True, text=True, timeout=30,
        )
        return r.returncode, r.stdout.strip(), r.stderr.strip()
    except subprocess.TimeoutExpired:
        return 1, "", "timeout"
    except FileNotFoundError:
        return 127, "", "binary not found"
    except ValueError as exc:
        # shlex.split can raise on malformed input
        return 2, "", f"shell parse error: {exc}"
```

### 2. Replaced `_quote()` with `shlex.quote()` for proper path handling

**File:** `src/grace_control/runtime/agent_runtime_selftest.py`

The old `_quote()` function was a shell-style single-quote escaper designed for `shell=True`. It did not handle spaces in paths correctly. Replaced with `shlex.quote()` which properly quotes all special characters, and `shlex.split()` correctly parses the quoted path back into a single argv element.

- `_quote(s)` → `shlex.quote(s)` in all git command call sites
- Removed the `_quote()` function (replaced by comment explaining the change)

### 3. Removed shell redirections (`2>/dev/null`) from all call sites

**File:** `src/grace_control/runtime/agent_runtime_selftest.py`

Shell redirections like `2>/dev/null` are shell syntax that do not work with `shell=False`. Since `subprocess.run(capture_output=True)` already captures stderr, the redirections were unnecessary. Removed from all 5 call sites:

| Call site | Before | After |
|-----------|--------|-------|
| Git root check | `git -C {_quote(root)} rev-parse --show-toplevel 2>/dev/null` | `git -C {shlex.quote(root)} rev-parse --show-toplevel` |
| Dirty worktree check | `git -C {_quote(root)} status --porcelain 2>/dev/null` | `git -C {shlex.quote(root)} status --porcelain` |
| OpenCode binary check | `command -v opencode 2>/dev/null` | `which opencode` |
| OpenCode auth check | `opencode auth list 2>/dev/null` | `opencode auth list` |
| OpenCode model check | `opencode models 2>/dev/null` | `opencode models` |

### 4. Replaced `command -v` with `which`

`command -v` is a shell builtin and cannot be executed with `subprocess.run(shell=False)`. Replaced with `which opencode`, which is a real binary executable that works without a shell.

### 5. Added 3 regression tests

**File:** `tests/test_w10_remove_legacy_defaults.py`

| Test | Description |
|------|-------------|
| `test_real_shell_runs_git_command_with_shell_false` | Creates a temp git repo, runs `git rev-parse --show-toplevel` via `_real_shell()`, asserts the output matches the repo root. Proves `_real_shell()` correctly splits and executes the command. |
| `test_real_shell_handles_path_with_spaces` | Creates a temp git repo in a path with spaces, uses `shlex.quote()` in the command string, runs `git rev-parse` via `_real_shell()`, asserts success. Proves `shlex.quote()` + `shlex.split()` pipeline handles paths with spaces correctly. |
| `test_selftest_git_check_passes_with_real_repo` | Creates a temp git repo, constructs a real `AgentRuntimeContract`, runs `AgentRuntimeSelftest()` with the default `_real_shell` runner (no mock), asserts `CHECK_GIT_ROOT_EQUALS_WORKTREE_ROOT` passes. This is the exact scenario the reviewer requested. |

## Acceptance Checklist

- [x] `_real_shell()` no longer broken for its callers — shlex.split() correctly converts string commands to argv
- [x] `shell=False` is maintained (no regression to `shell=True`)
- [x] All call sites updated: shell redirects removed, `_quote()` → `shlex.quote()`, `command -v` → `which`
- [x] Regression coverage proves `_real_shell()` can successfully run a git command with `shell=False`
- [x] Regression coverage proves selftest `CHECK_GIT_ROOT_EQUALS_WORKTREE_ROOT` passes against a real repo

## Test Results

```
tests/test_w05_evidence_contract.py .............. (14 passed)
tests/test_w06_process_command_hardening.py ........... (11 passed)
tests/test_w07_worker_error_handling.py ................ (16 passed)
tests/test_w08_stuck_scanner.py .......... (10 passed)
tests/test_w09_profile_cleanup.py ........ (8 passed)
tests/test_w10_remove_legacy_defaults.py ........ (8 passed)
Total: 67 passed
```

Existing selftest tests also verified:
```
tests/grace_control/runtime/test_agent_runtime_selftest.py .................... (28 passed)
```

## Changed Files

- `src/grace_control/runtime/agent_runtime_selftest.py` — `_real_shell()` uses `shlex.split()` for argv conversion; `_quote()` replaced by `shlex.quote()`; shell redirects removed; `command -v` replaced by `which`
- `tests/test_w10_remove_legacy_defaults.py` — 3 regression tests added (8 total)

## Known Limitations

- `LEGACY_FIELD_MAP` in `core/prompts/__init__.py` still exists for canonicalization of old LLM outputs (unchanged from attempt 1).
- `which` may not be available on all minimal Linux installations, but it is standard on all mainstream distributions and CI environments. If needed, a future change could use `shutil.which()` as a Python-native fallback.
