# SETUP.md - grace-orchestrator Setup Guide

This guide walks you through setting up grace-orchestrator for your project.

## Table of Contents

1. [Prerequisites](#prerequisites)
2. [Installation](#installation)
3. [Project Initialization](#project-initialization)
4. [Configuration](#configuration)
5. [Prefect Setup](#prefect-setup)
6. [Docker Setup](#docker-setup)
7. [First Verification](#first-verification)
8. [Troubleshooting](#troubleshooting)

## Prerequisites

### Required

- **Python 3.12 or higher**
  ```bash
  python --version  # Should be 3.12+
  ```

- **pip** (Python package manager)
  ```bash
  pip --version
  ```

### Optional (but recommended)

- **Docker** (for containerized workers)
  ```bash
  docker --version
  docker-compose --version
  ```

- **Prefect Server** (for workflow orchestration)
  ```bash
  prefect version
  ```

## Installation

### Option 1: Install from PyPI (recommended)

```bash
# Basic installation
pip install grace-orchestrator

# With Prefect support
pip install grace-orchestrator[prefect]

# With all optional dependencies
pip install grace-orchestrator[all]
```

### Option 2: Install from source

```bash
git clone https://github.com/yourusername/grace-orchestrator.git
cd grace-orchestrator
pip install -e ".[dev,prefect]"
```

### Verify Installation

```bash
gracectl --version
grace --version
```

## Project Initialization

### Step 1: Navigate to your project

```bash
cd /path/to/your/project
```

### Step 2: Initialize GRACE

```bash
grace init
```

This creates:

```
your-project/
├── grace/
│   ├── project.yaml          # Main configuration
│   ├── agent_profiles.yaml   # Agent settings
│   ├── requirements.xml      # System requirements
│   ├── technology.xml        # Tech stack
│   ├── development-plan.xml  # Module structure
│   └── knowledge-graph.xml   # Code semantics
```

### Step 3: Review generated files

Each file contains templates and examples. Review and customize them for your project.

## Configuration

### Configure project.yaml

Edit `grace/project.yaml`:

```yaml
defaults:
  report_path: test-results/grace-report.json
  log_dir: logs/gracectl
  repo_root: .

slices:
  # Define your first verification slice
  EXAMPLE-SLICE:
    title: "Example Verification Slice"
    description: "Template for your first slice"
    gate: "Gate 1: basic verification"
    vm_ids:
      - VM-EXAMPLE-MODULE
    docs:
      - docs/example.md
    commands:
      backend:
        - pytest tests/
      frontend:
        - npm test
    evidence:
      - test-results/example.json
```

### Configure agent_profiles.yaml

Edit `grace/agent_profiles.yaml`:

```yaml
planner:
  model: claude-opus-4
  temperature: 0.7
  max_tokens: 8000
  # Optional: custom system prompt
  # system_prompt_path: grace/prompts/planner.md

worker:
  model: claude-sonnet-4
  temperature: 0.3
  max_tokens: 16000

reviewer:
  model: claude-opus-4
  temperature: 0.5
  max_tokens: 8000
```

### Environment Variables

Create or update `.env`:

```bash
# Prefect configuration
PREFECT_API_URL=http://localhost:4200/api
GRACE_WORK_POOL=default
GRACE_LIVE_QUEUE=grace-live

# GRACE configuration
GRACE_PROJECT_CONFIG=grace/project.yaml
GRACE_REPO_ROOT=.

# Optional: Git configuration for worker
GRACE_GIT_USER_NAME="GRACE Worker"
GRACE_GIT_USER_EMAIL="grace-worker@example.com"

# Optional: API keys for AI models
ANTHROPIC_API_KEY=your-api-key-here
```

## Prefect Setup

### Option 1: Local Prefect Server

```bash
# Start Prefect server
prefect server start

# In another terminal, create work pool
prefect work-pool create default --type process

# Start a worker
prefect worker start --pool default
```

### Option 2: Prefect Cloud

```bash
# Login to Prefect Cloud
prefect cloud login

# Create work pool
prefect work-pool create grace-pool --type process

# Start worker
prefect worker start --pool grace-pool
```

### Deploy Verification Flows

```python
# deploy_flows.py
from grace_orchestrator import create_verification_flow

# Create flow for each slice
flow = create_verification_flow(
    slice_id="EXAMPLE-SLICE",
    config_path="grace/project.yaml"
)

# Deploy to Prefect
flow.deploy(
    name="example-slice-verification",
    work_pool="default",
    tags=["grace", "verification"]
)
```

Run deployment:

```bash
python deploy_flows.py
```

## Docker Setup

### Step 1: Add grace-worker to docker-compose.yml

```yaml
services:
  grace-worker:
    image: grace-orchestrator-worker:v0.1.0
    restart: unless-stopped
    environment:
      PREFECT_API_URL: ${PREFECT_API_URL:-http://prefect-server:4200/api}
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

### Step 2: Create Prefect network

```bash
docker network create prefect_default
```

### Step 3: Start grace-worker

```bash
docker-compose up -d grace-worker
```

### Step 4: Verify worker is running

```bash
docker-compose logs grace-worker
docker-compose ps grace-worker
```

## First Verification

### Step 1: List available slices

```bash
gracectl slice list
```

### Step 2: Run a verification

```bash
gracectl slice verify EXAMPLE-SLICE
```

### Step 3: View results

```bash
# Check evidence
gracectl evidence show EXAMPLE-SLICE

# View logs
tail -f logs/gracectl/EXAMPLE-SLICE.log

# Check report
cat test-results/grace-report.json
```

### Step 4: Watch live flows (optional)

```bash
gracectl watch start FLOW-EXAMPLE
```

## Troubleshooting

### Issue: gracectl command not found

**Cause**: Package not installed or not in PATH

**Solution**:
```bash
pip install grace-orchestrator
which gracectl
```

### Issue: Cannot connect to Prefect server

**Cause**: Prefect server not running or wrong URL

**Solution**:
```bash
# Check Prefect server status
curl http://localhost:4200/api/health

# Verify PREFECT_API_URL
echo $PREFECT_API_URL

# Start Prefect server if needed
prefect server start
```

### Issue: Worker not picking up flows

**Cause**: Work pool mismatch or worker not running

**Solution**:
```bash
# List work pools
prefect work-pool ls

# Check worker status
prefect worker ls

# Verify work pool in config matches deployment
grep GRACE_WORK_POOL .env
```

### Issue: Slice verification fails

**Cause**: Commands in project.yaml may be incorrect

**Solution**:
```bash
# Test commands manually
cd /path/to/project
pytest tests/  # Or whatever command is in project.yaml

# Check logs for details
tail -f logs/gracectl/SLICE-ID.log
```

### Issue: Docker worker can't access files

**Cause**: Volume mount or permissions issue

**Solution**:
```bash
# Check volume mounts
docker-compose config | grep -A 5 volumes

# Check permissions
docker-compose exec grace-worker ls -la /workspace

# Verify working directory
docker-compose exec grace-worker pwd
```

### Issue: Import errors in Python

**Cause**: Package not installed or wrong import path

**Solution**:
```bash
# Verify installation
pip show grace-orchestrator

# Check import
python -c "import grace_orchestrator; print(grace_orchestrator.__version__)"

# Update imports from old paths
# OLD: from prefect_grace.flows import ...
# NEW: from grace_orchestrator.flows import ...
```

## Next Steps

1. **Define your slices**: Add verification slices for your project in `grace/project.yaml`
2. **Customize agents**: Adjust agent profiles in `grace/agent_profiles.yaml`
3. **Set up CI/CD**: Integrate gracectl into your CI pipeline
4. **Monitor flows**: Use `gracectl watch` for observability
5. **Collect evidence**: Use `gracectl evidence` to track quality metrics

## Additional Resources

- [README.md](README.md) - Overview and features
- [MIGRATION.md](MIGRATION.md) - Migrating from embedded GRACE
- [CONTRIBUTING.md](CONTRIBUTING.md) - Contributing guidelines
- [Documentation](https://grace-orchestrator.readthedocs.io) - Full documentation
- [Examples](examples/) - Example projects and configurations

## Getting Help

- GitHub Issues: https://github.com/yourusername/grace-orchestrator/issues
- Discussions: https://github.com/yourusername/grace-orchestrator/discussions
- Documentation: https://grace-orchestrator.readthedocs.io
