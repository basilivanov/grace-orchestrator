# GRACE Orchestrator Migration Scripts

This directory contains helper scripts for migrating astro-project to use the `grace-orchestrator` package.

## Scripts Overview

### 1. validate_migration.sh

Validates that the grace-orchestrator migration is complete and correct.

**Usage:**
```bash
./scripts/validate_migration.sh
```

**What it checks:**
- ✓ grace-orchestrator package is installed
- ✓ supervisor bootstrap module is available
- ✓ grace/ directory structure is correct
- ✓ Required configuration files exist and are valid
- ✓ Old directories (src/prefect_grace/, gracectl/, infra/grace-worker/) are removed
- ✓ Docker configuration is updated
- ✓ Python imports are updated
- ✓ Environment variables are configured
- ✓ Runtime validation (imports work, HTTP/OpenAPI control surface is available)

**Exit codes:**
- `0`: Validation passed (with or without warnings)
- `1`: Validation failed (critical issues found)

**Example output:**
```
==========================================
GRACE Orchestrator Migration Validation
==========================================
Project: astro-project
Root: /opt/astro-project

==========================================
1. Package Installation
==========================================
Checking grace-orchestrator package... ✓ PASS
  Version: 0.1.0
Checking supervisor bootstrap module... ✓ PASS
  Entry point: python3 -m grace_control.supervisor

...

==========================================
Validation Summary
==========================================

Passed:   25
Warnings: 2
Failed:   0

✓ Migration validation PASSED with warnings.
```

---

### 2. migrate_to_grace_package.sh

Automates the migration process from embedded GRACE to grace-orchestrator package.

**Usage:**
```bash
# Dry run (shows what would be done)
./scripts/migrate_to_grace_package.sh --dry-run

# Full migration
./scripts/migrate_to_grace_package.sh

# Update imports only
./scripts/migrate_to_grace_package.sh --update-imports

# Skip backup branch creation
./scripts/migrate_to_grace_package.sh --skip-backup

# Verbose output
./scripts/migrate_to_grace_package.sh --verbose
```

**Options:**
- `--dry-run`: Show what would be done without making changes
- `--update-imports`: Only update Python imports (skip other steps)
- `--skip-backup`: Skip creating backup branch
- `--verbose, -v`: Show detailed output
- `--help, -h`: Show help message

**What it does:**
1. Creates backup branch (backup-before-grace-migration-TIMESTAMP)
2. Installs grace-orchestrator package
3. Migrates configuration files (project.yaml, agent_profiles.yaml)
4. Moves packets directory to grace/packets/
5. Updates Python imports (prefect_grace → grace_orchestrator)
6. Updates docker-compose.grace-worker.yml (manual step required)
7. Runs validation

**Example:**
```bash
$ ./scripts/migrate_to_grace_package.sh --dry-run

[INFO] Starting grace-orchestrator migration for astro-project
[INFO] Project root: /opt/astro-project
[WARN] DRY RUN MODE - No changes will be made

==> Step 0: Pre-flight checks
[SUCCESS] Pre-flight checks passed

==> Step 1: Create backup branch
[INFO] Current branch: prod-release-20260327
[INFO] Creating backup branch: backup-before-grace-migration-20260530-120000
[DRY RUN] Would execute: git checkout -b backup-before-grace-migration-20260530-120000

...
```

---

### 3. rollback_migration.sh

Rolls back the grace-orchestrator migration to pre-migration state.

**Usage:**
```bash
# Interactive rollback (with confirmation)
./scripts/rollback_migration.sh

# Dry run
./scripts/rollback_migration.sh --dry-run

# Force rollback (skip confirmation)
./scripts/rollback_migration.sh --force

# Verbose output
./scripts/rollback_migration.sh --verbose
```

**Options:**
- `--dry-run`: Show what would be done without making changes
- `--force`: Skip confirmation prompts
- `--verbose, -v`: Show detailed output
- `--help, -h`: Show help message

**What it does:**
1. Finds backup branch (backup-before-grace-migration*)
2. Creates rollback branch (rollback-grace-migration-TIMESTAMP)
3. Restores old directories from backup:
   - src/prefect_grace/
   - infra/grace-worker/
   - docker-compose.grace-worker.yml
4. Reverts Python imports (grace_orchestrator → prefect_grace)
5. Uninstalls grace-orchestrator package
6. Restores docker-compose.yml if modified
7. Commits rollback changes
8. Restarts Docker services

**Example:**
```bash
$ ./scripts/rollback_migration.sh

==========================================
GRACE Orchestrator Migration Rollback
==========================================

[INFO] Project root: /opt/astro-project

[WARN] This will rollback the grace-orchestrator migration and restore:
  - src/prefect_grace/ directory
  - infra/grace-worker/ directory
  - docker-compose.grace-worker.yml

[WARN] Current grace/ directory will be preserved.

Are you sure you want to continue? (yes/no): yes

==> Step 1: Find backup branch
[INFO] Found backup branch: backup-before-grace-migration-20260530-120000

...
```

---

## Migration Workflow

### Recommended workflow:

1. **Read the migration guide:**
   ```bash
   cat MIGRATION.md
   ```

2. **Run dry-run migration:**
   ```bash
   ./scripts/migrate_to_grace_package.sh --dry-run
   ```

3. **Perform actual migration:**
   ```bash
   ./scripts/migrate_to_grace_package.sh
   ```

4. **Validate migration:**
   ```bash
   ./scripts/validate_migration.sh
   ```

5. **Test the system through the supported control surface:**
   ```bash
   scripts/live_supervisor.sh --target-dir /tmp/grace-live-wt
   curl http://127.0.0.1:8042/api/admin/lifecycle/status
   ```

6. **If issues occur, rollback:**
   ```bash
   ./scripts/rollback_migration.sh
   ```

---

## Common Scenarios

### Scenario 1: First-time migration

```bash
# 1. Dry run to see what will happen
./scripts/migrate_to_grace_package.sh --dry-run

# 2. Perform migration
./scripts/migrate_to_grace_package.sh

# 3. Manually update docker-compose.grace-worker.yml (see MIGRATION.md)

# 4. Validate
./scripts/validate_migration.sh

# 5. Start and inspect through HTTP/OpenAPI
scripts/live_supervisor.sh --target-dir /tmp/grace-live-wt
curl http://127.0.0.1:8042/api/admin/lifecycle/status
```

### Scenario 2: Only update imports

If you've already migrated configuration but need to update imports:

```bash
./scripts/migrate_to_grace_package.sh --update-imports
```

### Scenario 3: Rollback after issues

```bash
# Rollback to pre-migration state
./scripts/rollback_migration.sh

# Fix issues, then try migration again
./scripts/migrate_to_grace_package.sh
```

### Scenario 4: Validate existing migration

If migration was done manually, validate it:

```bash
./scripts/validate_migration.sh
```

---

## Troubleshooting

### Script fails with "permission denied"

Make scripts executable:
```bash
chmod +x scripts/*.sh
```

### "No backup branch found" error

The rollback script requires a backup branch. Create one manually:
```bash
git checkout -b backup-before-grace-migration
git add -A
git commit -m "Backup before migration"
git checkout -
```

### Import updates fail

Manually update imports:
```bash
find . -name "*.py" -type f -exec sed -i 's/from prefect_grace\./from grace_orchestrator./g' {} +
find . -name "*.py" -type f -exec sed -i 's/import prefect_grace/import grace_orchestrator/g' {} +
```

### Validation shows warnings

Warnings are informational and don't block migration. Review them and address if needed:
- Yellow warnings: Non-critical issues
- Red failures: Must be fixed before proceeding

---

## Script Dependencies

All scripts require:
- Bash 4.0+
- Git
- Python 3.12+
- Standard Unix tools (grep, sed, find, etc.)

Migration script additionally requires:
- pip (for installing grace-orchestrator)

---

## Safety Features

### Backup Protection
- Migration script creates timestamped backup branch
- Rollback script requires backup branch to exist
- No destructive operations without backup

### Dry Run Mode
- All scripts support `--dry-run` flag
- Shows what would be done without making changes
- Safe to run multiple times

### Confirmation Prompts
- Rollback script requires confirmation (unless `--force`)
- Clear warnings before destructive operations

### Idempotency
- Scripts can be run multiple times safely
- Check current state before making changes
- Skip steps that are already complete

---

## Exit Codes

All scripts use standard exit codes:
- `0`: Success
- `1`: Failure or validation errors

Use in CI/CD:
```bash
if ./scripts/validate_migration.sh; then
    echo "Migration validated successfully"
else
    echo "Migration validation failed"
    exit 1
fi
```

---

## Support

For issues with migration scripts:
1. Check MIGRATION.md for detailed documentation
2. Run with `--verbose` flag for detailed output
3. Check script output for specific error messages
4. Review git status to see what changed

For issues with grace-orchestrator package:
- GitHub Issues: https://github.com/yourusername/grace-orchestrator/issues
- Documentation: https://grace-orchestrator.readthedocs.io
