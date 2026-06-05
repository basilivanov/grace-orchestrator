# Metrics Reference

## Execution Metrics

### Token Metrics

- **input_tokens**: Number of tokens in prompt
  - Type: integer
  - Range: >0
  - Source: Model API response

- **output_tokens**: Number of tokens in response
  - Type: integer
  - Range: >0
  - Source: Model API response

- **total_tokens**: input_tokens + output_tokens
  - Type: integer
  - Range: >0
  - Calculated field

### Cost Metrics

- **cost_usd**: Execution cost in USD
  - Type: float
  - Range: >=0
  - Calculated using model-specific pricing
  - See cost_calculator.py for pricing table

**Pricing Table (as of 2026-05-30):**

| Model | Input ($/1M tokens) | Output ($/1M tokens) |
|-------|---------------------|----------------------|
| claude-opus-4 | $15.00 | $75.00 |
| claude-sonnet-4 | $3.00 | $15.00 |
| gemini-3.1-pro | $1.25 | $5.00 |
| gemini-3.5-flash | $0.075 | $0.30 |

**Calculation:**
```python
cost_usd = (input_tokens / 1_000_000 * input_price) + (output_tokens / 1_000_000 * output_price)
```

### Duration Metrics

- **duration_seconds**: Wall-clock execution time
  - Type: float
  - Range: >0
  - Includes agent startup, execution, and shutdown
  - Measured from PACKET_START to PACKET_END

### Metadata

- **packet_id**: Unique packet identifier
- **executor_id**: Executor that ran the packet
- **model**: Model used for execution
- **complexity**: Packet complexity (simple/medium/complex)
- **timestamp**: ISO 8601 timestamp

---

## Aggregated Metrics

### Total Metrics

- **total_executions**: Count of all executions
  - Type: integer
  - Includes successful and failed executions

- **total_cost_usd**: Sum of all costs
  - Type: float
  - Total spend across all executions

- **total_tokens**: Sum of all tokens
  - Type: integer
  - Input + output tokens across all executions

- **avg_duration_seconds**: Average execution time
  - Type: float
  - Mean duration across all executions

### By Model

Metrics grouped by model:

```json
{
  "by_model": {
    "gemini-3.5-flash": {
      "count": 100,
      "cost_usd": 0.50,
      "tokens": 150000,
      "avg_duration_seconds": 45.2
    },
    "gemini-3.1-pro": {
      "count": 50,
      "cost_usd": 2.50,
      "tokens": 200000,
      "avg_duration_seconds": 120.5
    },
    "claude-opus-4": {
      "count": 20,
      "cost_usd": 15.00,
      "tokens": 100000,
      "avg_duration_seconds": 180.3
    }
  }
}
```

### By Complexity

Metrics grouped by complexity level:

```json
{
  "by_complexity": {
    "simple": {
      "count": 100,
      "cost_usd": 0.50,
      "tokens": 150000,
      "avg_cost_usd": 0.005
    },
    "medium": {
      "count": 50,
      "cost_usd": 2.50,
      "tokens": 200000,
      "avg_cost_usd": 0.050
    },
    "complex": {
      "count": 20,
      "cost_usd": 15.00,
      "tokens": 100000,
      "avg_cost_usd": 0.750
    }
  }
}
```

### Savings Metrics

Metrics showing cost savings from complexity routing:

- **actual_cost_usd**: Actual cost with complexity routing
  - Sum of all execution costs

- **premium_only_cost_usd**: Hypothetical cost if all used premium
  - Calculated as: total_executions * avg_premium_cost

- **savings_usd**: Difference (premium - actual)
  - Amount saved by using cheaper models

- **savings_pct**: Percentage saved
  - Calculated as: (savings_usd / premium_only_cost_usd) * 100

**Example:**
```json
{
  "savings": {
    "actual_cost_usd": 18.50,
    "premium_only_cost_usd": 51.00,
    "savings_usd": 32.50,
    "savings_pct": 63.7
  }
}
```

---

## Event Types

### EXECUTOR_SELECTED

Logged when executor is selected for packet.

**Fields:**
- event: "EXECUTOR_SELECTED"
- packet_id: Packet identifier
- executor_id: Selected executor
- model: Model to use
- role: Agent role (coder/planner/reviewer)
- complexity: Packet complexity
- reason: Selection reason

**Example:**
```json
{
  "event": "EXECUTOR_SELECTED",
  "packet_id": "FEAT-XYZ-V1",
  "executor_id": "coder-cheap",
  "model": "gemini-3.5-flash",
  "role": "coder",
  "complexity": "simple",
  "reason": "complexity_routing",
  "timestamp": "2026-05-30T10:00:00Z"
}
```

### PACKET_START

Logged when packet execution starts.

**Fields:**
- event: "PACKET_START"
- packet_id: Packet identifier
- role: Agent role
- timestamp: Start time

**Example:**
```json
{
  "event": "PACKET_START",
  "packet_id": "FEAT-XYZ-V1",
  "role": "coder",
  "timestamp": "2026-05-30T10:00:00Z"
}
```

### PACKET_END

Logged when packet execution completes.

**Fields:**
- event: "PACKET_END"
- packet_id: Packet identifier
- status: Terminal status (accepted/blocked/failed)
- returncode: Exit code
- duration_seconds: Execution duration
- timestamp: End time

**Example:**
```json
{
  "event": "PACKET_END",
  "packet_id": "FEAT-XYZ-V1",
  "status": "accepted",
  "returncode": 0,
  "duration_seconds": 300.5,
  "timestamp": "2026-05-30T10:05:00Z"
}
```

### EXECUTION_METRICS

Logged after packet execution with token and cost metrics.

**Fields:**
- event: "EXECUTION_METRICS"
- packet_id: Packet identifier
- executor_id: Executor used
- model: Model used
- input_tokens: Input token count
- output_tokens: Output token count
- total_tokens: Total token count
- cost_usd: Execution cost
- duration_seconds: Execution duration
- timestamp: Metric collection time

**Example:**
```json
{
  "event": "EXECUTION_METRICS",
  "packet_id": "FEAT-XYZ-V1",
  "executor_id": "coder-cheap",
  "model": "gemini-3.5-flash",
  "input_tokens": 1000,
  "output_tokens": 500,
  "total_tokens": 1500,
  "cost_usd": 0.002,
  "duration_seconds": 300.5,
  "timestamp": "2026-05-30T10:05:01Z"
}
```

### EXECUTOR_HISTORY_LOADED

Logged when executor history is loaded for rotation decisions.

**Fields:**
- event: "EXECUTOR_HISTORY_LOADED"
- packet_id: Packet identifier
- history_count: Number of previous executions
- timestamp: Load time

**Example:**
```json
{
  "event": "EXECUTOR_HISTORY_LOADED",
  "packet_id": "FEAT-XYZ-V2",
  "history_count": 2,
  "timestamp": "2026-05-30T10:10:00Z"
}
```

### PLANNER_BYPASS

Logged when planner is bypassed for simple packets.

**Fields:**
- event: "PLANNER_BYPASS"
- packet_id: Packet identifier
- complexity: Packet complexity
- requires_planner: false
- reason: Bypass reason
- timestamp: Decision time

**Example:**
```json
{
  "event": "PLANNER_BYPASS",
  "packet_id": "FEAT-SIMPLE-V1",
  "complexity": "simple",
  "requires_planner": false,
  "reason": "simple_packet_no_planning_needed",
  "timestamp": "2026-05-30T10:15:00Z"
}
```

### PLANNER_REQUIRED

Logged when planner is required for complex packets.

**Fields:**
- event: "PLANNER_REQUIRED"
- packet_id: Packet identifier
- complexity: Packet complexity
- requires_planner: true
- reason: Requirement reason
- timestamp: Decision time

**Example:**
```json
{
  "event": "PLANNER_REQUIRED",
  "packet_id": "FEAT-COMPLEX-V1",
  "complexity": "complex",
  "requires_planner": true,
  "reason": "complex_packet_needs_planning",
  "timestamp": "2026-05-30T10:20:00Z"
}
```

---

## Querying Metrics

### Command Line

```bash
# Get all metrics
python3 tools/aggregate_metrics.py state/

# Get metrics for specific packet
python3 tools/query_logs.sh state /tmp/logs.jsonl metrics | jq 'select(.packet_id=="FEAT-XYZ-V1")'

# Get cost by model
python3 tools/aggregate_metrics.py state/ | jq '.by_model'

# Get savings
python3 tools/aggregate_metrics.py state/ | jq '.savings'
```

### Python API

```python
from prefect_grace.tools import aggregate_metrics

# Get all metrics
metrics = aggregate_metrics("/path/to/state")

# Access specific metrics
print(f"Total cost: ${metrics['total_cost_usd']:.2f}")
print(f"Savings: {metrics['savings']['savings_pct']:.1f}%")

# By model
for model, stats in metrics['by_model'].items():
    print(f"{model}: {stats['count']} executions, ${stats['cost_usd']:.2f}")
```

### SQL Queries (if using database)

```sql
-- Total cost by model
SELECT 
  model,
  COUNT(*) as executions,
  SUM(cost_usd) as total_cost,
  AVG(duration_seconds) as avg_duration
FROM execution_metrics
GROUP BY model
ORDER BY total_cost DESC;

-- Savings calculation
SELECT 
  SUM(cost_usd) as actual_cost,
  COUNT(*) * (SELECT AVG(cost_usd) FROM execution_metrics WHERE model='claude-opus-4') as premium_cost,
  (COUNT(*) * (SELECT AVG(cost_usd) FROM execution_metrics WHERE model='claude-opus-4') - SUM(cost_usd)) as savings
FROM execution_metrics;

-- Failure rate by complexity
SELECT 
  complexity,
  COUNT(*) as total,
  SUM(CASE WHEN status='failed' THEN 1 ELSE 0 END) as failures,
  ROUND(100.0 * SUM(CASE WHEN status='failed' THEN 1 ELSE 0 END) / COUNT(*), 2) as failure_rate_pct
FROM execution_metrics
GROUP BY complexity;
```

---

## Metrics Dashboard

### Dashboard Components

1. **Overview Panel**
   - Total executions
   - Total cost
   - Savings percentage
   - Average duration

2. **Cost Breakdown**
   - Pie chart: cost by model
   - Bar chart: cost by complexity
   - Line chart: cost over time

3. **Performance Metrics**
   - Average duration by model
   - Success rate by complexity
   - Executor rotation frequency

4. **Trends**
   - Daily cost trend
   - Failure rate trend
   - Savings trend

### Generate Dashboard

```bash
# Generate HTML dashboard
python3 tools/generate_dashboard.sh state/ /var/www/dashboard/

# View dashboard
open /var/www/dashboard/index.html
```

### Dashboard Data Format

```json
{
  "generated_at": "2026-05-30T10:00:00Z",
  "period": {
    "start": "2026-05-23T00:00:00Z",
    "end": "2026-05-30T23:59:59Z"
  },
  "overview": {
    "total_executions": 170,
    "total_cost_usd": 18.50,
    "savings_pct": 63.7,
    "avg_duration_seconds": 85.3
  },
  "by_model": { ... },
  "by_complexity": { ... },
  "trends": {
    "daily_cost": [
      {"date": "2026-05-23", "cost_usd": 2.50},
      {"date": "2026-05-24", "cost_usd": 2.75},
      ...
    ]
  }
}
```

---

## Metrics Best Practices

### 1. Monitor Regularly

- Check metrics daily
- Review trends weekly
- Analyze anomalies immediately

### 2. Set Baselines

- Establish normal cost ranges
- Define acceptable failure rates
- Track savings targets

### 3. Alert on Anomalies

- Cost spikes (>50% increase)
- High failure rates (>10%)
- Low savings (<50%)

### 4. Optimize Continuously

- Review expensive packets
- Adjust complexity thresholds
- Improve prompts for failed packets

### 5. Archive Historical Data

- Keep 90 days of detailed metrics
- Aggregate older data monthly
- Backup metrics database

---

## Related Documentation

- [SUCCESS_CRITERIA.md](../src/prefect_grace/docs/SUCCESS_CRITERIA.md) - Success definitions
- [LOG_DRIVEN_VERIFICATION.md](LOG_DRIVEN_VERIFICATION.md) - Verification approach
- [RUNBOOK.md](RUNBOOK.md) - Operations runbook
