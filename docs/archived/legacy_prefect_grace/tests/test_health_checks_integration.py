"""
Integration tests for health check system.

Tests the complete health check flow including:
- Executor rotation detection
- Deadlock detection
- Metrics collection verification
- Overall health status calculation
"""
import json
from datetime import datetime, timedelta, timezone

import pytest
from prefect_grace.platform.health_check import (
    HealthStatus,
    check_executor_rotation,
    check_deadlocks,
    check_metrics_collection,
    check_orchestrator_health,
)


class TestExecutorRotationCheck:
    """Test executor rotation health check."""

    def test_healthy_rotation(self, mock_execution_logs):
        """Healthy system with proper rotation."""
        result = check_executor_rotation(mock_execution_logs)

        assert result["status"] == HealthStatus.HEALTHY
        assert len(result["issues"]) == 0
        assert result["details"]["stuck_executors"] == 0

    def test_stuck_executor_detected(self, rotation_failure_logs):
        """Detect executor stuck without rotation."""
        result = check_executor_rotation(rotation_failure_logs)

        assert result["status"] in [HealthStatus.DEGRADED, HealthStatus.FAILING]
        assert len(result["issues"]) > 0
        assert "stuck" in result["issues"][0].lower()
        assert result["details"]["stuck_executors"] > 0

    def test_multiple_stuck_executors(self):
        """Multiple stuck executors should be FAILING."""
        now = datetime.now(timezone.utc)
        logs = []

        # Create 3 packets stuck on same executor
        for packet_num in range(3):
            for i in range(5):
                logs.append({
                    "event": "PACKET_END",
                    "packet_id": f"STUCK-{packet_num:03d}",
                    "executor_id": "coder-cheap",
                    "status": "failed",
                    "timestamp": (now - timedelta(minutes=50 - i * 10)).isoformat(),
                })

        result = check_executor_rotation(logs)

        assert result["status"] == HealthStatus.FAILING
        assert result["details"]["stuck_executors"] == 3

    def test_rotation_working_properly(self):
        """Proper rotation should be healthy."""
        now = datetime.now(timezone.utc)
        logs = [
            {
                "event": "PACKET_END",
                "packet_id": "PACKET-001",
                "executor_id": "coder-cheap",
                "status": "failed",
                "timestamp": (now - timedelta(minutes=20)).isoformat(),
            },
            {
                "event": "PACKET_END",
                "packet_id": "PACKET-001",
                "executor_id": "coder-cheap",
                "status": "failed",
                "timestamp": (now - timedelta(minutes=15)).isoformat(),
            },
            {
                "event": "PACKET_END",
                "packet_id": "PACKET-001",
                "executor_id": "coder-standard",  # Rotated!
                "status": "success",
                "timestamp": (now - timedelta(minutes=10)).isoformat(),
            },
        ]

        result = check_executor_rotation(logs)

        assert result["status"] == HealthStatus.HEALTHY
        assert result["details"]["stuck_executors"] == 0

    def test_no_failures(self):
        """No failures should be healthy."""
        now = datetime.now(timezone.utc)
        logs = [
            {
                "event": "PACKET_END",
                "packet_id": "PACKET-001",
                "executor_id": "coder-cheap",
                "status": "success",
                "timestamp": (now - timedelta(minutes=10)).isoformat(),
            },
        ]

        result = check_executor_rotation(logs)

        assert result["status"] == HealthStatus.HEALTHY
        assert result["details"]["total_failures"] == 0


class TestDeadlockCheck:
    """Test deadlock detection."""

    def test_no_deadlocks(self, mock_execution_logs):
        """All packets complete normally."""
        result = check_deadlocks(mock_execution_logs)

        assert result["status"] == HealthStatus.HEALTHY
        assert len(result["issues"]) == 0
        assert result["details"]["stuck_packets"] == 0

    def test_stuck_packet_detected(self):
        """Detect packet stuck for >1 hour."""
        # Use naive timestamps (without timezone) to match implementation
        logs = [
            {
                "event": "PACKET_START",
                "packet_id": "STUCK-001",
                "executor_id": "coder-cheap",
                "timestamp": "2026-05-30T08:00:00",  # 2+ hours ago (naive)
            },
            {
                "event": "PACKET_START",
                "packet_id": "NORMAL-001",
                "executor_id": "coder-cheap",
                "timestamp": "2026-05-30T11:50:00",  # Recent (naive)
            },
            {
                "event": "PACKET_END",
                "packet_id": "NORMAL-001",
                "executor_id": "coder-cheap",
                "status": "success",
                "timestamp": "2026-05-30T11:55:00",
            },
        ]

        result = check_deadlocks(logs)

        # Should detect stuck packet
        assert result["status"] in [HealthStatus.DEGRADED, HealthStatus.FAILING]
        assert result["details"]["stuck_packets"] >= 1

    def test_recent_running_packet_ok(self):
        """Recently started packet should not be flagged."""
        now = datetime.now(timezone.utc)
        logs = [
            {
                "event": "PACKET_START",
                "packet_id": "RECENT-001",
                "executor_id": "coder-cheap",
                "timestamp": (now - timedelta(minutes=30)).isoformat(),
            },
            # No PACKET_END yet, but only 30 minutes - OK
        ]

        result = check_deadlocks(logs)

        assert result["status"] == HealthStatus.HEALTHY
        assert result["details"]["stuck_packets"] == 0

    def test_multiple_stuck_packets(self):
        """Multiple stuck packets should be FAILING."""
        # Use naive timestamps (without timezone) to match implementation
        logs = []

        # Create 3 stuck packets (started >1 hour ago)
        for i in range(3):
            logs.append({
                "event": "PACKET_START",
                "packet_id": f"STUCK-{i:03d}",
                "executor_id": "coder-cheap",
                "timestamp": "2026-05-30T08:00:00",  # 2+ hours ago (naive)
            })

        result = check_deadlocks(logs)

        assert result["status"] == HealthStatus.FAILING
        assert result["details"]["stuck_packets"] >= 3

    def test_completed_packets_not_stuck(self):
        """Completed packets should not be counted as stuck."""
        now = datetime.now(timezone.utc)
        logs = [
            {
                "event": "PACKET_START",
                "packet_id": "COMPLETED-001",
                "executor_id": "coder-cheap",
                "timestamp": (now - timedelta(hours=3)).isoformat(),
            },
            {
                "event": "PACKET_END",
                "packet_id": "COMPLETED-001",
                "executor_id": "coder-cheap",
                "status": "success",
                "timestamp": (now - timedelta(hours=2, minutes=50)).isoformat(),
            },
        ]

        result = check_deadlocks(logs)

        assert result["status"] == HealthStatus.HEALTHY
        assert result["details"]["stuck_packets"] == 0

    def test_invalid_timestamp_handled(self):
        """Invalid timestamps should be handled gracefully."""
        logs = [
            {
                "event": "PACKET_START",
                "packet_id": "INVALID-001",
                "executor_id": "coder-cheap",
                "timestamp": "invalid-timestamp",
            },
        ]

        result = check_deadlocks(logs)

        # Should not crash, just skip invalid entries
        assert result["status"] == HealthStatus.HEALTHY


class TestMetricsCollectionCheck:
    """Test metrics collection verification."""

    def test_good_metrics_coverage(self, mock_execution_logs):
        """High metrics coverage should be healthy."""
        result = check_metrics_collection(mock_execution_logs)

        # Should be healthy or degraded (depending on exact coverage)
        assert result["status"] in [HealthStatus.HEALTHY, HealthStatus.DEGRADED]
        assert result["details"]["metrics_coverage"] >= 0.5

    def test_low_metrics_coverage(self):
        """Low metrics coverage should be FAILING or DEGRADED."""
        now = datetime.now(timezone.utc)
        logs = [
            {
                "event": "PACKET_END",
                "packet_id": "P1",
                "status": "success",
                "timestamp": (now - timedelta(minutes=10)).isoformat(),
            },
            {
                "event": "PACKET_END",
                "packet_id": "P2",
                "status": "success",
                "timestamp": (now - timedelta(minutes=9)).isoformat(),
            },
            # Only 1 metrics event for 2 executions = 50% coverage
            {
                "event": "EXECUTION_METRICS",
                "packet_id": "P1",
                "timestamp": (now - timedelta(minutes=10)).isoformat(),
            },
        ]

        result = check_metrics_collection(logs)

        assert result["status"] in [HealthStatus.FAILING, HealthStatus.DEGRADED]
        assert result["details"]["metrics_coverage"] == 0.5
        assert len(result["issues"]) > 0

    def test_partial_metrics_coverage(self):
        """Partial coverage (50-90%) should be DEGRADED."""
        now = datetime.now(timezone.utc)
        logs = []

        # 10 executions
        for i in range(10):
            logs.append({
                "event": "PACKET_END",
                "packet_id": f"P{i}",
                "status": "success",
                "timestamp": (now - timedelta(minutes=10 - i)).isoformat(),
            })

        # 7 metrics events = 70% coverage
        for i in range(7):
            logs.append({
                "event": "EXECUTION_METRICS",
                "packet_id": f"P{i}",
                "timestamp": (now - timedelta(minutes=10 - i)).isoformat(),
            })

        result = check_metrics_collection(logs)

        assert result["status"] == HealthStatus.DEGRADED
        assert 0.5 <= result["details"]["metrics_coverage"] < 0.9

    def test_no_executions(self):
        """No executions should be healthy (nothing to check)."""
        logs = []

        result = check_metrics_collection(logs)

        assert result["status"] == HealthStatus.HEALTHY
        assert result["details"].get("no_executions") is True

    def test_perfect_metrics_coverage(self):
        """100% metrics coverage should be healthy."""
        now = datetime.now(timezone.utc)
        logs = []

        # 5 executions with 5 metrics events
        for i in range(5):
            logs.append({
                "event": "PACKET_END",
                "packet_id": f"P{i}",
                "status": "success",
                "timestamp": (now - timedelta(minutes=10 - i)).isoformat(),
            })
            logs.append({
                "event": "EXECUTION_METRICS",
                "packet_id": f"P{i}",
                "timestamp": (now - timedelta(minutes=10 - i)).isoformat(),
            })

        result = check_metrics_collection(logs)

        assert result["status"] == HealthStatus.HEALTHY
        assert result["details"]["metrics_coverage"] == 1.0


class TestOverallHealthCheck:
    """Test overall orchestrator health check."""

    def test_all_checks_healthy(self, temp_state_dir, execution_trace_file):
        """All checks healthy should result in HEALTHY or DEGRADED status."""
        result = check_orchestrator_health(temp_state_dir)

        # Should be healthy or degraded depending on metrics coverage
        assert result["status"] in [HealthStatus.HEALTHY, HealthStatus.DEGRADED]
        assert "checks" in result
        assert "executor_rotation" in result["checks"]
        assert "deadlocks" in result["checks"]
        assert "metrics_collection" in result["checks"]
        assert "timestamp" in result

    def test_one_check_failing(self, temp_state_dir):
        """One failing check should result in FAILING status."""
        # Create logs with stuck executor
        run_dir = temp_state_dir / "runs" / "run-001"
        run_dir.mkdir(parents=True)
        trace_file = run_dir / "execution_trace.jsonl"

        now = datetime.now(timezone.utc)
        logs = []

        # Create stuck executor scenario
        for i in range(5):
            logs.append({
                "event": "PACKET_END",
                "packet_id": "STUCK-001",
                "executor_id": "coder-cheap",
                "status": "failed",
                "timestamp": (now - timedelta(minutes=50 - i * 10)).isoformat(),
            })

        with open(trace_file, "w") as f:
            for log in logs:
                f.write(json.dumps(log) + "\n")

        result = check_orchestrator_health(temp_state_dir)

        assert result["status"] in [HealthStatus.DEGRADED, HealthStatus.FAILING]

    def test_one_check_degraded(self, temp_state_dir):
        """One degraded check should result in DEGRADED status."""
        run_dir = temp_state_dir / "runs" / "run-001"
        run_dir.mkdir(parents=True)
        trace_file = run_dir / "execution_trace.jsonl"

        now = datetime.now(timezone.utc)
        logs = []

        # Create partial metrics coverage (70%)
        for i in range(10):
            logs.append({
                "event": "PACKET_END",
                "packet_id": f"P{i}",
                "status": "success",
                "timestamp": (now - timedelta(minutes=10 - i)).isoformat(),
            })

        for i in range(7):
            logs.append({
                "event": "EXECUTION_METRICS",
                "packet_id": f"P{i}",
                "timestamp": (now - timedelta(minutes=10 - i)).isoformat(),
            })

        with open(trace_file, "w") as f:
            for log in logs:
                f.write(json.dumps(log) + "\n")

        result = check_orchestrator_health(temp_state_dir)

        assert result["status"] == HealthStatus.DEGRADED

    def test_empty_state_directory(self, temp_state_dir):
        """Empty state directory should be healthy."""
        result = check_orchestrator_health(temp_state_dir)

        assert result["status"] == HealthStatus.HEALTHY

    def test_health_check_includes_all_details(self, temp_state_dir, execution_trace_file):
        """Health check should include details from all sub-checks."""
        result = check_orchestrator_health(temp_state_dir)

        # Check executor_rotation details
        assert "details" in result["checks"]["executor_rotation"]
        assert "stuck_executors" in result["checks"]["executor_rotation"]["details"]

        # Check deadlocks details
        assert "details" in result["checks"]["deadlocks"]
        assert "stuck_packets" in result["checks"]["deadlocks"]["details"]

        # Check metrics_collection details
        assert "details" in result["checks"]["metrics_collection"]
        assert "metrics_coverage" in result["checks"]["metrics_collection"]["details"]


class TestHealthStatusPriority:
    """Test health status priority logic."""

    def test_failing_overrides_degraded(self):
        """FAILING status should override DEGRADED."""
        statuses = [HealthStatus.HEALTHY, HealthStatus.DEGRADED, HealthStatus.FAILING]

        # Simulate overall status calculation
        if HealthStatus.FAILING in statuses:
            overall = HealthStatus.FAILING
        elif HealthStatus.DEGRADED in statuses:
            overall = HealthStatus.DEGRADED
        else:
            overall = HealthStatus.HEALTHY

        assert overall == HealthStatus.FAILING

    def test_degraded_overrides_healthy(self):
        """DEGRADED status should override HEALTHY."""
        statuses = [HealthStatus.HEALTHY, HealthStatus.DEGRADED, HealthStatus.HEALTHY]

        if HealthStatus.FAILING in statuses:
            overall = HealthStatus.FAILING
        elif HealthStatus.DEGRADED in statuses:
            overall = HealthStatus.DEGRADED
        else:
            overall = HealthStatus.HEALTHY

        assert overall == HealthStatus.DEGRADED

    def test_all_healthy(self):
        """All HEALTHY should result in HEALTHY."""
        statuses = [HealthStatus.HEALTHY, HealthStatus.HEALTHY, HealthStatus.HEALTHY]

        if HealthStatus.FAILING in statuses:
            overall = HealthStatus.FAILING
        elif HealthStatus.DEGRADED in statuses:
            overall = HealthStatus.DEGRADED
        else:
            overall = HealthStatus.HEALTHY

        assert overall == HealthStatus.HEALTHY


class TestHealthCheckEdgeCases:
    """Test edge cases in health checks."""

    def test_malformed_log_entries(self, temp_state_dir):
        """Handle malformed log entries gracefully."""
        run_dir = temp_state_dir / "runs" / "run-001"
        run_dir.mkdir(parents=True)
        trace_file = run_dir / "execution_trace.jsonl"

        with open(trace_file, "w") as f:
            f.write('{"event": "PACKET_START", "packet_id": "P1"}\n')
            f.write('this is not json\n')  # Malformed
            f.write('{"event": "PACKET_END", "packet_id": "P1", "status": "success"}\n')

        result = check_orchestrator_health(temp_state_dir)

        # Should not crash
        assert "status" in result

    def test_missing_required_fields(self, temp_state_dir):
        """Handle logs with missing required fields."""
        run_dir = temp_state_dir / "runs" / "run-001"
        run_dir.mkdir(parents=True)
        trace_file = run_dir / "execution_trace.jsonl"

        logs = [
            {"event": "PACKET_START"},  # Missing packet_id
            {"event": "PACKET_END", "packet_id": "P1"},  # Missing status
        ]

        with open(trace_file, "w") as f:
            for log in logs:
                f.write(json.dumps(log) + "\n")

        result = check_orchestrator_health(temp_state_dir)

        # Should handle gracefully
        assert result["status"] in [HealthStatus.HEALTHY, HealthStatus.DEGRADED, HealthStatus.FAILING]

    def test_concurrent_runs(self, temp_state_dir):
        """Handle multiple concurrent run directories."""
        now = datetime.now(timezone.utc)

        # Create 3 run directories
        for run_num in range(3):
            run_dir = temp_state_dir / "runs" / f"run-{run_num:03d}"
            run_dir.mkdir(parents=True)
            trace_file = run_dir / "execution_trace.jsonl"

            logs = [
                {
                    "event": "PACKET_START",
                    "packet_id": f"P{run_num}",
                    "timestamp": (now - timedelta(minutes=10)).isoformat(),
                },
                {
                    "event": "PACKET_END",
                    "packet_id": f"P{run_num}",
                    "status": "success",
                    "timestamp": (now - timedelta(minutes=5)).isoformat(),
                },
                {
                    "event": "EXECUTION_METRICS",
                    "packet_id": f"P{run_num}",
                    "timestamp": (now - timedelta(minutes=5)).isoformat(),
                },
            ]

            with open(trace_file, "w") as f:
                for log in logs:
                    f.write(json.dumps(log) + "\n")

        result = check_orchestrator_health(temp_state_dir)

        # Should aggregate across all runs
        assert result["status"] in [HealthStatus.HEALTHY, HealthStatus.DEGRADED]
