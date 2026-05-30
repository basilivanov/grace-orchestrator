# grace-orchestrator

[![PyPI version](https://badge.fury.io/py/grace-orchestrator.svg)](https://badge.fury.io/py/grace-orchestrator)
[![Python 3.12+](https://img.shields.io/badge/python-3.12+-blue.svg)](https://www.python.org/downloads/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)

**GRACE** (Gated Release with Artifact-driven Continuous Evidence) is a verification orchestration framework that coordinates multi-agent AI workflows for software quality assurance.

GRACE enables teams to define verification slices—cohesive units of testing, evidence collection, and quality gates—and orchestrate their execution across backend tests, frontend E2E tests, live traffic replay, and observability monitoring.

## Features

- **Artifact-driven verification**: Define requirements, technology constraints, and development plans before coding
- **Multi-agent orchestration**: Coordinate planner, worker, and reviewer agents through Prefect workflows
- **Slice-based testing**: Group related verification tasks into cohesive slices with clear gates
- **Evidence collection**: Automatically gather test results, logs, and quality metrics
- **Live traffic replay**: Validate changes against real production patterns
- **Observability integration**: Monitor verification flows and track quality over time
- **CLI tooling**: `gracectl` command-line interface for slice verification and evidence management

## Quick Start

### Installation

```bash
pip install grace-orchestrator
```

For Prefect worker support:

```bash
pip install grace-orchestrator[prefect]
```

### Initialize a Project

```bash
# Create grace configuration in your project
grace init

# This creates:
# - grace/project.yaml          # Project configuration
# - grace/requirements.xml      # System requirements
# - grace/technology.xml        # Technology constraints
# - grace/development-plan.xml  # Module structure and phases
# - grace/knowledge-graph.xml   # Semantic code map
```

### Define a Verification Slice

Edit `grace/project.yaml`:

```yaml
slices:
  AUTH-FLOW:
    title: "Authentication Flow"
    description: "Login, logout, and session management"
    gate: "Gate 2: backend + frontend smoke"
    vm_ids:
      - VM-AUTH-SECURITY
      - VM-SESSION-LIFECYCLE
    docs:
      - docs/auth-design.md
    commands:
      backend:
        - pytest tests/test_auth.py
        - pytest tests/test_session.py
      frontend:
        - npm run test:e2e -- auth.spec.ts
    evidence:
      - test-results/auth-report.json
```

### Run Verification

```bash
# Verify a single slice
gracectl slice verify AUTH-FLOW

# Run all commands for a slice
gracectl slice replay AUTH-FLOW

# Watch for live traffic patterns
gracectl watch start FLOW-AUTH
```

## Architecture

GRACE orchestrates three types of agents:

1. **Planner**: Analyzes requirements, creates work packets, and defines verification strategy
2. **Worker**: Executes code changes, runs tests, and collects evidence
3. **Reviewer**: Validates changes against contracts, reviews evidence, and approves/rejects

### Workflow

```
┌─────────────┐
│   Planner   │  Analyzes requirements → Creates work packet
└──────┬──────┘
       │
       ▼
┌─────────────┐
│   Worker    │  Implements changes → Runs tests → Collects evidence
└──────┬──────┘
       │
       ▼
┌─────────────┐
│  Reviewer   │  Validates contracts → Reviews evidence → Gates release
└─────────────┘
```

### Prefect Integration

GRACE uses Prefect for workflow orchestration:

```python
from grace_orchestrator import create_verification_flow

flow = create_verification_flow(
    slice_id="AUTH-FLOW",
    project_config="grace/project.yaml"
)

flow.deploy(name="auth-verification", work_pool="default")
```

## Configuration

### Project Configuration (`grace/project.yaml`)

```yaml
defaults:
  report_path: test-results/grace-report.json
  log_dir: logs/gracectl
  repo_root: .

slices:
  SLICE-ID:
    title: "Human-readable title"
    description: "What this slice verifies"
    gate: "Gate level and criteria"
    vm_ids:
      - VM-MODULE-1
      - VM-MODULE-2
    docs:
      - path/to/design-doc.md
    commands:
      backend:
        - command to run backend tests
      frontend:
        - command to run frontend tests
      replay:
        - command to replay live traffic
    evidence:
      - path/to/evidence-file

watch:
  flows:
    - id: FLOW-ID
      label: "Flow description"
      script: path/to/watch-script.py
      args:
        --log: logs/app.jsonl
        --window-minutes: 30
      slices:
        - SLICE-ID
```

### Agent Profiles (`grace/agent_profiles.yaml`)

```yaml
planner:
  model: claude-opus-4
  temperature: 0.7
  max_tokens: 8000

worker:
  model: claude-sonnet-4
  temperature: 0.3
  max_tokens: 16000

reviewer:
  model: claude-opus-4
  temperature: 0.5
  max_tokens: 8000
```

## Docker Deployment

### Worker Container

```bash
docker build -f docker/Dockerfile.worker -t grace-worker:latest .
docker run -d \
  -e PREFECT_API_URL=http://prefect-server:4200/api \
  -e GRACE_PROJECT_CONFIG=/workspace/grace/project.yaml \
  -v $(pwd):/workspace \
  grace-worker:latest
```

### Docker Compose Integration

Add to your project's `docker-compose.yml`:

```yaml
services:
  grace-worker:
    image: grace-orchestrator-worker:v0.1.0
    environment:
      PREFECT_API_URL: http://prefect-server:4200/api
      GRACE_PROJECT_CONFIG: /workspace/grace/project.yaml
      GRACE_WORK_POOL: ${GRACE_WORK_POOL:-default}
      GRACE_LIVE_QUEUE: ${GRACE_LIVE_QUEUE:-grace-live}
    volumes:
      - .:/workspace
      - grace-state:/var/lib/grace-orchestrator
    working_dir: /workspace
    networks:
      - prefect

volumes:
  grace-state:

networks:
  prefect:
    external: true
```

## CLI Reference

### `gracectl slice`

```bash
# Verify a slice (run all commands and collect evidence)
gracectl slice verify SLICE-ID

# Replay a slice (run commands without full verification)
gracectl slice replay SLICE-ID

# List all slices
gracectl slice list
```

### `gracectl watch`

```bash
# Start watching a flow
gracectl watch start FLOW-ID

# Stop watching a flow
gracectl watch stop FLOW-ID

# List active watches
gracectl watch list
```

### `gracectl evidence`

```bash
# Collect evidence for a slice
gracectl evidence collect SLICE-ID

# Show evidence summary
gracectl evidence show SLICE-ID

# Export evidence to file
gracectl evidence export SLICE-ID --output evidence.json
```

### `gracectl env`

```bash
# Show environment configuration
gracectl env show

# Validate environment setup
gracectl env validate
```

## Development

### Setup

```bash
git clone https://github.com/yourusername/grace-orchestrator.git
cd grace-orchestrator

# Create virtual environment
python -m venv venv
source venv/bin/activate  # or `venv\Scripts\activate` on Windows

# Install in development mode
pip install -e ".[dev,prefect]"

# Run tests
pytest
```

### Project Structure

```
grace-orchestrator/
├── src/
│   └── grace_orchestrator/
│       ├── __init__.py
│       ├── cli/              # gracectl command-line interface
│       ├── core/             # Core orchestration logic
│       ├── agents/           # Planner, worker, reviewer agents
│       ├── flows/            # Prefect flow definitions
│       ├── templates/        # Project initialization templates
│       └── utils/            # Shared utilities
├── tests/
├── docker/
│   ├── Dockerfile.worker
│   └── docker-compose.fragment.yaml
├── docs/
├── pyproject.toml
├── README.md
└── LICENSE
```

## Examples

### Example 1: API Endpoint Verification

```yaml
slices:
  USER-API:
    title: "User API Endpoints"
    description: "CRUD operations for user management"
    gate: "Gate 2: unit + integration tests"
    vm_ids:
      - VM-USER-SERVICE
      - VM-AUTH-MIDDLEWARE
    commands:
      backend:
        - pytest tests/api/test_users.py -v
        - pytest tests/integration/test_user_flow.py
    evidence:
      - test-results/user-api.xml
```

### Example 2: Frontend Feature Verification

```yaml
slices:
  CHECKOUT-FLOW:
    title: "Checkout Flow"
    description: "Shopping cart to payment completion"
    gate: "Gate 3: E2E + live traffic replay"
    vm_ids:
      - VM-CART-UI
      - VM-PAYMENT-INTEGRATION
    commands:
      frontend:
        - npm run test:e2e -- checkout.spec.ts
      replay:
        - python tools/replay_checkout.py --log logs/checkout.jsonl
    evidence:
      - test-results/checkout-e2e.json
      - logs/checkout-replay-results.json
```

## Contributing

Contributions are welcome! Please read our [Contributing Guide](CONTRIBUTING.md) for details on our code of conduct and the process for submitting pull requests.

## License

This project is licensed under the MIT License - see the [LICENSE](LICENSE) file for details.

## Acknowledgments

GRACE is built on the principles of artifact-driven development and multi-agent orchestration. It integrates with:

- [Prefect](https://www.prefect.io/) for workflow orchestration
- [Anthropic Claude](https://www.anthropic.com/) for AI agent capabilities
- Standard testing frameworks (pytest, Jest, Playwright, etc.)

## Support

- Documentation: [https://grace-orchestrator.readthedocs.io](https://grace-orchestrator.readthedocs.io)
- Issues: [https://github.com/yourusername/grace-orchestrator/issues](https://github.com/yourusername/grace-orchestrator/issues)
- Discussions: [https://github.com/yourusername/grace-orchestrator/discussions](https://github.com/yourusername/grace-orchestrator/discussions)
