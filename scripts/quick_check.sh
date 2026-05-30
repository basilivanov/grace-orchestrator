#!/bin/bash
# Quick CI check - runs essential checks only

set -euo pipefail

echo "Running quick CI checks..."
echo ""

# Run tests
echo "1. Running tests..."
pytest src/prefect_grace/tests/ -v -x

# Check formatting
echo ""
echo "2. Checking code formatting..."
black --check src/prefect_grace
isort --check-only src/prefect_grace

# Run linter
echo ""
echo "3. Running linter..."
ruff check src/prefect_grace

echo ""
echo "✓ Quick checks passed!"
