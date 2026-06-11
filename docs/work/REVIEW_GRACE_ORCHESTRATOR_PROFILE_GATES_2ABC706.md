# Review: GRACE orchestrator profile-gates fix at 2abc706

## Verdict

**REWORK REQUIRED**

Commit `2abc70672e8af162eb3ea507edfd759d2d903387` fixes one important part of the previous review: `resolve_default_t2()` now receives `profile`, and T2 defaults are empty for FAST/NORMAL. However, the profile matrix is still not fully correct because T1 defaults still run for FAST whenever target repo `scripts/guardrails.sh` exists.

Reviewed commit:

```text
2abc70672e8af162eb3ea507edfd759d2d903387
fix: profile gates — T2 defaults only for STRICT, FAST/NORMAL get empty T2
```

## What is fixed

### Fixed: T2 defaults are gated by profile

`resolve_default_t2()` now accepts `profile` and returns empty commands unless `profile == "STRICT"`.

This fixes the previous major problem where FAST/NORMAL could receive T2 strict defaults.

New tests were added for:

```text
FAST + guardrails.sh -> no T2 defaults
NORMAL + guardrails.sh -> no T2 defaults
STRICT + guardrails.sh -> strict T2 default
```

This part is good.

## Blocking finding 1: FAST still runs T1 normal defaults

### Problem

The intended matrix is:

```text
FAST   -> T0 only
NORMAL -> T0 + T1
STRICT -> T0 + T1 + T2
```

But `resolve_default_t1()` still ignores profile entirely.

Current behavior:

```python
def resolve_default_t1(changed_files, worktree_path):
    guardrails = _detect_guardrails(base)
    if guardrails:
        commands.append(["bash", f"scripts/{guardrails}", "normal"])
        origins.append("auto:t1:guardrails_normal")
        return commands, origins
```

Because `_run_t1()` calls `resolve_default_gates(...)` for every profile, FAST packets will still run `bash scripts/guardrails.sh normal` when target repo has guardrails.

That violates the matrix and makes FAST potentially expensive.

### Required fix

Make T1 profile-aware too.

Expected behavior:

```text
FAST:
  T1 defaults = []

NORMAL:
  T1 defaults = guardrails normal / area defaults

STRICT:
  T1 defaults = guardrails normal / area defaults
```

Implementation options:

1. Change signature:

```python
def resolve_default_t1(changed_files, worktree_path, profile="NORMAL"):
    if profile == "FAST":
        return [], []
```

and call it from `resolve_default_gates()` with profile.

2. Or filter T1 defaults in `_run_t1()` before execution.

Preferred: option 1, keep policy inside `gate_resolver.py`.

### Required tests

Add tests:

```text
resolve_default_t1(..., profile="FAST") returns [] even with guardrails.sh
resolve_default_gates(..., profile="FAST") returns empty t1/t2 defaults
FAST pipeline with guardrails.sh present skips T1 and T2
NORMAL pipeline with guardrails.sh present runs T1 normal and skips T2
STRICT pipeline with guardrails.sh present runs T1 normal and T2 strict
```

## Major finding 2: profile comparison is string-literal fragile

### Problem

`resolve_default_t2()` checks:

```python
if profile != "STRICT":
    return commands, origins
```

If caller passes `AcceptanceProfile.STRICT` instead of string, this may fail depending on enum behavior and normalization. Current call passes `packet.acceptance_profile.value`, so current path is okay, but resolver is a public core helper and should normalize defensively.

### Suggested fix

Add helper:

```python
def _profile_value(profile) -> str:
    return getattr(profile, "value", profile).upper()
```

Use it in T1/T2 resolution.

## Major finding 3: dead `full` fallback remains unreachable

### Problem

`_detect_guardrails()` returns only `"guardrails.sh"` if the file exists. Then `resolve_default_t2()` checks the same file existence and returns strict. The fallback to `full` is still unreachable.

Current code:

```python
guardrails = _detect_guardrails(base)
if guardrails:
    strict_script = ["bash", f"scripts/{guardrails}", "strict"]
    if (base / "scripts" / guardrails).is_file():
        commands.append(strict_script)
        return commands, origins
    commands.append(["bash", f"scripts/{guardrails}", "full"])
```

The `full` branch cannot execute.

### Required fix

Either:

1. Remove the fallback and document strict as the required stable target repo interface.
2. Or implement real capability detection.

Given our direction, simplest is:

```text
if scripts/guardrails.sh exists -> run strict for STRICT profile
if it fails at runtime -> acceptance fails
```

No fake fallback.

## Existing findings not addressed by this patch

These were not expected to be fixed by this small commit, but remain open from the previous review:

1. Frontend lint absence still does not fail closed for NORMAL/STRICT.
2. Explicit string command normalization still appears risky if string verification commands are used.
3. Pipeline-level tests for FAST/NORMAL/STRICT command routing are still needed.

## Acceptance criteria for next patch

Before accepting the orchestrator auto-gates matrix, the next commit must show:

```text
FAST:
  T0 auto gates only
  T1 skipped unless explicit extra verification is intentionally allowed
  T2 skipped

NORMAL:
  T0 auto gates
  T1 auto normal/defaults
  T2 skipped unless explicit extra verification is intentionally allowed

STRICT:
  T0 auto gates
  T1 auto normal/defaults
  T2 auto strict/defaults
```

Also required:

```text
- T1 resolver accepts profile and returns [] for FAST
- T2 resolver keeps profile guard
- resolve_default_gates has tests for all profiles
- acceptance_pipeline has at least one test proving FAST does not execute guardrails normal
```

## Final decision

`2abc706` is a good partial fix, but not accepted yet.

The remaining blocker is that FAST still auto-runs T1 normal defaults when guardrails.sh exists. This must be fixed before the profile matrix can be considered safe.
