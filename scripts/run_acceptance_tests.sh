#!/bin/bash
set -e
echo "GRACE Acceptance Pipeline Tests"
echo "==============================="
echo ""

# 1. Core contracts + pipeline tests
echo "1. Acceptance core tests"
python -m pytest tests/grace_control/core -q
echo ""

# 2. Adapter integration tests
echo "2. Adapter integration tests"
python -m pytest tests/grace_control/adapters -q
echo ""

# 3. All tests
echo "3. Full test suite"
python -m pytest tests/ -q --ignore=tests/live -m "not slow" --deselect=tests/integration/test_retry_flow.py::test_two_run_records_created
echo ""

echo "All acceptance tests passed!"
