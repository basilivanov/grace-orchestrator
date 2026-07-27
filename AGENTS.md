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

## GRACE Canon

Every file you create must follow this exact GRACE canon template:

```python
# ############################################################################
# AI_HEADER: module_name — one-line description of what this module does
# ROLE: Detailed role. Who calls it, what it provides. One or two sentences.
# ############################################################################

# START_MODULE_CONTRACT
# purpose: What this module does. Who calls it, what it returns.
# inputs: List of inputs, parameters, or dependencies.
# returns: What this module returns or provides.
# side_effects: File writes, DB inserts, network calls, subprocess spawns.
# emitted_logs: List of GraceLogger msg= names this module emits.
# error_behavior: What exceptions this module may raise and when.
# END_MODULE_CONTRACT

# START_MODULE_MAP
# mapping:
#   - class: ClassName
#     methods:
#       - method_one
#       - method_two
#   - function: standalone_func
# END_MODULE_MAP

from __future__ import annotations
from grace_control.core.structured_logger import GraceLogger

_log = GraceLogger("component_name")


# START_BLOCK_CLASS
# START_FUNCTION_CONTRACT
# name: method_name
# purpose: What this method does.
# inputs: param_name — description.
# returns: What it returns (type and meaning).
# side_effects: File writes, DB inserts, etc.
# emitted_logs: my_func_start, my_func_done.
# error_behavior: Exceptions this method may raise and when.
# END_FUNCTION_CONTRACT
def method_name(self, param: str) -> str:
    _log.info("method_start", param=param)
    ...
    _log.info("method_done", result=result)
    return result
# END_BLOCK_CLASS


# START_BLOCK_MAIN
# START_FUNCTION_CONTRACT
# name: run
# purpose: Entry point.
# ...
# END_FUNCTION_CONTRACT
def run() -> dict:
    _log.info("run_start")
    ...
    return {}
# END_BLOCK_MAIN
```

Rules:
- Use `# ############################################################################` above and below `AI_HEADER`.
- Every public function/method must have `START_FUNCTION_CONTRACT` before it.
- Group related methods with `START_BLOCK_name / END_BLOCK_name`.
- Use `GraceLogger`, never `print()` or `logging.getLogger()`.
- `_log = GraceLogger("name")` must appear once at module level.
- Log messages must be static strings: `_log.info("msg_name", ctx_key=value)`.
- Do not import `prefect_grace`.
- Run `python3 scripts/grace_lint.py` before declaring completion.

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
