# Review: Solar Sage pilot 003 full pass + Stage 0 env isolation — 632eac2

Date: 2026-06-11
Commit reviewed: `632eac204bbb7f2372bce6ea39e453d98505c8bc`
Target repo merge commit: `6c9c26c`
Verdict: **ACCEPTED / FULL PASS**

## Summary

Solar Sage pilot 003 is accepted as a full pass.

The run validates the new GRACE flow:

```text
scenario YAML
→ Stage 0 read-only context-builder
→ real context bundle
→ architect-premium
→ bounded coder packet
→ acceptance/reviewer
→ target repo merge
```

## Reported pilot evidence

Accepted metrics:

| Metric | Result |
|---|---|
| `context_runs` | `1` |
| Bundle file | `5331 bytes`, `/tmp/grace-context/.../C1/context-bundle.md` |
| `mutation_detected` | `false` |
| Coder changes | only `__tests__/components/TabBar.test.tsx` (`+10` lines) |
| Production code | untouched |
| `lint/typecheck/test` | PASS, packet merged |
| `watchdog_restarts` | `0` |
| `real_agent_runs` | `2` (`1` context-builder + `1` coder) |
| `failures` | `0` |
| `exit_code` | `0` |
| Target repo merge | `6c9c26c` |

## Code review of final infra fix

Commit `632eac2` adds Stage 0 subprocess environment isolation for opencode.

The runner now strips `OPENCODE` and `OPENCODE_*` variables before launching the Stage 0 context-builder subprocess. This prevents `opencode run` from accidentally trying to reuse/attach to a stale or missing server session.

Accepted behavior:

```python
clean_env = os.environ.copy()
for k in list(clean_env):
    if k == "OPENCODE" or k.startswith("OPENCODE_"):
        del clean_env[k]
...
subprocess.run(..., env=clean_env)
```

This is the right fix for the observed `Session not found` failure class.

## Safety review

Accepted:

- Stage 0 still runs before feature submission.
- Stage 0 increments `context_runs` separately from coder runs.
- Stage 0 does not submit a normal packet for context-builder.
- Stage 0 has mutation guard and bundle existence guard from the previous accepted commits.
- `OPENCODE_*` env stripping is local to the Stage 0 subprocess and does not mutate the parent environment.
- Coder/worker flow is unaffected.

No new blocker found.

## Canon update

This pilot confirms the GRACE canon:

1. Context-builder must not run as a normal coder packet.
2. Context-builder runs as built-in Stage 0.
3. Stage 0 must be read-only with mutation detection.
4. Stage 0 must create a real non-empty context bundle.
5. Architect receives the bundle pointer.
6. Coder runs only after successful Stage 0.
7. Long-running pilots must expose live logs and early failure evidence.

## Final verdict

**ACCEPTED / FULL PASS.**

The updated Stage 0 context-builder flow is approved for small production pilots after Solar Sage pilot 003.
