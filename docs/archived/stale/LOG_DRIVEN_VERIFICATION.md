# Log-Driven Verification Guide

## Overview

GRACE orchestrator uses log-driven verification: cheap models analyze structured logs to verify orchestrator correctness instead of expensive end-to-end tests.

## How It Works

1. **Structured Logging**: All critical decisions logged as JSONL events
2. **Log Aggregation**: Collect execution_trace.jsonl from all runs
3. **Pattern Matching**: Cheap model checks success/failure patterns
4. **Automated Verification**: Returns PASS/FAIL verdict with issues

## Verification Patterns

### Success Patterns

1. **Executor Selection**: Complexity routing works correctly
   - Simple packets → coder-cheap (gemini-3.5-flash)
   - Medium packets → coder-standard (gemini-3.1-pro)
   - Complex packets → coder-premium (claude-opus-4)

2. **Executor Rotation**: After max_consecutive_failures, different executor selected

3. **Status Transitions**: All packets reach terminal state (accepted/blocked)

4. **Metrics Collection**: All executions have metrics (tokens, cost, duration)

### Failure Patterns

1. **Executor Stuck**: Same executor fails 5+ times without rotation
2. **Wrong Model**: Complex packet routed to cheap model
3. **Status Drift**: Packet stuck in running state >1 hour
4. **Missing Logs**: Critical events not logged

## Usage

### Command Line

```bash
# Verify orchestrator health
python3 tools/verify_orchestrator.py state/

# Check specific packet
python3 tools/verify_orchestrator.py state/ --packet P123

# Output JSON for automation
python3 tools/verify_orchestrator.py state/ --json
```

### Python API

```python
from prefect_grace.tools import verify_orchestrator

result = verify_orchestrator("/path/to/state")
if result["verdict"] == "PASS":
    print("✓ Orchestrator healthy")
else:
    print(f"✗ Issues: {result['checks']}")
```

## Cost Comparison

**Traditional Testing:**
- Run full feature pipeline: $0.50-$2.00
- Multiple test runs: $5-$20/day
- Manual verification: hours of engineer time

**Log-Driven Verification:**
- Analyze logs with cheap model: $0.001-$0.01
- Automated: runs in seconds
- Continuous: can run after every execution

**Savings: 99% cost reduction**

## Verification Checks

### 1. Executor Selection Check

Verifies that packets are routed to appropriate models based on complexity.

**Success Criteria:**
- Simple packets use gemini-3.5-flash
- Medium packets use gemini-3.1-pro
- Complex packets use claude-opus-4

**Example Log Pattern:**
```jsonl
{"event": "EXECUTOR_SELECTED", "packet_id": "FEAT-XYZ-V1", "complexity": "simple", "model": "gemini-3.5-flash", "reason": "complexity_routing"}
```

### 2. Executor Rotation Check

Verifies that failed executors are rotated after max_consecutive_failures.

**Success Criteria:**
- After 3 consecutive failures, different executor selected
- ExecutorHistoryStore loaded and consulted
- Rotation reason logged

**Example Log Pattern:**
```jsonl
{"event": "EXECUTOR_HISTORY_LOADED", "packet_id": "FEAT-XYZ-V1", "history_count": 2}
{"event": "EXECUTOR_SELECTED", "packet_id": "FEAT-XYZ-V1", "executor_id": "coder-standard", "reason": "rotation_after_failures"}
```

### 3. Status Transitions Check

Verifies that all packets reach terminal state.

**Success Criteria:**
- All packets have PACKET_START and PACKET_END events
- No packets stuck in running state >1 hour
- Terminal status is accepted or blocked

**Example Log Pattern:**
```jsonl
{"event": "PACKET_START", "packet_id": "FEAT-XYZ-V1", "timestamp": "2026-05-30T10:00:00Z"}
{"event": "PACKET_END", "packet_id": "FEAT-XYZ-V1", "status": "accepted", "timestamp": "2026-05-30T10:05:00Z"}
```

### 4. Metrics Collection Check

Verifies that execution metrics are collected for all runs.

**Success Criteria:**
- All executions have EXECUTION_METRICS event
- Metrics include tokens, cost, duration
- Values are reasonable (positive, non-zero)

**Example Log Pattern:**
```jsonl
{"event": "EXECUTION_METRICS", "packet_id": "FEAT-XYZ-V1", "input_tokens": 1000, "output_tokens": 500, "cost_usd": 0.002, "duration_seconds": 300}
```

## Integration with CI/CD

### GitHub Actions

```yaml
name: Verify Orchestrator

on:
  schedule:
    - cron: '0 */6 * * *'  # Every 6 hours
  workflow_dispatch:

jobs:
  verify:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v3
      
      - name: Run verification
        run: |
          python3 tools/verify_orchestrator.py state/ --json > verification.json
          
      - name: Check results
        run: |
          verdict=$(jq -r '.verdict' verification.json)
          if [ "$verdict" != "PASS" ]; then
            echo "Verification failed!"
            jq '.checks' verification.json
            exit 1
          fi
          
      - name: Upload results
        uses: actions/upload-artifact@v3
        with:
          name: verification-results
          path: verification.json
```

### GitLab CI

```yaml
verify-orchestrator:
  stage: test
  script:
    - python3 tools/verify_orchestrator.py state/ --json > verification.json
    - |
      verdict=$(jq -r '.verdict' verification.json)
      if [ "$verdict" != "PASS" ]; then
        echo "Verification failed!"
        jq '.checks' verification.json
        exit 1
      fi
  artifacts:
    paths:
      - verification.json
    reports:
      junit: verification.json
  only:
    - schedules
```

## Troubleshooting

### Issue: Verification Always Fails

**Symptoms:**
- All checks return FAIL
- No logs found

**Solution:**
1. Check state directory path is correct
2. Verify execution_trace.jsonl files exist
3. Check log format is valid JSONL

```bash
# Validate logs
python3 tools/validate_logs.py state/
```

### Issue: Missing Metrics

**Symptoms:**
- metrics_present check fails
- Some executions missing EXECUTION_METRICS

**Solution:**
1. Check token parsing in codex_launcher.py
2. Verify cost_calculator.py has model pricing
3. Ensure metrics stored after execution

```bash
# Check metrics coverage
python3 tools/query_logs.sh state /tmp/logs.jsonl metrics | wc -l
```

### Issue: False Positives

**Symptoms:**
- Verification passes but orchestrator has issues
- Patterns not catching real problems

**Solution:**
1. Review verification patterns in verify_orchestrator.py
2. Add new patterns for specific issues
3. Adjust thresholds (e.g., stuck timeout)

## Best Practices

1. **Run verification after every deployment**
   - Catch issues early
   - Verify orchestrator health

2. **Monitor verification trends**
   - Track pass/fail rate over time
   - Identify degradation patterns

3. **Customize patterns for your use case**
   - Add domain-specific checks
   - Adjust thresholds based on workload

4. **Integrate with alerting**
   - Send alerts on verification failures
   - Page on-call for critical issues

5. **Archive verification results**
   - Keep history for trend analysis
   - Debug issues with historical data

## Related Documentation

- [SUCCESS_CRITERIA.md](../src/prefect_grace/docs/SUCCESS_CRITERIA.md) - Success definitions
- [RUNBOOK.md](RUNBOOK.md) - Operations runbook
- [METRICS.md](METRICS.md) - Metrics reference
