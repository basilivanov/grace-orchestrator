#!/bin/bash
# migrate_to_grace_package.sh
# Automates migration to grace-orchestrator package for astro-project

set -e

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

# Configuration
DRY_RUN=false
UPDATE_IMPORTS_ONLY=false
SKIP_BACKUP=false
VERBOSE=false

# Parse arguments
while [[ $# -gt 0 ]]; do
    case $1 in
        --dry-run)
            DRY_RUN=true
            shift
            ;;
        --update-imports)
            UPDATE_IMPORTS_ONLY=true
            shift
            ;;
        --skip-backup)
            SKIP_BACKUP=true
            shift
            ;;
        --verbose|-v)
            VERBOSE=true
            shift
            ;;
        --help|-h)
            echo "Usage: $0 [OPTIONS]"
            echo ""
            echo "Options:"
            echo "  --dry-run          Show what would be done without making changes"
            echo "  --update-imports   Only update Python imports (skip other steps)"
            echo "  --skip-backup      Skip creating backup branch"
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

log_info "Starting grace-orchestrator migration for astro-project"
log_info "Project root: $PROJECT_ROOT"

if [ "$DRY_RUN" = true ]; then
    log_warn "DRY RUN MODE - No changes will be made"
fi

# Step 0: Pre-flight checks
log_step "Step 0: Pre-flight checks"

if [ ! -d "$PROJECT_ROOT/.git" ]; then
    log_error "Not a git repository. Migration requires git for backup."
    exit 1
fi

if [ ! -f "$PROJECT_ROOT/gracectl.yaml" ]; then
    log_error "gracectl.yaml not found. Is this an astro-project?"
    exit 1
fi

log_success "Pre-flight checks passed"

# Step 1: Create backup branch
if [ "$SKIP_BACKUP" = false ] && [ "$UPDATE_IMPORTS_ONLY" = false ]; then
    log_step "Step 1: Create backup branch"

    BACKUP_BRANCH="backup-before-grace-migration-$(date +%Y%m%d-%H%M%S)"
    CURRENT_BRANCH=$(git branch --show-current)

    log_info "Current branch: $CURRENT_BRANCH"
    log_info "Creating backup branch: $BACKUP_BRANCH"

    run_cmd "git checkout -b $BACKUP_BRANCH"
    run_cmd "git add -A"
    run_cmd "git commit -m 'Backup before grace-orchestrator migration' || true"
    run_cmd "git checkout $CURRENT_BRANCH"

    log_success "Backup branch created: $BACKUP_BRANCH"
else
    log_info "Skipping backup branch creation"
fi

# Step 2: Install grace-orchestrator
if [ "$UPDATE_IMPORTS_ONLY" = false ]; then
    log_step "Step 2: Install grace-orchestrator package"

    if pip show grace-orchestrator &>/dev/null; then
        log_warn "grace-orchestrator already installed"
        VERSION=$(pip show grace-orchestrator | grep Version | cut -d' ' -f2)
        log_info "Current version: $VERSION"
    else
        log_info "Installing grace-orchestrator[prefect]..."
        run_cmd "pip install grace-orchestrator[prefect]"
        log_success "grace-orchestrator installed"
    fi

    # Verify installation
    if [ "$DRY_RUN" = false ]; then
        if command -v gracectl &>/dev/null; then
            log_success "gracectl command available at: $(which gracectl)"
        else
            log_error "gracectl command not found after installation"
            exit 1
        fi
    fi
fi

# Step 3: Migrate configuration files
if [ "$UPDATE_IMPORTS_ONLY" = false ]; then
    log_step "Step 3: Migrate configuration files"

    # Ensure grace/ directory exists
    if [ ! -d "$PROJECT_ROOT/grace" ]; then
        log_info "Creating grace/ directory"
        run_cmd "mkdir -p $PROJECT_ROOT/grace"
    fi

    # Migrate project.yaml
    if [ -f "$PROJECT_ROOT/src/prefect_grace/project.yaml" ]; then
        log_info "Migrating project.yaml"
        run_cmd "cp $PROJECT_ROOT/src/prefect_grace/project.yaml $PROJECT_ROOT/grace/project.yaml"
        log_success "project.yaml migrated to grace/"
    else
        log_warn "src/prefect_grace/project.yaml not found"
    fi

    # Migrate agent_profiles.yaml
    if [ -f "$PROJECT_ROOT/src/prefect_grace/agent_profiles.yaml" ]; then
        log_info "Migrating agent_profiles.yaml"
        run_cmd "cp $PROJECT_ROOT/src/prefect_grace/agent_profiles.yaml $PROJECT_ROOT/grace/agent_profiles.yaml"
        log_success "agent_profiles.yaml migrated to grace/"
    else
        log_warn "src/prefect_grace/agent_profiles.yaml not found"
    fi

    # Migrate packet_registry.yaml if exists
    if [ -f "$PROJECT_ROOT/src/prefect_grace/packet_registry.yaml" ]; then
        log_info "Migrating packet_registry.yaml"
        run_cmd "cp $PROJECT_ROOT/src/prefect_grace/packet_registry.yaml $PROJECT_ROOT/grace/packet_registry.yaml"
        log_success "packet_registry.yaml migrated to grace/"
    fi
fi

# Step 4: Move packets directory
if [ "$UPDATE_IMPORTS_ONLY" = false ]; then
    log_step "Step 4: Move packets directory"

    if [ -d "$PROJECT_ROOT/src/prefect_grace/packets" ]; then
        PACKET_COUNT=$(find "$PROJECT_ROOT/src/prefect_grace/packets" -mindepth 1 -maxdepth 1 -type d 2>/dev/null | wc -l)
        log_info "Found $PACKET_COUNT packets in src/prefect_grace/packets/"

        if [ ! -d "$PROJECT_ROOT/grace/packets" ]; then
            log_info "Creating grace/packets/ directory"
            run_cmd "mkdir -p $PROJECT_ROOT/grace/packets"
        fi

        log_info "Copying packets to grace/packets/"
        run_cmd "cp -r $PROJECT_ROOT/src/prefect_grace/packets/* $PROJECT_ROOT/grace/packets/ 2>/dev/null || true"

        log_success "Packets moved to grace/packets/"
    else
        log_warn "src/prefect_grace/packets/ not found"
    fi
fi

# Step 5: Update Python imports
log_step "Step 5: Update Python imports"

log_info "Searching for files with old imports..."

# Find files with old imports (excluding backups, cache, worktrees)
OLD_IMPORT_FILES=$(grep -r "from prefect_grace" --include="*.py" "$PROJECT_ROOT" 2>/dev/null | \
    grep -v ".pyc" | \
    grep -v "__pycache__" | \
    grep -v "backup" | \
    grep -v ".worktrees" | \
    grep -v ".git" | \
    cut -d: -f1 | \
    sort -u || echo "")

if [ -z "$OLD_IMPORT_FILES" ]; then
    log_success "No files with old imports found"
else
    FILE_COUNT=$(echo "$OLD_IMPORT_FILES" | wc -l)
    log_info "Found $FILE_COUNT files with old imports"

    if [ "$VERBOSE" = true ]; then
        echo "$OLD_IMPORT_FILES" | while read -r file; do
            echo "  - $file"
        done
    fi

    log_info "Updating imports from 'prefect_grace' to 'grace_orchestrator'..."

    echo "$OLD_IMPORT_FILES" | while read -r file; do
        if [ -f "$file" ]; then
            if [ "$VERBOSE" = true ]; then
                log_info "Updating: $file"
            fi
            run_cmd "sed -i 's/from prefect_grace\\./from grace_orchestrator./g' '$file'"
            run_cmd "sed -i 's/import prefect_grace/import grace_orchestrator/g' '$file'"
        fi
    done

    log_success "Python imports updated"
fi

# Step 6: Update docker-compose.grace-worker.yml
if [ "$UPDATE_IMPORTS_ONLY" = false ]; then
    log_step "Step 6: Update docker-compose.grace-worker.yml"

    if [ -f "$PROJECT_ROOT/docker-compose.grace-worker.yml" ]; then
        log_info "Backing up docker-compose.grace-worker.yml"
        run_cmd "cp $PROJECT_ROOT/docker-compose.grace-worker.yml $PROJECT_ROOT/docker-compose.grace-worker.yml.backup"

        log_warn "docker-compose.grace-worker.yml requires manual update"
        log_info "See MIGRATION.md Step 4.2 for the new configuration"
        log_info "Key changes needed:"
        echo "  - Use grace-orchestrator-worker image"
        echo "  - Update environment variables (GRACE_PROJECT_CONFIG)"
        echo "  - Update command to: ['grace-worker', 'start']"
    else
        log_warn "docker-compose.grace-worker.yml not found"
    fi
fi

# Step 7: Run validation
if [ "$DRY_RUN" = false ]; then
    log_step "Step 7: Validate migration"

    if [ -f "$PROJECT_ROOT/scripts/validate_migration.sh" ]; then
        log_info "Running validation script..."
        bash "$PROJECT_ROOT/scripts/validate_migration.sh" || true
    else
        log_warn "Validation script not found at scripts/validate_migration.sh"
    fi
fi

# Summary
echo ""
echo "=========================================="
echo "Migration Summary"
echo "=========================================="
echo ""

if [ "$DRY_RUN" = true ]; then
    log_warn "DRY RUN completed - no changes were made"
    echo ""
    echo "To perform the actual migration, run:"
    echo "  $0"
else
    log_success "Migration steps completed!"
    echo ""
    echo "Next steps:"
    echo "  1. Review the changes: git status"
    echo "  2. Update docker-compose.grace-worker.yml manually (see MIGRATION.md)"
    echo "  3. Test the migration: ./scripts/validate_migration.sh"
    echo "  4. Test a slice: gracectl slice list"
    echo "  5. Remove old directories after verification:"
    echo "     rm -rf src/prefect_grace/ gracectl/ infra/grace-worker/"
    echo ""
    echo "If you need to rollback:"
    echo "  ./scripts/rollback_migration.sh"
fi

echo ""
