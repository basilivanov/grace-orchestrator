## TZ Compliance Rule
When given a TZ/спецификацию:
- Use EXACT field names from the TZ, not existing codebase names
- Use EXACT function signatures from the TZ
- If TZ conflicts with existing code → change the code, not the TZ
- Check every TZ requirement against implementation before declaring "done"
- Do NOT substitute "it works" for "it matches the spec"

## Coder mode
- You are not the architect.
- Do not rename spec fields.
- Do not replace required functions/classes with convenient equivalents.
- If implementation conflicts with TZ, change implementation.
- If exact implementation is impossible, stop and return BLOCKER.

## Debugging and observability tools

### grace trace — execution timeline
```bash
grace trace --packet pkt_xxx        # timeline for packet
grace trace --feature feat_yyy      # timeline for feature
grace trace --wave wave_zzz         # packets in wave
grace trace --packet pkt_xxx --json # machine-readable JSON
grace trace --packet pkt_xxx --full # full context: acceptance + verifier + recovery reports
```

Shows the full lifecycle: claim → execute → acceptance → verifier → recovery → merge. Every step includes the reason — why it failed, which decision was made, by whom.

### Structured logging
All components emit structured JSONL logs with `trace_id`, `packet_id`, and `reason` fields:
- `acceptance_pipeline`: T0/T1/T2 command failures with exit_code + stderr
- `feature_recovery`: classify_failure + decide_recovery decisions
- `recovery_controller`: build_signal, evaluate, apply_* (start/skip/done)
- `packet_executor`: execution_rejected with verdict + stages
- `worker`: recovery_check + recovery_applied

Logs go to stderr as JSONL. Each log line includes `component`, `msg`, `trace_id`, `ctx.reason`.

### Recovery ladder (odd/even)
- Odd attempts (1, 3, 5): skip verifier, fast path to coder
- Even attempts (2, 4, 6): run verifier → classify → switch coder or return to architect
- Attempt 7+: new architect with full context from all previous attempts
- Coder ladder reads from agent_profiles.yaml (priority-based)
- Profiles (FAST/NORMAL/STRICT) always preserved; STRICT never downgraded
