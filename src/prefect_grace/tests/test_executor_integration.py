"""
Integration tests for executor selection and rotation.

Tests the complete executor selection flow including:
- Complexity-based routing
- Failure detection and rotation
- History tracking
- Edge cases
"""
import pytest
from prefect_grace.platform.executor_registry import (
    ExecutorSpec,
    ExecutorSelection,
    load_executor_specs,
    select_executor_for_packet,
    record_executor_attempt,
    _is_executor_failure,
    _count_consecutive_failures,
    _filter_history_for_packet_role,
)
from prefect_grace.platform.state_store import ExecutorHistoryStore


class TestExecutorSpecLoading:
    """Test loading executor specs from project config."""

    def test_load_executor_specs_from_new_format(self, mock_project_config):
        """Test loading executors from new executors list format."""
        specs = load_executor_specs(mock_project_config)

        assert len(specs) == 3
        assert specs[0].executor_id == "coder-cheap"
        assert specs[0].model == "gemini-3.5-flash"
        assert specs[0].priority == 10
        assert specs[0].max_consecutive_failures == 2
        assert "simple" in specs[0].metadata.get("complexity", [])

    def test_load_executor_specs_backward_compatibility(self):
        """Test backward compatibility with old config format."""
        class OldAgentExecutor:
            def __init__(self):
                self.default = "codex-cli"
                self.command = "codex-cli execute"
                self.executors = None

        class OldProject:
            def __init__(self):
                self.agent_executor = OldAgentExecutor()

        project = OldProject()
        specs = load_executor_specs(project)

        assert len(specs) == 1
        assert specs[0].executor_id == "codex-cli"
        assert specs[0].kind == "codex"
        assert specs[0].command == "codex-cli execute"

    def test_load_executor_specs_validates_required_fields(self):
        """Test that invalid specs raise ValueError."""
        class BadAgentExecutor:
            def __init__(self):
                self.executors = [
                    {
                        "executor_id": "test",
                        # Missing 'kind' and 'command'
                    }
                ]

        class BadProject:
            def __init__(self):
                self.agent_executor = BadAgentExecutor()

        project = BadProject()
        with pytest.raises(ValueError, match="invalid kind"):
            load_executor_specs(project)


class TestComplexityRouting:
    """Test complexity-based executor routing."""

    def test_simple_packet_routes_to_cheap_executor(self, mock_project_config, sample_packets):
        """Simple packets should use coder-cheap."""
        simple_packet = sample_packets[0]  # complexity: simple

        selection = select_executor_for_packet(
            project=mock_project_config,
            packet=simple_packet,
            history=[],
        )

        assert selection.ok is True
        assert selection.selected.executor_id == "coder-cheap"
        assert selection.selected.model == "gemini-3.5-flash"
        assert selection.reason == "selected"

    def test_medium_packet_routes_to_standard_executor(self, mock_project_config, sample_packets):
        """Medium packets should use coder-standard."""
        medium_packet = sample_packets[1]  # complexity: medium

        selection = select_executor_for_packet(
            project=mock_project_config,
            packet=medium_packet,
            history=[],
        )

        assert selection.ok is True
        assert selection.selected.executor_id == "coder-standard"
        assert selection.selected.model == "gemini-3.1-pro"

    def test_complex_packet_routes_to_premium_executor(self, mock_project_config, sample_packets):
        """Complex packets should use coder-premium."""
        complex_packet = sample_packets[2]  # complexity: complex

        selection = select_executor_for_packet(
            project=mock_project_config,
            packet=complex_packet,
            history=[],
        )

        assert selection.ok is True
        assert selection.selected.executor_id == "coder-premium"
        assert selection.selected.model == "claude-opus-4"


class TestExecutorRotation:
    """Test executor rotation after failures."""

    def test_rotation_after_two_failures(self, mock_project_config):
        """After 2 consecutive failures, should rotate to next executor."""
        # Use a packet without complexity to allow all executors
        packet = {
            "packet_id": "SIMPLE-001",
            "role": "coder",
            "source_hash": "hash001",
        }

        # Create history with 2 failures on coder-cheap
        history = [
            {
                "packet_id": "SIMPLE-001",
                "role": "coder",
                "executor_id": "coder-cheap",
                "returncode": 1,
                "domain_status": "agent_failed",
                "recorded_at": "2026-05-30T10:00:00Z",
                "source_hash": "hash001",
            },
            {
                "packet_id": "SIMPLE-001",
                "role": "coder",
                "executor_id": "coder-cheap",
                "returncode": 1,
                "domain_status": "agent_failed",
                "recorded_at": "2026-05-30T10:05:00Z",
                "source_hash": "hash001",
            },
        ]

        selection = select_executor_for_packet(
            project=mock_project_config,
            packet=packet,
            history=history,
        )

        # Should rotate to next executor (coder-standard)
        assert selection.ok is True
        assert selection.selected.executor_id == "coder-standard"

    def test_all_executors_exhausted(self, mock_project_config, sample_packets):
        """When all executors fail, should return ok=False."""
        packet = sample_packets[0]

        # Create history with 2 failures for each executor
        history = []
        for executor_id in ["coder-cheap", "coder-standard", "coder-premium"]:
            for i in range(2):
                history.append({
                    "packet_id": "SIMPLE-001",
                    "role": "coder",
                    "executor_id": executor_id,
                    "returncode": 1,
                    "domain_status": "agent_failed",
                    "recorded_at": f"2026-05-30T10:{i:02d}:00Z",
                    "source_hash": "hash001",
                })

        selection = select_executor_for_packet(
            project=mock_project_config,
            packet=packet,
            history=history,
        )

        assert selection.ok is False
        assert selection.reason == "all_executors_failed"
        assert len(selection.warnings) > 0

    def test_rotation_respects_priority_order(self, mock_project_config):
        """Rotation should try executors in priority order."""
        # Use packet without complexity to allow all executors
        packet = {
            "packet_id": "TEST-001",
            "role": "coder",
            "source_hash": "hash001",
        }

        # Fail the first two executors
        history = []
        for executor_id in ["coder-cheap", "coder-standard"]:
            for i in range(2):
                history.append({
                    "packet_id": "TEST-001",
                    "role": "coder",
                    "executor_id": executor_id,
                    "returncode": 1,
                    "domain_status": "agent_failed",
                    "recorded_at": f"2026-05-30T10:{i:02d}:00Z",
                    "source_hash": "hash001",
                })

        selection = select_executor_for_packet(
            project=mock_project_config,
            packet=packet,
            history=history,
        )

        # Should select coder-premium (priority 30)
        assert selection.ok is True
        assert selection.selected.executor_id == "coder-premium"


class TestFailureDetection:
    """Test failure detection logic."""

    def test_is_executor_failure_returncode(self):
        """Non-zero returncode is a failure."""
        record = {"returncode": 1}
        assert _is_executor_failure(record) is True

    def test_is_executor_failure_agent_failed(self):
        """agent_failed domain status is a failure."""
        record = {"domain_status": "agent_failed", "returncode": 0}
        assert _is_executor_failure(record) is True

    def test_is_executor_failure_timeout(self):
        """Timeout termination is a failure."""
        record = {"termination_reason": "timeout", "returncode": 0}
        assert _is_executor_failure(record) is True

    def test_is_executor_failure_scope_blocked_not_failure(self):
        """scope_blocked is NOT a failure."""
        record = {"domain_status": "scope_blocked", "returncode": 0}
        assert _is_executor_failure(record) is False

    def test_is_executor_failure_skipped_not_failure(self):
        """Skipped status is NOT a failure."""
        record = {"status": "skipped", "returncode": 1}
        assert _is_executor_failure(record) is False

    def test_is_executor_failure_success(self):
        """Successful execution is not a failure."""
        record = {"returncode": 0, "domain_status": "accepted"}
        assert _is_executor_failure(record) is False


class TestConsecutiveFailureCounting:
    """Test consecutive failure counting logic."""

    def test_count_consecutive_failures_basic(self):
        """Count consecutive failures for same executor."""
        history = [
            {
                "packet_id": "TEST-001",
                "role": "coder",
                "executor_id": "coder-cheap",
                "returncode": 1,
                "recorded_at": "2026-05-30T10:02:00Z",
            },
            {
                "packet_id": "TEST-001",
                "role": "coder",
                "executor_id": "coder-cheap",
                "returncode": 1,
                "recorded_at": "2026-05-30T10:01:00Z",
            },
        ]

        count = _count_consecutive_failures(history, "coder-cheap", None)
        assert count == 2

    def test_count_consecutive_failures_stops_at_success(self):
        """Stop counting at first success."""
        history = [
            {
                "packet_id": "TEST-001",
                "role": "coder",
                "executor_id": "coder-cheap",
                "returncode": 1,
                "recorded_at": "2026-05-30T10:03:00Z",
            },
            {
                "packet_id": "TEST-001",
                "role": "coder",
                "executor_id": "coder-cheap",
                "returncode": 0,
                "recorded_at": "2026-05-30T10:02:00Z",
            },
            {
                "packet_id": "TEST-001",
                "role": "coder",
                "executor_id": "coder-cheap",
                "returncode": 1,
                "recorded_at": "2026-05-30T10:01:00Z",
            },
        ]

        count = _count_consecutive_failures(history, "coder-cheap", None)
        assert count == 1  # Only the most recent failure

    def test_count_consecutive_failures_filters_by_source_hash(self):
        """Only count failures with matching source_hash."""
        history = [
            {
                "packet_id": "TEST-001",
                "role": "coder",
                "executor_id": "coder-cheap",
                "returncode": 1,
                "source_hash": "new_hash",
                "recorded_at": "2026-05-30T10:02:00Z",
            },
            {
                "packet_id": "TEST-001",
                "role": "coder",
                "executor_id": "coder-cheap",
                "returncode": 1,
                "source_hash": "old_hash",
                "recorded_at": "2026-05-30T10:01:00Z",
            },
        ]

        count = _count_consecutive_failures(history, "coder-cheap", "new_hash")
        assert count == 1  # Only count the one with matching hash

    def test_count_consecutive_failures_ignores_scope_blocked(self):
        """scope_blocked records don't affect the count."""
        history = [
            {
                "packet_id": "TEST-001",
                "role": "coder",
                "executor_id": "coder-cheap",
                "returncode": 1,
                "recorded_at": "2026-05-30T10:03:00Z",
            },
            {
                "packet_id": "TEST-001",
                "role": "coder",
                "executor_id": "coder-cheap",
                "domain_status": "scope_blocked",
                "recorded_at": "2026-05-30T10:02:00Z",
            },
            {
                "packet_id": "TEST-001",
                "role": "coder",
                "executor_id": "coder-cheap",
                "returncode": 1,
                "recorded_at": "2026-05-30T10:01:00Z",
            },
        ]

        count = _count_consecutive_failures(history, "coder-cheap", None)
        assert count == 2  # scope_blocked is ignored


class TestRequestedExecutor:
    """Test explicit executor requests."""

    def test_requested_executor_selected(self, mock_project_config):
        """Explicitly requested executor should be selected."""
        packet = {
            "packet_id": "TEST-001",
            "role": "coder",
            "complexity": "simple",
        }

        selection = select_executor_for_packet(
            project=mock_project_config,
            packet=packet,
            history=[],
            requested_executor="coder-premium",
        )

        assert selection.ok is True
        assert selection.selected.executor_id == "coder-premium"
        assert selection.reason == "requested"

    def test_requested_executor_disabled(self, mock_project_config):
        """Requesting a disabled executor should fail."""
        # Modify config to disable an executor
        mock_project_config.agent_executor.executors[0]["enabled"] = False

        packet = {
            "packet_id": "TEST-001",
            "role": "coder",
        }

        selection = select_executor_for_packet(
            project=mock_project_config,
            packet=packet,
            history=[],
            requested_executor="coder-cheap",
        )

        assert selection.ok is False
        assert "disabled" in selection.reason

    def test_requested_executor_not_found(self, mock_project_config):
        """Requesting a non-existent executor should fail."""
        packet = {
            "packet_id": "TEST-001",
            "role": "coder",
        }

        selection = select_executor_for_packet(
            project=mock_project_config,
            packet=packet,
            history=[],
            requested_executor="nonexistent",
        )

        assert selection.ok is False
        assert "not_found" in selection.reason


class TestHistoryFiltering:
    """Test history filtering logic."""

    def test_filter_history_for_packet_role(self):
        """Filter history to specific packet and role."""
        history = [
            {"packet_id": "P1", "role": "coder", "recorded_at": "2026-05-30T10:00:00Z"},
            {"packet_id": "P2", "role": "coder", "recorded_at": "2026-05-30T10:01:00Z"},
            {"packet_id": "P1", "role": "verifier", "recorded_at": "2026-05-30T10:02:00Z"},
            {"packet_id": "P1", "role": "coder", "recorded_at": "2026-05-30T10:03:00Z"},
        ]

        filtered = _filter_history_for_packet_role(history, "P1", "coder")

        assert len(filtered) == 2
        # Should be sorted newest first
        assert filtered[0]["recorded_at"] == "2026-05-30T10:03:00Z"
        assert filtered[1]["recorded_at"] == "2026-05-30T10:00:00Z"


class TestRecordExecutorAttempt:
    """Test recording executor attempts."""

    def test_record_executor_attempt(self, temp_state_dir):
        """Test recording an execution attempt."""
        result = {
            "feature_id": "FEAT-001",
            "wave_id": "W01",
            "source_hash": "abc123",
            "status": "completed",
            "returncode": 0,
            "domain_status": "accepted",
            "executor_kind": "codex",
            "selection_reason": "selected",
        }

        record = record_executor_attempt(
            state_root=temp_state_dir,
            packet_id="PACKET-001",
            role="coder",
            executor_id="coder-cheap",
            result=result,
            attempt=1,
        )

        assert record["packet_id"] == "PACKET-001"
        assert record["role"] == "coder"
        assert record["executor_id"] == "coder-cheap"
        assert record["returncode"] == 0
        assert record["attempt"] == 1
        assert "recorded_at" in record

        # Verify it was saved
        store = ExecutorHistoryStore(temp_state_dir)
        history = store.list_executions()
        assert len(history) == 1
        assert history[0]["packet_id"] == "PACKET-001"
