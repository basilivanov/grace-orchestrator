# Review: auto-gates blockers fix — 53f7680

Date: 2026-06-11
Repository: `basilivanov/grace-orchestrator`
Reviewed commit: `53f76801bad5a9af6c184ca1f17aa85a21c8434b`
Verdict: **ACCEPTED WITH MINOR FOLLOW-UP**

## 1. Summary

Commit `53f7680` closes the three reported auto-gate blockers:

```text
1. explicit string commands no longer become list(c) char arrays
2. NORMAL/STRICT frontend changes now fail closed if no frontend GRACE lint exists
3. pipeline-level FAST/NORMAL/STRICT profile tests were added
```

This is enough to continue Solar Sage pilots.

## 2. Accepted fixes

### 2.1 Explicit string command handling

Accepted.

`_run_t1()` and `_run_t2()` now convert explicit string commands with:

```python
c.split()
```

instead of:

```python
list(c)
```

This fixes the serious bug where a command like:

```text
pnpm typecheck
```

was converted into characters instead of argv tokens.

### 2.2 Profile-aware T0 frontend fail-closed behavior

Accepted.

`resolve_default_t0()` now accepts profile and creates a blocking command for frontend changes when no frontend lint/fallback exists under `NORMAL` or `STRICT`:

```text
auto:t0:frontend_lint_missing
```

This is the correct conservative behavior.

`FAST` remains lightweight.

### 2.3 T0 ruff stays scoped to Python files

Accepted.

The resolver only adds ruff command when changed files include `.py` or `.pyi`:

```python
py_files = [f for f in changed_files if f.endswith(".py") or f.endswith(".pyi")]
...
if py_files:
    commands.append(["python3", "-m", "ruff", "check"] + py_files)
```

This protects TS/TSX frontend pilots from the earlier invalid-syntax failure.

### 2.4 Pipeline-level profile tests

Accepted.

The commit adds pipeline tests for:

```text
FAST skips default T1/T2
FAST runs explicit T1
NORMAL runs T1, not T2
STRICT runs T1 + T2
STRICT fails without guardrails
```

This covers the correct acceptance-profile matrix at pipeline level, not only resolver level.

## 3. Minor follow-up

### M1. Prefer `shlex.split()` over `str.split()` later

Current fix is good enough for normal explicit commands like:

```text
pnpm typecheck
pnpm test:run
python3 scripts/foo.py --flag value
```

But `str.split()` does not preserve quoted shell strings. Example:

```text
python3 -c "print('hello world')"
```

would still split incorrectly.

This is not a blocker for current Solar Sage gates, but a follow-up should replace:

```python
c.split()
```

with:

```python
shlex.split(c)
```

and add tests for quoted command strings.

### M2. Existing fallback `ruff src/` should be revisited later

`AcceptancePipeline._build_t0_commands()` still has legacy fallback:

```python
self._t0_command_template = [["python3", "-m", "ruff", "check", "src/"]]
```

This was not introduced by this commit and is not blocking this review.

But for mixed target repos, a future cleanup should ensure frontend-only repos do not accidentally run Python ruff fallback when no T0 command is appropriate.

## 4. Decision

```text
ACCEPTED WITH MINOR FOLLOW-UP
```

The three requested blockers are closed.

Proceed with Solar Sage flow.

## 5. Required next action

No blocking action before continuing.

Recommended later tech-debt ticket:

```text
TZ_ACCEPTANCE_COMMAND_STRING_SHLEX_SPLIT.md
```

Scope:

```text
replace str.split with shlex.split for explicit verification command strings
add quoted command tests
```
