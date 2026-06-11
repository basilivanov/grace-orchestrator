# Review: Stage 0 context-builder bundle contract fix — da93cbd

Date: 2026-06-11
Commit reviewed: `da93cbd83df111d7179f05822c6d6ac0379ef84d`
Verdict: **ACCEPTED FOR PILOT 003 RETRY**

## Summary

The previous blocker from `0334445` is resolved.

The implementation now:

- writes the exact `context_bundle_output_path` into `EXECUTION_PACKET.md`;
- checks that `context-bundle.md` exists and is non-empty after Stage 0;
- fails fast with `CONTEXT_BUILDER_MISSING_BUNDLE` if the file is absent or empty;
- includes a regression test for the fake-success case where the agent exits 0 and prints JSON but does not create the bundle;
- updates the clean-agent mutation test to create the expected bundle file.

## Accepted evidence

`wave_resume_runner.py` now appends the runner-owned bundle output path to the context-builder packet before executing the agent:

```python
prompt_text += f"\n\ncontext_bundle_output_path: {bundle_path}\n"
```

After the agent run and mutation detection, the runner verifies:

```python
bundle_exists = bundle_path.exists()
bundle_nonempty = bundle_exists and bundle_path.stat().st_size > 0
```

If the check fails, the runner touches `MISSING_BUNDLE`, records `CONTEXT_BUILDER_MISSING_BUNDLE`, and stops before architect/coder flow.

## Remaining notes

This is still a P0 read-only guard rather than a true OS-level read-only sandbox. That is acceptable for now because:

- mutations are detected;
- mutation diff evidence is saved;
- target repo is reset/cleaned;
- flow stops before architect/coder submission.

The next validation must be a real Solar Sage pilot 003 retry.

## Required pilot 003 retry evidence

Pilot 003 retry must prove:

- `context_runs >= 1`;
- `context_bundle_path` exists and points to a non-empty file;
- Stage 0 has no target repo mutation;
- architect receives the bundle pointer;
- coder changes only `__tests__/components/TabBar.test.tsx`;
- `pnpm lint` passes with 0 errors;
- `pnpm typecheck` passes;
- `pnpm test:run` passes;
- final report exists.

## Verdict

**ACCEPTED FOR PILOT 003 RETRY.**

Do not call this feature fully accepted until the actual Solar Sage pilot 003 run passes with real `context_runs >= 1` and bundle evidence.
