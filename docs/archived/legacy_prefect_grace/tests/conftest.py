"""
Pytest configuration and fixtures for prefect_grace tests.
"""
import json
import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, List

import pytest
import yaml


@pytest.fixture
def temp_state_dir(tmp_path):
    """Create a temporary state directory structure."""
    state_root = tmp_path / "state"
    state_root.mkdir()
    (state_root / "runs").mkdir()
    return state_root


@pytest.fixture
def mock_executor_history():
    """Mock execution history with various scenarios."""
    return [
        {
            "packet_id": "PACKET-001",
            "role": "coder",
            "executor_id": "coder-cheap",
            "status": "completed",
            "returncode": 0,
            "domain_status": "accepted",
            "recorded_at": "2026-05-30T10:00:00Z",
            "source_hash": "abc123",
        },
        {
            "packet_id": "PACKET-002",
            "role": "coder",
            "executor_id": "coder-cheap",
            "status": "failed",
            "returncode": 1,
            "domain_status": "agent_failed",
            "recorded_at": "2026-05-30T10:05:00Z",
            "source_hash": "def456",
        },
        {
            "packet_id": "PACKET-002",
            "role": "coder",
            "executor_id": "coder-cheap",
            "status": "failed",
            "returncode": 1,
            "domain_status": "agent_failed",
            "recorded_at": "2026-05-30T10:10:00Z",
            "source_hash": "def456",
        },
        {
            "packet_id": "PACKET-002",
            "role": "coder",
            "executor_id": "coder-standard",
            "status": "completed",
            "returncode": 0,
            "domain_status": "accepted",
            "recorded_at": "2026-05-30T10:15:00Z",
            "source_hash": "def456",
        },
    ]


@pytest.fixture
def mock_execution_logs():
    """Mock execution logs for health checks and verification."""
    now = datetime.now(timezone.utc)
    return [
        {
            "event": "PACKET_START",
            "packet_id": "PACKET-001",
            "executor_id": "coder-cheap",
            "timestamp": (now - timedelta(minutes=30)).isoformat(),
        },
        {
            "event": "PACKET_END",
            "packet_id": "PACKET-001",
            "executor_id": "coder-cheap",
            "status": "success",
            "timestamp": (now - timedelta(minutes=25)).isoformat(),
        },
        {
            "event": "EXECUTION_METRICS",
            "packet_id": "PACKET-001",
            "executor_id": "coder-cheap",
            "model": "gemini-3.5-flash",
            "total_tokens": 50000,
            "cost_usd": 0.20,
            "duration_seconds": 120,
            "timestamp": (now - timedelta(minutes=25)).isoformat(),
        },
        {
            "event": "PACKET_START",
            "packet_id": "PACKET-002",
            "executor_id": "coder-cheap",
            "timestamp": (now - timedelta(minutes=20)).isoformat(),
        },
        {
            "event": "PACKET_END",
            "packet_id": "PACKET-002",
            "executor_id": "coder-cheap",
            "status": "failed",
            "timestamp": (now - timedelta(minutes=18)).isoformat(),
        },
        {
            "event": "PACKET_START",
            "packet_id": "PACKET-002",
            "executor_id": "coder-cheap",
            "timestamp": (now - timedelta(minutes=15)).isoformat(),
        },
        {
            "event": "PACKET_END",
            "packet_id": "PACKET-002",
            "executor_id": "coder-cheap",
            "status": "failed",
            "timestamp": (now - timedelta(minutes=13)).isoformat(),
        },
        {
            "event": "PACKET_START",
            "packet_id": "PACKET-002",
            "executor_id": "coder-standard",
            "timestamp": (now - timedelta(minutes=10)).isoformat(),
        },
        {
            "event": "PACKET_END",
            "packet_id": "PACKET-002",
            "executor_id": "coder-standard",
            "status": "success",
            "timestamp": (now - timedelta(minutes=5)).isoformat(),
        },
        {
            "event": "EXECUTION_METRICS",
            "packet_id": "PACKET-002",
            "executor_id": "coder-standard",
            "model": "gemini-3.1-pro",
            "total_tokens": 75000,
            "cost_usd": 1.50,
            "duration_seconds": 180,
            "timestamp": (now - timedelta(minutes=5)).isoformat(),
        },
    ]


@pytest.fixture
def mock_codex_output_gemini():
    """Mock Codex output with Gemini token format."""
    return """
=== Execution Complete ===
Status: success
Total tokens: 50000
Input tokens: 30000
Output tokens: 20000
Model: gemini-3.5-flash
"""


@pytest.fixture
def mock_codex_output_claude():
    """Mock Codex output with Claude token format."""
    return """
=== Execution Complete ===
Status: success
Usage: {"input_tokens": 40000, "output_tokens": 25000}
Model: claude-sonnet-4
"""


@pytest.fixture
def mock_codex_output_openai():
    """Mock Codex output with OpenAI token format."""
    return """
=== Execution Complete ===
Status: success
Completion tokens: 15000
Prompt tokens: 35000
Model: gpt-4
"""


@pytest.fixture
def mock_agent_profiles():
    """Mock agent profiles configuration."""
    return {
        "executors": [
            {
                "executor_id": "coder-cheap",
                "kind": "codex",
                "command": "codex-cli",
                "model": "gemini-3.5-flash",
                "enabled": True,
                "priority": 10,
                "max_consecutive_failures": 2,
                "roles": ["coder"],
                "metadata": {"complexity": ["simple"]},
            },
            {
                "executor_id": "coder-standard",
                "kind": "codex",
                "command": "codex-cli",
                "model": "gemini-3.1-pro",
                "enabled": True,
                "priority": 20,
                "max_consecutive_failures": 2,
                "roles": ["coder"],
                "metadata": {"complexity": ["medium"]},
            },
            {
                "executor_id": "coder-premium",
                "kind": "codex",
                "command": "codex-cli",
                "model": "claude-opus-4",
                "enabled": True,
                "priority": 30,
                "max_consecutive_failures": 2,
                "roles": ["coder"],
                "metadata": {"complexity": ["complex"]},
            },
        ]
    }


@pytest.fixture
def mock_project_config(mock_agent_profiles):
    """Mock project configuration."""
    class MockAgentExecutor:
        def __init__(self, profiles):
            self.executors = profiles["executors"]
            self.default = "coder-cheap"
            self.command = "codex-cli"

    class MockProject:
        def __init__(self, profiles):
            self.agent_executor = MockAgentExecutor(profiles)
            self.project_key = "test-project"

    return MockProject(mock_agent_profiles)


@pytest.fixture
def sample_packets():
    """Sample packets with different complexities."""
    return [
        {
            "packet_id": "SIMPLE-001",
            "role": "coder",
            "complexity": "simple",
            "source_hash": "hash001",
        },
        {
            "packet_id": "MEDIUM-001",
            "role": "coder",
            "complexity": "medium",
            "source_hash": "hash002",
        },
        {
            "packet_id": "COMPLEX-001",
            "role": "coder",
            "complexity": "complex",
            "source_hash": "hash003",
        },
    ]


@pytest.fixture
def execution_trace_file(temp_state_dir, mock_execution_logs):
    """Create a sample execution trace file."""
    run_dir = temp_state_dir / "runs" / "run-001"
    run_dir.mkdir(parents=True)
    trace_file = run_dir / "execution_trace.jsonl"

    with open(trace_file, "w") as f:
        for log in mock_execution_logs:
            f.write(json.dumps(log) + "\n")

    return trace_file


@pytest.fixture
def executor_history_store(temp_state_dir, mock_executor_history):
    """Create ExecutorHistoryStore with sample data."""
    from prefect_grace.platform.state_store import ExecutorHistoryStore

    store = ExecutorHistoryStore(temp_state_dir)
    for record in mock_executor_history:
        store.append_execution(record)

    return store


@pytest.fixture
def stuck_packet_logs():
    """Mock logs with stuck packets for deadlock detection."""
    now = datetime.now(timezone.utc)
    return [
        {
            "event": "PACKET_START",
            "packet_id": "STUCK-001",
            "executor_id": "coder-cheap",
            "timestamp": (now - timedelta(hours=2)).isoformat(),
        },
        # No PACKET_END event - stuck!
        {
            "event": "PACKET_START",
            "packet_id": "NORMAL-001",
            "executor_id": "coder-cheap",
            "timestamp": (now - timedelta(minutes=10)).isoformat(),
        },
        {
            "event": "PACKET_END",
            "packet_id": "NORMAL-001",
            "executor_id": "coder-cheap",
            "status": "success",
            "timestamp": (now - timedelta(minutes=5)).isoformat(),
        },
    ]


@pytest.fixture
def rotation_failure_logs():
    """Mock logs showing executor rotation failures."""
    now = datetime.now(timezone.utc)
    logs = []

    # Packet fails 5 times on same executor without rotation
    for i in range(5):
        logs.append({
            "event": "PACKET_START",
            "packet_id": "ROTATION-FAIL-001",
            "executor_id": "coder-cheap",
            "timestamp": (now - timedelta(minutes=50 - i * 10)).isoformat(),
        })
        logs.append({
            "event": "PACKET_END",
            "packet_id": "ROTATION-FAIL-001",
            "executor_id": "coder-cheap",
            "status": "failed",
            "timestamp": (now - timedelta(minutes=48 - i * 10)).isoformat(),
        })

    return logs
