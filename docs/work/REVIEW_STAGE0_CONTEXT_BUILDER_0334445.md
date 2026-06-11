# Review: Stage 0 built-in context-builder — 0334445

Date: 2026-06-11
Commit reviewed: `033444542a3986e2634ccea557d37bb8684373dc`
Verdict: **REWORK REQUIRED — architecture accepted, but bundle artifact contract is incomplete**

## Summary

The implementation moves context-builder out of the normal coder packet flow and into a built-in Stage 0 before API feature submission. This is the right architectural direction.

Accepted parts:

- `context-builder` role alias added for `context-collector-flash`.
- Stage 0 runs before API feature submission.
- Stage 0 filters context-builder packets out of submitted waves.
- Stage 0 checks clean repo before running.
- Stage 0 detects mutations using `git status`, `git rev-parse HEAD`, and `git diff --exit-code`.
- Stage 0 saves mutation diff evidence and performs `git reset --hard HEAD` + `git clean -fd`.
- Stage 0 injects context bundle metadata into the first non-context-builder packet.
- Tests cover the key intended flows.

However, one blocker remains: Stage 0 reports a `context_bundle_path` even if the bundle file was never actually created by the context-builder.

## Blocker 1 — `context_bundle_path` is reported without verifying file existence

Current code initializes a default `bundle_info` with:

```python
"context_bundle_path": str(bundle_path)
```

but does not check whether `bundle_path.exists()` after the agent run. If opencode returns successful JSON but does not write the markdown bundle, the runner still reports a valid path and continues.

This violates the pilot 003 requirement that `context_bundle_path` must be present **and real**.

Required fix:

```python
if not bundle_path.exists() or bundle_path.stat().st_size == 0:
    self.report["failures"].append(
        f"CONTEXT_BUILDER_MISSING_BUNDLE: {pkt_id} did not create {bundle_path}"
    )
    return []
```

Also save the raw stdout/stderr already collected as evidence, which the code already does.

Acceptance after fix:

- A successful Stage 0 must prove the bundle file exists and is non-empty.
- A fake/nonexistent `context_bundle_path` from agent JSON must not be accepted.
- Add a test where agent exits 0 and prints JSON, but does not create bundle file → Stage 0 fails.

## Blocker 2 — Prompt/path mismatch for bundle output

The runner writes `EXECUTION_PACKET.md` under:

```text
/tmp/grace-context/<scenario_id>/<packet_id>/EXECUTION_PACKET.md
```

and expects:

```text
/tmp/grace-context/<scenario_id>/<packet_id>/context-bundle.md
```

But the packet prompt written to the agent does not include the exact required output path. The generic profile prompt says `/tmp/grace-context/<packet_id>/context-bundle.md`, which does not include `<scenario_id>`, and the scenario prompt does not inject the resolved `bundle_path`.

Required fix:

Append a runner-generated instruction to `EXECUTION_PACKET.md`, for example:

```markdown
## Runner-provided output contract

Write the context bundle markdown exactly here:
`/tmp/grace-context/<scenario_id>/<packet_id>/context-bundle.md`

Your final stdout line must be JSON with:
- context_bundle_path
- context_bundle_url
- context_bundle_summary
- selected_files
- truncated
- missing_context
- warnings
```

Do not rely on the model to infer the path.

## Important non-blocker — wording conflict: read-only cwd vs writing bundle outside cwd

The context-builder prompt says “work only inside cwd” / “do not read outside cwd”, but the bundle is intentionally written outside cwd under `/tmp/grace-context`.

This is okay architecturally, but the prompt should distinguish:

```text
Read only inside cwd/target repo.
Write artifacts only under the provided context_bundle_output_path.
Do not write inside the target repo.
```

Otherwise the agent may either refuse to write the bundle or write into the target repo.

## Important non-blocker — `real_agent_runs` now includes context-builder

Stage 0 increments both:

```python
context_runs += 1
real_agent_runs += 1
```

This is not necessarily wrong, because context-builder is a real agent run. But reports must avoid interpreting `real_agent_runs` as coder runs. The report already has `context_runs` and `coder_runs`, so this is acceptable if dashboards treat them separately.

## Important non-blocker — cleanup scope is correct

Cleanup commands run with `cwd=str(target_root)`, while bundle artifacts live under `/tmp/grace-context/...`. That avoids deleting the bundle artifacts during `git clean -fd`. Keep this invariant.

## Required tests to add

Add tests for:

1. Agent exits 0, prints valid JSON, but does not create bundle file → fail with `CONTEXT_BUILDER_MISSING_BUNDLE`.
2. Agent prints `context_bundle_path` pointing outside expected bundle dir → runner either rejects it or normalizes to the runner-owned `bundle_path`.
3. Runner writes exact `context_bundle_output_path` into `EXECUTION_PACKET.md`.
4. Prompt distinguishes “read only inside cwd” from “write artifacts only to bundle path”.

## Final verdict

**REWORK REQUIRED** before retrying Solar Sage pilot 003.

Do not run pilot 003 retry yet. First fix the bundle artifact contract so Stage 0 cannot falsely pass without an actual context bundle file.
