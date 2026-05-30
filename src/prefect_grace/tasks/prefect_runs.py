from __future__ import annotations

from collections import Counter
import os
from typing import Any

from prefect_grace.runtime_config import load_runtime_config


def _feature_id_from_run(run: Any) -> str | None:
    parameters = dict(getattr(run, "parameters", {}) or {})
    if parameters.get("feature_id"):
        return str(parameters["feature_id"])
    tags = list(getattr(run, "tags", []) or [])
    for tag in tags:
        text = str(tag)
        if text.startswith("feature:"):
            return text.split(":", 1)[1]
    name = str(getattr(run, "name", "") or "")
    if name.startswith("feature:"):
        parts = name.split(":", 2)
        if len(parts) >= 2:
            return parts[1]
    return None


def _is_feature_run(run: Any) -> bool:
    name = str(getattr(run, "name", "") or "")
    tags = list(getattr(run, "tags", []) or [])
    return name.startswith("feature:") or any(str(tag).startswith("feature:") for tag in tags)


def list_recent_feature_flow_runs(*, limit: int = 100) -> list[dict[str, Any]]:
    runtime = load_runtime_config()
    os.environ["PREFECT_API_URL"] = runtime.api_url
    try:
        from prefect.client.orchestration import get_client
        from prefect.client.schemas.sorting import FlowRunSort
    except ModuleNotFoundError:  # pragma: no cover
        return []

    with get_client(sync_client=True) as client:
        runs = client.read_flow_runs(limit=limit, sort=FlowRunSort.EXPECTED_START_TIME_DESC)

    records: list[dict[str, Any]] = []
    for run in runs:
        if not _is_feature_run(run):
            continue
        feature_id = _feature_id_from_run(run)
        if not feature_id:
            continue
        state_type = str(getattr(getattr(run, "state_type", None), "value", getattr(run, "state_type", None)) or "").lower()
        state_name = str(getattr(run, "state_name", "") or "")
        records.append(
            {
                "flow_run_id": str(getattr(run, "id", "") or ""),
                "feature_id": feature_id,
                "name": str(getattr(run, "name", "") or ""),
                "state_type": state_type,
                "state_name": state_name,
                "status": state_name or state_type,
                "created": getattr(run, "created", None),
                "expected_start_time": getattr(run, "expected_start_time", None),
                "start_time": getattr(run, "start_time", None),
                "end_time": getattr(run, "end_time", None),
                "work_queue_name": getattr(run, "work_queue_name", None),
                "tags": list(getattr(run, "tags", []) or []),
            }
        )
    return records


def latest_feature_run_index(runs: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    index: dict[str, dict[str, Any]] = {}
    for run in runs:
        feature_id = str(run.get("feature_id") or "")
        if feature_id and feature_id not in index:
            index[feature_id] = run
    return index


def feature_run_status_counts(runs: list[dict[str, Any]]) -> dict[str, int]:
    return dict(Counter(str(item.get("state_type") or "unknown") for item in runs))
