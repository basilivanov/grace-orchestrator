#!/bin/bash
set -e
echo "GRACE Guardrails"
echo "================"
echo ""

case "${1:-all}" in
  acceptance)
    echo "Acceptance pipeline tests"
    pytest tests/grace_control/core tests/grace_control/adapters/test_packet_executor_acceptance.py -q
    ;;
  coverage)
    echo "Acceptance pipeline — coverage gate (80%)"
    pytest tests/grace_control/core tests/grace_control/adapters/test_packet_executor_acceptance.py \
      --cov=grace_control.core.acceptance_pipeline \
      --cov=grace_control.core.command_runner \
      --cov=grace_control.core.contracts \
      --cov=grace_control.core.evidence \
      --cov=grace_control.core.scope_guard \
      --cov-report=term-missing \
      --cov-fail-under=80 -q
    ;;
  lint)
    echo "GRACE Canon lint"
    python scripts/grace_lint.py src/grace_control/core/
    ;;
  all|*)
    echo "Full guardrails pass"
    bash "$0" acceptance
    echo ""
    bash "$0" lint
    echo ""
    echo "All guardrails passed!"
    ;;
esac
