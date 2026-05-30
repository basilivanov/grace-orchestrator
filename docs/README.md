# GRACE Orchestrator Documentation

Complete documentation for the GRACE (Gated Release with Artifact-driven Continuous Evidence) orchestrator.

## Getting Started

### New Users

- **[Quick Start Guide](QUICKSTART.md)** - Get up and running in 5 minutes
  - Installation
  - Your first packet
  - Basic configuration
  - Common tasks

### Core Concepts

- **[Architecture Overview](../README.md#architecture)** - System design and workflow
- **[Cost Optimization](METRICS.md#cost-optimization)** - How complexity routing saves 87% on costs
- **[Success Criteria](../src/prefect_grace/docs/SUCCESS_CRITERIA.md)** - What "success" means for packets and features

## Operations

### Daily Operations

- **[Operations Runbook](RUNBOOK.md)** - Troubleshooting and operations guide
  - Common issues and resolutions
  - Health monitoring
  - Performance tuning
  - Backup and recovery
  - Alerting

### Monitoring

- **[Metrics Reference](METRICS.md)** - Complete metrics documentation
  - Execution metrics (tokens, cost, duration)
  - Aggregated metrics
  - Event types
  - Querying metrics
  - Dashboard setup

- **[Log-Driven Verification](LOG_DRIVEN_VERIFICATION.md)** - Verification approach
  - How it works
  - Verification patterns
  - Cost comparison (99% savings vs traditional testing)
  - CI/CD integration

## Reference

### Configuration

- **[Agent Profiles](../grace/agent_profiles.yaml)** - Executor and model configuration
- **[Project Configuration](../grace/project.yaml)** - Project settings and slices

### Tools

Located in `tools/` directory:

- `verify_orchestrator.py` - Verify orchestrator health
- `aggregate_metrics.py` - Aggregate and analyze metrics
- `health_check.py` - Health monitoring
- `query_logs.sh` - Query execution logs
- `view_trace.py` - Visualize execution traces

### API Reference

Coming soon: Full Python API documentation.

## Architecture Deep Dive

### Components

1. **Architect** - Classifies packet complexity
   - Simple: <100 LOC, routine changes
   - Medium: 100-500 LOC, moderate complexity
   - Complex: >500 LOC, architectural changes

2. **Planner** - Creates execution plans (optional for simple packets)
   - Analyzes requirements
   - Defines work breakdown
   - Can be bypassed for simple tasks

3. **Executor Selection** - Routes to appropriate model
   - Complexity-based routing
   - History-based rotation on failures
   - Cost optimization

4. **Executors** - Execute packets with selected models
   - `coder-cheap`: gemini-3.5-flash ($0.001-$0.01/packet)
   - `coder-standard`: gemini-3.1-pro ($0.05-$0.20/packet)
   - `coder-premium`: claude-opus-4 ($0.50-$2.00/packet)

5. **Reviewer** - Validates results
   - Contract validation
   - Evidence review
   - Quality gates

### Data Flow

```
Packet → Architect → Complexity Classification
                    ↓
              Executor Selection
                    ↓
         ┌──────────┴──────────┐
         ▼          ▼          ▼
      Flash       Pro       Opus
         └──────────┬──────────┘
                    ▼
              Execution
                    ▼
         Metrics Collection
                    ▼
         Structured Logging
                    ▼
              Reviewer
```

## Cost Optimization

### Complexity Routing

GRACE automatically routes packets to cost-appropriate models:

| Complexity | Model | Cost/Packet | Use Case |
|------------|-------|-------------|----------|
| Simple | gemini-3.5-flash | $0.001-$0.01 | Routine changes, <100 LOC |
| Medium | gemini-3.1-pro | $0.05-$0.20 | Moderate changes, 100-500 LOC |
| Complex | claude-opus-4 | $0.50-$2.00 | Major changes, >500 LOC |

### Savings Example

**Without complexity routing** (all premium):
- 100 packets × $1.00 = $100.00

**With complexity routing**:
- 70 simple × $0.005 = $0.35
- 20 medium × $0.10 = $2.00
- 10 complex × $1.00 = $10.00
- **Total: $12.35 (87.7% savings)**

### Log-Driven Verification

Traditional testing:
- Run full pipeline: $0.50-$2.00
- Multiple runs: $5-$20/day

Log-driven verification:
- Analyze logs: $0.001-$0.01
- **99% cost reduction**

## Best Practices

### 1. Packet Design

- Keep packets focused and cohesive
- Write clear acceptance criteria
- Include test requirements
- Document expected complexity

### 2. Monitoring

- Run health checks daily
- Review metrics weekly
- Set up alerting for anomalies
- Archive historical data

### 3. Cost Management

- Monitor savings percentage (target >60%)
- Review expensive packets
- Adjust complexity thresholds as needed
- Enable planner bypass for simple tasks

### 4. Quality Assurance

- Use log-driven verification
- Set up CI/CD integration
- Monitor failure rates
- Review and improve prompts

## Troubleshooting

### Quick Diagnostics

```bash
# Check orchestrator health
python3 tools/health_check.py state/

# Verify logs
python3 tools/verify_orchestrator.py state/

# View metrics
python3 tools/aggregate_metrics.py state/

# Query specific events
python3 tools/query_logs.sh state /tmp/logs.jsonl metrics
```

### Common Issues

See [RUNBOOK.md](RUNBOOK.md) for detailed troubleshooting:

- Executor stuck on same model
- Metrics not collected
- Packets stuck in running state
- High failure rate
- Cost exceeds budget

## Contributing

See [CONTRIBUTING.md](../CONTRIBUTING.md) for contribution guidelines.

## Support

- **Issues**: [GitHub Issues](https://github.com/yourusername/grace-orchestrator/issues)
- **Discussions**: [GitHub Discussions](https://github.com/yourusername/grace-orchestrator/discussions)
- **Documentation**: This site

## License

MIT License - see [LICENSE](../LICENSE) for details.
