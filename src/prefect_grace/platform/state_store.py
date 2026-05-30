# ############################################################################
# AI_HEADER: state_store
# ROLE: Stores and manages run results, execution history, and packet states.
# ############################################################################

# START_MODULE_CONTRACT
# purpose: File-backed state persistence for features, packets, and executions.
# inputs: state_root directory, data records.
# returns: state queries and storage updates.
# side_effects: Reads/writes YAML files to the local file system.
# emitted_logs: none.
# error_behavior: Raises ValueError if identifiers are missing.
# END_MODULE_CONTRACT

# START_MODULE_MAP
# mapping:
#   - class: PacketRegistryStore
#   - class: RunStore
#   - class: ExecutorHistoryStore
# END_MODULE_MAP

from __future__ import annotations

import uuid
from pathlib import Path
from typing import Any

import yaml

#START_BLOCK_PACKETS_STORE
class PacketRegistryStore:
    # START_FUNCTION_CONTRACT
    # name: load_packet
    # purpose: Load a packet's saved record from registry store.
    # inputs:
    #   packet_id: string identifier.
    # returns: dict containing packet data, or None.
    # side_effects: Reads registry file from disk.
    # emitted_logs: none.
    # error_behavior: none.
    # END_FUNCTION_CONTRACT
    def __init__(self, state_root: Path | str):
        self.file_path = Path(state_root) / "packet_registry.yaml"

    def _load_all(self) -> dict[str, dict[str, Any]]:
        if not self.file_path.exists():
            return {}
        try:
            with open(self.file_path, "r", encoding="utf-8") as f:
                return yaml.safe_load(f) or {}
        except Exception:
            return {}

    def _save_all(self, data: dict[str, dict[str, Any]]) -> None:
        self.file_path.parent.mkdir(parents=True, exist_ok=True)
        with open(self.file_path, "w", encoding="utf-8") as f:
            yaml.safe_dump(data, f, default_flow_style=False, allow_unicode=True)

    def load_packet(self, packet_id: str) -> dict[str, Any] | None:
        data = self._load_all()
        return data.get(packet_id)

    # START_FUNCTION_CONTRACT
    # name: upsert_packet
    # purpose: Saves or updates a packet record in registry store.
    # inputs:
    #   packet: dict containing packet data.
    # returns: none.
    # side_effects: Writes registry file to disk.
    # emitted_logs: none.
    # error_behavior: Raises ValueError if packet_id is missing.
    # END_FUNCTION_CONTRACT
    def upsert_packet(self, packet: dict[str, Any]) -> None:
        packet_id = packet.get("packet_id")
        if not packet_id:
            raise ValueError("packet_id is required")
        data = self._load_all()
        existing = data.get(packet_id, {})
        merged = {**existing, **packet}
        data[packet_id] = merged
        self._save_all(data)

    # START_FUNCTION_CONTRACT
    # name: update_resume_state
    # purpose: Updates resume tracking fields for a packet.
    # inputs:
    #   packet_id: string identifier.
    #   **kwargs: resume state fields to update.
    # returns: none.
    # side_effects: Writes registry file to disk.
    # emitted_logs: none.
    # error_behavior: Raises ValueError if packet not found in registry.
    # END_FUNCTION_CONTRACT
    def update_resume_state(self, packet_id: str, **kwargs: Any) -> None:
        data = self._load_all()
        if packet_id not in data:
            raise ValueError(f"Packet {packet_id} not found in registry")
        data[packet_id].update(kwargs)
        self._save_all(data)

    # START_FUNCTION_CONTRACT
    # name: list_packets
    # purpose: Lists all registered packets in the store.
    # inputs:
    #   project_key: string identifier (optional).
    # returns: list of registered packets dicts.
    # side_effects: Reads registry file from disk.
    # emitted_logs: none.
    # error_behavior: none.
    # END_FUNCTION_CONTRACT
    def list_packets(self, project_key: str | None = None) -> list[dict[str, Any]]:
        data = self._load_all()
        return list(data.values())

#END_BLOCK_PACKETS_STORE
#START_BLOCK_RUNS_STORE
class RunStore:
    def __init__(self, state_root: Path | str):
        self.file_path = Path(state_root) / "runs.yaml"

    def _load_all(self) -> dict[str, dict[str, Any]]:
        if not self.file_path.exists():
            return {}
        try:
            with open(self.file_path, "r", encoding="utf-8") as f:
                return yaml.safe_load(f) or {}
        except Exception:
            return {}

    def _save_all(self, data: dict[str, dict[str, Any]]) -> None:
        self.file_path.parent.mkdir(parents=True, exist_ok=True)
        with open(self.file_path, "w", encoding="utf-8") as f:
            yaml.safe_dump(data, f, default_flow_style=False, allow_unicode=True)

    # START_FUNCTION_CONTRACT
    # name: create_run
    # purpose: Creates a new feature run record in the store.
    # inputs:
    #   record: dict of run info.
    # returns: string run_id.
    # side_effects: Writes runs file to disk.
    # emitted_logs: none.
    # error_behavior: none.
    # END_FUNCTION_CONTRACT
    def create_run(self, record: dict[str, Any]) -> str:
        run_id = record.get("run_id") or str(uuid.uuid4())
        data = self._load_all()
        record_copy = dict(record)
        record_copy["run_id"] = run_id
        data[run_id] = record_copy
        self._save_all(data)
        return run_id

    # START_FUNCTION_CONTRACT
    # name: update_run
    # purpose: Updates an existing run record with patch dict details.
    # inputs:
    #   run_id: string run identifier.
    #   patch: dict of patches to merge.
    # returns: none.
    # side_effects: Writes runs file to disk.
    # emitted_logs: none.
    # error_behavior: Raises ValueError if run_id is missing or doesn't exist.
    # END_FUNCTION_CONTRACT
    def update_run(self, run_id: str, patch: dict[str, Any]) -> None:
        data = self._load_all()
        if run_id not in data:
            raise ValueError(f"Run {run_id} not found")
        data[run_id].update(patch)
        self._save_all(data)

    # START_FUNCTION_CONTRACT
    # name: get_run
    # purpose: Get a run's record from the store.
    # inputs:
    #   run_id: string run identifier.
    # returns: dict containing run data, or None.
    # side_effects: Reads runs file from disk.
    # emitted_logs: none.
    # error_behavior: none.
    # END_FUNCTION_CONTRACT
    def get_run(self, run_id: str) -> dict[str, Any] | None:
        return self._load_all().get(run_id)

    # START_FUNCTION_CONTRACT
    # name: list_runs
    # purpose: List all stored run records.
    # inputs: none.
    # returns: list of run record dictionaries.
    # side_effects: Reads runs file from disk.
    # emitted_logs: none.
    # error_behavior: none.
    # END_FUNCTION_CONTRACT
    def list_runs(self) -> list[dict[str, Any]]:
        return list(self._load_all().values())

#END_BLOCK_RUNS_STORE
#START_BLOCK_HISTORY_STORE
class ExecutorHistoryStore:
    def __init__(self, state_root: Path | str):
        self.file_path = Path(state_root) / "executor_history.yaml"

    def _load_all(self) -> list[dict[str, Any]]:
        if not self.file_path.exists():
            return []
        try:
            with open(self.file_path, "r", encoding="utf-8") as f:
                return yaml.safe_load(f) or []
        except Exception:
            return []

    def _save_all(self, data: list[dict[str, Any]]) -> None:
        self.file_path.parent.mkdir(parents=True, exist_ok=True)
        with open(self.file_path, "w", encoding="utf-8") as f:
            yaml.safe_dump(data, f, default_flow_style=False, allow_unicode=True)

    # START_FUNCTION_CONTRACT
    # name: append_execution
    # purpose: Appends an execution entry into history logs.
    # inputs:
    #   record: dict of execution details.
    # returns: none.
    # side_effects: Writes executor_history file to disk.
    # emitted_logs: none.
    # error_behavior: none.
    # END_FUNCTION_CONTRACT
    def append_execution(self, record: dict[str, Any]) -> None:
        data = self._load_all()
        data.append(record)
        self._save_all(data)

    # START_FUNCTION_CONTRACT
    # name: list_executions
    # purpose: List all logged executions.
    # inputs: none.
    # returns: list of execution dict records.
    # side_effects: Reads executor_history file from disk.
    # emitted_logs: none.
    # error_behavior: none.
    # END_FUNCTION_CONTRACT
    def list_executions(self) -> list[dict[str, Any]]:
        return self._load_all()

#END_BLOCK_HISTORY_STORE
