#!/usr/bin/env python3
"""
End-to-end test for health check system.
"""
import sys
import json
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from prefect_grace.platform.health_check import (
    check_orchestrator_health,
    check_executor_rotation,
    check_deadlocks,
    check_metrics_collection,
    HealthStatus
)


def test_healthy_system():
    """Test health check with healthy logs."""
    # Create temp state directory
    with tempfile.TemporaryDirectory() as tmpdir:
        state_root = Path(tmpdir)
        runs_dir = state_root / "runs" / "test-run"
        runs_dir.mkdir(parents=True)

        # Write healthy logs
        trace_file = runs_dir / "execution_trace.jsonl"
        with open(trace_file, 'w') as f:
            f.write(json.dumps({
                "event": "PACKET_START",
                "packet_id": "P1",
                "timestamp": "2026-05-30T10:00:00Z"
            }) + "\n")
            f.write(json.dumps({
                "event": "EXECUTOR_SELECTED",
                "packet_id": "P1",
                "executor_id": "E1",
                "timestamp": "2026-05-30T10:00:01Z"
            }) + "\n")
            f.write(json.dumps({
                "event": "PACKET_END",
                "packet_id": "P1",
                "status": "accepted",
                "timestamp": "2026-05-30T10:05:00Z"
            }) + "\n")
            f.write(json.dumps({
                "event": "EXECUTION_METRICS",
                "packet_id": "P1",
                "timestamp": "2026-05-30T10:05:01Z"
            }) + "\n")

        result = check_orchestrator_health(state_root)
        assert result["status"] == HealthStatus.HEALTHY
        print("✓ Healthy system detection works")


def test_degraded_system():
    """Test health check with degraded logs."""
    # Create temp state directory
    with tempfile.TemporaryDirectory() as tmpdir:
        state_root = Path(tmpdir)
        runs_dir = state_root / "runs" / "test-run"
        runs_dir.mkdir(parents=True)

        # Write logs with stuck executor (but include metrics to avoid failing status)
        trace_file = runs_dir / "execution_trace.jsonl"
        with open(trace_file, 'w') as f:
            for i in range(5):
                f.write(json.dumps({
                    "event": "PACKET_END",
                    "packet_id": "P1",
                    "status": "failed",
                    "executor_id": "E1",
                    "timestamp": f"2026-05-30T10:0{i}:00Z"
                }) + "\n")
                # Add metrics for each execution
                f.write(json.dumps({
                    "event": "EXECUTION_METRICS",
                    "packet_id": "P1",
                    "timestamp": f"2026-05-30T10:0{i}:01Z"
                }) + "\n")

        result = check_orchestrator_health(state_root)
        assert result["status"] == HealthStatus.DEGRADED
        assert len(result["checks"]["executor_rotation"]["issues"]) > 0
        print("✓ Degraded system detection works")


def test_empty_logs():
    """Test health check with no logs."""
    with tempfile.TemporaryDirectory() as tmpdir:
        state_root = Path(tmpdir)
        result = check_orchestrator_health(state_root)
        assert result["status"] == HealthStatus.HEALTHY
        print("✓ Empty logs handled gracefully")


def test_malformed_logs():
    """Test health check with malformed logs."""
    with tempfile.TemporaryDirectory() as tmpdir:
        state_root = Path(tmpdir)
        runs_dir = state_root / "runs" / "test-run"
        runs_dir.mkdir(parents=True)

        # Write malformed logs
        trace_file = runs_dir / "execution_trace.jsonl"
        with open(trace_file, 'w') as f:
            f.write("not json\n")
            f.write("{incomplete json\n")
            f.write(json.dumps({"event": "PACKET_START", "packet_id": "P1"}) + "\n")

        result = check_orchestrator_health(state_root)
        # Should not crash, should handle gracefully
        assert "status" in result
        print("✓ Malformed logs handled gracefully")


if __name__ == "__main__":
    test_healthy_system()
    test_degraded_system()
    test_empty_logs()
    test_malformed_logs()
    print("\n✓ All end-to-end health check tests passed")
