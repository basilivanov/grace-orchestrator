# Quick Start Guide

Get started with GRACE orchestrator in 5 minutes.

## Prerequisites

- Python 3.12+
- Git
- 4GB RAM minimum
- API keys for AI models (Claude, Gemini)

## Installation

### 1. Install GRACE

```bash
pip install grace-orchestrator
```

For development with Prefect:

```bash
pip install grace-orchestrator[prefect]
```

### 2. Set Up API Keys

```bash
# Claude API key
export ANTHROPIC_API_KEY="sk-ant-..."

# Gemini API key
export GOOGLE_API_KEY="..."

# Verify keys
python3 -c "import os; print('Claude:', 'OK' if os.getenv('ANTHROPIC_API_KEY') else 'MISSING'); print('Gemini:', 'OK' if os.getenv('GOOGLE_API_KEY') else 'MISSING')"
```

### 3. Initialize Project

```bash
# Navigate to your project
cd /path/to/your/project

# Initialize GRACE
grace init

# This creates:
# - grace/project.yaml          # Project configuration
# - grace/agent_profiles.yaml   # Agent and executor configuration
# - grace/requirements.xml      # System requirements
# - grace/technology.xml        # Technology constraints
```

## Your First Packet

### 1. Create a Feature Packet

Create a packet directory:

```bash
mkdir -p packets/FEAT-HELLO-V1
```

Create packet specification:

```bash
cat > packets/FEAT-HELLO-V1/packet.md <<'EOF'
# FEAT-HELLO-V1: Hello World Feature

## Objective
Add a simple "Hello World" endpoint to the API.

## Requirements
- Add GET /api/hello endpoint
- Return JSON: {"message": "Hello, World!"}
- Add unit test

## Acceptance Criteria
- Endpoint returns 200 status
- Response matches expected format
- Test passes
EOF
```

### 2. Run the Packet

```bash
# Execute packet with GRACE
python3 -m prefect_grace.flows.codex_launcher \
  --packet FEAT-HELLO-V1 \
  --role coder

# Check status
cat state/runs/latest/execution_trace.jsonl | grep PACKET_END
```

### 3. View Results

```bash
# Check packet status
python3 tools/query_logs.sh state /tmp/logs.jsonl all | grep FEAT-HELLO-V1

# View metrics
python3 tools/aggregate_metrics.py state/ | jq '.by_complexity'

# Check cost
python3 tools/aggregate_metrics.py state/ | jq '.total_cost_usd'
```

## Understanding the Output

### Execution Trace

The execution trace shows what happened:

```jsonl
{"event": "PACKET_START", "packet_id": "FEAT-HELLO-V1", "timestamp": "2026-05-30T10:00:00Z"}
{"event": "EXECUTOR_SELECTED", "executor_id": "coder-cheap", "model": "gemini-3.5-flash", "complexity": "simple"}
{"event": "PACKET_END", "status": "accepted", "returncode": 0, "duration_seconds": 45.2}
{"event": "EXECUTION_METRICS", "cost_usd": 0.002, "tokens": 1500}
```

### Key Events

- **PACKET_START**: Execution began
- **EXECUTOR_SELECTED**: Model chosen based on complexity
- **PACKET_END**: Execution completed
- **EXECUTION_METRICS**: Cost and token usage

## Configuration

### Agent Profiles

Edit `grace/agent_profiles.yaml`:

```yaml
executors:
  coder-cheap:
    model: gemini-3.5-flash
    priority: 1
    max_consecutive_failures: 3
    
  coder-standard:
    model: gemini-3.1-pro
    priority: 2
    max_consecutive_failures: 3
    
  coder-premium:
    model: claude-opus-4
    priority: 3
    max_consecutive_failures: 3

complexity_routing:
  simple: coder-cheap
  medium: coder-standard
  complex: coder-premium
```

### Project Configuration

Edit `grace/project.yaml`:

```yaml
defaults:
  report_path: test-results/grace-report.json
  log_dir: logs/gracectl
  repo_root: .
  state_dir: state

slices:
  API-ENDPOINTS:
    title: "API Endpoints"
    description: "REST API verification"
    commands:
      backend:
        - pytest tests/api/
    evidence:
      - test-results/api-report.json
```

## Common Tasks

### Run Multiple Packets

```bash
# Run all packets in a directory
for packet in packets/FEAT-*-V1; do
  python3 -m prefect_grace.flows.codex_launcher \
    --packet $(basename $packet) \
    --role coder
done
```

### Check Health

```bash
# Run health check
python3 tools/health_check.py state/

# Expected output:
# ✓ Recent activity: PASS
# ✓ No stuck packets: PASS
# ✓ Cost tracking: PASS
# ✓ Error rate: PASS
# ✓ Executor diversity: PASS
```

### View Metrics

```bash
# Total cost
python3 tools/aggregate_metrics.py state/ | jq '.total_cost_usd'

# Savings
python3 tools/aggregate_metrics.py state/ | jq '.savings.savings_pct'

# Cost by model
python3 tools/aggregate_metrics.py state/ | jq '.by_model'
```

### Verify Orchestrator

```bash
# Run verification
python3 tools/verify_orchestrator.py state/

# Expected output:
# ✓ Executor selection: PASS
# ✓ Executor rotation: PASS
# ✓ Status transitions: PASS
# ✓ Metrics collection: PASS
# Verdict: PASS
```

## Troubleshooting

### Issue: API Key Not Found

```bash
# Check environment variables
env | grep API_KEY

# Set keys
export ANTHROPIC_API_KEY="sk-ant-..."
export GOOGLE_API_KEY="..."
```

### Issue: Packet Failed

```bash
# Check logs
cat state/runs/latest/execution_trace.jsonl | grep ERROR

# View packet output
cat state/runs/latest/output.log

# Check failure reason
python3 tools/query_logs.sh state /tmp/logs.jsonl all | jq 'select(.packet_id=="FEAT-HELLO-V1" and .event=="PACKET_END")'
```

### Issue: High Cost

```bash
# Check which model was used
python3 tools/query_logs.sh state /tmp/logs.jsonl all | jq 'select(.event=="EXECUTOR_SELECTED")'

# Review complexity classification
cat packets/FEAT-HELLO-V1/packet.md

# Adjust complexity in architect_prompt.md if needed
```

## Next Steps

### 1. Learn About Complexity Routing

Complexity routing saves cost by using cheaper models for simple tasks:

- **Simple** (gemini-3.5-flash): Routine changes, <100 LOC
- **Medium** (gemini-3.1-pro): Moderate changes, 100-500 LOC
- **Complex** (claude-opus-4): Major changes, >500 LOC

See [METRICS.md](METRICS.md) for details.

### 2. Set Up Monitoring

```bash
# Add health check to cron
echo "0 * * * * python3 /path/to/tools/health_check.py /path/to/state/" | crontab -

# Generate daily dashboard
echo "0 2 * * * python3 /path/to/tools/aggregate_metrics.py /path/to/state/ > /var/www/dashboard/metrics.json" | crontab -
```

### 3. Integrate with CI/CD

Add to `.github/workflows/grace.yml`:

```yaml
name: GRACE Verification

on: [push, pull_request]

jobs:
  verify:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v3
      
      - name: Install GRACE
        run: pip install grace-orchestrator
        
      - name: Run packet
        env:
          ANTHROPIC_API_KEY: ${{ secrets.ANTHROPIC_API_KEY }}
          GOOGLE_API_KEY: ${{ secrets.GOOGLE_API_KEY }}
        run: |
          python3 -m prefect_grace.flows.codex_launcher \
            --packet FEAT-HELLO-V1 \
            --role coder
            
      - name: Check results
        run: |
          python3 tools/verify_orchestrator.py state/
```

### 4. Explore Advanced Features

- **Executor Rotation**: Automatic failover to different models
- **Planner Bypass**: Skip planning for simple tasks
- **Cost Budgets**: Set per-packet cost limits
- **Custom Executors**: Add your own model configurations

See [RUNBOOK.md](RUNBOOK.md) for operations guide.

## Architecture Overview

```
┌─────────────────────────────────────────────────────────┐
│                    GRACE Orchestrator                    │
├─────────────────────────────────────────────────────────┤
│                                                          │
│  ┌──────────────┐      ┌──────────────┐                │
│  │  Architect   │─────▶│   Planner    │                │
│  │  (Classify)  │      │  (Optional)  │                │
│  └──────────────┘      └──────────────┘                │
│         │                      │                         │
│         ▼                      ▼                         │
│  ┌──────────────────────────────────┐                  │
│  │     Executor Selection           │                  │
│  │  - Complexity routing            │                  │
│  │  - History-based rotation        │                  │
│  │  - Cost optimization             │                  │
│  └──────────────────────────────────┘                  │
│         │                                                │
│         ▼                                                │
│  ┌──────────────┐  ┌──────────────┐  ┌──────────────┐ │
│  │ coder-cheap  │  │coder-standard│  │coder-premium │ │
│  │ (Flash)      │  │   (Pro)      │  │   (Opus)     │ │
│  └──────────────┘  └──────────────┘  └──────────────┘ │
│         │                  │                  │         │
│         └──────────────────┴──────────────────┘         │
│                           │                              │
│                           ▼                              │
│                  ┌──────────────┐                       │
│                  │   Reviewer   │                       │
│                  │  (Validate)  │                       │
│                  └──────────────┘                       │
│                                                          │
└─────────────────────────────────────────────────────────┘
```

### Key Components

1. **Architect**: Classifies packet complexity
2. **Planner**: Creates execution plan (optional for simple packets)
3. **Executor Selection**: Routes to appropriate model
4. **Executors**: Run packet with selected model
5. **Reviewer**: Validates results

### Data Flow

1. Packet submitted
2. Architect classifies complexity
3. Executor selected based on complexity and history
4. Packet executed with selected model
5. Metrics collected (tokens, cost, duration)
6. Results validated by reviewer
7. Logs written to execution_trace.jsonl

## Cost Optimization

### Typical Costs

- **Simple packet**: $0.001-$0.01 (Flash)
- **Medium packet**: $0.05-$0.20 (Pro)
- **Complex packet**: $0.50-$2.00 (Opus)

### Savings Example

Without complexity routing (all Opus):
- 100 packets × $1.00 = $100.00

With complexity routing:
- 70 simple × $0.005 = $0.35
- 20 medium × $0.10 = $2.00
- 10 complex × $1.00 = $10.00
- **Total: $12.35 (87.7% savings)**

### Optimization Tips

1. **Classify accurately**: Review architect_prompt.md
2. **Enable planner bypass**: Skip planning for simple tasks
3. **Monitor metrics**: Track cost trends
4. **Adjust thresholds**: Tune complexity boundaries

## Resources

### Documentation

- [LOG_DRIVEN_VERIFICATION.md](LOG_DRIVEN_VERIFICATION.md) - Verification approach
- [RUNBOOK.md](RUNBOOK.md) - Operations guide
- [METRICS.md](METRICS.md) - Metrics reference
- [SUCCESS_CRITERIA.md](../src/prefect_grace/docs/SUCCESS_CRITERIA.md) - Success definitions

### Tools

- `tools/verify_orchestrator.py` - Verify orchestrator health
- `tools/aggregate_metrics.py` - Aggregate metrics
- `tools/health_check.py` - Health monitoring
- `tools/query_logs.sh` - Query execution logs

### Support

- GitHub Issues: Report bugs and request features
- Documentation: Full reference documentation
- Examples: Sample packets and configurations

## Summary

You've learned how to:

1. ✓ Install GRACE orchestrator
2. ✓ Create and run your first packet
3. ✓ View execution metrics
4. ✓ Verify orchestrator health
5. ✓ Understand cost optimization

Next: Explore [RUNBOOK.md](RUNBOOK.md) for advanced operations.
