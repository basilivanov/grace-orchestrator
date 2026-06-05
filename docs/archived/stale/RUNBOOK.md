# Operations Runbook

## Common Issues

### Issue: Executor Stuck on Same Model

**Symptoms:**
- Packet fails 5+ times with same executor
- No rotation happening
- Health check shows "executor_stuck"

**Diagnosis:**
```bash
# Check executor history
python3 tools/query_logs.sh state /tmp/logs.jsonl rotations

# Verify history loading
grep "EXECUTOR_HISTORY_LOADED" state/runs/*/execution_trace.jsonl

# Check consecutive failures
python3 tools/query_logs.sh state /tmp/logs.jsonl all | grep -A5 "EXECUTOR_SELECTED"
```

**Resolution:**
1. Check ExecutorHistoryStore is loading (codex_launcher.py:161)
2. Verify max_consecutive_failures in agent_profiles.yaml
3. Check executor priority ordering in agent_profiles.yaml
4. Manually rotate if stuck:
   ```bash
   # Force different executor
   export GRACE_FORCE_EXECUTOR=coder-standard
   python3 -m prefect_grace.flows.codex_launcher --packet FEAT-XYZ-V1
   ```

**Prevention:**
- Set max_consecutive_failures=3 in agent_profiles.yaml
- Monitor executor diversity in health checks
- Alert on same executor used >5 times

---

### Issue: Metrics Not Collected

**Symptoms:**
- Health check shows low metrics coverage
- Cost dashboard shows $0.00
- Missing EXECUTION_METRICS events

**Diagnosis:**
```bash
# Check metrics events
python3 tools/query_logs.sh state /tmp/logs.jsonl metrics

# Verify cost calculator
python3 -c "from prefect_grace.platform.cost_calculator import calculate_cost; print(calculate_cost('gemini-3.5-flash', 100, 200))"

# Check token parsing
grep "tokens_used" state/runs/*/execution_trace.jsonl
```

**Resolution:**
1. Verify token parsing in codex_launcher.py:
   ```python
   # Check token extraction logic
   tokens_match = re.search(r'(\d+) input tokens, (\d+) output tokens', output)
   ```

2. Check cost_calculator.py has model pricing:
   ```bash
   python3 -c "from prefect_grace.platform.cost_calculator import MODEL_PRICING; print(MODEL_PRICING)"
   ```

3. Ensure metrics stored in ExecutorHistoryStore:
   ```python
   # Verify metrics storage
   history_store.add_execution(packet_id, executor_id, success, metrics)
   ```

**Prevention:**
- Add unit tests for token parsing
- Validate metrics after each execution
- Alert on missing metrics >5%

---

### Issue: Packets Stuck in Running State

**Symptoms:**
- Health check shows deadlocks
- Packets never reach terminal state
- No PACKET_END events

**Diagnosis:**
```bash
# Find stuck packets
python3 tools/view_trace.py state timeline | grep PACKET_START

# Check for PACKET_END
python3 tools/query_logs.sh state /tmp/logs.jsonl all | grep PACKET_END

# Check packet age
python3 -c "
import json
from datetime import datetime
for line in open('state/runs/latest/execution_trace.jsonl'):
    event = json.loads(line)
    if event['event'] == 'PACKET_START':
        start = datetime.fromisoformat(event['timestamp'])
        age = (datetime.now() - start).total_seconds() / 3600
        print(f\"{event['packet_id']}: {age:.1f} hours\")
"
```

**Resolution:**
1. Check for agent hangs (timeout configuration):
   ```yaml
   # agent_profiles.yaml
   coder:
     timeout_seconds: 3600  # 1 hour max
   ```

2. Verify PACKET_END logging in wave_execution_phase.py:
   ```python
   # Ensure PACKET_END always logged
   finally:
       log_event("PACKET_END", packet_id=packet_id, status=status)
   ```

3. Kill stuck processes:
   ```bash
   # Find and kill stuck agent processes
   ps aux | grep "prefect_grace" | grep -v grep
   kill -9 <PID>
   ```

**Prevention:**
- Set reasonable timeouts in agent_profiles.yaml
- Add watchdog timer for long-running packets
- Monitor packet age in health checks

---

### Issue: High Failure Rate

**Symptoms:**
- Health check shows >10% failure rate
- Many packets blocked or failed
- Cost higher than expected

**Diagnosis:**
```bash
# Check failure rate
python3 tools/aggregate_metrics.py state/ | jq '.failure_rate'

# Find common failure reasons
python3 tools/query_logs.sh state /tmp/logs.jsonl all | grep "status.*failed" | jq -r '.reason' | sort | uniq -c | sort -rn

# Check error patterns
grep "ERROR" state/runs/*/execution_trace.jsonl | head -20
```

**Resolution:**
1. Analyze failure patterns:
   ```bash
   # Group by failure reason
   python3 tools/analyze_failures.py state/
   ```

2. Adjust complexity thresholds if wrong model selected:
   ```markdown
   # architect_prompt.md
   - Simple: <100 LOC, no new dependencies
   - Medium: 100-500 LOC, existing patterns
   - Complex: >500 LOC, new architecture
   ```

3. Improve prompts for common failure cases:
   ```bash
   # Review failed packet prompts
   python3 tools/extract_prompts.py state/ --status failed
   ```

**Prevention:**
- Monitor failure rate trends
- Review and improve agent prompts
- Add retry logic for transient failures

---

### Issue: Cost Exceeds Budget

**Symptoms:**
- Cost dashboard shows high spend
- Savings percentage <50%
- Too many premium model executions

**Diagnosis:**
```bash
# Check cost breakdown
python3 tools/aggregate_metrics.py state/ | jq '.by_model'

# Find expensive packets
python3 tools/query_logs.sh state /tmp/logs.jsonl metrics | jq 'select(.cost_usd > 0.1)'

# Check complexity distribution
python3 tools/aggregate_metrics.py state/ | jq '.by_complexity'
```

**Resolution:**
1. Review complexity routing:
   ```bash
   # Check if simple packets using expensive models
   python3 tools/query_logs.sh state /tmp/logs.jsonl all | jq 'select(.complexity=="simple" and .model=="claude-opus-4")'
   ```

2. Adjust architect prompt to classify more as simple:
   ```markdown
   # architect_prompt.md
   Classify as SIMPLE if:
   - Routine changes to existing code
   - Well-established patterns
   - No architectural decisions
   ```

3. Enable planner bypass for simple tasks:
   ```yaml
   # agent_profiles.yaml
   architect:
     bypass_planner_threshold: simple
   ```

**Prevention:**
- Set cost budgets per packet
- Alert on high-cost executions
- Review complexity classification weekly

---

## Health Monitoring

### Daily Health Check

```bash
# Run health check
python3 tools/health_check.py state/

# Alert if not healthy
./tools/alert_on_health.sh state/ /var/log/orchestrator_alerts.log
```

**Expected Output:**
```json
{
  "status": "healthy",
  "checks": {
    "recent_activity": "PASS",
    "no_stuck_packets": "PASS",
    "cost_tracking": "PASS",
    "error_rate": "PASS",
    "executor_diversity": "PASS"
  },
  "metrics": {
    "total_executions": 150,
    "failure_rate": 0.05,
    "avg_cost_usd": 0.015,
    "savings_pct": 65.2
  }
}
```

### Metrics Dashboard

```bash
# Generate dashboard
./tools/generate_dashboard.sh state/ /var/www/dashboard/

# View savings
python3 tools/aggregate_metrics.py state/ | jq '.savings'
```

**Dashboard Sections:**
1. **Overview**: Total executions, cost, savings
2. **By Model**: Usage and cost per model
3. **By Complexity**: Distribution and routing accuracy
4. **Trends**: Cost and failure rate over time
5. **Alerts**: Current issues and warnings

### Automated Monitoring

Set up cron jobs for continuous monitoring:

```bash
# /etc/cron.d/grace-orchestrator

# Health check every hour
0 * * * * /usr/local/bin/python3 /opt/grace/tools/health_check.py /var/lib/grace/state/ >> /var/log/grace/health.log 2>&1

# Metrics aggregation every 6 hours
0 */6 * * * /usr/local/bin/python3 /opt/grace/tools/aggregate_metrics.py /var/lib/grace/state/ > /var/www/dashboard/metrics.json 2>&1

# Verification daily
0 2 * * * /usr/local/bin/python3 /opt/grace/tools/verify_orchestrator.py /var/lib/grace/state/ --json > /var/log/grace/verification.json 2>&1
```

---

## Performance Tuning

### Optimize Model Selection

1. Analyze cost by complexity:
```bash
python3 tools/aggregate_metrics.py state/ | jq '.by_complexity'
```

2. Adjust complexity thresholds in architect_prompt.md:
```markdown
# Current thresholds
- Simple: <100 LOC, no new dependencies
- Medium: 100-500 LOC, existing patterns
- Complex: >500 LOC, new architecture

# Tuned thresholds (more aggressive)
- Simple: <200 LOC, minor changes
- Medium: 200-1000 LOC, moderate complexity
- Complex: >1000 LOC, major refactoring
```

3. Monitor savings percentage (target >60%):
```bash
python3 tools/aggregate_metrics.py state/ | jq '.savings.savings_pct'
```

### Reduce Execution Time

1. Check duration by model:
```bash
python3 tools/aggregate_metrics.py state/ | jq '.by_model[] | {model: .model, avg_duration: .avg_duration_seconds}'
```

2. Use faster models for simple tasks:
```yaml
# agent_profiles.yaml
executors:
  coder-cheap:
    model: gemini-3.5-flash  # Fast and cheap
    priority: 1
```

3. Enable planner bypass for simple tasks:
```yaml
# agent_profiles.yaml
architect:
  bypass_planner_threshold: simple
```

**Expected Improvements:**
- 50% reduction in execution time for simple tasks
- 30% reduction in overall cost
- Maintained quality for complex tasks

### Optimize Prompt Size

1. Check prompt token usage:
```bash
python3 tools/query_logs.sh state /tmp/logs.jsonl metrics | jq '.input_tokens' | awk '{sum+=$1; count++} END {print "Avg input tokens:", sum/count}'
```

2. Reduce prompt size:
   - Remove unnecessary context
   - Use prompt caching for repeated content
   - Compress examples

3. Monitor impact on quality:
```bash
# Check failure rate after optimization
python3 tools/aggregate_metrics.py state/ | jq '.failure_rate'
```

---

## Backup and Recovery

### Backup State Directory

```bash
# Daily backup
tar -czf grace-state-$(date +%Y%m%d).tar.gz state/

# Upload to S3
aws s3 cp grace-state-$(date +%Y%m%d).tar.gz s3://grace-backups/

# Retention: keep 30 days
find . -name "grace-state-*.tar.gz" -mtime +30 -delete
```

### Restore from Backup

```bash
# Download backup
aws s3 cp s3://grace-backups/grace-state-20260530.tar.gz .

# Extract
tar -xzf grace-state-20260530.tar.gz

# Verify integrity
python3 tools/validate_logs.py state/
```

### Disaster Recovery

1. **State directory corrupted:**
   ```bash
   # Restore from latest backup
   ./scripts/restore_state.sh grace-state-20260530.tar.gz
   
   # Verify health
   python3 tools/health_check.py state/
   ```

2. **Logs missing:**
   ```bash
   # Reconstruct from packet artifacts
   python3 tools/reconstruct_logs.py state/
   ```

3. **Metrics lost:**
   ```bash
   # Recalculate from logs
   python3 tools/recalculate_metrics.py state/
   ```

---

## Alerting

### Configure Alerts

```yaml
# alerts.yaml
alerts:
  high_failure_rate:
    threshold: 0.10
    window_hours: 24
    severity: warning
    
  executor_stuck:
    threshold: 5
    severity: critical
    
  cost_spike:
    threshold_pct: 50
    window_hours: 6
    severity: warning
    
  missing_metrics:
    threshold_pct: 0.05
    severity: warning
```

### Alert Channels

```bash
# Slack webhook
export SLACK_WEBHOOK_URL="https://hooks.slack.com/services/..."

# PagerDuty
export PAGERDUTY_API_KEY="..."

# Email
export ALERT_EMAIL="ops@example.com"
```

### Test Alerts

```bash
# Test alert system
python3 tools/test_alerts.py --config alerts.yaml

# Send test alert
python3 tools/send_alert.py --severity critical --message "Test alert"
```

---

## Related Documentation

- [LOG_DRIVEN_VERIFICATION.md](LOG_DRIVEN_VERIFICATION.md) - Verification approach
- [METRICS.md](METRICS.md) - Metrics reference
- [SUCCESS_CRITERIA.md](../src/prefect_grace/docs/SUCCESS_CRITERIA.md) - Success definitions
