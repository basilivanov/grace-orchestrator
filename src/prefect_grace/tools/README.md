# Orchestrator Tools

Tools for analyzing and debugging Grace orchestrator execution.

## Log Analysis Tools

### aggregate_logs.py

Collects all execution logs from packet runs into a single stream.

**Usage:**
```bash
python3 aggregate_logs.py <state_root>
```

**Example:**
```bash
python3 aggregate_logs.py state > all_logs.jsonl
```

**Output:** JSONL stream of all log events, sorted by timestamp.

---

### query_logs.sh

Query execution logs using jq for common analysis patterns.

**Usage:**
```bash
./query_logs.sh [state_root] [logs_file] [query]
```

**Queries:**
- `selections` - Show all executor selections (which model was chosen for each packet)
- `failures` - Show all packet failures with reasons
- `metrics` - Show aggregated metrics (total cost, tokens, duration)
- `rotations` - Show executor rotation events (when models were switched)
- `all` - Show all events chronologically

**Examples:**
```bash
# Show executor selections
./query_logs.sh state /tmp/logs.jsonl selections

# Show metrics summary
./query_logs.sh state /tmp/logs.jsonl metrics

# Show all failures
./query_logs.sh state /tmp/logs.jsonl failures

# Show all events
./query_logs.sh state /tmp/logs.jsonl all
```

**Output Format:**
- `selections`: `timestamp | packet_id | complexity -> model`
- `failures`: `timestamp | packet_id | role | reason`
- `metrics`: JSON summary with totals and averages
- `rotations`: `timestamp | packet_id | previous_executor -> executor_id`

---

### view_trace.py

Interactive log viewer for execution traces.

**Usage:**
```bash
python3 view_trace.py <state_root> [command] [args]
```

**Commands:**
- `timeline [limit]` - Show chronological timeline of events (default: last 50)
- `packets` - List all packet IDs
- `<packet_id>` - Show detailed trace for specific packet

**Examples:**
```bash
# Show last 50 events
python3 view_trace.py state timeline

# Show last 100 events
python3 view_trace.py state timeline 100

# List all packets
python3 view_trace.py state packets

# View trace for specific packet
python3 view_trace.py state FEAT-REFERRAL-LEADERBOARD-V10
```

**Output:**
- Timeline shows: `timestamp | event | packet_id`
- Packet trace shows all events with relevant details (model, status, metrics)

---

### validate_logs.py

Validate execution logs against expected schema.

**Usage:**
```bash
python3 validate_logs.py <state_root>
```

**Example:**
```bash
python3 validate_logs.py state
```

**Output:** JSON validation report:
```json
{
  "valid": true,
  "errors": [],
  "warnings": [],
  "total_events": 42
}
```

**Validation Checks:**
- Required fields present for each event type
- Timestamp format
- Status values are valid
- Numeric fields are actually numeric

**Exit Code:** 0 if valid, 1 if errors found

---

## Verification Tools

### verify_orchestrator.py

Verify orchestrator state and configuration using success criteria.

**Usage:**
```bash
python3 verify_orchestrator.py <state_root>
```

**Output:** JSON verification report:
```json
{
  "verdict": "PASS",
  "checks": {
    "executor_selection": {"passed": true, "issues": []},
    "executor_rotation": {"passed": true, "issues": []},
    "status_transitions": {"passed": true, "issues": []},
    "metrics_present": {"passed": true, "issues": []}
  },
  "metrics": {
    "total_executions": 10,
    "total_cost_usd": 0.05,
    "avg_cost_per_execution": 0.005
  }
}
```

**Verification Checks:**
- **executor_selection**: Verifies complexity routing (simple→cheap, complex→premium)
- **executor_rotation**: Verifies rotation after consecutive failures
- **status_transitions**: Verifies packets reach terminal state (not stuck)
- **metrics_present**: Verifies all executions have metrics

See `docs/SUCCESS_CRITERIA.md` for detailed success definitions.

**Success Detection Functions:**

```python
from verify_orchestrator import check_packet_success, check_feature_success

# Check if a packet succeeded
result = check_packet_success(logs, "FEAT-XYZ-V1")
print(f"Success: {result['success']}")
print(f"Issues: {result['issues']}")

# Check if a feature succeeded
result = check_feature_success(logs, "FEAT-XYZ")
print(f"Success rate: {result['successful_packets']}/{result['total_packets']}")
```

---

### test_success_criteria.py

Test success criteria detection functions.

**Usage:**
```bash
python3 test_success_criteria.py
```

**Tests:**
- Packet success detection
- Packet failure detection (wrong status, missing events)
- Feature success detection
- Feature partial failure detection
- Empty logs handling

**Exit Code:** 0 if all tests pass, 1 if any test fails

---

## Success Criteria

All verification tools use consistent success criteria defined in `docs/SUCCESS_CRITERIA.md`.

### Packet Success

A packet succeeds when:
- Status is `accepted`
- Return code is 0
- All required events present (PACKET_START, EXECUTOR_SELECTED, PACKET_END)
- Metrics collected

### Feature Success

A feature succeeds when all its packets succeed.

### Checking Success

```bash
# Run full verification
python3 verify_orchestrator.py state

# Test success detection
python3 test_success_criteria.py

# Check specific packet
python3 -c "
from verify_orchestrator import check_packet_success
from aggregate_logs import aggregate_logs
from pathlib import Path

logs = aggregate_logs(Path('state'))
result = check_packet_success(logs, 'FEAT-XYZ-V1')
print(f'Success: {result[\"success\"]}')
print(f'Issues: {result[\"issues\"]}')
"
```

See `docs/SUCCESS_CRITERIA.md` for complete definitions.

---

## Common Workflows

### Debug a Failed Packet

```bash
# 1. Find failures
./query_logs.sh state /tmp/logs.jsonl failures

# 2. View detailed trace
python3 view_trace.py state FEAT-XYZ-V1

# 3. Check metrics
./query_logs.sh state /tmp/logs.jsonl metrics
```

### Analyze Executor Behavior

```bash
# See which models were selected
./query_logs.sh state /tmp/logs.jsonl selections

# Check for rotations
./query_logs.sh state /tmp/logs.jsonl rotations
```

### Validate Log Quality

```bash
# Check schema compliance
python3 validate_logs.py state

# View recent activity
python3 view_trace.py state timeline 100
```

### Cost Analysis

```bash
# Get cost summary
./query_logs.sh state /tmp/logs.jsonl metrics

# View per-packet metrics
python3 view_trace.py state FEAT-XYZ-V1 | grep -A3 "EXECUTION_METRICS"
```

---

## Health Check Tools

### health_check.py

Check orchestrator health and detect issues.

**Usage:**
```bash
python3 health_check.py <state_root>
```

**Example:**
```bash
python3 health_check.py state
```

**Output:** JSON health report:
```json
{
  "status": "healthy",
  "checks": {
    "executor_rotation": {
      "status": "healthy",
      "issues": [],
      "details": {"stuck_executors": 0, "total_failures": 0}
    },
    "deadlocks": {
      "status": "healthy",
      "issues": [],
      "details": {"stuck_packets": 0, "running_packets": 0}
    },
    "metrics_collection": {
      "status": "healthy",
      "issues": [],
      "details": {"metrics_coverage": 1.0, "total_executions": 10, "metrics_collected": 10}
    }
  },
  "timestamp": "2026-05-30T14:30:00"
}
```

**Health Checks:**
- **executor_rotation**: Detects packets stuck on same executor (5+ failures without rotation)
- **deadlocks**: Detects packets stuck in running state (>1 hour)
- **metrics_collection**: Verifies metrics are being collected (>90% coverage)

**Status Levels:**
- `healthy` - All checks passing
- `degraded` - Minor issues detected (1-2 problems)
- `failing` - Major issues detected (3+ problems)

**Exit Codes:**
- 0 = healthy
- 1 = degraded
- 2 = failing

---

### alert_on_health.sh

Alert on orchestrator health issues.

**Usage:**
```bash
./alert_on_health.sh [state_root] [alert_file]
```

**Example:**
```bash
./alert_on_health.sh state /tmp/orchestrator_alerts.log
```

**Behavior:**
- Runs health check
- If status is not healthy, logs alert to file
- Can be extended to send alerts to monitoring systems
- Returns health check output

**Integration:**
```bash
# Run periodically via cron
*/15 * * * * /path/to/alert_on_health.sh /path/to/state /var/log/orchestrator_alerts.log

# Or use with monitoring
./alert_on_health.sh state | curl -X POST https://monitoring.example.com/alerts -d @-
```

---

### test_health_check.py

Test health check functionality.

**Usage:**
```bash
python3 test_health_check.py
```

**Tests:**
- Executor rotation detection
- Deadlock detection
- Metrics collection verification

**Exit Code:** 0 if all tests pass, 1 if any test fails

---

## Requirements

- Python 3.7+
- jq (for query_logs.sh, alert_on_health.sh)
- Bash (for query_logs.sh, alert_on_health.sh)

## Notes

- All tools handle missing logs gracefully
- Logs are aggregated from `state/runs/*/execution_trace.jsonl`
- Tools work with empty or partial log sets
- Malformed log lines are skipped with warnings
