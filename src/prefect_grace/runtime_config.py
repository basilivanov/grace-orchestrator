from __future__ import annotations

from dataclasses import dataclass
import os
from pathlib import Path
from typing import Mapping, Any
import warnings

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


def _get_config_search_paths() -> list[Path]:
    """Get config file search paths in priority order.

    Priority:
    1. Explicit GRACE_CONFIG_PATH environment variable
    2. Project-local grace/runtime.yaml
    3. User home ~/.grace/runtime.yaml
    4. Package-local (deprecated, for backward compatibility)
    """
    paths = []

    # 1. Explicit env var (highest priority)
    env_path = os.environ.get("GRACE_CONFIG_PATH")
    if env_path:
        path = Path(env_path)
        if path.exists():
            paths.append(path)

    # 2. Project-local grace/runtime.yaml
    cwd_grace = Path.cwd() / "grace" / "runtime.yaml"
    if cwd_grace.exists():
        paths.append(cwd_grace)

    # 3. User home config
    home_config = Path.home() / ".grace" / "runtime.yaml"
    if home_config.exists():
        paths.append(home_config)

    # 4. Package-local (deprecated, for backward compat)
    if DEFAULT_CONFIG_PATH.exists():
        warnings.warn(
            f"Loading config from package-local {DEFAULT_CONFIG_PATH} is deprecated. "
            f"Move config to grace/runtime.yaml or ~/.grace/runtime.yaml",
            DeprecationWarning,
            stacklevel=3
        )
        paths.append(DEFAULT_CONFIG_PATH)

    return paths


def _get_project_config_search_paths() -> list[Path]:
    """Get project.yaml search paths in priority order."""
    paths = []

    # 1. Project-local grace/project.yaml
    cwd_grace = Path.cwd() / "grace" / "project.yaml"
    if cwd_grace.exists():
        paths.append(cwd_grace)

    # 2. User home config
    home_config = Path.home() / ".grace" / "project.yaml"
    if home_config.exists():
        paths.append(home_config)

    # 3. Package-local (deprecated)
    if DEFAULT_PROJECT_CONFIG_PATH.exists():
        paths.append(DEFAULT_PROJECT_CONFIG_PATH)

    return paths


def load_runtime_config(
    *,
    config_path: Path | None = None,
    env: Mapping[str, str] | None = None,
) -> PrefectGraceRuntimeConfig:
    env_map = dict(os.environ if env is None else env)

    raw = {}

    # If explicit config_path provided, use it
    if config_path is not None:
        raw = _load_yaml(config_path)
    else:
        # Search for runtime.yaml in priority order
        search_paths = _get_config_search_paths()
        for path in search_paths:
            raw = _load_yaml(path)
            if raw:
                break

    # If runtime.yaml doesn't exist or is empty, try loading from project.yaml v2
    if not raw:
        project_search_paths = _get_project_config_search_paths()
        for project_path in project_search_paths:
            project_raw = _load_yaml(project_path)
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

                if raw:
                    break

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
            "grace-process",
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
