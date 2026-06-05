#!/bin/bash
# Verify Phase 3 Day 9: Cost Dashboard implementation

echo "=== Phase 3 Day 9: Cost Dashboard - Verification ==="
echo ""

PASS=0
FAIL=0

# Check file existence
echo "Checking files..."
for file in aggregate_metrics.py dashboard.html generate_dashboard.sh test_dashboard.py; do
    if [ -f "$file" ]; then
        echo "  ✓ $file exists"
        ((PASS++))
    else
        echo "  ✗ $file missing"
        ((FAIL++))
    fi
done

# Check executability
echo ""
echo "Checking executability..."
for file in aggregate_metrics.py generate_dashboard.sh test_dashboard.py; do
    if [ -x "$file" ]; then
        echo "  ✓ $file is executable"
        ((PASS++))
    else
        echo "  ✗ $file not executable"
        ((FAIL++))
    fi
done

# Check Python syntax
echo ""
echo "Checking Python syntax..."
for file in aggregate_metrics.py test_dashboard.py; do
    if python3 -m py_compile "$file" 2>/dev/null; then
        echo "  ✓ $file syntax valid"
        ((PASS++))
    else
        echo "  ✗ $file syntax error"
        ((FAIL++))
    fi
done

# Check bash syntax
echo ""
echo "Checking bash syntax..."
if bash -n generate_dashboard.sh 2>/dev/null; then
    echo "  ✓ generate_dashboard.sh syntax valid"
    ((PASS++))
else
    echo "  ✗ generate_dashboard.sh syntax error"
    ((FAIL++))
fi

# Check HTML validity
echo ""
echo "Checking HTML..."
if grep -q "<!DOCTYPE html>" dashboard.html; then
    echo "  ✓ dashboard.html has DOCTYPE"
    ((PASS++))
else
    echo "  ✗ dashboard.html missing DOCTYPE"
    ((FAIL++))
fi

if grep -q "fetch('metrics.json')" dashboard.html; then
    echo "  ✓ dashboard.html loads metrics.json"
    ((PASS++))
else
    echo "  ✗ dashboard.html doesn't load metrics"
    ((FAIL++))
fi

# Check aggregate_metrics.py functionality
echo ""
echo "Checking aggregate_metrics.py functionality..."
if python3 aggregate_metrics.py ../state 2>/dev/null | jq -e '.total_executions' >/dev/null 2>&1; then
    echo "  ✓ aggregate_metrics.py produces valid JSON"
    ((PASS++))
else
    echo "  ✗ aggregate_metrics.py output invalid"
    ((FAIL++))
fi

# Check README documentation
echo ""
echo "Checking documentation..."
if grep -q "aggregate_metrics.py" README.md; then
    echo "  ✓ README documents aggregate_metrics.py"
    ((PASS++))
else
    echo "  ✗ README missing aggregate_metrics.py"
    ((FAIL++))
fi

if grep -q "generate_dashboard.sh" README.md; then
    echo "  ✓ README documents generate_dashboard.sh"
    ((PASS++))
else
    echo "  ✗ README missing generate_dashboard.sh"
    ((FAIL++))
fi

if grep -q "Cost Dashboard" README.md; then
    echo "  ✓ README has Cost Dashboard section"
    ((PASS++))
else
    echo "  ✗ README missing Cost Dashboard section"
    ((FAIL++))
fi

# Summary
echo ""
echo "=== Summary ==="
echo "  Passed: $PASS"
echo "  Failed: $FAIL"
echo ""

if [ $FAIL -eq 0 ]; then
    echo "✓ All checks passed!"
    exit 0
else
    echo "✗ Some checks failed"
    exit 1
fi
