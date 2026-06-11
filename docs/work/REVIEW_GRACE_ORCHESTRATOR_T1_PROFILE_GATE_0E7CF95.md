# Review: GRACE orchestrator T1 profile-gate fix at 0e7cf95

## Verdict

**PARTIAL ACCEPT / REWORK STILL REQUIRED**

Commit `0e7cf9534b1027da964734ee4324d8ac2cb437bb` fixes the specific blocker from `REVIEW_GRACE_ORCHESTRATOR_PROFILE_GATES_2ABC706.md`: FAST no longer receives default T1 commands when `scripts/guardrails.sh` exists.

However, the overall auto-gates matrix is not fully accepted yet because older blockers remain in the pipeline implementation, especially explicit string command normalization and fail-closed behavior for missing frontend GRACE lint in NORMAL/STRICT.

Reviewed commit:

```text
0e7cf9534b1027da964734ee4324d8ac2cb437bb
fix: T1 profile gate — FAST gets no T1 defaults, only NORMAL/STRICT
```

## What is fixed

### Fixed: FAST gets no T1 defaults

`resolve_default_t1()` now accepts `profile` and returns empty command/origin lists when `profile == "FAST"`.

Expected behavior now holds:

```text
FAST + scripts/guardrails.sh present -> no auto T1 defaults
```

`resolve_default_gates()` now passes `profile` into both T1 and T2 resolvers.

### Fixed: test coverage for T1 FAST default suppression

A test was added:

```text
test_t1_fast_returns_empty_even_with_guardrails
```

This proves the direct resolver-level behavior for FAST + guardrails.

## Current matrix status

Based on `gate_resolver.py` after this commit:

```text
FAST:
  T0 defaults: yes
  T1 defaults: no
  T2 defaults: no

NORMAL:
  T0 defaults: yes
  T1 defaults: yes
  T2 defaults: no

STRICT:
  T0 defaults: yes
  T1 defaults: yes
  T2 defaults: yes
```

This is now aligned with the intended high-level profile matrix.

## Remaining blocker 1: explicit string commands are still broken

### Problem

`acceptance_pipeline.py` still normalizes explicit architect commands like this:

```python
all_cmds = list(t1_defaults) + [list(c) if isinstance(c, str) else c for c in explicit]
```

and similarly for T2:

```python
all_cmds = list(t2_defaults) + [list(c) if isinstance(c, str) else c for c in explicit]
```

If architect/packet verification contains a string command, e.g.:

```python
"python3 -m pytest -q"
```

then `list(c)` turns it into a list of characters:

```python
["p", "y", "t", "h", "o", "n", "3", ...]
```

`CommandRunner.run()` supports strings directly, so this conversion is wrong and can make `extra_verification` unusable.

### Required fix

Replace both T1 and T2 normalization with:

```python
def _normalize_command(c):
    return c if isinstance(c, str) else list(c)
```

Then:

```python
all_cmds = list(t1_defaults) + [_normalize_command(c) for c in explicit]
```

Add tests:

```text
explicit verification.t1 string command remains a string and runs through CommandRunner string path
explicit verification.t2 string command remains a string and runs through CommandRunner string path
```

## Remaining blocker 2: frontend lint absence still does not fail closed for NORMAL/STRICT

### Problem

`resolve_default_t0()` still has the policy comment:

```text
If no frontend lint exists and frontend changed, we just warn
(don't fail — some repos manage frontend separately)
```

But there is no warning object and no blocking issue. For NORMAL/STRICT, this should fail closed when frontend files are touched and neither `scripts/grace_front_lint.py` nor legacy `scripts/grace/check-markers.sh` exists.

This is an orchestrator policy issue, separate from SolarSage. SolarSage now has a fail-closed frontend gate, but GRACE should still fail closed for target repos that change frontend files without providing any frontend GRACE lint.

### Required fix

Add fail-closed behavior for NORMAL/STRICT:

```text
frontend touched + no frontend GRACE lint + profile NORMAL/STRICT -> T0 failed with clear blocking issue
frontend touched + no frontend GRACE lint + profile FAST -> warning or explicit skipped mechanical gate
```

Implementation can be done with a typed `GateResolution` containing commands, warnings, and blocking_issues, or by handling it in `_run_t0()` after touched-area detection.

Add tests:

```text
NORMAL frontend change without frontend lint -> T0 fails
STRICT frontend change without frontend lint -> T0 fails
FAST frontend change without frontend lint -> does not claim frontend lint passed
```

## Remaining major issue 3: unreachable `full` fallback in T2 resolver

### Problem

`resolve_default_t2()` still checks only that `scripts/guardrails.sh` exists and then always returns `strict`. The `full` fallback remains unreachable because the same file-existence condition is used.

Current behavior is effectively:

```text
if scripts/guardrails.sh exists -> bash scripts/guardrails.sh strict
else -> no T2 default
```

That is acceptable only if we define `strict` as required stable target-repo interface. If so, remove the unreachable fallback and document the contract. Otherwise implement real capability detection.

### Recommended fix

For now, keep the stable contract simple:

```text
scripts/guardrails.sh strict is required for STRICT target-repo acceptance
```

Remove the dead `full` fallback to avoid misleading reports.

## Remaining major issue 4: profile comparison should be normalized

### Problem

The resolver compares raw strings:

```python
if profile == "FAST":
if profile != "STRICT":
```

The current call path passes `packet.acceptance_profile.value`, so it likely works in the pipeline, but resolver helpers should be robust to enum values and lowercase strings.

### Suggested fix

Add:

```python
def _profile_value(profile) -> str:
    return str(getattr(profile, "value", profile)).upper()
```

Use it in T1/T2 resolution.

## Tests still missing before full acceptance

Add pipeline-level tests, not only resolver-level tests:

```text
FAST + guardrails.sh present:
  T0 runs cheap defaults
  T1 skipped
  T2 skipped

NORMAL + guardrails.sh present:
  T1 runs guardrails normal
  T2 skipped

STRICT + guardrails.sh present:
  T1 runs guardrails normal
  T2 runs guardrails strict
```

Use a fake `CommandRunner` to record commands without executing external scripts.

## Final decision

The specific T1/FAST blocker is fixed and accepted.

The overall auto-gates matrix remains **not fully accepted** until the remaining blocking issues are fixed:

```text
1. explicit string command normalization
2. fail-closed behavior when frontend lint is missing under NORMAL/STRICT
3. pipeline-level profile routing tests
```

After those are fixed, the orchestrator side can be accepted as the runtime counterpart to the now-accepted SolarSage guardrails interface.
