# Migration Guide: Adopting grace-orchestrator

This guide helps you migrate an existing project to use the extracted `grace-orchestrator` package.

## Overview

The `grace-orchestrator` package extracts GRACE verification orchestration into a standalone, reusable library. This migration moves GRACE-specific code out of your project repository while maintaining all functionality.

**For astro-project**: This migration consolidates the current `src/prefect_grace/` directory, `gracectl/` CLI, and related infrastructure into the external `grace-orchestrator` package.

## Prerequisites

- Python 3.12 or higher
- Prefect 3.6+ (if using workflow orchestration)
- Existing project with GRACE verification setup
- Docker and docker-compose (for worker deployment)
- Backup of your current working state

## Migration Steps

### Step 1: Install grace-orchestrator

```bash
pip install grace-orchestrator[prefect]
```

Or add to your `requirements.txt`:

```
grace-orchestrator[prefect]>=0.1.0
```

### Step 2: Restructure Project Files

#### Before (embedded GRACE) - astro-project current state:

```
astro-project/
├── src/prefect_grace/      # DELETE after migration
│   ├── flows/
│   ├── tasks/
│   ├── platform/
│   ├── policies/
│   ├── prompts/
│   ├── packets/
│   ├── cli.py
│   ├── project.yaml
│   ├── agent_profiles.yaml
│   └── ...
├── gracectl/               # DELETE after migration
│   ├── cli.py
│   ├── commands/
│   ├── config.py
│   └── ...
├── gracectl.yaml           # KEEP (used by gracectl CLI)
├── docker-compose.grace-worker.yml  # REPLACE with fragment
├── infra/grace-worker/     # DELETE after migration
│   ├── Dockerfile
│   ├── entrypoint.sh
│   └── requirements.txt
└── grace/                  # ALREADY EXISTS - enhance
    ├── requirements.xml
    ├── technology.xml
    ├── development-plan.xml
    ├── knowledge-graph.xml
    └── verification-matrix.md
```

#### After (using grace-orchestrator):

```
astro-project/
├── grace/                  # Enhanced GRACE configuration directory
│   ├── project.yaml        # NEW - migrated from src/prefect_grace/project.yaml
│   ├── agent_profiles.yaml # NEW - migrated from src/prefect_grace/agent_profiles.yaml
│   ├── requirements.xml    # EXISTING
│   ├── technology.xml      # EXISTING
│   ├── development-plan.xml # EXISTING
│   ├── knowledge-graph.xml # EXISTING
│   └── verification-matrix.md # EXISTING
├── gracectl.yaml           # KEEP - used by gracectl CLI for slice definitions
├── docker-compose.yml      # UPDATE - add grace-worker service
├── scripts/                # NEW migration helper scripts
│   ├── validate_migration.sh
│   ├── migrate_to_grace_package.sh
│   └── rollback_migration.sh
└── ...
```

### Step 3: Migrate Configuration

#### 3.1 Create grace/ directory (if not exists)

```bash
# For astro-project, grace/ already exists, so just verify:
ls -la grace/
```

#### 3.2 Migrate project.yaml to grace/

**For astro-project**: Copy the project configuration from `src/prefect_grace/project.yaml`:

```bash
# Backup existing files
cp src/prefect_grace/project.yaml src/prefect_grace/project.yaml.backup
cp grace/project.yaml grace/project.yaml.backup 2>/dev/null || true

# Copy project.yaml to grace/
cp src/prefect_grace/project.yaml grace/project.yaml
```

**Important path updates for astro-project**:

The `project.yaml` in astro-project already uses correct relative paths:

```yaml
# Current (correct):
project:
  root: /opt/astro-project
  grace_dir: grace
  packets_dir: prefect_grace/packets  # Will need to move packets

runtime:
  state_root: /var/lib/grace-orchestrator/astro-project
```

After migration, update `packets_dir`:

```yaml
project:
  root: /opt/astro-project
  grace_dir: grace
  packets_dir: grace/packets  # NEW location
```

#### 3.3 Migrate agent_profiles.yaml

**For astro-project**: Copy agent profiles from `src/prefect_grace/agent_profiles.yaml`:

```bash
cp src/prefect_grace/agent_profiles.yaml grace/agent_profiles.yaml
```

Current astro-project agent_profiles.yaml structure:

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

This structure is compatible with grace-orchestrator and requires no changes.

#### 3.4 Move packets directory

**For astro-project**: The packets are currently in `src/prefect_grace/packets/`:

```bash
# Create grace/packets directory
mkdir -p grace/packets

# Move packets (or copy for safety during migration)
cp -r src/prefect_grace/packets/* grace/packets/

# Verify packet structure
ls -la grace/packets/ | head -20
```

#### 3.5 Verify GRACE artifacts

**For astro-project**: The grace/ directory already contains required XML artifacts:

```bash
ls -la grace/
# Should show:
# - requirements.xml
# - technology.xml
# - development-plan.xml
# - knowledge-graph.xml
# - verification-matrix.md
```

If any are missing, initialize them:

```bash
grace init
```

### Step 4: Update Docker Configuration

#### 4.1 Replace grace-worker Dockerfile

**For astro-project**: Delete the project-specific Dockerfile and use the package-provided image:

```bash
# Current astro-project structure:
# infra/grace-worker/Dockerfile
# infra/grace-worker/entrypoint.sh
# infra/grace-worker/requirements.txt

# These will be replaced by grace-orchestrator package
```

Pull the pre-built image:

```bash
docker pull grace-orchestrator-worker:v0.1.0
```

Or build from the package:

```bash
docker build -f $(python -c "import grace_orchestrator; print(grace_orchestrator.__path__[0])")/docker/Dockerfile.worker -t grace-worker:latest .
```

#### 4.2 Update docker-compose.grace-worker.yml

**For astro-project**: Replace the current `docker-compose.grace-worker.yml` with the new configuration.

**Current astro-project configuration** (docker-compose.grace-worker.yml):

```yaml
services:
  grace_worker:
    build:
      context: .
      dockerfile: infra/grace-worker/Dockerfile
      args:
        ASTRO_UID: ${ASTRO_GRACE_WORKER_UID:-1001}
        ASTRO_GID: ${ASTRO_GRACE_WORKER_GID:-1003}
    restart: unless-stopped
    profiles:
      - grace-worker
    environment:
      GRACE_REPO_ROOT: /opt/astro-project
      PREFECT_API_URL: ${GRACE_PREFECT_API_URL:-http://prefect-server:4200/api}
      PREFECT_WORK_POOL: ${GRACE_PREFECT_WORK_POOL:-astro-process}
      # ... more env vars
    volumes:
      - ./:/opt/astro-project
      - /var/lib/grace-orchestrator/astro-project:/var/lib/grace-orchestrator/astro-project
    networks:
      - prefect
    command: ["worker"]
```

**New configuration** (using grace-orchestrator):

```yaml
services:
  grace_worker:
    image: grace-orchestrator-worker:v0.1.0
    restart: unless-stopped
    profiles:
      - grace-worker
    group_add:
      - "${GRACE_DOCKER_GID:-105}"
    env_file:
      - .env
    environment:
      # Core GRACE configuration
      GRACE_PROJECT_CONFIG: /workspace/grace/project.yaml
      GRACE_WORK_POOL: ${GRACE_WORK_POOL:-astro-process}
      GRACE_LIVE_QUEUE: ${GRACE_LIVE_QUEUE:-grace-live}
      
      # Prefect configuration
      PREFECT_API_URL: ${PREFECT_API_URL:-http://prefect-server:4200/api}
      
      # Executor configuration (astro-project specific)
      CODEX_HOME: /home/astro/.codex
      GEMINI_HOME: /home/astro/.gemini
      HOME: /home/astro
      PYTHONPATH: /workspace
      
      # Git configuration
      GRACE_GIT_USER_NAME: ${GRACE_GIT_USER_NAME:-GRACE Worker}
      GRACE_GIT_USER_EMAIL: ${GRACE_GIT_USER_EMAIL:-grace-worker@local.invalid}
      
      # LLM proxy configuration (astro-project specific)
      OPENAI_API_BASE: ${LLM_CLI_OPENAI_BASE_URL_CODEX:-http://cliproxy:8080/v1}
      OPENAI_API_KEY: ${LLM_CLI_OPENAI_API_KEY_CODEX:-sk-cliproxy-local}
    
    volumes:
      - .:/workspace
      - grace-state:/var/lib/grace-orchestrator
      - /opt/astro-project/.cache/codex-cliproxy-home:/home/astro/.codex
      - /home/astro/.gemini:/home/astro/.gemini
      - /home/astro/.ssh:/home/astro/.ssh:ro
      - /usr/bin/docker:/usr/bin/docker:ro
      - /usr/local/bin/agy:/usr/local/bin/agy:ro
      - /var/run/docker.sock:/var/run/docker.sock
    
    working_dir: /workspace
    networks:
      - default
      - prefect
    
    command: ["grace-worker", "start"]

volumes:
  grace-state:

networks:
  prefect:
    external: true
    name: prefect_default
```

**Key changes for astro-project**:
- Uses `grace-orchestrator-worker` image instead of custom build
- Simplified environment variables (GRACE_PROJECT_CONFIG replaces GRACE_REPO_ROOT)
- Retains astro-project specific volumes (codex, gemini, ssh, docker)
- Command changed from `["worker"]` to `["grace-worker", "start"]`

### Step 5: Update CLI Usage

#### Before (embedded gracectl) - astro-project:

```bash
# Using Python module
python -m gracectl.cli slice verify M-NATAL-SUMMARY-LAYER

# Or direct Python import
python -c "from gracectl.cli import main; main()"
```

#### After (grace-orchestrator package):

```bash
# Global gracectl command
gracectl slice verify M-NATAL-SUMMARY-LAYER

# Or using grace-orchestrator module
python -m grace_orchestrator.cli slice verify M-NATAL-SUMMARY-LAYER
```

The `gracectl` command is now installed globally with the package and reads from `gracectl.yaml` (unchanged).

**For astro-project**: The `gracectl.yaml` file remains in the project root and defines slices like:
- `M-NATAL-SUMMARY-LAYER`
- `FEED-PERSONALIZED-DAILY`
- `ADMIN-ENTITLEMENTS-FLOW`
- `FORECAST-LADDER-CATALOG-FLIP`

### Step 6: Update Python Imports

**For astro-project**: Update imports in custom scripts and tests.

#### Current imports in astro-project:

```python
# trigger_feature.py
from prefect_grace.flows.feature_pipeline import feature_pipeline

# demo_resources.py
from prefect_grace.resources import (
    get_resource,
    list_resources
)

# scripts/agent_done_notify.py
from prefect_grace.tasks.telegram_notify import notify_agent_work_event

# tests/test_prefect_grace_*.py
from prefect_grace.platform.packet_parser import parse_packet_markdown
from prefect_grace.platform.state_store import PacketRegistryStore
from prefect_grace.platform.nightly_batch_execution_guard import (
    NightlyBatchExecutionGuard
)
```

#### After migration:

```python
# trigger_feature.py
from grace_orchestrator.flows.feature_pipeline import feature_pipeline

# demo_resources.py
from grace_orchestrator.resources import (
    get_resource,
    list_resources
)

# scripts/agent_done_notify.py
from grace_orchestrator.tasks.telegram_notify import notify_agent_work_event

# tests/test_prefect_grace_*.py (rename to test_grace_orchestrator_*.py)
from grace_orchestrator.platform.packet_parser import parse_packet_markdown
from grace_orchestrator.platform.state_store import PacketRegistryStore
from grace_orchestrator.platform.nightly_batch_execution_guard import (
    NightlyBatchExecutionGuard
)
```

**Files to update in astro-project**:
- `/opt/astro-project/trigger_feature.py`
- `/opt/astro-project/demo_resources.py`
- `/opt/astro-project/scripts/agent_done_notify.py`
- `/opt/astro-project/tests/test_prefect_grace_*.py` (multiple files)

**Search and replace pattern**:
```bash
# Find all imports
grep -r "from prefect_grace" --include="*.py" .

# Replace (use with caution)
find . -name "*.py" -type f -exec sed -i 's/from prefect_grace\./from grace_orchestrator./g' {} +
find . -name "*.py" -type f -exec sed -i 's/import prefect_grace/import grace_orchestrator/g' {} +
```

### Step 7: Update Environment Variables

**For astro-project**: Update your `.env` file with new GRACE-specific variables.

#### Current .env structure (relevant GRACE variables):

```bash
# No explicit GRACE variables currently
# Worker configuration is in docker-compose.grace-worker.yml
```

#### Add to .env after migration:

```bash
# GRACE Orchestrator Configuration
GRACE_PROJECT_CONFIG=grace/project.yaml
GRACE_WORK_POOL=astro-process
GRACE_LIVE_QUEUE=grace-live
GRACE_MONITORING_QUEUE=grace-monitoring

# GRACE Worker Configuration
GRACE_PREFECT_API_URL=http://prefect-server:4200/api
GRACE_PREFECT_WORKER_LIMIT=1
GRACE_GIT_USER_NAME=GRACE Worker
GRACE_GIT_USER_EMAIL=grace-worker@local.invalid

# GRACE Docker Configuration (for host volume permissions)
GRACE_DOCKER_GID=105
ASTRO_GRACE_WORKER_UID=1001
ASTRO_GRACE_WORKER_GID=1003

# Executor Configuration (agy/codex)
LLM_CLI_OPENAI_BASE_URL_CODEX=http://cliproxy:8080/v1
LLM_CLI_OPENAI_API_KEY_CODEX=sk-cliproxy-local
```

**Note**: Most of these already exist in astro-project's environment, just consolidate them under GRACE section.

### Step 8: Clean Up Old Files

After verifying everything works, remove the old GRACE implementation:

**For astro-project**:

```bash
# IMPORTANT: Create a backup branch first!
git checkout -b backup-before-grace-migration
git add -A
git commit -m "Backup before grace-orchestrator migration"
git checkout prod-release-20260327

# Remove old GRACE implementation
rm -rf src/prefect_grace/
rm -rf gracectl/
rm -rf infra/grace-worker/
rm docker-compose.grace-worker.yml.backup  # if you created one

# Keep these files:
# - gracectl.yaml (still used for slice definitions)
# - grace/ directory (enhanced with new configs)
# - docker-compose.grace-worker.yml (updated version)

# Update .gitignore
cat >> .gitignore << 'EOF'

# GRACE Orchestrator
grace/packets/*/
!grace/packets/.gitkeep
grace/.cache/
EOF
```

**Files to DELETE**:
- `/opt/astro-project/src/prefect_grace/` (entire directory)
- `/opt/astro-project/gracectl/` (entire directory)
- `/opt/astro-project/infra/grace-worker/` (entire directory)

**Files to KEEP**:
- `/opt/astro-project/gracectl.yaml` (slice definitions)
- `/opt/astro-project/grace/` (GRACE artifacts and new configs)
- `/opt/astro-project/docker-compose.grace-worker.yml` (updated version)

### Step 9: Verify Migration

Run comprehensive verification to ensure everything works:

**For astro-project**:

```bash
# 1. Verify grace-orchestrator is installed
pip show grace-orchestrator
which gracectl

# 2. Verify configuration files
ls -la grace/
cat grace/project.yaml | head -20
cat grace/agent_profiles.yaml

# 3. Test gracectl CLI
gracectl slice list

# 4. Verify Docker setup
docker-compose --profile grace-worker config
docker-compose --profile grace-worker up -d grace_worker
docker-compose logs grace_worker

# 5. Run a test slice verification
gracectl slice verify M-NATAL-SUMMARY-LAYER --dry-run

# 6. Check worker status
docker-compose ps grace_worker
docker exec astro-project-grace_worker-1 grace-worker status

# 7. Verify Python imports work
python -c "from grace_orchestrator.flows.feature_pipeline import feature_pipeline; print('Import successful')"

# 8. Run updated tests
pytest tests/test_grace_orchestrator_*.py -v

# 9. Test feature pipeline
python trigger_feature.py  # Should work with updated imports
```

**Use the validation script** (see scripts/validate_migration.sh below):

```bash
./scripts/validate_migration.sh
```

## Common Issues

### Issue: gracectl command not found

**Solution**: Ensure grace-orchestrator is installed in your active Python environment:

```bash
pip install grace-orchestrator
which gracectl
```

### Issue: Worker can't find project.yaml

**Solution**: Ensure `GRACE_PROJECT_CONFIG` points to the correct path inside the container:

```yaml
environment:
  GRACE_PROJECT_CONFIG: /workspace/grace/project.yaml
```

**For astro-project**: Verify the volume mount maps correctly:

```bash
docker exec astro-project-grace_worker-1 ls -la /workspace/grace/
```

### Issue: Import errors in custom scripts

**Solution**: Update all imports from `prefect_grace.*` and `gracectl.*` to `grace_orchestrator.*`

**For astro-project**: Run the import update script:

```bash
# Find all files with old imports
grep -r "from prefect_grace" --include="*.py" .

# Update imports (backup first!)
./scripts/migrate_to_grace_package.sh --update-imports
```

### Issue: Slice commands fail

**Solution**: Verify that command paths in `grace/project.yaml` are relative to the project root and work from the container's working directory.

**For astro-project**: Test commands manually:

```bash
# Test backend command
docker exec astro-project-backend-1 python3 scripts/pipeline.py

# Test frontend command
./scripts/run_e2e.sh e2e/quality.spec.ts
```

### Issue: Packets not found

**Solution**: Ensure packets were moved to `grace/packets/`:

```bash
ls -la grace/packets/
```

**For astro-project**: Verify packet_registry.yaml was updated:

```bash
cat grace/packet_registry.yaml
```

### Issue: Worker fails to start with permission errors

**Solution**: Check Docker socket and volume permissions:

```bash
# Check Docker socket permissions
ls -la /var/run/docker.sock

# Verify GRACE_DOCKER_GID matches docker group
getent group docker

# Update .env with correct GID
echo "GRACE_DOCKER_GID=$(getent group docker | cut -d: -f3)" >> .env
```

**For astro-project**: Ensure UID/GID match your system:

```bash
# Check current user
id -u  # Should match ASTRO_GRACE_WORKER_UID
id -g  # Should match ASTRO_GRACE_WORKER_GID
```

### Issue: Tests fail after migration

**Solution**: Update test imports and rename test files:

```bash
# Rename test files
for f in tests/test_prefect_grace_*.py; do
  mv "$f" "${f/prefect_grace/grace_orchestrator}"
done

# Update imports in tests
find tests/ -name "test_grace_orchestrator_*.py" -exec sed -i 's/from prefect_grace/from grace_orchestrator/g' {} +
```

### Issue: Feature pipeline fails

**Solution**: Verify trigger_feature.py has updated imports:

```python
# Should be:
from grace_orchestrator.flows.feature_pipeline import feature_pipeline

# Not:
from prefect_grace.flows.feature_pipeline import feature_pipeline
```

**For astro-project**: Test the feature pipeline:

```bash
python trigger_feature.py
```

## Rollback Plan

If you need to rollback the migration:

### Option 1: Use the rollback script

```bash
./scripts/rollback_migration.sh
```

### Option 2: Manual rollback

1. **Restore from backup branch**:

```bash
git checkout backup-before-grace-migration
git checkout -b rollback-grace-migration
```

2. **Restore old directories**:

```bash
# Restore src/prefect_grace/
git checkout backup-before-grace-migration -- src/prefect_grace/

# Restore gracectl/
git checkout backup-before-grace-migration -- gracectl/

# Restore infra/grace-worker/
git checkout backup-before-grace-migration -- infra/grace-worker/

# Restore docker-compose.grace-worker.yml
git checkout backup-before-grace-migration -- docker-compose.grace-worker.yml
```

3. **Uninstall grace-orchestrator**:

```bash
pip uninstall grace-orchestrator
```

4. **Revert docker-compose changes**:

```bash
git checkout backup-before-grace-migration -- docker-compose.yml
```

5. **Restart services**:

```bash
docker-compose --profile grace-worker down
docker-compose --profile grace-worker up -d
```

### What to keep after rollback

- `grace/` directory (contains valuable GRACE artifacts)
- `gracectl.yaml` (slice definitions)
- Any new packets created during migration testing

## Migration Helper Scripts

Three helper scripts are provided to automate and validate the migration:

### 1. validate_migration.sh

Validates that the migration is complete and correct:

```bash
./scripts/validate_migration.sh
```

Checks:
- grace-orchestrator package is installed
- grace/ directory structure is correct
- Configuration files are valid
- Old directories are removed
- Imports are updated
- Docker setup is correct

### 2. migrate_to_grace_package.sh

Automates the migration process:

```bash
# Dry run (shows what would be done)
./scripts/migrate_to_grace_package.sh --dry-run

# Full migration
./scripts/migrate_to_grace_package.sh

# Update imports only
./scripts/migrate_to_grace_package.sh --update-imports
```

Steps performed:
1. Creates backup branch
2. Installs grace-orchestrator
3. Migrates configuration files
4. Moves packets directory
5. Updates imports
6. Updates docker-compose
7. Runs validation

### 3. rollback_migration.sh

Rolls back the migration to pre-migration state:

```bash
./scripts/rollback_migration.sh
```

Steps performed:
1. Restores from backup branch
2. Uninstalls grace-orchestrator
3. Restores old directories
4. Reverts docker-compose changes
5. Restarts services

## Benefits After Migration

- **Cleaner repository**: GRACE orchestration code is external
- **Easier updates**: `pip install --upgrade grace-orchestrator`
- **Reusable across projects**: Same GRACE setup for multiple projects
- **Better separation**: Project code vs. orchestration framework
- **Community improvements**: Benefit from upstream GRACE enhancements
- **Reduced maintenance**: No need to maintain GRACE infrastructure code
- **Standardized workflows**: Consistent GRACE experience across projects

## Astro-Project Specific Notes

### Current State

The astro-project currently has:
- **src/prefect_grace/**: 15+ subdirectories with flows, tasks, platform code
- **gracectl/**: CLI implementation with commands for slice verification
- **infra/grace-worker/**: Custom Docker setup for GRACE worker
- **gracectl.yaml**: Slice definitions (4 main slices with verification matrices)
- **grace/**: GRACE artifacts (requirements.xml, technology.xml, etc.)

### After Migration

- **grace/**: Enhanced with project.yaml, agent_profiles.yaml, packets/
- **gracectl.yaml**: Unchanged (still used for slice definitions)
- **docker-compose.grace-worker.yml**: Updated to use grace-orchestrator image
- **Removed**: src/prefect_grace/, gracectl/, infra/grace-worker/

### Key Files to Update

1. **trigger_feature.py**: Update import from `prefect_grace.flows.feature_pipeline`
2. **demo_resources.py**: Update import from `prefect_grace.resources`
3. **scripts/agent_done_notify.py**: Update import from `prefect_grace.tasks.telegram_notify`
4. **tests/test_prefect_grace_*.py**: Rename and update imports

### Slice Definitions

The following slices are defined in gracectl.yaml and will continue to work:
- **M-NATAL-SUMMARY-LAYER**: Natal summary layer verification
- **FEED-PERSONALIZED-DAILY**: Daily feed API + homepage states
- **ADMIN-ENTITLEMENTS-FLOW**: Admin entitlements flow
- **FORECAST-LADDER-CATALOG-FLIP**: Forecast ladder catalog alignment

### Docker Volumes

Astro-project specific volumes to preserve:
- `/opt/astro-project/.cache/codex-cliproxy-home:/home/astro/.codex`
- `/home/astro/.gemini:/home/astro/.gemini`
- `/home/astro/.ssh:/home/astro/.ssh:ro`
- `/usr/bin/docker:/usr/bin/docker:ro`
- `/usr/local/bin/agy:/usr/local/bin/agy:ro`
- `/var/run/docker.sock:/var/run/docker.sock`

### Environment Variables

Astro-project uses these executor-specific variables:
- `LLM_CLI_OPENAI_BASE_URL_CODEX`: Cliproxy URL for LLM access
- `LLM_CLI_OPENAI_API_KEY_CODEX`: Cliproxy API key
- `CODEX_HOME`: Codex CLI home directory
- `GEMINI_HOME`: Gemini CLI home directory

These should be preserved in the new docker-compose.grace-worker.yml.

## Next Steps

1. Review the [grace-orchestrator documentation](https://grace-orchestrator.readthedocs.io)
2. Explore advanced features like custom agents and flow hooks
3. Contribute improvements back to the grace-orchestrator project
4. Consider extracting common patterns from astro-project to grace-orchestrator

## Support

- GitHub Issues: https://github.com/yourusername/grace-orchestrator/issues
- Documentation: https://grace-orchestrator.readthedocs.io
- Discussions: https://github.com/yourusername/grace-orchestrator/discussions

## Appendix: Quick Reference

### Command Mapping

| Before (embedded) | After (package) |
|-------------------|-----------------|
| `python -m gracectl.cli slice list` | `gracectl slice list` |
| `python -m gracectl.cli slice verify SLICE-ID` | `gracectl slice verify SLICE-ID` |
| `python -m prefect_grace.cli deploy` | `grace-orchestrator deploy` |
| `from prefect_grace.flows import X` | `from grace_orchestrator.flows import X` |

### File Mapping

| Before | After |
|--------|-------|
| `src/prefect_grace/project.yaml` | `grace/project.yaml` |
| `src/prefect_grace/agent_profiles.yaml` | `grace/agent_profiles.yaml` |
| `src/prefect_grace/packets/` | `grace/packets/` |
| `gracectl.yaml` | `gracectl.yaml` (unchanged) |
| `infra/grace-worker/Dockerfile` | (use grace-orchestrator image) |

### Environment Variable Mapping

| Before | After |
|--------|-------|
| `GRACE_REPO_ROOT` | `GRACE_PROJECT_CONFIG` |
| `PREFECT_WORK_POOL` | `GRACE_WORK_POOL` |
| `PREFECT_LIVE_QUEUE` | `GRACE_LIVE_QUEUE` |

### Troubleshooting Commands

```bash
# Verify installation
pip show grace-orchestrator
which gracectl

# Test configuration
gracectl slice list
gracectl --version

# Check worker
docker-compose --profile grace-worker ps
docker-compose logs grace_worker

# Validate migration
./scripts/validate_migration.sh

# Rollback if needed
./scripts/rollback_migration.sh
```

---

**Migration Guide Version**: 1.0  
**Last Updated**: 2026-05-30  
**Target Package Version**: grace-orchestrator >= 0.1.0
