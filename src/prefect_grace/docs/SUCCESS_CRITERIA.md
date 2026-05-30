# Success Criteria

This document defines what "success" means for packets, features, and orchestrator operations. These criteria are used by automated verification tools and health checks.

## Packet Success

A packet is considered **successful** when:

1. **Status**: Final status is `accepted` (not `blocked` or `failed`)
2. **Execution**: returncode == 0
3. **Metrics**: Metrics collected (tokens, cost, duration)
4. **Logs**: All expected events present:
   - `PACKET_START`
   - `EXECUTOR_SELECTED`
   - `PACKET_END`
5. **No errors**: No critical errors in execution_trace.jsonl

### Packet Failure

A packet is considered **failed** when:

- Status is `failed` or `blocked`
- returncode != 0
- Missing critical events (PACKET_START, EXECUTOR_SELECTED, PACKET_END)
- Stuck in `running` state for >1 hour
- Critical errors in execution trace

### Example: Successful Packet Logs

```jsonl
{"event": "PACKET_START", "packet_id": "FEAT-XYZ-V1", "timestamp": "2026-05-30T10:00:00Z"}
{"event": "EXECUTOR_SELECTED", "packet_id": "FEAT-XYZ-V1", "executor_id": "coder-cheap", "model": "gemini-3.5-flash", "complexity": "simple"}
{"event": "PACKET_END", "packet_id": "FEAT-XYZ-V1", "status": "accepted", "returncode": 0, "timestamp": "2026-05-30T10:05:00Z"}
{"event": "EXECUTION_METRICS", "packet_id": "FEAT-XYZ-V1", "tokens_used": 1500, "cost_usd": 0.002, "duration_seconds": 300}
```

---

## Feature Success

A feature is considered **successful** when:

1. **All waves complete**: All required waves reach terminal state
2. **Packets accepted**: All critical packets accepted
3. **No blockers**: No unresolved blockers
4. **Review passed**: Final review verdict is `accept` (if review enabled)
5. **Metrics**: Total cost within budget

### Feature Failure

A feature is considered **failed** when:

- Any critical packet blocked
- Review verdict is `reject`
- Timeout exceeded
- Budget exceeded
- Too many packet retries

### Feature Success Calculation

```python
feature_success = (
    all_critical_packets_accepted and
    no_unresolved_blockers and
    cost_within_budget and
    (review_verdict == "accept" or review_disabled)
)
```

---

## Executor Selection Success

Executor selection is **correct** when:

1. **Complexity routing**: 
   - Simple packets → `coder-cheap` (gemini-3.5-flash)
   - Medium packets → `coder-standard` (gemini-3.1-pro)
   - Complex packets → `coder-premium` (claude-opus-4)

2. **Rotation**: After `max_consecutive_failures`, different executor selected

3. **History**: ExecutorHistoryStore loaded and used for selection

### Executor Selection Failure

Selection is **incorrect** when:

- Simple packet uses expensive model (opus/pro)
- Complex packet uses cheap model (flash)
- Same executor used after 3+ consecutive failures
- ExecutorHistoryStore not loaded

### Example: Correct Selection

```jsonl
{"event": "EXECUTOR_SELECTED", "packet_id": "SIMPLE-TASK", "complexity": "simple", "model": "gemini-3.5-flash"}
{"event": "EXECUTOR_SELECTED", "packet_id": "COMPLEX-TASK", "complexity": "complex", "model": "claude-opus-4"}
```

---

## Verification Success

Verification is **successful** when:

1. **All patterns pass**: 
   - executor_selection
   - executor_rotation
   - status_transitions
   - metrics_present

2. **No critical issues**: 
   - No executor stuck
   - No wrong model selection
   - No missing metrics

3. **Metrics present**: All executions have metrics

4. **Logs complete**: No missing critical events

### Verification Failure

Verification **fails** when:

- Any verification pattern fails
- Critical issues detected
- Logs incomplete or malformed
- Metrics missing for executions

---

## Metrics Success

Metrics collection is **successful** when:

1. **All fields present**:
   - `tokens_used` (int)
   - `cost_usd` (float)
   - `duration_seconds` (float)

2. **Values reasonable**:
   - tokens_used > 0
   - cost_usd >= 0
   - duration_seconds > 0

3. **Timing correct**: Metrics logged after PACKET_END

### Metrics Failure

Metrics collection **fails** when:

- Missing required fields
- Invalid values (negative, zero tokens)
- Metrics logged before execution completes

---

## Health Check Success

Health checks **pass** when:

1. **Recent activity**: Logs from last 24 hours present
2. **No stuck packets**: No packets in `running` state >1 hour
3. **Cost tracking**: All executions have cost metrics
4. **Error rate**: <10% packet failure rate
5. **Executor diversity**: Multiple executors used (not stuck on one)

### Health Check Failure

Health checks **fail** when:

- No recent activity (>24 hours)
- Multiple stuck packets
- High failure rate (>10%)
- All packets using same executor (rotation broken)
- Missing metrics for >5% of executions

---

## Usage in Tools

### Check Packet Success

```python
from verify_orchestrator import check_packet_success

result = check_packet_success(logs, "FEAT-XYZ-V1")
if result["success"]:
    print("Packet succeeded!")
else:
    print(f"Packet failed: {result['issues']}")
```

### Check Feature Success

```python
from verify_orchestrator import check_feature_success

result = check_feature_success(logs, "FEAT-XYZ")
print(f"Success rate: {result['successful_packets']}/{result['total_packets']}")
```

### Run Full Verification

```bash
python3 tools/verify_orchestrator.py state
```

---

## Automated Verification

These criteria are checked by:

1. **verify_orchestrator.py**: Main verification tool
2. **validate_logs.py**: Schema and format validation
3. **query_logs.sh**: Quick status checks
4. **Health checks**: Periodic automated checks (Phase 2 Day 7)

All tools use these criteria consistently for success detection.
