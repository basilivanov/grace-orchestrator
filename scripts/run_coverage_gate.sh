#!/bin/bash
set -e
echo "GRACE Acceptance Pipeline — Coverage Gate"
echo "========================================="
echo ""

echo "Running tests with coverage..."
pytest \
  tests/grace_control/core \
  tests/grace_control/adapters/test_packet_executor_acceptance.py \
  --cov=src/grace_control/core \
  --cov=src/grace_control/adapters/packet_executor.py \
  --cov-report=term-missing \
  --cov-fail-under=100 \
  -q

echo ""
echo "Coverage gate passed!"
