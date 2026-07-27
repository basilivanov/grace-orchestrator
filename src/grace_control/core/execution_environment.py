# ############################################################################
# AI_HEADER: execution_environment — discover deterministic target-repository facts
# ROLE: Architect planning probes this module before prompt construction; the plan
#       compiler consumes the same read-only facts when validating commands.
# ############################################################################

# START_MODULE_CONTRACT
# purpose: Discover standard execution and verification facts in a target repository.
# inputs: Target repository root and optional grace/project.yaml overrides.
# returns: ExecutionEnvironment containing only repository-relative facts.
# side_effects: Reads standard project files and directory metadata.
# emitted_logs: environment_probe_done, environment_override_ignored.
# error_behavior: Malformed or unreadable optional files are ignored and logged.
# END_MODULE_CONTRACT

# START_MODULE_MAP
# mapping:
#   - class: ExecutionEnvironment
#   - function: probe_execution_environment
# END_MODULE_MAP

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

import yaml
from pydantic import BaseModel, Field

from grace_control.core.structured_logger import GraceLogger

_log = GraceLogger("execution_environment")

_COMPOSE_FILES = (
    "compose.yaml",
    "compose.yml",
    "docker-compose.yaml",
    "docker-compose.yml",
)
_STANDARD_CONFIG_FILES = (
    "Makefile",
    "justfile",
    "pyproject.toml",
    "package.json",
    *_COMPOSE_FILES,
    ".gitignore",
    "grace/project.yaml",
)


# START_BLOCK_MODELS
class ExecutionEnvironment(BaseModel):
    shell: str
    python_candidates: list[str] = Field(default_factory=list)
    executable_scripts: list[str] = Field(default_factory=list)
    verification_entrypoints: list[str] = Field(default_factory=list)
    compose_services: list[str] = Field(default_factory=list)
    ignored_patterns: list[str] = Field(default_factory=list)
    config_sources: list[str] = Field(default_factory=list)

    model_config = {"frozen": False}
# END_BLOCK_MODELS


# START_BLOCK_DISCOVERY_HELPERS
def _read_yaml(path: Path) -> dict[str, Any]:
    try:
        value = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    except (OSError, UnicodeError, yaml.YAMLError) as exc:
        _log.warn(
            "environment_override_ignored",
            source=path.name,
            reason=type(exc).__name__,
        )
        return {}
    return value if isinstance(value, dict) else {}


def _repository_relative_path(root: Path, value: str) -> str | None:
    candidate = Path(value)
    if candidate.is_absolute():
        try:
            candidate = candidate.relative_to(root)
        except ValueError:
            return None
    if ".." in candidate.parts:
        return None
    normalized = candidate.as_posix()
    if normalized.startswith("./"):
        normalized = normalized[2:]
    return normalized or None


def _discover_scripts(root: Path) -> tuple[list[str], list[str]]:
    scripts_root = root / "scripts"
    if not scripts_root.is_dir():
        return [], []
    script_paths = sorted(
        path.relative_to(root).as_posix()
        for pattern in ("*.sh", "*.py")
        for path in scripts_root.glob(pattern)
        if path.is_file()
    )
    executable = [
        relative
        for relative in script_paths
        if os.access(root / relative, os.X_OK)
    ]
    return executable, script_paths


def _discover_compose_services(root: Path) -> list[str]:
    services: set[str] = set()
    for relative in _COMPOSE_FILES:
        path = root / relative
        if not path.is_file():
            continue
        raw = _read_yaml(path)
        compose_services = raw.get("services", {})
        if isinstance(compose_services, dict):
            services.update(
                str(name) for name in compose_services if isinstance(name, str)
            )
    return sorted(services)


def _discover_ignored_patterns(root: Path) -> list[str]:
    path = root / ".gitignore"
    if not path.is_file():
        return []
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except (OSError, UnicodeError):
        return []
    return [line.strip() for line in lines if line.strip() and not line.lstrip().startswith("#")]


def _read_overrides(root: Path) -> tuple[str | None, list[str] | None]:
    path = root / "grace" / "project.yaml"
    if not path.is_file():
        return None, None
    raw = _read_yaml(path)
    environment = raw.get("environment", {})
    verification = raw.get("verification", {})

    python_override: str | None = None
    if isinstance(environment, dict) and isinstance(environment.get("python"), str):
        python_override = _repository_relative_path(root, environment["python"])
        if python_override is None:
            _log.warn(
                "environment_override_ignored",
                source="grace/project.yaml",
                reason="python_path_outside_target_repo",
            )

    verification_overrides: list[str] | None = None
    if isinstance(verification, dict):
        configured = [
            value.strip()
            for value in verification.values()
            if isinstance(value, str) and value.strip()
        ]
        if configured:
            verification_overrides = configured
    return python_override, verification_overrides
# END_BLOCK_DISCOVERY_HELPERS


# START_BLOCK_PUBLIC_API
# START_FUNCTION_CONTRACT
# name: probe_execution_environment
# purpose: Discover standard, read-only execution facts before architect planning.
# inputs: target_repo_root — root of the repository being planned and compiled.
# returns: ExecutionEnvironment with deterministic repository-relative facts.
# side_effects: Reads scripts, project configs, compose files, and .gitignore.
# emitted_logs: environment_probe_done, environment_override_ignored.
# error_behavior: Missing standard files produce empty fact lists; invalid overrides are ignored.
# END_FUNCTION_CONTRACT
def probe_execution_environment(
    *,
    target_repo_root: Path | None = None,
) -> ExecutionEnvironment:
    root = (target_repo_root or Path.cwd()).resolve()
    executable_scripts, discovered_scripts = _discover_scripts(root)

    python_candidates = (
        [".venv/bin/python"]
        if (root / ".venv" / "bin" / "python").is_file()
        else []
    )
    discovered_entrypoints = list(discovered_scripts)
    for relative in ("Makefile", "justfile"):
        if (root / relative).is_file():
            discovered_entrypoints.append(relative)

    python_override, verification_overrides = _read_overrides(root)
    if python_override is not None:
        python_candidates = [python_override]
    verification_entrypoints = (
        verification_overrides
        if verification_overrides is not None
        else sorted(set(discovered_entrypoints))
    )

    environment = ExecutionEnvironment(
        shell="/bin/sh",
        python_candidates=python_candidates,
        executable_scripts=executable_scripts,
        verification_entrypoints=verification_entrypoints,
        compose_services=_discover_compose_services(root),
        ignored_patterns=_discover_ignored_patterns(root),
        config_sources=[
            relative for relative in _STANDARD_CONFIG_FILES if (root / relative).is_file()
        ],
    )
    _log.info(
        "environment_probe_done",
        python_count=len(environment.python_candidates),
        script_count=len(environment.executable_scripts),
        verification_count=len(environment.verification_entrypoints),
        compose_service_count=len(environment.compose_services),
    )
    return environment
# END_BLOCK_PUBLIC_API
