#!/bin/bash
set -e

echo "=== Verifying P1 Fixes ==="
echo ""

cd /tmp/grace-orchestrator-export

echo "1. Testing pytest config..."
if pytest --collect-only 2>&1 | grep -q "src/prefect_grace/tests"; then
    echo "   ✅ Tests discovered in correct location"
else
    echo "   ❌ ERROR: Tests not discovered in src/prefect_grace/tests"
    exit 1
fi
echo ""

echo "2. Checking for yourusername..."
if grep -r "yourusername" pyproject.toml README.md MIGRATION.md SETUP.md CHANGELOG.md CONTRIBUTING.md docs/ 2>/dev/null; then
    echo "   ❌ ERROR: Found remaining 'yourusername' references"
    exit 1
else
    echo "   ✅ No 'yourusername' references found"
fi
echo ""

echo "3. Checking coverage threshold..."
if grep -q "fail-under=75" .github/workflows/ci.yml; then
    echo "   ✅ Coverage threshold updated to 75%"
else
    echo "   ❌ ERROR: Coverage threshold not updated"
    exit 1
fi
echo ""

echo "4. Checking mypy strict config..."
if grep -q "disallow_untyped_defs = true" pyproject.toml; then
    echo "   ✅ Strict mypy configured"
else
    echo "   ❌ ERROR: Strict mypy not configured"
    exit 1
fi
echo ""

echo "5. Checking pre-commit config..."
if [ -f .pre-commit-config.yaml ]; then
    echo "   ✅ Pre-commit config exists"
else
    echo "   ❌ ERROR: Pre-commit config missing"
    exit 1
fi
echo ""

echo "6. Checking development docs..."
if [ -f docs/DEVELOPMENT.md ]; then
    echo "   ✅ Development documentation exists"
else
    echo "   ❌ ERROR: Development documentation missing"
    exit 1
fi
echo ""

echo "✅ All P1 fixes verified successfully!"
