from __future__ import annotations

from pathlib import Path
from typing import Any

from prefect_grace.storage.file_backend import read_yaml, write_yaml, locked_update_yaml


def load_state(name: str, *, state_root: Path | str) -> dict[str, Any]:
    state_dir = Path(state_root)
    return read_yaml(state_dir / f"{name}.yaml")


def save_state(name: str, payload: dict[str, Any], *, state_root: Path | str) -> None:
    state_dir = Path(state_root)
    write_yaml(state_dir / f"{name}.yaml", payload)


def update_state(name: str, mutator: Any, *, state_root: Path | str) -> dict[str, Any]:
    state_dir = Path(state_root)
    return locked_update_yaml(state_dir / f"{name}.yaml", mutator)


def append_record(name: str, key: str, record: dict[str, Any], *, state_root: Path | str) -> dict[str, Any]:
    state_dir = Path(state_root)
    def mutator(payload: dict[str, Any]) -> dict[str, Any]:
        items = list(payload.get(key, []) or [])
        items.append(record)
        payload[key] = items
        return payload

    locked_update_yaml(state_dir / f"{name}.yaml", mutator)
    return record


def update_record(name: str, key: str, id_field: str, id_value: str, updates: dict[str, Any], *, state_root: Path | str) -> dict[str, Any]:
    state_dir = Path(state_root)
    updated_record: dict[str, Any] = {}

    def mutator(payload: dict[str, Any]) -> dict[str, Any]:
        nonlocal updated_record
        items = list(payload.get(key, []) or [])
        for index, item in enumerate(items):
            if str(item.get(id_field)) == id_value:
                updated_record = {**item, **updates}
                items[index] = updated_record
                payload[key] = items
                return payload
        raise KeyError(f"No {name}.{key} record with {id_field}={id_value}")

    locked_update_yaml(state_dir / f"{name}.yaml", mutator)
    return updated_record


def find_record(name: str, key: str, id_field: str, id_value: str, *, state_root: Path | str) -> dict[str, Any]:
    payload = load_state(name, state_root=state_root)
    for item in payload.get(key, []) or []:
        if str(item.get(id_field)) == id_value:
            return dict(item)
    raise KeyError(f"No {name}.{key} record with {id_field}={id_value}")


def find_packet_from_registry(
    packet_id: str,
    runtime_state_root: str | Path | None = None,
    project_root: str | Path | None = None
) -> dict[str, Any]:
    """
    Find packet in new packet_registry.yaml format.

    New format: {packet_id: {packet_data}, ...}
    Falls back to old format if new registry not found.
    """
    # Try new registry format first
    if runtime_state_root:
        registry_path = Path(runtime_state_root) / "state" / "packet_registry.yaml"
        if registry_path.exists():
            data = read_yaml(registry_path)
            if packet_id in data:
                packet_data = dict(data[packet_id])
                # Add packet_path from 'path' field if present
                if "path" in packet_data and "packet_path" not in packet_data:
                    # Convert relative path to absolute
                    packet_path = Path(packet_data["path"])
                    if not packet_path.is_absolute() and project_root:
                        packet_path = Path(project_root) / packet_path
                    packet_data["packet_path"] = str(packet_path)
                return packet_data

    # Fallback to old format: {packets: [{packet_id: ...}, ...]}
    try:
        return find_record("packets", "packets", "packet_id", packet_id, state_root=runtime_state_root or Path(__file__).resolve().parents[1] / "state")
    except KeyError:
        raise KeyError(f"No packet record with packet_id={packet_id}")


def upsert_record(name: str, key: str, id_field: str, record: dict[str, Any], *, state_root: Path | str) -> dict[str, Any]:
    state_dir = Path(state_root)
    stored_record: dict[str, Any] = {}

    def mutator(payload: dict[str, Any]) -> dict[str, Any]:
        nonlocal stored_record
        items = list(payload.get(key, []) or [])
        for index, item in enumerate(items):
            if str(item.get(id_field)) == str(record[id_field]):
                stored_record = {**item, **record}
                items[index] = stored_record
                payload[key] = items
                return payload
        stored_record = dict(record)
        items.append(stored_record)
        payload[key] = items
        return payload

    locked_update_yaml(state_dir / f"{name}.yaml", mutator)
    return stored_record
