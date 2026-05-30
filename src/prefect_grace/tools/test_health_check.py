#!/usr/bin/env python3
"""
Test health check functionality.
"""
import sys
from pathlib import Path

# Add parent directory to path
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from prefect_grace.platform.health_check import (
    check_executor_rotation,
    check_deadlocks,
    check_metrics_collection,
    HealthStatus
)


def test_executor_rotation():
    """Test executor rotation check."""
    # Healthy: rotation working
    logs = [
        {"event": "PACKET_END", "packet_id": "P1", "status": "failed", "executor_id": "E1"},
        {"event": "PACKET_END", "packet_id": "P1", "status": "failed", "executor_id": "E2"},
    ]
    result = check_executor_rotation(logs)
    assert result["status"] == HealthStatus.HEALTHY
    print("✓ Executor rotation check works")


def test_deadlocks():
    """Test deadlock detection."""
    # No deadlocks
    logs = [
        {"event": "PACKET_START", "packet_id": "P1", "timestamp": "2026-05-30T10:00:00Z"},
        {"event": "PACKET_END", "packet_id": "P1", "timestamp": "2026-05-30T10:05:00Z"}
    ]
    result = check_deadlocks(logs)
    assert result["status"] == HealthStatus.HEALTHY
    print("✓ Deadlock check works")


def test_metrics_collection():
    """Test metrics collection check."""
    # Good coverage
    logs = [
        {"event": "PACKET_END", "packet_id": "P1"},
        {"event": "EXECUTION_METRICS", "packet_id": "P1"}
    ]
    result = check_metrics_collection(logs)
    assert result["status"] == HealthStatus.HEALTHY
    print("✓ Metrics collection check works")


if __name__ == "__main__":
    test_executor_rotation()
    test_deadlocks()
    test_metrics_collection()
    print("\n✓ All health check tests passed")
