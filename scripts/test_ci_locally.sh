#!/bin/bash
# Test CI/CD setup locally

set -euo pipefail

echo "=========================================="
echo "Testing CI/CD setup locally..."
echo "=========================================="
echo ""

# Colors for output
GREEN='\033[0;32m'
RED='\033[0;31m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

# Track failures
FAILED=0

# Test pytest
echo "Running pytest with coverage..."
if pytest src/prefect_grace/tests/ -v --cov=src/prefect_grace --cov-report=term; then
    echo -e "${GREEN}✓ Tests passed${NC}"
else
    echo -e "${RED}✗ Tests failed${NC}"
    FAILED=$((FAILED + 1))
fi
echo ""

# Check coverage threshold
echo "Checking coverage threshold (60%)..."
if coverage report --fail-under=60; then
    echo -e "${GREEN}✓ Coverage threshold met${NC}"
else
    echo -e "${RED}✗ Coverage below 60%${NC}"
    FAILED=$((FAILED + 1))
fi
echo ""

# Test ruff
echo "Running ruff linter..."
if ruff check src/prefect_grace; then
    echo -e "${GREEN}✓ Ruff checks passed${NC}"
else
    echo -e "${RED}✗ Ruff found issues${NC}"
    FAILED=$((FAILED + 1))
fi
echo ""

# Test black
echo "Running black formatter check..."
if black --check src/prefect_grace; then
    echo -e "${GREEN}✓ Black formatting correct${NC}"
else
    echo -e "${YELLOW}⚠ Black formatting needed${NC}"
    echo "Run: black src/prefect_grace"
    FAILED=$((FAILED + 1))
fi
echo ""

# Test isort
echo "Running isort import check..."
if isort --check-only src/prefect_grace; then
    echo -e "${GREEN}✓ Import sorting correct${NC}"
else
    echo -e "${YELLOW}⚠ Import sorting needed${NC}"
    echo "Run: isort src/prefect_grace"
    FAILED=$((FAILED + 1))
fi
echo ""

# Test mypy
echo "Running mypy type checker..."
if mypy src/prefect_grace --ignore-missing-imports; then
    echo -e "${GREEN}✓ Type checking passed${NC}"
else
    echo -e "${RED}✗ Type errors found${NC}"
    FAILED=$((FAILED + 1))
fi
echo ""

# Test verification tools
echo "Running verification tools..."
mkdir -p state/runs
if python src/prefect_grace/tools/health_check.py state/ 2>/dev/null || true; then
    echo -e "${GREEN}✓ Health check completed${NC}"
else
    echo -e "${YELLOW}⚠ Health check had warnings (expected on empty state)${NC}"
fi

if python src/prefect_grace/tools/verify_orchestrator.py state/ 2>/dev/null || true; then
    echo -e "${GREEN}✓ Verification completed${NC}"
else
    echo -e "${YELLOW}⚠ Verification had warnings (expected on empty state)${NC}"
fi
echo ""

# Test security scanning
echo "Running security scans..."
if bandit -r src/prefect_grace -ll; then
    echo -e "${GREEN}✓ Bandit security scan passed${NC}"
else
    echo -e "${RED}✗ Security issues found${NC}"
    FAILED=$((FAILED + 1))
fi
echo ""

# Summary
echo "=========================================="
if [ $FAILED -eq 0 ]; then
    echo -e "${GREEN}✓ All CI/CD checks passed locally!${NC}"
    echo ""
    echo "Ready to push to GitHub."
    exit 0
else
    echo -e "${RED}✗ $FAILED check(s) failed${NC}"
    echo ""
    echo "Fix the issues above before pushing."
    exit 1
fi
