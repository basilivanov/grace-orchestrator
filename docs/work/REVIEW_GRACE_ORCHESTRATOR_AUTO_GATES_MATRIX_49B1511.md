# Review: GRACE orchestrator auto-gates matrix at 49b1511

## Verdict

**REWORK REQUIRED**

The commit implements a useful first slice: `gate_resolver.py`, touched-area detection, automatic default command resolution, and additive command origins. However, the implementation currently violates the intended FAST/NORMAL/STRICT matrix: profile-specific routing is not enforced inside the resolver, so lower profiles can run heavier gates than intended.

Reviewed commit:

```text
49b1511bfa26a45f15dfe9ed197bc0ac90be0182
feat: auto-gates matrix — TouchedArea detection + gate_resolver + T0/T1/T2 auto defaults
```

Compared against previous commit:

```text
1be66e745ff3bbf2fac041b4017c6b80cc307883
```

Changed files:

```text
src/grace_control/core/acceptance_pipeline.py
src/grace_control/core/contracts.py
src/grace_control/core/gate_resolver.py
tests/grace_control/core/test_acceptance_pipeline.py
tests/grace_control/core/test_gate_resolver.py
```

## What is good

1. `StageResult.command_origins` was added, which is the right direction for evidence provenance.
2. `validate_packet_contract()` no longer hard-fails NORMAL/STRICT only because `verification.t1` is missing. This matches the target design where default gates are auto-resolved later.
3. `gate_resolver.py` creates a dedicated place for touched-area and default-gate logic.
4. T0 now delegates default command resolution instead of hardcoding only backend `grace_lint.py` + ruff.
5. Tests were added for touched-area detection and basic resolver outputs.

## Blocking finding 1: profile is ignored by default gate resolution

### Problem

`resolve_default_gates(changed_files, profile, worktree_path)` accepts a `profile`, but the profile is not used to suppress or alter T1/T2 defaults.

Current behavior:

- `resolve_default_t1()` returns `bash scripts/guardrails.sh normal` whenever `scripts/guardrails.sh` exists.
- `resolve_default_t2()` returns `bash scripts/guardrails.sh strict` whenever `scripts/guardrails.sh` exists.
- `_run_t1()` and `_run_t2()` call `resolve_default_gates(...)` for every packet profile.

Result: FAST and NORMAL packets can automatically run strict/full gates through T2 if the target repo has `scripts/guardrails.sh`.

That breaks the desired matrix:

```text
FAST   -> T0 only, no T1/T2 heavy gates
NORMAL -> T0 + T1, no T2 strict by default
STRICT -> T0 + T1 + T2 strict
```

### Required fix

Profile handling must move into the resolver or into `_run_t1/_run_t2` before commands are executed.

Minimum required behavior:

```text
FAST:
  T1 defaults = []
  T2 defaults = []

NORMAL:
  T1 defaults = target normal / area-based defaults
  T2 defaults = [] unless explicit extra_verification.t2 is provided

STRICT:
  T1 defaults = target normal / area-based defaults
  T2 defaults = target strict/full defaults
```

Add regression tests:

```text
FAST + guardrails.sh present -> _run_t1 skips, _run_t2 skips
NORMAL + guardrails.sh present -> _run_t1 runs normal, _run_t2 skips unless explicit
STRICT + guardrails.sh present -> _run_t1 runs normal, _run_t2 runs strict
```

## Blocking finding 2: T2 default resolver always chooses strict when any guardrails.sh exists

### Problem

`resolve_default_t2()` checks only that `scripts/guardrails.sh` exists and then returns:

```bash
bash scripts/guardrails.sh strict
```

It does not verify whether the script actually supports the `strict` command. The fallback to `full` is unreachable because the same file existence condition is checked twice.

### Required fix

Do one of these:

1. Prefer a simple stable contract: if `scripts/guardrails.sh` exists, assume `strict` must be supported and fail at runtime if not supported. Remove the dead `full` fallback.
2. Or implement real capability detection by parsing `scripts/guardrails.sh --help` / dry-running a safe capability command, then select `strict` or `full`.

The current code claims fallback behavior but cannot actually fall back.

Add test:

```text
resolve_default_t2 reports strict only when strict is supported, or clearly documents no fallback.
```

## Major finding 3: frontend lint absence is not enforced for NORMAL/STRICT

### Problem

The TZ required: if frontend changed and no frontend GRACE lint exists, NORMAL/STRICT should fail clearly. Current resolver has a comment saying it will only warn when no frontend lint exists, but it does not return a warning or failure command.

In practice, frontend-only changes without `scripts/grace_front_lint.py` or legacy `scripts/grace/check-markers.sh` may proceed without frontend GRACE marker/size lint.

### Required fix

T0 should produce a failing command or blocking issue when frontend files are changed and no frontend GRACE lint is available for NORMAL/STRICT.

Acceptable design:

- Add a `GateResolution` structure with `commands`, `origins`, `warnings`, `blocking_issues`.
- Or add a synthetic command that fails with clear stderr.
- Or let `_run_t0()` explicitly check missing frontend lint after touched-area detection.

Add test:

```text
NORMAL/STRICT frontend change + no grace_front_lint.py + no check-markers.sh -> T0 fails clearly.
FAST frontend change + no frontend lint -> warning or skipped cheap lint, but not accepted as fully checked.
```

## Major finding 4: explicit string commands are converted to character arrays

### Problem

`_run_t1()` and `_run_t2()` merge explicit architect commands using:

```python
[list(c) if isinstance(c, str) else c for c in explicit]
```

If an explicit command is a string, e.g. `"pnpm test"`, this becomes:

```python
["p", "n", "p", "m", " ", "t", "e", "s", "t"]
```

`CommandRunner.run()` supports command strings directly, so this conversion is wrong.

### Required fix

Use:

```python
[c if isinstance(c, str) else list(c) for c in explicit]
```

or normalize through a helper:

```python
def normalize_command(c):
    return c if isinstance(c, str) else list(c)
```

Add test:

```text
explicit verification string command remains a string and runs through CommandRunner string path.
```

## Major finding 5: tests do not cover pipeline profile routing

### Problem

The new tests verify resolver outputs in isolation, but they do not verify `_run_t1/_run_t2` behavior for FAST/NORMAL/STRICT with `guardrails.sh` present.

This is why the profile-routing bug passed.

### Required fix

Add acceptance pipeline tests with a fake `CommandRunner` that records commands without executing external scripts.

Required cases:

```text
FAST + frontend changed + guardrails.sh present:
  T0 runs cheap lint only
  T1 skipped
  T2 skipped

NORMAL + backend changed + guardrails.sh present:
  T1 runs guardrails normal
  T2 skipped

STRICT + frontend+backend changed + guardrails.sh present:
  T1 runs guardrails normal
  T2 runs guardrails strict
```

## Suggested implementation direction

### Introduce typed gate resolution

Replace raw dicts with dataclasses:

```python
@dataclass(frozen=True)
class GateCommand:
    command: list[str] | str
    origin: str

@dataclass(frozen=True)
class GateResolution:
    t0: list[GateCommand]
    t1: list[GateCommand]
    t2: list[GateCommand]
    touched_areas: list[TouchedArea]
    warnings: list[str]
    blocking_issues: list[str]
```

This removes the risk of command/origin length mismatch and lets missing required gates be represented without fake commands.

### Profile matrix should be explicit

Resolver should have one obvious profile branch:

```python
if profile == "FAST":
    return t0_only
if profile == "NORMAL":
    return t0_plus_t1
if profile == "STRICT":
    return t0_plus_t1_plus_t2
```

### Keep Stage 0 separate

Do not mix Stage 0 context-builder logic with T0/T1/T2 acceptance gates.

## Required actions before acceptance

1. Make `profile` effective in gate resolution.
2. Ensure FAST does not run T1/T2 heavy gates by default.
3. Ensure NORMAL does not run T2 strict by default.
4. Ensure STRICT runs T2 strict/full by default and fails clearly if unavailable.
5. Fix explicit string command normalization.
6. Add pipeline-level tests for FAST/NORMAL/STRICT command routing.
7. Add missing frontend-lint behavior for NORMAL/STRICT.
8. Re-run relevant unit tests and include evidence in the next report.

## Final decision

Do not treat commit `49b1511` as accepted yet.

It is a good architectural direction, but the profile matrix is currently unsafe because strict/full target repo gates can run under FAST/NORMAL due to resolver profile being ignored.
