from __future__ import annotations

from dataclasses import dataclass
import os
from pathlib import Path
from typing import Mapping, Any

import yaml

DEFAULT_CONFIG_PATH = Path(__file__).resolve().with_name("runtime.yaml")
DEFAULT_PROJECT_CONFIG_PATH = Path(__file__).resolve().with_name("project.yaml")


@dataclass(frozen=True)
class PrefectGraceRuntimeConfig:
    api_url: str
    public_ui_url: str | None
    work_pool_name: str
    live_queue_name: str
    live_queue_limit: int | None
    monitoring_queue_name: str
    monitoring_queue_limit: int | None
    monitoring_interval_seconds: int
    working_directory: str


def _load_yaml(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    return yaml.safe_load(path.read_text(encoding="utf-8")) or {}


def _normalize_optional_int(value: object) -> int | None:
    if value in (None, "", "none", "null", "None", "Null"):
        return None
    return int(str(value))


def _first_non_empty(*values: object) -> object | None:
    for value in values:
        if value not in (None, ""):
            return value
    return None


def load_runtime_config(
    *,
    config_path: Path | None = None,
    env: Mapping[str, str] | None = None,
) -> PrefectGraceRuntimeConfig:
    env_map = dict(os.environ if env is None else env)

    # Try to load from runtime.yaml first, then fall back to project.yaml
    if config_path is None:
        config_path = DEFAULT_CONFIG_PATH

    raw = _load_yaml(config_path)

    # If runtime.yaml doesn't exist or is empty, try loading from project.yaml v2
    if not raw and config_path == DEFAULT_CONFIG_PATH:
        project_raw = _load_yaml(DEFAULT_PROJECT_CONFIG_PATH)
        if project_raw and project_raw.get("version") == 2:
            # Extract runtime config from v2 project.yaml
            workflow_runtime = project_raw.get("workflow_runtime", {})
            if isinstance(workflow_runtime, dict):
                raw = {
                    "api_url": workflow_runtime.get("api_url"),
                    "public_ui_url": workflow_runtime.get("public_ui_url"),
                    "work_pool_name": workflow_runtime.get("work_pool"),
                    "monitoring_interval_seconds": workflow_runtime.get("monitoring_interval_seconds"),
                }

                queues = workflow_runtime.get("queues", {})
                if isinstance(queues, dict):
                    live_queue = queues.get("live", {})
                    monitoring_queue = queues.get("monitoring", {})

                    if isinstance(live_queue, dict):
                        raw["live_queue_name"] = live_queue.get("name")
                        raw["live_queue_limit"] = live_queue.get("concurrency_limit")

                    if isinstance(monitoring_queue, dict):
                        raw["monitoring_queue_name"] = monitoring_queue.get("name")
                        raw["monitoring_queue_limit"] = monitoring_queue.get("concurrency_limit")

                # Get working_directory from project.root
                project_section = project_raw.get("project", {})
                if isinstance(project_section, dict):
                    raw["working_directory"] = project_section.get("root")

    api_url = str(
        _first_non_empty(
            env_map.get("PREFECT_GRACE_API_URL"),
            env_map.get("PREFECT_API_URL"),
            raw.get("api_url"),
            "http://127.0.0.1:4200/api",
        )
    )
    public_ui_url = _first_non_empty(
        env_map.get("PREFECT_GRACE_PUBLIC_UI_URL"),
        raw.get("public_ui_url"),
        None,
    )
    work_pool_name = str(
        _first_non_empty(
            env_map.get("PREFECT_GRACE_WORK_POOL"),
            raw.get("work_pool_name"),
            "astro-process",
        )
    )
    live_queue_name = str(
        _first_non_empty(
            env_map.get("PREFECT_GRACE_LIVE_QUEUE"),
            raw.get("live_queue_name"),
            "grace-live",
        )
    )
    live_queue_limit = _normalize_optional_int(
        _first_non_empty(
            env_map.get("PREFECT_GRACE_LIVE_QUEUE_LIMIT"),
            raw.get("live_queue_limit"),
            "1",
        )
    )
    monitoring_queue_name = str(
        _first_non_empty(
            env_map.get("PREFECT_GRACE_MONITORING_QUEUE"),
            raw.get("monitoring_queue_name"),
            "grace-monitoring",
        )
    )
    monitoring_queue_limit = _normalize_optional_int(
        _first_non_empty(
            env_map.get("PREFECT_GRACE_MONITORING_QUEUE_LIMIT"),
            raw.get("monitoring_queue_limit"),
            "1",
        )
    )
    monitoring_interval_seconds = int(
        str(
            _first_non_empty(
                env_map.get("PREFECT_GRACE_MONITORING_INTERVAL_SECONDS"),
                raw.get("monitoring_interval_seconds"),
                "300",
            )
        )
    )
    working_directory = str(
        _first_non_empty(
            env_map.get("PREFECT_GRACE_WORKDIR"),
            raw.get("working_directory"),
            str(Path.cwd()),
        )
    )

    return PrefectGraceRuntimeConfig(
        api_url=api_url,
        public_ui_url=str(public_ui_url) if public_ui_url else None,
        work_pool_name=work_pool_name,
        live_queue_name=live_queue_name,
        live_queue_limit=live_queue_limit,
        monitoring_queue_name=monitoring_queue_name,
        monitoring_queue_limit=monitoring_queue_limit,
        monitoring_interval_seconds=monitoring_interval_seconds,
        working_directory=working_directory,
    )
