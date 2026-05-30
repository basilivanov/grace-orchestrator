"""
End-to-end test for simple packet execution.

Tests the complete packet execution flow from start to finish:
- Packet creation
- Executor selection
- Execution with coder-cheap
- Metrics collection
- Health verification
- Success criteria validation
"""
import json
from datetime import datetime, timezone
from pathlib import Path

import pytest


class TestSimplePacketE2E:
    """End-to-end test for simple packet execution."""

    def test_simple_packet_full_flow(self, temp_state_dir, mock_project_config):
        """Test complete flow for a simple packet."""
        from prefect_grace.platform.executor_registry import select_executor_for_packet, record_executor_attempt
        from prefect_grace.platform.state_store import ExecutorHistoryStore
        from prefect_grace.tools.aggregate_logs import aggregate_logs
        from prefect_grace.platform.health_check import check_orchestrator_health

        # 1. Create simple packet
        packet = {
            "packet_id": "SIMPLE-E2E-001",
            "role": "coder",
            "complexity": "simple",
            "source_hash": "e2e_hash_001",
            "title": "Add user authentication",
        }

        # 2. Select executor
        selection = select_executor_for_packet(
            project=mock_project_config,
            packet=packet,
            history=[],
        )

        assert selection.ok is True
        assert selection.selected.executor_id == "coder-cheap"
        assert selection.selected.model == "gemini-3.5-flash"

        # 3. Simulate execution
        execution_result = {
            "feature_id": "FEAT-001",
            "wave_id": "W01",
            "source_hash": "e2e_hash_001",
            "status": "completed",
            "returncode": 0,
            "domain_status": "accepted",
            "executor_kind": "codex",
            "selection_reason": "selected",
        }

        # 4. Record execution attempt
        record = record_executor_attempt(
            state_root=temp_state_dir,
            packet_id=packet["packet_id"],
            role=packet["role"],
            executor_id=selection.selected.executor_id,
            result=execution_result,
            attempt=1,
        )

        assert record["packet_id"] == "SIMPLE-E2E-001"
        assert record["returncode"] == 0

        # 5. Create execution trace with metrics
        run_dir = temp_state_dir / "runs" / "run-e2e-001"
        run_dir.mkdir(parents=True)
        trace_file = run_dir / "execution_trace.jsonl"

        now = datetime.now(timezone.utc)
        logs = [
            {
                "event": "PACKET_START",
                "packet_id": "SIMPLE-E2E-001",
                "executor_id": "coder-cheap",
                "timestamp": now.isoformat(),
            },
            {
                "event": "EXECUTOR_SELECTED",
                "packet_id": "SIMPLE-E2E-001",
                "complexity": "simple",
                "executor_id": "coder-cheap",
                "model": "gemini-3.5-flash",
                "timestamp": now.isoformat(),
            },
            {
                "event": "PACKET_END",
                "packet_id": "SIMPLE-E2E-001",
                "executor_id": "coder-cheap",
                "status": "success",
                "timestamp": now.isoformat(),
            },
            {
                "event": "EXECUTION_METRICS",
                "packet_id": "SIMPLE-E2E-001",
                "executor_id": "coder-cheap",
                "model": "gemini-3.5-flash",
                "total_tokens": 45000,
                "cost_usd": 0.18,
                "duration_seconds": 95,
                "timestamp": now.isoformat(),
            },
        ]

        with open(trace_file, "w") as f:
            for log in logs:
                f.write(json.dumps(log) + "\n")

        # 6. Verify logs
        aggregated = aggregate_logs(temp_state_dir)
        assert len(aggregated) == 4

        # 7. Check health
        health = check_orchestrator_health(temp_state_dir)
        assert health["status"] == "healthy"

        # 8. Validate success criteria
        # - Correct executor selected
        executor_selections = [log for log in aggregated if log.get("event") == "EXECUTOR_SELECTED"]
        assert len(executor_selections) == 1
        assert executor_selections[0]["executor_id"] == "coder-cheap"

        # - Packet completed
        packet_ends = [log for log in aggregated if log.get("event") == "PACKET_END"]
        assert len(packet_ends) == 1
        assert packet_ends[0]["status"] == "success"

        # - Metrics collected
        metrics = [log for log in aggregated if log.get("event") == "EXECUTION_METRICS"]
        assert len(metrics) == 1
        assert metrics[0]["total_tokens"] == 45000
        assert metrics[0]["cost_usd"] == 0.18

    def test_simple_packet_with_retry(self, temp_state_dir, mock_project_config):
        """Test simple packet that fails once then succeeds."""
        from prefect_grace.platform.executor_registry import select_executor_for_packet, record_executor_attempt
        from prefect_grace.tools.aggregate_logs import aggregate_logs

        packet = {
            "packet_id": "SIMPLE-RETRY-001",
            "role": "coder",
            "complexity": "simple",
            "source_hash": "retry_hash_001",
        }

        # First attempt - select executor
        selection1 = select_executor_for_packet(
            project=mock_project_config,
            packet=packet,
            history=[],
        )

        assert selection1.selected.executor_id == "coder-cheap"

        # First attempt - fails
        result1 = {
            "source_hash": "retry_hash_001",
            "status": "failed",
            "returncode": 1,
            "domain_status": "agent_failed",
            "executor_kind": "codex",
            "selection_reason": "selected",
        }

        record_executor_attempt(
            state_root=temp_state_dir,
            packet_id=packet["packet_id"],
            role=packet["role"],
            executor_id=selection1.selected.executor_id,
            result=result1,
            attempt=1,
        )

        # Second attempt - select executor (should be same, only 1 failure)
        from prefect_grace.platform.state_store import ExecutorHistoryStore
        history = ExecutorHistoryStore(temp_state_dir).list_executions()

        selection2 = select_executor_for_packet(
            project=mock_project_config,
            packet=packet,
            history=history,
        )

        assert selection2.selected.executor_id == "coder-cheap"

        # Second attempt - succeeds
        result2 = {
            "source_hash": "retry_hash_001",
            "status": "completed",
            "returncode": 0,
            "domain_status": "accepted",
            "executor_kind": "codex",
            "selection_reason": "selected",
        }

        record_executor_attempt(
            state_root=temp_state_dir,
            packet_id=packet["packet_id"],
            role=packet["role"],
            executor_id=selection2.selected.executor_id,
            result=result2,
            attempt=2,
        )

        # Create execution trace
        run_dir = temp_state_dir / "runs" / "run-retry-001"
        run_dir.mkdir(parents=True)
        trace_file = run_dir / "execution_trace.jsonl"

        now = datetime.now(timezone.utc)
        logs = [
            # First attempt
            {"event": "PACKET_START", "packet_id": "SIMPLE-RETRY-001", "executor_id": "coder-cheap", "attempt": 1, "timestamp": now.isoformat()},
            {"event": "PACKET_END", "packet_id": "SIMPLE-RETRY-001", "executor_id": "coder-cheap", "status": "failed", "timestamp": now.isoformat()},
            # Second attempt
            {"event": "PACKET_START", "packet_id": "SIMPLE-RETRY-001", "executor_id": "coder-cheap", "attempt": 2, "timestamp": now.isoformat()},
            {"event": "PACKET_END", "packet_id": "SIMPLE-RETRY-001", "executor_id": "coder-cheap", "status": "success", "timestamp": now.isoformat()},
            {"event": "EXECUTION_METRICS", "packet_id": "SIMPLE-RETRY-001", "total_tokens": 50000, "cost_usd": 0.20, "timestamp": now.isoformat()},
        ]

        with open(trace_file, "w") as f:
            for log in logs:
                f.write(json.dumps(log) + "\n")

        # Verify final state
        aggregated = aggregate_logs(temp_state_dir)
        packet_ends = [log for log in aggregated if log.get("event") == "PACKET_END"]
        assert len(packet_ends) == 2
        assert packet_ends[0]["status"] == "failed"
        assert packet_ends[1]["status"] == "success"

    def test_simple_packet_with_rotation(self, temp_state_dir, mock_project_config):
        """Test simple packet that rotates after 2 failures."""
        from prefect_grace.platform.executor_registry import select_executor_for_packet, record_executor_attempt
        from prefect_grace.platform.state_store import ExecutorHistoryStore

        # Use packet without complexity to allow all executors
        packet = {
            "packet_id": "SIMPLE-ROTATION-001",
            "role": "coder",
            "source_hash": "rotation_hash_001",
        }

        # Attempt 1 - coder-cheap fails
        selection1 = select_executor_for_packet(
            project=mock_project_config,
            packet=packet,
            history=[],
        )
        assert selection1.ok is True
        assert selection1.selected.executor_id == "coder-cheap"

        record_executor_attempt(
            state_root=temp_state_dir,
            packet_id=packet["packet_id"],
            role=packet["role"],
            executor_id=selection1.selected.executor_id,
            result={"returncode": 1, "domain_status": "agent_failed", "source_hash": "rotation_hash_001"},
            attempt=1,
        )

        # Attempt 2 - coder-cheap fails again
        history = ExecutorHistoryStore(temp_state_dir).list_executions()
        selection2 = select_executor_for_packet(
            project=mock_project_config,
            packet=packet,
            history=history,
        )
        assert selection2.ok is True
        assert selection2.selected.executor_id == "coder-cheap"

        record_executor_attempt(
            state_root=temp_state_dir,
            packet_id=packet["packet_id"],
            role=packet["role"],
            executor_id=selection2.selected.executor_id,
            result={"returncode": 1, "domain_status": "agent_failed", "source_hash": "rotation_hash_001"},
            attempt=2,
        )

        # Attempt 3 - should rotate to coder-standard
        history = ExecutorHistoryStore(temp_state_dir).list_executions()
        selection3 = select_executor_for_packet(
            project=mock_project_config,
            packet=packet,
            history=history,
        )
        assert selection3.ok is True
        assert selection3.selected.executor_id == "coder-standard"

        record_executor_attempt(
            state_root=temp_state_dir,
            packet_id=packet["packet_id"],
            role=packet["role"],
            executor_id=selection3.selected.executor_id,
            result={"returncode": 0, "domain_status": "accepted", "source_hash": "rotation_hash_001"},
            attempt=3,
        )

        # Verify rotation happened
        history = ExecutorHistoryStore(temp_state_dir).list_executions()
        assert len(history) == 3
        assert history[0]["executor_id"] == "coder-cheap"
        assert history[1]["executor_id"] == "coder-cheap"
        assert history[2]["executor_id"] == "coder-standard"

    def test_multiple_simple_packets(self, temp_state_dir, mock_project_config):
        """Test multiple simple packets executing successfully."""
        from prefect_grace.platform.executor_registry import select_executor_for_packet, record_executor_attempt
        from prefect_grace.tools.aggregate_logs import aggregate_logs
        from prefect_grace.tools.aggregate_metrics import aggregate_metrics

        packets = [
            {"packet_id": f"SIMPLE-{i:03d}", "role": "coder", "complexity": "simple", "source_hash": f"hash_{i}"}
            for i in range(5)
        ]

        run_dir = temp_state_dir / "runs" / "run-multi-001"
        run_dir.mkdir(parents=True)
        trace_file = run_dir / "execution_trace.jsonl"

        now = datetime.now(timezone.utc)
        all_logs = []

        for i, packet in enumerate(packets):
            # Select executor
            selection = select_executor_for_packet(
                project=mock_project_config,
                packet=packet,
                history=[],
            )
            assert selection.selected.executor_id == "coder-cheap"

            # Record execution
            record_executor_attempt(
                state_root=temp_state_dir,
                packet_id=packet["packet_id"],
                role=packet["role"],
                executor_id=selection.selected.executor_id,
                result={"returncode": 0, "domain_status": "accepted", "source_hash": packet["source_hash"]},
                attempt=1,
            )

            # Add logs
            all_logs.extend([
                {"event": "PACKET_START", "packet_id": packet["packet_id"], "executor_id": "coder-cheap", "timestamp": now.isoformat()},
                {"event": "PACKET_END", "packet_id": packet["packet_id"], "executor_id": "coder-cheap", "status": "success", "timestamp": now.isoformat()},
                {"event": "EXECUTION_METRICS", "packet_id": packet["packet_id"], "total_tokens": 50000, "cost_usd": 0.20, "timestamp": now.isoformat()},
            ])

        with open(trace_file, "w") as f:
            for log in all_logs:
                f.write(json.dumps(log) + "\n")

        # Verify all packets completed
        aggregated = aggregate_logs(temp_state_dir)
        packet_ends = [log for log in aggregated if log.get("event") == "PACKET_END"]
        assert len(packet_ends) == 5
        assert all(log["status"] == "success" for log in packet_ends)

        # Verify metrics
        metrics = aggregate_metrics(temp_state_dir)
        assert metrics["total_executions"] == 5
        assert metrics["total_tokens"] == 250000
        assert metrics["total_cost_usd"] == 1.00

    def test_simple_packet_cost_efficiency(self, temp_state_dir, mock_project_config):
        """Test that simple packets use cost-efficient executor."""
        from prefect_grace.platform.executor_registry import select_executor_for_packet
        from prefect_grace.tools.aggregate_metrics import aggregate_metrics

        packet = {
            "packet_id": "SIMPLE-COST-001",
            "role": "coder",
            "complexity": "simple",
            "source_hash": "cost_hash_001",
        }

        # Select executor
        selection = select_executor_for_packet(
            project=mock_project_config,
            packet=packet,
            history=[],
        )

        # Should use cheap executor
        assert selection.selected.executor_id == "coder-cheap"
        assert selection.selected.model == "gemini-3.5-flash"

        # Create execution trace
        run_dir = temp_state_dir / "runs" / "run-cost-001"
        run_dir.mkdir(parents=True)
        trace_file = run_dir / "execution_trace.jsonl"

        now = datetime.now(timezone.utc)
        logs = [
            {"event": "PACKET_END", "packet_id": "SIMPLE-COST-001", "status": "success", "timestamp": now.isoformat()},
            {"event": "EXECUTION_METRICS", "packet_id": "SIMPLE-COST-001", "model": "gemini-3.5-flash", "total_tokens": 50000, "cost_usd": 0.20, "timestamp": now.isoformat()},
        ]

        with open(trace_file, "w") as f:
            for log in logs:
                f.write(json.dumps(log) + "\n")

        # Calculate savings vs premium
        metrics = aggregate_metrics(temp_state_dir)

        # Premium would cost: 50000 * $75/1M = $3.75
        # Actual cost: $0.20
        # Savings: $3.55 (94.7%)
        assert metrics["savings"]["actual_cost_usd"] == 0.20
        assert metrics["savings"]["savings_pct"] > 90.0


class TestE2EEdgeCases:
    """Test edge cases in end-to-end flow."""

    def test_packet_with_missing_complexity(self, temp_state_dir, mock_project_config):
        """Test packet without complexity field."""
        from prefect_grace.platform.executor_registry import select_executor_for_packet

        packet = {
            "packet_id": "NO-COMPLEXITY-001",
            "role": "coder",
            # No complexity field
            "source_hash": "no_complexity_hash",
        }

        # Should still select an executor (first by priority)
        selection = select_executor_for_packet(
            project=mock_project_config,
            packet=packet,
            history=[],
        )

        assert selection.ok is True
        assert selection.selected is not None

    def test_packet_with_unknown_complexity(self, temp_state_dir, mock_project_config):
        """Test packet with unknown complexity value."""
        from prefect_grace.platform.executor_registry import select_executor_for_packet

        packet = {
            "packet_id": "UNKNOWN-COMPLEXITY-001",
            "role": "coder",
            "complexity": "ultra-mega-complex",  # Not in any executor's metadata
            "source_hash": "unknown_complexity_hash",
        }

        # Should still select an executor (fallback to first by priority)
        selection = select_executor_for_packet(
            project=mock_project_config,
            packet=packet,
            history=[],
        )

        assert selection.ok is True
        assert selection.selected is not None

    def test_all_executors_disabled(self, temp_state_dir, mock_project_config):
        """Test when all executors are disabled."""
        from prefect_grace.platform.executor_registry import select_executor_for_packet

        # Disable all executors
        for executor in mock_project_config.agent_executor.executors:
            executor["enabled"] = False

        packet = {
            "packet_id": "NO-EXECUTOR-001",
            "role": "coder",
            "complexity": "simple",
        }

        selection = select_executor_for_packet(
            project=mock_project_config,
            packet=packet,
            history=[],
        )

        assert selection.ok is False
        assert selection.reason == "no_executor_available"

    def test_packet_with_scope_blocked(self, temp_state_dir, mock_project_config):
        """Test packet that gets scope_blocked (not a failure)."""
        from prefect_grace.platform.executor_registry import select_executor_for_packet, record_executor_attempt, _is_executor_failure

        packet = {
            "packet_id": "SCOPE-BLOCKED-001",
            "role": "coder",
            "complexity": "simple",
            "source_hash": "scope_blocked_hash",
        }

        selection = select_executor_for_packet(
            project=mock_project_config,
            packet=packet,
            history=[],
        )

        # Record scope_blocked result
        result = {
            "returncode": 0,
            "domain_status": "scope_blocked",
            "source_hash": "scope_blocked_hash",
        }

        record = record_executor_attempt(
            state_root=temp_state_dir,
            packet_id=packet["packet_id"],
            role=packet["role"],
            executor_id=selection.selected.executor_id,
            result=result,
            attempt=1,
        )

        # scope_blocked should NOT be considered a failure
        assert _is_executor_failure(record) is False
