# Real-Loop Orchestrator Smoke Report

**Date:** 2026-06-09
**Commit:** 97a8f9d
**Verdict:** BLOCKED (infrastructure works, LLM model quality blocks coder)

## Summary

| Field | Value |
|-------|-------|
| Scenario | one-wave-basic-backend |
| Profile | FAST (no verifier/reviewer) |
| Target project | `/tmp/grace-orchestrator-export/sandbox` |
| Feature ID | `feat_dF9jO044vX` |
| Wave count | 1 |
| Packets | `pkt_CUQoNVLzP5` |
| Run IDs | none (execution rejected before run creation) |
| Run dir | `/tmp/grace-real-smoke/runs/20260609-222029-one-wave-basic-backend` |
| Harness | `scripts/real_loop_smoke.sh` + `scripts/real_loop_smoke.py` |

## Pipeline Verification

The GRACE orchestrator pipeline was verified end-to-end at the infrastructure level:

| Stage | Result |
|-------|--------|
| API startup | ✅ |
| Feature creation (`POST /api/architect/plan`) | ✅ — `feat_dF9jO044vX` with 1 packet |
| Worker registration | ✅ — worker `smoke-w1` registered |
| Packet claim | ✅ — `pkt_CUQoNVLzP5` claimed at attempt 1 |
| Coder launch (`opencode run`) | ✅ — process started with `cliproxy/gemini-3-flash-agent` |
| Coder completion | ✅ — `exit_code=0` after ~4.5 min |
| Execution rejection | ✅ — correctly rejected with "Worktree issue" |
| Packet release + retry | ✅ — returned to ready pool, retried |

## Failures Found

### Blocker: Coder LLM model quality (gemini-3-flash-agent)

The coder LLM (`cliproxy/gemini-3-flash-agent` via local proxy at `localhost:18317`) was invoked successfully but failed to produce useful output:

- The LLM spent the entire execution in an infinite loop calling `Glob("")` with empty pattern strings (see `agent_stderr.log`)
- Each call failed with `SchemaError: Missing key at ["pattern"]`
- The model never recovered and created zero files
- `git status` in the worktree: `nothing to commit, working tree clean`
- Evidence: `execution_rejected` verdict="?" with empty stages
- Root cause: model quality issue — gemini-3-flash-agent cannot follow the tool-calling instructions reliably with the GRACE canon prompt

### Model availability

| Model | Status |
|-------|--------|
| `cliproxy/gemini-3-flash-agent` | ✅ Works — but generates invalid tool calls |
| `cliproxy/claude-sonnet-4-6` | ❌ 429 quota exceeded (resets ~2026-06-11) |
| `cliproxy/gpt-5.4-mini` | ❌ auth_unavailable (no configured auth) |

### Pre-existing issues discovered

- `agent_profiles.yaml` referenced `deepseek/deepseek-v4-flash` and `deepseek/deepseek-v4-pro` models not configured in `opencode` CLI — required update to `cliproxy/gemini-3-flash-agent`
- Auto-planner (wave_gate) creates stale features/packets that compete with smoke-test features unless DB is cleaned
- URL-encoded SQLite files (`%2Ftmp%2Fgrace-full.db`) appeared in worktrees — likely from prior test runs
- `GRACE_WORKER_ID` is an env var, not in process command line — monitoring scripts cannot find worker by `grep <worker-id>` in `ps aux`

## Bugs Fixed

- Updated `src/grace_control/config/agent_profiles.yaml`: replaced all unavailable model references (`deepseek/deepseek-v4-*`, `opencode/claude-sonnet-4-6`, `cliproxy/claude-sonnet-4-6`, `cliproxy/gpt-5.4-mini`) with `cliproxy/gemini-3-flash-agent` (7 profiles affected)
- Created `scripts/real_loop_smoke.sh` and `scripts/real_loop_smoke.py` — reusable smoke harness per TZ requirements

## Remaining Blockers

1. **Coder LLM model quality**: gemini-3-flash-agent generates Glob("") calls in an infinite loop. Needs either:
   - A model that follows tool-calling instructions (claude-sonnet-4-6 when quota resets)
   - A model that works with `agy` backend (different prompt format)
   - Or improved prompt engineering for the coder profile
2. **Claude Sonnet 4-6 quota** resets in ~39h — cannot use currently
3. **No T0/T1/T2 verification** was reached because coder produced no files

## Next Steps

1. Try `coder_agy` profile with `gemini-3.5-flash` (different CLI backend, may handle prompts differently)
2. Or wait for claude-sonnet-4-6 quota reset and retry with `coder-sonnet`
3. Revert `agent_profiles.yaml` model changes if original models work through a different mechanism
4. Run scenarios 2 and 3 only after scenario 1 coder issue is resolved

## Artifacts

Artifacts from the harness run:
```
/tmp/grace-real-smoke/runs/20260609-222029-one-wave-basic-backend/
  01-feature-spec.json
  02-plan-response.json
  03-feature-id.txt
  04-packet-ids.txt
  05-packet-pkt_CUQoNVLzP5.json (×N polling snapshots)
  06-trace-pkt_CUQoNVLzP5.json
```

Additional diagnostic artifacts:
```
/tmp/grace-worker-err.log                         — worker stderr (full timeline)
/tmp/grace-api-smoke.log                          — API access + structured log
.grace/state/packets/pkt_CUQoNVLzP5/runs/R01/     — execution state
.grace/state/packets/pkt_CUQoNVLzP5/runs/R01/agent_stderr.log  — coder LLM stderr
.grace/state/packets/pkt_CUQoNVLzP5/runs/R01/agent_stdout.log  — coder LLM stdout (empty)
```

## Notes

- This report was generated automatically from test results by `scripts/real_loop_smoke.py`.
- Environment secrets have been excluded.
- The LLM-oriented sections (scenarios 2 and 3) were not attempted due to the coder blocker in scenario 1.
- The harness scripts are functional and reusable — see `scripts/real_loop_smoke.sh --help`.
