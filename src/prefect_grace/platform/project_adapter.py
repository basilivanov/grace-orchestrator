# ############################################################################
# AI_HEADER: project_adapter
# ROLE: Loads and provides project configurations for GRACE adapter.
# ############################################################################

# START_MODULE_CONTRACT
# purpose: Load and validate the project.yaml configuration.
# inputs: None (loaded from disk by default).
# returns: ProjectAdapterConfig.
# side_effects: Reads project.yaml from disk.
# emitted_logs: None.
# error_behavior: Raises FileNotFoundError if configuration is missing.
# END_MODULE_CONTRACT

# START_MODULE_MAP
# mapping:
#   - class: PrefectConfig
#   - class: AgentExecutorConfig
#   - class: ProjectAdapterConfig
#   - function: load_project_adapter
# END_MODULE_MAP

from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping

import yaml

#START_BLOCK_DATA_MODELS
def _required_string(data: Mapping[str, Any], field_name: str, context: str) -> str:
    value = data.get(field_name)
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{context}.{field_name} must be a non-empty string")
    return value.strip()


def _required_mapping(data: Mapping[str, Any], field_name: str, context: str) -> dict[str, Any]:
    value = data.get(field_name)
    if not isinstance(value, dict):
        raise ValueError(f"{context}.{field_name} must be a mapping")
    return value


def _default_project_config_path() -> Path:
    repo_root = Path(__file__).resolve().parents[2]
    grace_project = repo_root / "grace" / "project.yaml"
    if grace_project.exists():
        return grace_project
    return repo_root / "prefect_grace" / "project.yaml"


def _deep_merge(base: dict[str, Any], patch: Mapping[str, Any]) -> dict[str, Any]:
    merged = deepcopy(base)
    for key, value in patch.items():
        if isinstance(value, Mapping) and isinstance(merged.get(key), dict):
            merged[key] = _deep_merge(merged[key], value)
        else:
            merged[key] = value
    return merged


def _flatten_nested_config(data: Mapping[str, Any]) -> dict[str, Any]:
    result = dict(data)
    project_data = result.pop("project", None)
    runtime_data = result.pop("runtime", None)
    workflow_runtime_data = result.pop("workflow_runtime", None)
    executors_data = result.pop("executors", None)

    if isinstance(project_data, dict):
        key_map = {
            "key": "project_key",
            "root": "repo_root",
            "default_branch": "default_branch",
            "grace_dir": "grace_dir",
            "packets_dir": "packets_dir",
        }
        for source_key, target_key in key_map.items():
            if source_key in project_data and target_key not in result:
                result[target_key] = project_data[source_key]

    if isinstance(runtime_data, dict):
        key_map = {
            "state_root": "runtime_state_root",
            "artifact_root": "artifact_root",
            "worktree_root": "worktree_root",
        }
        for source_key, target_key in key_map.items():
            if source_key in runtime_data and target_key not in result:
                result[target_key] = runtime_data[source_key]

    if isinstance(workflow_runtime_data, dict):
        runtime_type = workflow_runtime_data.get("type")
        if runtime_type and isinstance(runtime_type, str):
            result["workflow_runtime"] = runtime_type
        elif "workflow_runtime" not in result:
            # Default to prefect if not specified
            result["workflow_runtime"] = "prefect"

        # Map v2 workflow_runtime structure to v1 prefect structure
        work_pool = workflow_runtime_data.get("work_pool")
        queues = workflow_runtime_data.get("queues", {})

        if work_pool or queues:
            prefect_config = {}
            if work_pool:
                prefect_config["work_pool"] = work_pool

            if isinstance(queues, dict):
                live_queue = queues.get("live", {})
                monitoring_queue = queues.get("monitoring", {})

                if isinstance(live_queue, dict) and "name" in live_queue:
                    prefect_config["live_queue"] = live_queue["name"]
                if isinstance(monitoring_queue, dict) and "name" in monitoring_queue:
                    prefect_config["monitoring_queue"] = monitoring_queue["name"]

            if prefect_config and "prefect" not in result:
                result["prefect"] = prefect_config

    if isinstance(executors_data, dict):
        # Map v2 executors structure to v1 agent_executor structure
        agent_executor = {}
        if "default" in executors_data:
            agent_executor["default"] = executors_data["default"]
        if "command" in executors_data:
            agent_executor["command"] = executors_data["command"]
        if "items" in executors_data:
            agent_executor["executors"] = executors_data["items"]

        if agent_executor and "agent_executor" not in result:
            result["agent_executor"] = agent_executor

    return result


def _apply_defaults(data: Mapping[str, Any]) -> dict[str, Any]:
    config = _flatten_nested_config(data)
    project_key = str(config.get("project_key") or "project").strip()
    state_root = f"/var/lib/grace-orchestrator/{project_key}"

    # Preserve the version from the original data
    version = data.get("version", 1)

    defaults: dict[str, Any] = {
        "version": version,
        "project_key": project_key,
        "repo_root": str(Path.cwd()),
        "default_branch": "main",
        "grace_dir": "grace",
        "packets_dir": "grace/packets",
        "runtime_state_root": state_root,
        "artifact_root": f"{state_root}/artifacts",
        "worktree_root": f"{state_root}/worktrees",
        "workflow_runtime": "prefect",
        "prefect": {
            "work_pool": f"{project_key}-process",
            "live_queue": f"{project_key}-live",
            "monitoring_queue": f"{project_key}-monitoring",
        },
        "agent_executor": {
            "default": "codex-cli",
            "command": "codex1",
        },
    }
    return _deep_merge(defaults, config)


def _resolve_config_path(config_path: Path | str | None) -> Path:
    if config_path is None:
        return _default_project_config_path()

    path = Path(config_path)
    if path.is_dir():
        grace_project = path / "grace" / "project.yaml"
        if grace_project.exists():
            return grace_project
        return path / "prefect_grace" / "project.yaml"
    return path

@dataclass(frozen=True)
class PrefectConfig:
    work_pool: str
    live_queue: str
    monitoring_queue: str

    # START_FUNCTION_CONTRACT
    # name: from_dict
    # purpose: Parse PrefectConfig from dictionary.
    # inputs:
    #   data: dict containing Prefect config fields.
    # returns: PrefectConfig instance.
    # side_effects: none.
    # emitted_logs: none.
    # error_behavior: none.
    # END_FUNCTION_CONTRACT
    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> PrefectConfig:
        return cls(
            work_pool=_required_string(data, "work_pool", "prefect"),
            live_queue=_required_string(data, "live_queue", "prefect"),
            monitoring_queue=_required_string(data, "monitoring_queue", "prefect"),
        )

    # START_FUNCTION_CONTRACT
    # name: to_dict
    # purpose: Convert PrefectConfig to dictionary.
    # inputs: none.
    # returns: dict containing PrefectConfig fields.
    # side_effects: none.
    # emitted_logs: none.
    # error_behavior: none.
    # END_FUNCTION_CONTRACT
    def to_dict(self) -> dict[str, Any]:
        return {
            "work_pool": self.work_pool,
            "live_queue": self.live_queue,
            "monitoring_queue": self.monitoring_queue,
        }


@dataclass(frozen=True)
class AgentExecutorConfig:
    default: str
    command: str
    executors: list[dict[str, Any]] | None = None

    # START_FUNCTION_CONTRACT
    # name: from_dict
    # purpose: Parse AgentExecutorConfig from dictionary.
    # inputs:
    #   data: dict containing executor config fields.
    # returns: AgentExecutorConfig instance.
    # side_effects: none.
    # emitted_logs: none.
    # error_behavior: none.
    # END_FUNCTION_CONTRACT
    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> AgentExecutorConfig:
        return cls(
            default=_required_string(data, "default", "agent_executor"),
            command=_required_string(data, "command", "agent_executor"),
            executors=data.get("executors"),
        )

    # START_FUNCTION_CONTRACT
    # name: to_dict
    # purpose: Convert AgentExecutorConfig to dictionary.
    # inputs: none.
    # returns: dict containing AgentExecutorConfig fields.
    # side_effects: none.
    # emitted_logs: none.
    # error_behavior: none.
    # END_FUNCTION_CONTRACT
    def to_dict(self) -> dict[str, Any]:
        result = {
            "default": self.default,
            "command": self.command,
        }
        if self.executors is not None:
            result["executors"] = self.executors
        return result


@dataclass(frozen=True)
class ProjectAdapterConfig:
    version: int
    project_key: str
    repo_root: str
    default_branch: str
    grace_dir: str
    packets_dir: str
    runtime_state_root: str
    artifact_root: str
    worktree_root: str
    workflow_runtime: str
    prefect: PrefectConfig
    agent_executor: AgentExecutorConfig

    # START_FUNCTION_CONTRACT
    # name: from_dict
    # purpose: Parse ProjectAdapterConfig from dictionary.
    # inputs:
    #   data: dict containing configuration fields.
    # returns: ProjectAdapterConfig instance.
    # side_effects: none.
    # emitted_logs: none.
    # error_behavior: none.
    # END_FUNCTION_CONTRACT
    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> ProjectAdapterConfig:
        version = data.get("version", 1)
        if version not in (1, 2):
            raise ValueError(f"project.version must be 1 or 2, got {version}")

        # Handle v2 schema by flattening it to v1 internal format
        # Only flatten if we have nested structure (workflow_runtime is a dict)
        if version == 2 and isinstance(data.get("workflow_runtime"), dict):
            data = _flatten_nested_config(data)

        prefect_data = _required_mapping(data, "prefect", "project")
        agent_executor_data = _required_mapping(data, "agent_executor", "project")
        return cls(
            version=version,
            project_key=_required_string(data, "project_key", "project"),
            repo_root=_required_string(data, "repo_root", "project"),
            default_branch=_required_string(data, "default_branch", "project"),
            grace_dir=_required_string(data, "grace_dir", "project"),
            packets_dir=_required_string(data, "packets_dir", "project"),
            runtime_state_root=_required_string(data, "runtime_state_root", "project"),
            artifact_root=_required_string(data, "artifact_root", "project"),
            worktree_root=_required_string(data, "worktree_root", "project"),
            workflow_runtime=_required_string(data, "workflow_runtime", "project"),
            prefect=PrefectConfig.from_dict(prefect_data),
            agent_executor=AgentExecutorConfig.from_dict(agent_executor_data),
        )

    # START_FUNCTION_CONTRACT
    # name: to_dict
    # purpose: Convert ProjectAdapterConfig to dictionary.
    # inputs: none.
    # returns: dict containing ProjectAdapterConfig fields.
    # side_effects: none.
    # emitted_logs: none.
    # error_behavior: none.
    # END_FUNCTION_CONTRACT
    def to_dict(self) -> dict[str, Any]:
        return {
            "version": self.version,
            "project_key": self.project_key,
            "repo_root": self.repo_root,
            "default_branch": self.default_branch,
            "grace_dir": self.grace_dir,
            "packets_dir": self.packets_dir,
            "runtime_state_root": self.runtime_state_root,
            "artifact_root": self.artifact_root,
            "worktree_root": self.worktree_root,
            "workflow_runtime": self.workflow_runtime,
            "prefect": self.prefect.to_dict(),
            "agent_executor": self.agent_executor.to_dict(),
        }

#END_BLOCK_DATA_MODELS
#START_BLOCK_CONFIG_LOADER
# START_FUNCTION_CONTRACT
# name: load_project_adapter
# purpose: Load project configuration from a file with optional overrides.
# inputs:
#   config_path: Path | str | None, path to project.yaml.
#   overrides: Mapping[str, Any] | None, optional overrides to apply.
# returns: ProjectAdapterConfig instance.
# side_effects: Reads configuration file from disk.
# emitted_logs: none.
# error_behavior: Raises FileNotFoundError if config path does not exist.
# END_FUNCTION_CONTRACT
def load_project_adapter(
    config_path: Path | str | None = None,
    overrides: Mapping[str, Any] | None = None,
) -> ProjectAdapterConfig:
    config_path = _resolve_config_path(config_path)

    if not config_path.exists():
        raise FileNotFoundError(f"Project configuration file not found at {config_path}")

    with open(config_path, "r", encoding="utf-8") as f:
        data = yaml.safe_load(f) or {}

    data = _apply_defaults(data)

    if overrides:
        data = _deep_merge(data, overrides)

    return ProjectAdapterConfig.from_dict(data)

#END_BLOCK_CONFIG_LOADER
