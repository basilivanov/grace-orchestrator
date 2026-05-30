"""
Integration tests for verification patterns.

Tests the log-driven verification system including:
- Log aggregation from multiple runs
- Pattern matching for executor selection and rotation
- Success criteria validation
- Failure pattern detection
"""
import json
from datetime import datetime, timedelta, timezone

import pytest
from prefect_grace.tools.verification_patterns import (
    SUCCESS_PATTERNS,
    FAILURE_PATTERNS,
)


class TestLogAggregation:
    """Test log aggregation from multiple runs."""

    def test_aggregate_logs_from_single_run(self, temp_state_dir):
        """Aggregate logs from a single run directory."""
        from prefect_grace.tools.aggregate_logs import aggregate_logs

        run_dir = temp_state_dir / "runs" / "run-001"
        run_dir.mkdir(parents=True)
        trace_file = run_dir / "execution_trace.jsonl"

        logs = [
            {"event": "PACKET_START", "packet_id": "P1", "timestamp": "2026-05-30T10:00:00Z"},
            {"event": "PACKET_END", "packet_id": "P1", "timestamp": "2026-05-30T10:05:00Z"},
        ]

        with open(trace_file, "w") as f:
            for log in logs:
                f.write(json.dumps(log) + "\n")

        aggregated = aggregate_logs(temp_state_dir)

        assert len(aggregated) == 2
        assert aggregated[0]["packet_id"] == "P1"

    def test_aggregate_logs_from_multiple_runs(self, temp_state_dir):
        """Aggregate logs from multiple run directories."""
        from prefect_grace.tools.aggregate_logs import aggregate_logs

        # Create 3 run directories
        for i in range(3):
            run_dir = temp_state_dir / "runs" / f"run-{i:03d}"
            run_dir.mkdir(parents=True)
            trace_file = run_dir / "execution_trace.jsonl"

            log = {"event": "PACKET_START", "packet_id": f"P{i}", "timestamp": f"2026-05-30T10:{i:02d}:00Z"}

            with open(trace_file, "w") as f:
                f.write(json.dumps(log) + "\n")

        aggregated = aggregate_logs(temp_state_dir)

        assert len(aggregated) == 3
        # Should be sorted by timestamp
        assert aggregated[0]["packet_id"] == "P0"
        assert aggregated[1]["packet_id"] == "P1"
        assert aggregated[2]["packet_id"] == "P2"

    def test_aggregate_logs_sorted_by_timestamp(self, temp_state_dir):
        """Logs should be sorted by timestamp."""
        from prefect_grace.tools.aggregate_logs import aggregate_logs

        run_dir = temp_state_dir / "runs" / "run-001"
        run_dir.mkdir(parents=True)
        trace_file = run_dir / "execution_trace.jsonl"

        logs = [
            {"event": "PACKET_END", "packet_id": "P1", "timestamp": "2026-05-30T10:05:00Z"},
            {"event": "PACKET_START", "packet_id": "P1", "timestamp": "2026-05-30T10:00:00Z"},
            {"event": "PACKET_START", "packet_id": "P2", "timestamp": "2026-05-30T10:10:00Z"},
        ]

        with open(trace_file, "w") as f:
            for log in logs:
                f.write(json.dumps(log) + "\n")

        aggregated = aggregate_logs(temp_state_dir)

        # Should be sorted by timestamp
        assert aggregated[0]["timestamp"] == "2026-05-30T10:00:00Z"
        assert aggregated[1]["timestamp"] == "2026-05-30T10:05:00Z"
        assert aggregated[2]["timestamp"] == "2026-05-30T10:10:00Z"

    def test_aggregate_logs_handles_missing_runs_dir(self, temp_state_dir):
        """Handle missing runs directory gracefully."""
        from prefect_grace.tools.aggregate_logs import aggregate_logs

        # Remove runs directory
        import shutil
        shutil.rmtree(temp_state_dir / "runs")

        aggregated = aggregate_logs(temp_state_dir)

        assert aggregated == []


class TestExecutorSelectionPattern:
    """Test verification of executor selection patterns."""

    def test_verify_simple_packet_uses_cheap_executor(self, temp_state_dir):
        """Verify simple packets use coder-cheap."""
        from prefect_grace.tools.aggregate_logs import aggregate_logs

        run_dir = temp_state_dir / "runs" / "run-001"
        run_dir.mkdir(parents=True)
        trace_file = run_dir / "execution_trace.jsonl"

        logs = [
            {
                "event": "EXECUTOR_SELECTED",
                "packet_id": "SIMPLE-001",
                "complexity": "simple",
                "executor_id": "coder-cheap",
                "model": "gemini-3.5-flash",
                "timestamp": "2026-05-30T10:00:00Z",
            },
        ]

        with open(trace_file, "w") as f:
            for log in logs:
                f.write(json.dumps(log) + "\n")

        aggregated = aggregate_logs(temp_state_dir)

        # Verify pattern
        simple_selections = [
            log for log in aggregated
            if log.get("event") == "EXECUTOR_SELECTED"
            and log.get("complexity") == "simple"
        ]

        assert len(simple_selections) > 0
        assert all(log.get("executor_id") == "coder-cheap" for log in simple_selections)

    def test_verify_complex_packet_uses_premium_executor(self, temp_state_dir):
        """Verify complex packets use coder-premium."""
        from prefect_grace.tools.aggregate_logs import aggregate_logs

        run_dir = temp_state_dir / "runs" / "run-001"
        run_dir.mkdir(parents=True)
        trace_file = run_dir / "execution_trace.jsonl"

        logs = [
            {
                "event": "EXECUTOR_SELECTED",
                "packet_id": "COMPLEX-001",
                "complexity": "complex",
                "executor_id": "coder-premium",
                "model": "claude-opus-4",
                "timestamp": "2026-05-30T10:00:00Z",
            },
        ]

        with open(trace_file, "w") as f:
            for log in logs:
                f.write(json.dumps(log) + "\n")

        aggregated = aggregate_logs(temp_state_dir)

        # Verify pattern
        complex_selections = [
            log for log in aggregated
            if log.get("event") == "EXECUTOR_SELECTED"
            and log.get("complexity") == "complex"
        ]

        assert len(complex_selections) > 0
        assert all(log.get("executor_id") == "coder-premium" for log in complex_selections)

    def test_detect_wrong_model_for_complexity(self, temp_state_dir):
        """Detect when complex packet uses cheap model (failure pattern)."""
        from prefect_grace.tools.aggregate_logs import aggregate_logs

        run_dir = temp_state_dir / "runs" / "run-001"
        run_dir.mkdir(parents=True)
        trace_file = run_dir / "execution_trace.jsonl"

        logs = [
            {
                "event": "EXECUTOR_SELECTED",
                "packet_id": "COMPLEX-001",
                "complexity": "complex",
                "executor_id": "coder-cheap",  # Wrong!
                "model": "gemini-3.5-flash",
                "timestamp": "2026-05-30T10:00:00Z",
            },
        ]

        with open(trace_file, "w") as f:
            for log in logs:
                f.write(json.dumps(log) + "\n")

        aggregated = aggregate_logs(temp_state_dir)

        # Check for failure pattern
        violations = [
            log for log in aggregated
            if log.get("event") == "EXECUTOR_SELECTED"
            and log.get("complexity") == "complex"
            and log.get("executor_id") != "coder-premium"
        ]

        assert len(violations) > 0  # Detected the violation


class TestExecutorRotationPattern:
    """Test verification of executor rotation patterns."""

    def test_verify_rotation_after_failures(self, temp_state_dir):
        """Verify rotation happens after consecutive failures."""
        from prefect_grace.tools.aggregate_logs import aggregate_logs

        run_dir = temp_state_dir / "runs" / "run-001"
        run_dir.mkdir(parents=True)
        trace_file = run_dir / "execution_trace.jsonl"

        logs = [
            {
                "event": "EXECUTOR_SELECTED",
                "packet_id": "P1",
                "executor_id": "coder-cheap",
                "attempt": 1,
                "timestamp": "2026-05-30T10:00:00Z",
            },
            {
                "event": "PACKET_END",
                "packet_id": "P1",
                "executor_id": "coder-cheap",
                "status": "failed",
                "timestamp": "2026-05-30T10:05:00Z",
            },
            {
                "event": "EXECUTOR_SELECTED",
                "packet_id": "P1",
                "executor_id": "coder-cheap",
                "attempt": 2,
                "timestamp": "2026-05-30T10:06:00Z",
            },
            {
                "event": "PACKET_END",
                "packet_id": "P1",
                "executor_id": "coder-cheap",
                "status": "failed",
                "timestamp": "2026-05-30T10:11:00Z",
            },
            {
                "event": "EXECUTOR_ROTATED",
                "packet_id": "P1",
                "from_executor": "coder-cheap",
                "to_executor": "coder-standard",
                "reason": "max_consecutive_failures",
                "timestamp": "2026-05-30T10:12:00Z",
            },
            {
                "event": "EXECUTOR_SELECTED",
                "packet_id": "P1",
                "executor_id": "coder-standard",
                "attempt": 3,
                "timestamp": "2026-05-30T10:12:00Z",
            },
        ]

        with open(trace_file, "w") as f:
            for log in logs:
                f.write(json.dumps(log) + "\n")

        aggregated = aggregate_logs(temp_state_dir)

        # Verify rotation happened
        rotations = [log for log in aggregated if log.get("event") == "EXECUTOR_ROTATED"]
        assert len(rotations) > 0
        assert rotations[0]["from_executor"] == "coder-cheap"
        assert rotations[0]["to_executor"] == "coder-standard"

    def test_detect_missing_rotation(self, temp_state_dir):
        """Detect when rotation should have happened but didn't."""
        from prefect_grace.tools.aggregate_logs import aggregate_logs

        run_dir = temp_state_dir / "runs" / "run-001"
        run_dir.mkdir(parents=True)
        trace_file = run_dir / "execution_trace.jsonl"

        # 3+ failures on same executor without rotation
        logs = []
        for i in range(3):
            logs.extend([
                {
                    "event": "EXECUTOR_SELECTED",
                    "packet_id": "P1",
                    "executor_id": "coder-cheap",
                    "attempt": i + 1,
                    "timestamp": f"2026-05-30T10:{i * 10:02d}:00Z",
                },
                {
                    "event": "PACKET_END",
                    "packet_id": "P1",
                    "executor_id": "coder-cheap",
                    "status": "failed",
                    "timestamp": f"2026-05-30T10:{i * 10 + 5:02d}:00Z",
                },
            ])

        with open(trace_file, "w") as f:
            for log in logs:
                f.write(json.dumps(log) + "\n")

        aggregated = aggregate_logs(temp_state_dir)

        # Check for failure pattern: executor_stuck
        packet_failures = {}
        for log in aggregated:
            if log.get("event") == "PACKET_END" and log.get("status") == "failed":
                packet_id = log.get("packet_id")
                executor_id = log.get("executor_id")
                if packet_id not in packet_failures:
                    packet_failures[packet_id] = []
                packet_failures[packet_id].append(executor_id)

        # Check if same executor failed 3+ times
        stuck_executors = [
            (pid, execs) for pid, execs in packet_failures.items()
            if len(execs) >= 3 and len(set(execs)) == 1
        ]

        assert len(stuck_executors) > 0  # Detected the violation


class TestStatusTransitionPattern:
    """Test verification of status transition patterns."""

    def test_verify_all_packets_reach_terminal_state(self, temp_state_dir):
        """Verify all packets reach terminal state."""
        from prefect_grace.tools.aggregate_logs import aggregate_logs

        run_dir = temp_state_dir / "runs" / "run-001"
        run_dir.mkdir(parents=True)
        trace_file = run_dir / "execution_trace.jsonl"

        logs = [
            {"event": "PACKET_START", "packet_id": "P1", "timestamp": "2026-05-30T10:00:00Z"},
            {"event": "PACKET_END", "packet_id": "P1", "status": "accepted", "timestamp": "2026-05-30T10:05:00Z"},
            {"event": "PACKET_START", "packet_id": "P2", "timestamp": "2026-05-30T10:10:00Z"},
            {"event": "PACKET_END", "packet_id": "P2", "status": "blocked", "timestamp": "2026-05-30T10:15:00Z"},
        ]

        with open(trace_file, "w") as f:
            for log in logs:
                f.write(json.dumps(log) + "\n")

        aggregated = aggregate_logs(temp_state_dir)

        # Track packet states
        started = set()
        ended = set()

        for log in aggregated:
            if log.get("event") == "PACKET_START":
                started.add(log.get("packet_id"))
            elif log.get("event") == "PACKET_END":
                ended.add(log.get("packet_id"))

        # All started packets should have ended
        assert started == ended

    def test_detect_stuck_packets(self, temp_state_dir):
        """Detect packets stuck in running state."""
        from prefect_grace.tools.aggregate_logs import aggregate_logs

        run_dir = temp_state_dir / "runs" / "run-001"
        run_dir.mkdir(parents=True)
        trace_file = run_dir / "execution_trace.jsonl"

        now = datetime.now(timezone.utc)
        logs = [
            {
                "event": "PACKET_START",
                "packet_id": "STUCK-001",
                "timestamp": (now - timedelta(hours=2)).isoformat(),
            },
            # No PACKET_END - stuck!
            {
                "event": "PACKET_START",
                "packet_id": "NORMAL-001",
                "timestamp": (now - timedelta(minutes=10)).isoformat(),
            },
            {
                "event": "PACKET_END",
                "packet_id": "NORMAL-001",
                "status": "accepted",
                "timestamp": (now - timedelta(minutes=5)).isoformat(),
            },
        ]

        with open(trace_file, "w") as f:
            for log in logs:
                f.write(json.dumps(log) + "\n")

        aggregated = aggregate_logs(temp_state_dir)

        # Find stuck packets
        started = {}
        ended = set()

        for log in aggregated:
            if log.get("event") == "PACKET_START":
                started[log.get("packet_id")] = log.get("timestamp")
            elif log.get("event") == "PACKET_END":
                ended.add(log.get("packet_id"))

        stuck = [pid for pid in started if pid not in ended]
        assert "STUCK-001" in stuck


class TestMetricsPresencePattern:
    """Test verification of metrics presence."""

    def test_verify_metrics_collected_for_all_executions(self, temp_state_dir):
        """Verify metrics are collected for all executions."""
        from prefect_grace.tools.aggregate_logs import aggregate_logs

        run_dir = temp_state_dir / "runs" / "run-001"
        run_dir.mkdir(parents=True)
        trace_file = run_dir / "execution_trace.jsonl"

        logs = [
            {"event": "PACKET_END", "packet_id": "P1", "status": "accepted", "timestamp": "2026-05-30T10:05:00Z"},
            {"event": "EXECUTION_METRICS", "packet_id": "P1", "total_tokens": 50000, "timestamp": "2026-05-30T10:05:00Z"},
            {"event": "PACKET_END", "packet_id": "P2", "status": "accepted", "timestamp": "2026-05-30T10:15:00Z"},
            {"event": "EXECUTION_METRICS", "packet_id": "P2", "total_tokens": 75000, "timestamp": "2026-05-30T10:15:00Z"},
        ]

        with open(trace_file, "w") as f:
            for log in logs:
                f.write(json.dumps(log) + "\n")

        aggregated = aggregate_logs(temp_state_dir)

        # Count executions and metrics
        executions = [log for log in aggregated if log.get("event") == "PACKET_END"]
        metrics = [log for log in aggregated if log.get("event") == "EXECUTION_METRICS"]

        assert len(executions) == len(metrics)

    def test_detect_missing_metrics(self, temp_state_dir):
        """Detect when metrics are missing for executions."""
        from prefect_grace.tools.aggregate_logs import aggregate_logs

        run_dir = temp_state_dir / "runs" / "run-001"
        run_dir.mkdir(parents=True)
        trace_file = run_dir / "execution_trace.jsonl"

        logs = [
            {"event": "PACKET_END", "packet_id": "P1", "status": "accepted", "timestamp": "2026-05-30T10:05:00Z"},
            {"event": "EXECUTION_METRICS", "packet_id": "P1", "total_tokens": 50000, "timestamp": "2026-05-30T10:05:00Z"},
            {"event": "PACKET_END", "packet_id": "P2", "status": "accepted", "timestamp": "2026-05-30T10:15:00Z"},
            # Missing metrics for P2!
        ]

        with open(trace_file, "w") as f:
            for log in logs:
                f.write(json.dumps(log) + "\n")

        aggregated = aggregate_logs(temp_state_dir)

        # Find packets with missing metrics
        executions = {log.get("packet_id") for log in aggregated if log.get("event") == "PACKET_END"}
        metrics = {log.get("packet_id") for log in aggregated if log.get("event") == "EXECUTION_METRICS"}

        missing_metrics = executions - metrics
        assert "P2" in missing_metrics


class TestSuccessPatterns:
    """Test success pattern definitions."""

    def test_success_patterns_defined(self):
        """Verify success patterns are defined."""
        assert "executor_selection" in SUCCESS_PATTERNS
        assert "executor_rotation" in SUCCESS_PATTERNS
        assert "status_transitions" in SUCCESS_PATTERNS
        assert "metrics_present" in SUCCESS_PATTERNS

    def test_success_patterns_have_checks(self):
        """Each success pattern should have checks."""
        for pattern_name, pattern in SUCCESS_PATTERNS.items():
            assert "description" in pattern
            assert "checks" in pattern
            assert isinstance(pattern["checks"], list)
            assert len(pattern["checks"]) > 0


class TestFailurePatterns:
    """Test failure pattern definitions."""

    def test_failure_patterns_defined(self):
        """Verify failure patterns are defined."""
        assert "executor_stuck" in FAILURE_PATTERNS
        assert "wrong_model" in FAILURE_PATTERNS
        assert "status_drift" in FAILURE_PATTERNS
        assert "missing_logs" in FAILURE_PATTERNS

    def test_failure_patterns_have_descriptions(self):
        """Each failure pattern should have a description."""
        for pattern_name, description in FAILURE_PATTERNS.items():
            assert isinstance(description, str)
            assert len(description) > 0


class TestVerdictCalculation:
    """Test verdict calculation from patterns."""

    def test_calculate_pass_verdict(self, temp_state_dir):
        """Calculate PASS verdict when all patterns match."""
        from prefect_grace.tools.aggregate_logs import aggregate_logs

        run_dir = temp_state_dir / "runs" / "run-001"
        run_dir.mkdir(parents=True)
        trace_file = run_dir / "execution_trace.jsonl"

        # Create logs that satisfy all success patterns
        logs = [
            # Executor selection
            {"event": "EXECUTOR_SELECTED", "packet_id": "SIMPLE-001", "complexity": "simple", "executor_id": "coder-cheap", "timestamp": "2026-05-30T10:00:00Z"},
            # Status transition
            {"event": "PACKET_START", "packet_id": "SIMPLE-001", "timestamp": "2026-05-30T10:00:00Z"},
            {"event": "PACKET_END", "packet_id": "SIMPLE-001", "status": "accepted", "timestamp": "2026-05-30T10:05:00Z"},
            # Metrics present
            {"event": "EXECUTION_METRICS", "packet_id": "SIMPLE-001", "total_tokens": 50000, "timestamp": "2026-05-30T10:05:00Z"},
        ]

        with open(trace_file, "w") as f:
            for log in logs:
                f.write(json.dumps(log) + "\n")

        aggregated = aggregate_logs(temp_state_dir)

        # Verify all success criteria
        checks_passed = 0

        # Check executor selection
        selections = [log for log in aggregated if log.get("event") == "EXECUTOR_SELECTED"]
        if all(log.get("executor_id") == "coder-cheap" for log in selections if log.get("complexity") == "simple"):
            checks_passed += 1

        # Check status transitions
        started = {log.get("packet_id") for log in aggregated if log.get("event") == "PACKET_START"}
        ended = {log.get("packet_id") for log in aggregated if log.get("event") == "PACKET_END"}
        if started == ended:
            checks_passed += 1

        # Check metrics present
        executions = {log.get("packet_id") for log in aggregated if log.get("event") == "PACKET_END"}
        metrics = {log.get("packet_id") for log in aggregated if log.get("event") == "EXECUTION_METRICS"}
        if executions == metrics:
            checks_passed += 1

        # Verdict: PASS if all checks passed
        verdict = "PASS" if checks_passed >= 3 else "FAIL"
        assert verdict == "PASS"

    def test_calculate_fail_verdict(self, temp_state_dir):
        """Calculate FAIL verdict when failure patterns detected."""
        from prefect_grace.tools.aggregate_logs import aggregate_logs

        run_dir = temp_state_dir / "runs" / "run-001"
        run_dir.mkdir(parents=True)
        trace_file = run_dir / "execution_trace.jsonl"

        # Create logs with failure pattern (executor stuck)
        logs = []
        for i in range(3):
            logs.extend([
                {"event": "EXECUTOR_SELECTED", "packet_id": "P1", "executor_id": "coder-cheap", "timestamp": f"2026-05-30T10:{i * 10:02d}:00Z"},
                {"event": "PACKET_END", "packet_id": "P1", "executor_id": "coder-cheap", "status": "failed", "timestamp": f"2026-05-30T10:{i * 10 + 5:02d}:00Z"},
            ])

        with open(trace_file, "w") as f:
            for log in logs:
                f.write(json.dumps(log) + "\n")

        aggregated = aggregate_logs(temp_state_dir)

        # Check for executor_stuck pattern
        packet_failures = {}
        for log in aggregated:
            if log.get("event") == "PACKET_END" and log.get("status") == "failed":
                packet_id = log.get("packet_id")
                executor_id = log.get("executor_id")
                if packet_id not in packet_failures:
                    packet_failures[packet_id] = []
                packet_failures[packet_id].append(executor_id)

        failure_detected = any(
            len(execs) >= 3 and len(set(execs)) == 1
            for execs in packet_failures.values()
        )

        verdict = "FAIL" if failure_detected else "PASS"
        assert verdict == "FAIL"
