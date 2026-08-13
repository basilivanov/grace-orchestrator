#!/bin/bash
# validate_migration.sh
# Validates grace-orchestrator migration for astro-project

set -e

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

# Counters
PASSED=0
FAILED=0
WARNINGS=0

# Helper functions
print_header() {
    echo ""
    echo "=========================================="
    echo "$1"
    echo "=========================================="
}

print_check() {
    echo -n "Checking $1... "
}

print_pass() {
    echo -e "${GREEN}✓ PASS${NC}"
    ((PASSED++))
}

print_fail() {
    echo -e "${RED}✗ FAIL${NC}"
    echo -e "${RED}  $1${NC}"
    ((FAILED++))
}

print_warn() {
    echo -e "${YELLOW}⚠ WARNING${NC}"
    echo -e "${YELLOW}  $1${NC}"
    ((WARNINGS++))
}

# Change to project root
cd "$(dirname "$0")/.."
PROJECT_ROOT=$(pwd)

print_header "GRACE Orchestrator Migration Validation"
echo "Project: astro-project"
echo "Root: $PROJECT_ROOT"

# Check 1: grace-orchestrator package installed
print_header "1. Package Installation"

print_check "grace-orchestrator package"
if pip show grace-orchestrator &>/dev/null; then
    VERSION=$(pip show grace-orchestrator | grep Version | cut -d' ' -f2)
    print_pass
    echo "  Version: $VERSION"
else
    print_fail "grace-orchestrator not installed. Run: pip install grace-orchestrator[prefect]"
fi

print_check "supervisor bootstrap module"
if python3 -m grace_control.supervisor --help &>/dev/null; then
    print_pass
    echo "  Entry point: python3 -m grace_control.supervisor"
else
    print_fail "supervisor bootstrap module is not available"
fi

# Check 2: grace/ directory structure
print_header "2. Directory Structure"

print_check "grace/ directory exists"
if [ -d "$PROJECT_ROOT/grace" ]; then
    print_pass
else
    print_fail "grace/ directory not found"
fi

REQUIRED_FILES=(
    "grace/project.yaml"
    "grace/agent_profiles.yaml"
    "grace/requirements.xml"
    "grace/technology.xml"
    "grace/development-plan.xml"
    "grace/knowledge-graph.xml"
)

for file in "${REQUIRED_FILES[@]}"; do
    print_check "$file"
    if [ -f "$PROJECT_ROOT/$file" ]; then
        print_pass
    else
        print_fail "$file not found"
    fi
done

print_check "grace/packets/ directory"
if [ -d "$PROJECT_ROOT/grace/packets" ]; then
    PACKET_COUNT=$(find "$PROJECT_ROOT/grace/packets" -mindepth 1 -maxdepth 1 -type d 2>/dev/null | wc -l)
    print_pass
    echo "  Packets found: $PACKET_COUNT"
else
    print_warn "grace/packets/ directory not found. Packets may still be in src/prefect_grace/packets/"
fi

# Check 3: Old directories removed
print_header "3. Old Implementation Cleanup"

print_check "src/prefect_grace/ removed"
if [ ! -d "$PROJECT_ROOT/src/prefect_grace" ]; then
    print_pass
else
    print_warn "src/prefect_grace/ still exists. Should be removed after migration."
fi

print_check "gracectl/ removed"
if [ ! -d "$PROJECT_ROOT/gracectl" ]; then
    print_pass
else
    print_warn "gracectl/ still exists. Should be removed after migration."
fi

print_check "infra/grace-worker/ removed"
if [ ! -d "$PROJECT_ROOT/infra/grace-worker" ]; then
    print_pass
else
    print_warn "infra/grace-worker/ still exists. Should be removed after migration."
fi

# Check 4: Configuration files valid
print_header "4. Configuration Validation"

print_check "grace/project.yaml syntax"
if python3 -c "import yaml; yaml.safe_load(open('$PROJECT_ROOT/grace/project.yaml'))" 2>/dev/null; then
    print_pass
else
    print_fail "grace/project.yaml has invalid YAML syntax"
fi

print_check "grace/agent_profiles.yaml syntax"
if python3 -c "import yaml; yaml.safe_load(open('$PROJECT_ROOT/grace/agent_profiles.yaml'))" 2>/dev/null; then
    print_pass
else
    print_fail "grace/agent_profiles.yaml has invalid YAML syntax"
fi

print_check "gracectl.yaml exists"
if [ -f "$PROJECT_ROOT/gracectl.yaml" ]; then
    print_pass
    echo "  (Used for slice definitions)"
else
    print_fail "gracectl.yaml not found"
fi

# Check 5: Docker configuration
print_header "5. Docker Configuration"

print_check "docker-compose.grace-worker.yml exists"
if [ -f "$PROJECT_ROOT/docker-compose.grace-worker.yml" ]; then
    print_pass
else
    print_fail "docker-compose.grace-worker.yml not found"
fi

print_check "docker-compose.grace-worker.yml uses grace-orchestrator image"
if grep -q "grace-orchestrator-worker" "$PROJECT_ROOT/docker-compose.grace-worker.yml" 2>/dev/null; then
    print_pass
else
    print_warn "docker-compose.grace-worker.yml may not be using grace-orchestrator image"
fi

print_check "GRACE_PROJECT_CONFIG environment variable"
if grep -q "GRACE_PROJECT_CONFIG" "$PROJECT_ROOT/docker-compose.grace-worker.yml" 2>/dev/null; then
    print_pass
else
    print_fail "GRACE_PROJECT_CONFIG not found in docker-compose.grace-worker.yml"
fi

# Check 6: Python imports updated
print_header "6. Python Import Updates"

print_check "Old prefect_grace imports"
OLD_IMPORTS=$(grep -r "from prefect_grace" --include="*.py" "$PROJECT_ROOT" 2>/dev/null | grep -v ".pyc" | grep -v "__pycache__" | grep -v "backup" | wc -l)
if [ "$OLD_IMPORTS" -eq 0 ]; then
    print_pass
else
    print_warn "Found $OLD_IMPORTS files with old 'from prefect_grace' imports"
    echo "  Run: grep -r 'from prefect_grace' --include='*.py' . | grep -v backup"
fi

print_check "New grace_orchestrator imports"
NEW_IMPORTS=$(grep -r "from grace_orchestrator" --include="*.py" "$PROJECT_ROOT" 2>/dev/null | grep -v ".pyc" | grep -v "__pycache__" | wc -l)
if [ "$NEW_IMPORTS" -gt 0 ]; then
    print_pass
    echo "  Found $NEW_IMPORTS files with new imports"
else
    print_warn "No files found with 'from grace_orchestrator' imports. May need to update imports."
fi

# Check 7: Environment variables
print_header "7. Environment Configuration"

print_check ".env file exists"
if [ -f "$PROJECT_ROOT/.env" ]; then
    print_pass
else
    print_warn ".env file not found. Using .env.example as reference."
fi

ENV_FILE="$PROJECT_ROOT/.env"
if [ ! -f "$ENV_FILE" ]; then
    ENV_FILE="$PROJECT_ROOT/.env.example"
fi

RECOMMENDED_VARS=(
    "GRACE_PROJECT_CONFIG"
    "GRACE_WORK_POOL"
    "GRACE_LIVE_QUEUE"
)

for var in "${RECOMMENDED_VARS[@]}"; do
    print_check "$var in environment"
    if grep -q "^${var}=" "$ENV_FILE" 2>/dev/null || grep -q "^#${var}=" "$ENV_FILE" 2>/dev/null; then
        print_pass
    else
        print_warn "$var not found in $ENV_FILE"
    fi
done

# Check 8: Test imports work
print_header "8. Runtime Validation"

print_check "grace_orchestrator module imports"
if python3 -c "import grace_orchestrator" 2>/dev/null; then
    print_pass
else
    print_fail "Cannot import grace_orchestrator module"
fi

print_check "HTTP/OpenAPI control surface"
if python3 -c "from grace_control.api.main import app; assert any(getattr(route, 'path', '') == '/api/admin/lifecycle/status' for route in app.routes)" &>/dev/null; then
    print_pass
else
    print_fail "HTTP/OpenAPI lifecycle status route is not available"
fi

# Summary
print_header "Validation Summary"
echo ""
echo -e "${GREEN}Passed:   $PASSED${NC}"
echo -e "${YELLOW}Warnings: $WARNINGS${NC}"
echo -e "${RED}Failed:   $FAILED${NC}"
echo ""

if [ $FAILED -eq 0 ]; then
    if [ $WARNINGS -eq 0 ]; then
        echo -e "${GREEN}✓ Migration validation PASSED with no issues!${NC}"
        exit 0
    else
        echo -e "${YELLOW}⚠ Migration validation PASSED with warnings.${NC}"
        echo "Review warnings above and address if needed."
        exit 0
    fi
else
    echo -e "${RED}✗ Migration validation FAILED.${NC}"
    echo "Fix the failed checks above before proceeding."
    exit 1
fi
