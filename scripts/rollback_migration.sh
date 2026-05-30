#!/bin/bash
# rollback_migration.sh
# Rolls back grace-orchestrator migration for astro-project

set -e

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

# Configuration
DRY_RUN=false
FORCE=false
VERBOSE=false

# Parse arguments
while [[ $# -gt 0 ]]; do
    case $1 in
        --dry-run)
            DRY_RUN=true
            shift
            ;;
        --force)
            FORCE=true
            shift
            ;;
        --verbose|-v)
            VERBOSE=true
            shift
            ;;
        --help|-h)
            echo "Usage: $0 [OPTIONS]"
            echo ""
            echo "Rolls back grace-orchestrator migration to pre-migration state."
            echo ""
            echo "Options:"
            echo "  --dry-run          Show what would be done without making changes"
            echo "  --force            Skip confirmation prompts"
            echo "  --verbose, -v      Show detailed output"
            echo "  --help, -h         Show this help message"
            exit 0
            ;;
        *)
            echo "Unknown option: $1"
            echo "Use --help for usage information"
            exit 1
            ;;
    esac
done

# Helper functions
log_info() {
    echo -e "${BLUE}[INFO]${NC} $1"
}

log_success() {
    echo -e "${GREEN}[SUCCESS]${NC} $1"
}

log_warn() {
    echo -e "${YELLOW}[WARN]${NC} $1"
}

log_error() {
    echo -e "${RED}[ERROR]${NC} $1"
}

log_step() {
    echo ""
    echo -e "${GREEN}==>${NC} $1"
}

run_cmd() {
    if [ "$VERBOSE" = true ]; then
        echo -e "${BLUE}  \$ $1${NC}"
    fi

    if [ "$DRY_RUN" = true ]; then
        echo -e "${YELLOW}  [DRY RUN] Would execute: $1${NC}"
        return 0
    fi

    eval "$1"
}

# Change to project root
cd "$(dirname "$0")/.."
PROJECT_ROOT=$(pwd)

log_warn "=========================================="
log_warn "GRACE Orchestrator Migration Rollback"
log_warn "=========================================="
echo ""
log_info "Project root: $PROJECT_ROOT"

if [ "$DRY_RUN" = true ]; then
    log_warn "DRY RUN MODE - No changes will be made"
fi

# Confirmation prompt
if [ "$FORCE" = false ] && [ "$DRY_RUN" = false ]; then
    echo ""
    log_warn "This will rollback the grace-orchestrator migration and restore:"
    echo "  - src/prefect_grace/ directory"
    echo "  - gracectl/ directory"
    echo "  - infra/grace-worker/ directory"
    echo "  - docker-compose.grace-worker.yml"
    echo ""
    log_warn "Current grace/ directory will be preserved."
    echo ""
    read -p "Are you sure you want to continue? (yes/no): " -r
    echo ""
    if [[ ! $REPLY =~ ^[Yy][Ee][Ss]$ ]]; then
        log_info "Rollback cancelled"
        exit 0
    fi
fi

# Step 1: Find backup branch
log_step "Step 1: Find backup branch"

BACKUP_BRANCH=$(git branch --list "backup-before-grace-migration*" | head -1 | xargs)

if [ -z "$BACKUP_BRANCH" ]; then
    log_error "No backup branch found matching 'backup-before-grace-migration*'"
    log_info "Available branches:"
    git branch --list | head -10
    echo ""
    log_error "Cannot proceed with rollback without backup branch"
    exit 1
fi

log_info "Found backup branch: $BACKUP_BRANCH"

# Step 2: Create rollback branch
log_step "Step 2: Create rollback branch"

CURRENT_BRANCH=$(git branch --show-current)
ROLLBACK_BRANCH="rollback-grace-migration-$(date +%Y%m%d-%H%M%S)"

log_info "Current branch: $CURRENT_BRANCH"
log_info "Creating rollback branch: $ROLLBACK_BRANCH"

run_cmd "git checkout -b $ROLLBACK_BRANCH"

log_success "Rollback branch created"

# Step 3: Restore old directories
log_step "Step 3: Restore old directories from backup"

log_info "Restoring src/prefect_grace/ from $BACKUP_BRANCH"
run_cmd "git checkout $BACKUP_BRANCH -- src/prefect_grace/ || true"

log_info "Restoring gracectl/ from $BACKUP_BRANCH"
run_cmd "git checkout $BACKUP_BRANCH -- gracectl/ || true"

log_info "Restoring infra/grace-worker/ from $BACKUP_BRANCH"
run_cmd "git checkout $BACKUP_BRANCH -- infra/grace-worker/ || true"

log_info "Restoring docker-compose.grace-worker.yml from $BACKUP_BRANCH"
run_cmd "git checkout $BACKUP_BRANCH -- docker-compose.grace-worker.yml || true"

log_success "Old directories restored"

# Step 4: Revert Python imports
log_step "Step 4: Revert Python imports"

log_info "Searching for files with new imports..."

NEW_IMPORT_FILES=$(grep -r "from grace_orchestrator" --include="*.py" "$PROJECT_ROOT" 2>/dev/null | \
    grep -v ".pyc" | \
    grep -v "__pycache__" | \
    grep -v "backup" | \
    grep -v ".worktrees" | \
    grep -v ".git" | \
    cut -d: -f1 | \
    sort -u || echo "")

if [ -z "$NEW_IMPORT_FILES" ]; then
    log_info "No files with new imports found"
else
    FILE_COUNT=$(echo "$NEW_IMPORT_FILES" | wc -l)
    log_info "Found $FILE_COUNT files with new imports"

    if [ "$VERBOSE" = true ]; then
        echo "$NEW_IMPORT_FILES" | while read -r file; do
            echo "  - $file"
        done
    fi

    log_info "Reverting imports from 'grace_orchestrator' to 'prefect_grace'..."

    echo "$NEW_IMPORT_FILES" | while read -r file; do
        if [ -f "$file" ]; then
            if [ "$VERBOSE" = true ]; then
                log_info "Updating: $file"
            fi
            run_cmd "sed -i 's/from grace_orchestrator\\./from prefect_grace./g' '$file'"
            run_cmd "sed -i 's/import grace_orchestrator/import prefect_grace/g' '$file'"
        fi
    done

    log_success "Python imports reverted"
fi

# Step 5: Uninstall grace-orchestrator
log_step "Step 5: Uninstall grace-orchestrator package"

if [ "$DRY_RUN" = false ]; then
    if pip show grace-orchestrator &>/dev/null; then
        log_info "Uninstalling grace-orchestrator..."
        run_cmd "pip uninstall -y grace-orchestrator"
        log_success "grace-orchestrator uninstalled"
    else
        log_info "grace-orchestrator not installed, skipping"
    fi
else
    log_info "Would uninstall grace-orchestrator package"
fi

# Step 6: Restore docker-compose.yml if modified
log_step "Step 6: Check docker-compose.yml"

if git diff $BACKUP_BRANCH -- docker-compose.yml &>/dev/null; then
    log_info "docker-compose.yml has changes, restoring from backup"
    run_cmd "git checkout $BACKUP_BRANCH -- docker-compose.yml || true"
    log_success "docker-compose.yml restored"
else
    log_info "docker-compose.yml unchanged, skipping"
fi

# Step 7: Commit rollback changes
log_step "Step 7: Commit rollback changes"

if [ "$DRY_RUN" = false ]; then
    run_cmd "git add -A"
    run_cmd "git commit -m 'Rollback grace-orchestrator migration' || true"
    log_success "Rollback changes committed"
else
    log_info "Would commit rollback changes"
fi

# Step 8: Restart services
log_step "Step 8: Restart Docker services"

log_info "Stopping grace-worker service..."
run_cmd "docker-compose --profile grace-worker down || true"

log_info "Starting grace-worker service..."
run_cmd "docker-compose --profile grace-worker up -d || true"

log_success "Docker services restarted"

# Summary
echo ""
echo "=========================================="
echo "Rollback Summary"
echo "=========================================="
echo ""

if [ "$DRY_RUN" = true ]; then
    log_warn "DRY RUN completed - no changes were made"
    echo ""
    echo "To perform the actual rollback, run:"
    echo "  $0"
else
    log_success "Rollback completed successfully!"
    echo ""
    echo "Restored from backup branch: $BACKUP_BRANCH"
    echo "Current branch: $ROLLBACK_BRANCH"
    echo ""
    echo "Restored directories:"
    echo "  ✓ src/prefect_grace/"
    echo "  ✓ gracectl/"
    echo "  ✓ infra/grace-worker/"
    echo "  ✓ docker-compose.grace-worker.yml"
    echo ""
    echo "Next steps:"
    echo "  1. Verify the rollback: git status"
    echo "  2. Test old gracectl: python -m gracectl.cli slice list"
    echo "  3. Check worker: docker-compose logs grace_worker"
    echo "  4. Merge rollback branch if satisfied:"
    echo "     git checkout $CURRENT_BRANCH"
    echo "     git merge $ROLLBACK_BRANCH"
    echo ""
    echo "Note: grace/ directory was preserved and may contain migrated configs."
    echo "      Review grace/ directory if needed."
fi

echo ""
