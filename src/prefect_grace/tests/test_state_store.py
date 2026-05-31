"""
Tests for platform.state_store module.

Tests PacketRegistryStore, RunStore, and ExecutorHistoryStore with
concurrent access scenarios.
"""

import multiprocessing
import uuid
from pathlib import Path

import pytest

from prefect_grace.platform.state_store import (
    PacketRegistryStore,
    RunStore,
    ExecutorHistoryStore,
)


class TestPacketRegistryStore:
    """Tests for PacketRegistryStore."""

    def test_load_packet_nonexistent(self, tmp_path):
        """Test loading a packet that doesn't exist returns None."""
        store = PacketRegistryStore(tmp_path)
        result = store.load_packet("nonexistent")
        assert result is None

    def test_upsert_packet_creates_new(self, tmp_path):
        """Test upserting a new packet."""
        store = PacketRegistryStore(tmp_path)
        packet = {
            "packet_id": "test-packet-1",
            "name": "Test Packet",
            "status": "pending",
        }

        store.upsert_packet(packet)

        loaded = store.load_packet("test-packet-1")
        assert loaded == packet

    def test_upsert_packet_merges_existing(self, tmp_path):
        """Test upserting merges with existing packet data."""
        store = PacketRegistryStore(tmp_path)

        # Insert initial packet
        initial = {
            "packet_id": "test-packet-1",
            "name": "Test Packet",
            "status": "pending",
        }
        store.upsert_packet(initial)

        # Update with partial data
        update = {
            "packet_id": "test-packet-1",
            "status": "running",
            "progress": 50,
        }
        store.upsert_packet(update)

        # Should merge both
        loaded = store.load_packet("test-packet-1")
        assert loaded["name"] == "Test Packet"
        assert loaded["status"] == "running"
        assert loaded["progress"] == 50

    def test_upsert_packet_requires_packet_id(self, tmp_path):
        """Test upserting without packet_id raises ValueError."""
        store = PacketRegistryStore(tmp_path)
        packet = {"name": "Test Packet"}

        with pytest.raises(ValueError, match="packet_id is required"):
            store.upsert_packet(packet)

    def test_update_resume_state(self, tmp_path):
        """Test updating resume state fields."""
        store = PacketRegistryStore(tmp_path)

        # Insert initial packet
        packet = {
            "packet_id": "test-packet-1",
            "name": "Test Packet",
        }
        store.upsert_packet(packet)

        # Update resume state
        store.update_resume_state(
            "test-packet-1",
            resume_from="step-3",
            last_checkpoint="2024-01-01T00:00:00Z"
        )

        loaded = store.load_packet("test-packet-1")
        assert loaded["resume_from"] == "step-3"
        assert loaded["last_checkpoint"] == "2024-01-01T00:00:00Z"

    def test_update_resume_state_nonexistent_raises(self, tmp_path):
        """Test updating resume state for nonexistent packet raises ValueError."""
        store = PacketRegistryStore(tmp_path)

        with pytest.raises(ValueError, match="not found in registry"):
            store.update_resume_state("nonexistent", resume_from="step-1")

    def test_list_packets(self, tmp_path):
        """Test listing all packets."""
        store = PacketRegistryStore(tmp_path)

        # Insert multiple packets
        for i in range(3):
            store.upsert_packet({
                "packet_id": f"packet-{i}",
                "name": f"Packet {i}",
            })

        packets = store.list_packets()
        assert len(packets) == 3
        packet_ids = {p["packet_id"] for p in packets}
        assert packet_ids == {"packet-0", "packet-1", "packet-2"}

    def test_list_packets_empty(self, tmp_path):
        """Test listing packets when store is empty."""
        store = PacketRegistryStore(tmp_path)
        packets = store.list_packets()
        assert packets == []


def _concurrent_packet_worker(state_root, worker_id, num_packets):
    """Worker function for concurrent packet upserts."""
    store = PacketRegistryStore(state_root)
    for i in range(num_packets):
        packet = {
            "packet_id": f"worker-{worker_id}-packet-{i}",
            "worker_id": worker_id,
            "index": i,
        }
        store.upsert_packet(packet)


def test_packet_store_concurrent_upserts(tmp_path):
    """Test concurrent packet upserts don't lose data."""
    num_workers = 4
    packets_per_worker = 10

    # Spawn worker processes
    processes = []
    for worker_id in range(num_workers):
        p = multiprocessing.Process(
            target=_concurrent_packet_worker,
            args=(tmp_path, worker_id, packets_per_worker)
        )
        p.start()
        processes.append(p)

    # Wait for completion
    for p in processes:
        p.join()

    # Verify all packets were stored
    store = PacketRegistryStore(tmp_path)
    packets = store.list_packets()
    assert len(packets) == num_workers * packets_per_worker

    # Verify each worker's packets
    for worker_id in range(num_workers):
        worker_packets = [p for p in packets if p["worker_id"] == worker_id]
        assert len(worker_packets) == packets_per_worker


class TestRunStore:
    """Tests for RunStore."""

    def test_create_run_generates_id(self, tmp_path):
        """Test creating a run generates an ID if not provided."""
        store = RunStore(tmp_path)
        record = {"name": "Test Run", "status": "pending"}

        run_id = store.create_run(record)

        assert run_id is not None
        loaded = store.get_run(run_id)
        assert loaded["name"] == "Test Run"
        assert loaded["run_id"] == run_id

    def test_create_run_uses_provided_id(self, tmp_path):
        """Test creating a run uses provided ID."""
        store = RunStore(tmp_path)
        run_id = "custom-run-id"
        record = {"run_id": run_id, "name": "Test Run"}

        returned_id = store.create_run(record)

        assert returned_id == run_id
        loaded = store.get_run(run_id)
        assert loaded["run_id"] == run_id

    def test_update_run(self, tmp_path):
        """Test updating a run."""
        store = RunStore(tmp_path)
        run_id = store.create_run({"name": "Test Run", "status": "pending"})

        store.update_run(run_id, {"status": "running", "progress": 50})

        loaded = store.get_run(run_id)
        assert loaded["status"] == "running"
        assert loaded["progress"] == 50
        assert loaded["name"] == "Test Run"

    def test_update_run_nonexistent_raises(self, tmp_path):
        """Test updating nonexistent run raises ValueError."""
        store = RunStore(tmp_path)

        with pytest.raises(ValueError, match="not found"):
            store.update_run("nonexistent", {"status": "running"})

    def test_get_run_nonexistent(self, tmp_path):
        """Test getting nonexistent run returns None."""
        store = RunStore(tmp_path)
        result = store.get_run("nonexistent")
        assert result is None

    def test_list_runs(self, tmp_path):
        """Test listing all runs."""
        store = RunStore(tmp_path)

        # Create multiple runs
        run_ids = []
        for i in range(3):
            run_id = store.create_run({"name": f"Run {i}"})
            run_ids.append(run_id)

        runs = store.list_runs()
        assert len(runs) == 3
        loaded_ids = {r["run_id"] for r in runs}
        assert loaded_ids == set(run_ids)

    def test_list_runs_empty(self, tmp_path):
        """Test listing runs when store is empty."""
        store = RunStore(tmp_path)
        runs = store.list_runs()
        assert runs == []


def _concurrent_run_worker(state_root, worker_id, num_runs):
    """Worker function for concurrent run creation."""
    store = RunStore(state_root)
    for i in range(num_runs):
        store.create_run({
            "name": f"Worker {worker_id} Run {i}",
            "worker_id": worker_id,
        })


def test_run_store_concurrent_creates(tmp_path):
    """Test concurrent run creation doesn't lose data."""
    num_workers = 4
    runs_per_worker = 10

    # Spawn worker processes
    processes = []
    for worker_id in range(num_workers):
        p = multiprocessing.Process(
            target=_concurrent_run_worker,
            args=(tmp_path, worker_id, runs_per_worker)
        )
        p.start()
        processes.append(p)

    # Wait for completion
    for p in processes:
        p.join()

    # Verify all runs were stored
    store = RunStore(tmp_path)
    runs = store.list_runs()
    assert len(runs) == num_workers * runs_per_worker


class TestExecutorHistoryStore:
    """Tests for ExecutorHistoryStore."""

    def test_append_execution(self, tmp_path):
        """Test appending an execution record."""
        store = ExecutorHistoryStore(tmp_path)
        record = {
            "execution_id": "exec-1",
            "status": "success",
            "timestamp": "2024-01-01T00:00:00Z",
        }

        store.append_execution(record)

        executions = store.list_executions()
        assert len(executions) == 1
        assert executions[0] == record

    def test_append_multiple_executions(self, tmp_path):
        """Test appending multiple execution records."""
        store = ExecutorHistoryStore(tmp_path)

        for i in range(3):
            store.append_execution({
                "execution_id": f"exec-{i}",
                "index": i,
            })

        executions = store.list_executions()
        assert len(executions) == 3
        assert executions[0]["index"] == 0
        assert executions[2]["index"] == 2

    def test_list_executions_empty(self, tmp_path):
        """Test listing executions when store is empty."""
        store = ExecutorHistoryStore(tmp_path)
        executions = store.list_executions()
        assert executions == []


def _concurrent_execution_worker(state_root, worker_id, num_executions):
    """Worker function for concurrent execution appends."""
    store = ExecutorHistoryStore(state_root)
    for i in range(num_executions):
        store.append_execution({
            "execution_id": f"worker-{worker_id}-exec-{i}",
            "worker_id": worker_id,
            "index": i,
        })


def test_executor_history_concurrent_appends(tmp_path):
    """Test concurrent execution appends don't lose data."""
    num_workers = 4
    executions_per_worker = 10

    # Spawn worker processes
    processes = []
    for worker_id in range(num_workers):
        p = multiprocessing.Process(
            target=_concurrent_execution_worker,
            args=(tmp_path, worker_id, executions_per_worker)
        )
        p.start()
        processes.append(p)

    # Wait for completion
    for p in processes:
        p.join()

    # Verify all executions were stored
    store = ExecutorHistoryStore(tmp_path)
    executions = store.list_executions()
    assert len(executions) == num_workers * executions_per_worker

    # Verify each worker's executions
    for worker_id in range(num_workers):
        worker_execs = [e for e in executions if e["worker_id"] == worker_id]
        assert len(worker_execs) == executions_per_worker


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
