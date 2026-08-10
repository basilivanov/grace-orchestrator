# ############################################################################
# AI_HEADER: project_registry — validated Admin Hub project configuration
# ROLE: Owns the Hub-side project registry and immutable project identities.
#       It validates transport and path metadata without opening project-local
#       databases or filesystems.
# ############################################################################

# START_MODULE_CONTRACT
# purpose: Parse and validate the Admin Hub project registry, then expose
#          immutable ProjectContext values for request-scoped service calls.
# inputs: YAML mappings/files or the GRACE project registry path environment.
# returns: ProjectRegistry and frozen ProjectContext values.
# side_effects: Reads the configured registry file and environment variables.
# emitted_logs: project_registry_loaded, project_registry_invalid.
# error_behavior: Raises ProjectRegistryError for malformed or unsafe config.
# END_MODULE_CONTRACT

# START_MODULE_MAP
# mapping:
#   - class: ProjectRegistryError
#   - class: ProjectContext
#   - class: ProjectRegistry
#     methods:
#       - from_mapping
#       - from_yaml
#       - from_file
#       - load
#       - get
#       - list_projects
#       - enabled_projects
#   - function: load_project_registry
#   - function: mask_api_endpoint
# END_MODULE_MAP

from __future__ import annotations

import os
import re
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any, ClassVar
from urllib.parse import urlsplit, urlunsplit

import yaml

from grace_control.core.structured_logger import GraceLogger

_log = GraceLogger("project_registry")

_KEY_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_-]{0,63}$")
_DEFAULT_REGISTRY_PATH = Path("/etc/grace/projects.yaml")
_REGISTRY_ENV_NAMES = (
    "GRACE_PROJECTS_CONFIG",
    "GRACE_PROJECT_REGISTRY",
    "GRACE_PROJECTS_FILE",
)


# START_BLOCK_ERRORS
class ProjectRegistryError(ValueError):
    """Raised when the Hub project registry cannot be used safely."""


# END_BLOCK_ERRORS


# START_BLOCK_CONTEXT
@dataclass(frozen=True, slots=True)
class ProjectContext:
    """Immutable identity and transport metadata for one project runtime."""

    key: str
    name: str
    enabled: bool
    unix_user: str | None
    project_root: Path
    api_url: str | None
    api_socket: Path | None
    description: str
    tags: tuple[str, ...]
    api_token: str | None = None
    api_password: str | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.key, str) or not _KEY_PATTERN.fullmatch(self.key):
            raise ProjectRegistryError(
                "project key must match ^[A-Za-z0-9][A-Za-z0-9_-]{0,63}$"
            )
        if not isinstance(self.name, str) or not self.name.strip():
            raise ProjectRegistryError(f"project {self.key!r} name must be non-empty")

        try:
            root = Path(self.project_root).expanduser()
        except (TypeError, ValueError) as exc:
            raise ProjectRegistryError(
                f"project {self.key!r} project_root must be a non-empty absolute path"
            ) from exc
        if not root.is_absolute() or not str(root).strip():
            raise ProjectRegistryError(
                f"project {self.key!r} project_root must be a non-empty absolute path"
            )
        object.__setattr__(self, "project_root", root)

        api_url = self.api_url.strip() if isinstance(self.api_url, str) else self.api_url
        api_socket = Path(self.api_socket).expanduser() if self.api_socket else None
        if api_url and api_socket:
            raise ProjectRegistryError(
                f"project {self.key!r} must configure exactly one of api_url or api_socket"
            )
        if not api_url and not api_socket:
            raise ProjectRegistryError(
                f"project {self.key!r} must configure exactly one usable API transport"
            )
        if api_url:
            parsed = urlsplit(api_url)
            if parsed.scheme not in {"http", "https"} or not parsed.netloc:
                raise ProjectRegistryError(
                    f"project {self.key!r} api_url must be an http(s) URL"
                )
            if parsed.username or parsed.password:
                raise ProjectRegistryError(
                    f"project {self.key!r} api_url must not contain credentials"
                )
        if api_socket and not api_socket.is_absolute():
            raise ProjectRegistryError(
                f"project {self.key!r} api_socket must be an absolute path"
            )
        object.__setattr__(self, "api_url", api_url)
        object.__setattr__(self, "api_socket", api_socket)

        tags = tuple(self.tags)
        if any(not isinstance(tag, str) or not tag.strip() for tag in tags):
            raise ProjectRegistryError(f"project {self.key!r} tags must be non-empty strings")
        object.__setattr__(self, "tags", tuple(tag.strip() for tag in tags))
        if self.unix_user is not None:
            unix_user = str(self.unix_user).strip()
            object.__setattr__(self, "unix_user", unix_user or None)


# END_BLOCK_CONTEXT


# START_BLOCK_REGISTRY
class ProjectRegistry:
    """Validated immutable collection of configured project contexts."""

    _DEFAULT_PATH: ClassVar[Path] = _DEFAULT_REGISTRY_PATH

    def __init__(self, projects: Iterable[ProjectContext] = ()) -> None:
        contexts = tuple(projects)
        seen: set[str] = set()
        for context in contexts:
            if context.key in seen:
                raise ProjectRegistryError(
                    f"duplicate project key {context.key!r}; project keys must be unique"
                )
            seen.add(context.key)
        self._projects = contexts

    # START_FUNCTION_CONTRACT
    # name: from_mapping
    # purpose: Parse a mapping containing the top-level projects list.
    # inputs: raw — decoded registry mapping.
    # returns: Validated ProjectRegistry.
    # side_effects: None.
    # emitted_logs: project_registry_invalid on validation failure.
    # error_behavior: Raises ProjectRegistryError for malformed entries.
    # END_FUNCTION_CONTRACT
    @classmethod
    def from_mapping(cls, raw: Mapping[str, Any] | None) -> ProjectRegistry:
        if raw is None:
            return cls()
        if not isinstance(raw, Mapping):
            raise ProjectRegistryError("project registry root must be a mapping")
        entries = raw.get("projects", [])
        if not isinstance(entries, list):
            raise ProjectRegistryError("project registry 'projects' must be a list")
        contexts: list[ProjectContext] = []
        for index, entry in enumerate(entries):
            if not isinstance(entry, Mapping):
                raise ProjectRegistryError(f"project entry {index} must be a mapping")
            try:
                contexts.append(_context_from_entry(entry))
            except ProjectRegistryError:
                raise
            except (TypeError, ValueError) as exc:
                raise ProjectRegistryError(f"invalid project entry {index}: {exc}") from exc
        registry = cls(contexts)
        _log.info("project_registry_loaded", project_count=len(contexts))
        return registry

    # START_FUNCTION_CONTRACT
    # name: from_yaml
    # purpose: Decode YAML text and validate the resulting project registry.
    # inputs: content — YAML registry text.
    # returns: Validated ProjectRegistry.
    # side_effects: None.
    # emitted_logs: project_registry_invalid on parse failure.
    # error_behavior: Raises ProjectRegistryError for invalid YAML or schema.
    # END_FUNCTION_CONTRACT
    @classmethod
    def from_yaml(cls, content: str) -> ProjectRegistry:
        try:
            raw = yaml.safe_load(content) or {}
        except yaml.YAMLError as exc:
            _log.error("project_registry_invalid", reason="yaml_parse_error")
            raise ProjectRegistryError(f"failed to parse project registry YAML: {exc}") from exc
        try:
            return cls.from_mapping(raw)
        except ProjectRegistryError:
            _log.error("project_registry_invalid", reason="schema_validation_error")
            raise

    # START_FUNCTION_CONTRACT
    # name: from_file
    # purpose: Read and validate a registry file; a missing default file means
    #          an empty registry so local single-project mode remains usable.
    # inputs: path — registry YAML path.
    # returns: Validated ProjectRegistry.
    # side_effects: Reads the registry file.
    # emitted_logs: project_registry_loaded, project_registry_invalid.
    # error_behavior: Raises ProjectRegistryError for unreadable or invalid files.
    # END_FUNCTION_CONTRACT
    @classmethod
    def from_file(cls, path: Path | str) -> ProjectRegistry:
        registry_path = Path(path).expanduser()
        if not registry_path.exists():
            if registry_path == cls._DEFAULT_PATH:
                _log.info("project_registry_loaded", project_count=0)
                return cls()
            raise ProjectRegistryError(f"project registry file not found: {registry_path}")
        try:
            content = registry_path.read_text(encoding="utf-8")
        except OSError as exc:
            _log.error("project_registry_invalid", reason="file_read_error")
            raise ProjectRegistryError(f"cannot read project registry {registry_path}: {exc}") from exc
        try:
            registry = cls.from_yaml(content)
        except ProjectRegistryError as exc:
            raise ProjectRegistryError(f"invalid project registry {registry_path}: {exc}") from exc
        return registry

    # START_FUNCTION_CONTRACT
    # name: load
    # purpose: Load the configured registry path, honoring explicit paths and
    #          supported GRACE project registry environment overrides.
    # inputs: path — optional registry YAML path.
    # returns: Validated ProjectRegistry.
    # side_effects: Reads environment and the registry file.
    # emitted_logs: project_registry_loaded, project_registry_invalid.
    # error_behavior: Raises ProjectRegistryError for invalid configuration.
    # END_FUNCTION_CONTRACT
    @classmethod
    def load(cls, path: Path | str | None = None) -> ProjectRegistry:
        if path is not None:
            return cls.from_file(path)
        for env_name in _REGISTRY_ENV_NAMES:
            configured = os.environ.get(env_name, "").strip()
            if configured:
                return cls.from_file(configured)
        return cls.from_file(cls._DEFAULT_PATH)

    # START_FUNCTION_CONTRACT
    # name: get
    # purpose: Resolve one immutable project context by its safe registry key.
    # inputs: project_key — configured project key.
    # returns: ProjectContext for the key.
    # side_effects: None.
    # emitted_logs: None.
    # error_behavior: Raises KeyError when the key is not configured.
    # END_FUNCTION_CONTRACT
    def get(self, project_key: str) -> ProjectContext:
        for context in self._projects:
            if context.key == project_key:
                return context
        raise KeyError(project_key)

    # START_FUNCTION_CONTRACT
    # name: list_projects
    # purpose: Return all configured project contexts in registry order.
    # inputs: None.
    # returns: Tuple of immutable ProjectContext values.
    # side_effects: None.
    # emitted_logs: None.
    # error_behavior: Never raises.
    # END_FUNCTION_CONTRACT
    def list_projects(self) -> tuple[ProjectContext, ...]:
        return self._projects

    # START_FUNCTION_CONTRACT
    # name: enabled_projects
    # purpose: Return only projects eligible for default remote fan-out.
    # inputs: None.
    # returns: Tuple of enabled immutable ProjectContext values.
    # side_effects: None.
    # emitted_logs: None.
    # error_behavior: Never raises.
    # END_FUNCTION_CONTRACT
    def enabled_projects(self) -> tuple[ProjectContext, ...]:
        return tuple(context for context in self._projects if context.enabled)


# END_BLOCK_REGISTRY


# START_BLOCK_BUILDERS
def _context_from_entry(entry: Mapping[str, Any]) -> ProjectContext:
    key = entry.get("key")
    if key is None or not isinstance(key, str) or not key.strip():
        raise ProjectRegistryError("project key must be non-empty")
    api_url = _non_empty_string(entry.get("api_url"))
    api_socket_value = entry.get("api_socket")
    if api_socket_value is None:
        api_socket_value = entry.get("unix_socket")
    api_socket = _non_empty_string(api_socket_value)
    if api_url and api_socket:
        raise ProjectRegistryError(
            f"project {key!r} must configure exactly one of api_url or api_socket"
        )
    tags = entry.get("tags", [])
    if tags is None:
        tags = []
    if not isinstance(tags, (list, tuple)):
        raise ProjectRegistryError(f"project {key!r} tags must be a list")
    project_root = entry.get("project_root")
    if not isinstance(project_root, (str, Path)) or not str(project_root).strip():
        raise ProjectRegistryError(
            f"project {key!r} project_root must be a non-empty absolute path"
        )
    enabled = entry.get("enabled", True)
    if not isinstance(enabled, bool):
        raise ProjectRegistryError(f"project {key!r} enabled must be boolean")
    auth = entry.get("auth")
    auth_mapping = auth if isinstance(auth, Mapping) else {}
    secret_token = _first_secret(entry, "api_token", "token", "api_key") or _first_secret(
        auth_mapping, "api_token", "token", "api_key"
    )
    secret_password = _first_secret(entry, "api_password", "password") or _first_secret(
        auth_mapping, "api_password", "password"
    )
    return ProjectContext(
        key=key.strip(),
        name=str(entry.get("name") or key).strip(),
        enabled=enabled,
        unix_user=entry.get("unix_user"),
        project_root=project_root,
        api_url=api_url,
        api_socket=Path(api_socket) if api_socket else None,
        description=str(entry.get("description") or ""),
        tags=tuple(tags),
        api_token=secret_token,
        api_password=secret_password,
    )


def _non_empty_string(value: Any) -> str | None:
    if value is None:
        return None
    if not isinstance(value, (str, Path)):
        raise ProjectRegistryError("transport value must be a string or path")
    value = str(value).strip()
    return value or None


def _first_secret(entry: Mapping[str, Any], *names: str) -> str | None:
    for name in names:
        value = entry.get(name)
        if value is not None:
            return str(value)
    return None


# START_FUNCTION_CONTRACT
# name: load_project_registry
# purpose: Load the Admin Hub registry from an explicit path or configured
#          GRACE_PROJECTS_CONFIG-compatible environment override.
# inputs: path — optional registry YAML path.
# returns: Validated ProjectRegistry.
# side_effects: Reads environment and registry YAML.
# emitted_logs: project_registry_loaded, project_registry_invalid.
# error_behavior: Raises ProjectRegistryError for invalid configuration.
# END_FUNCTION_CONTRACT
def load_project_registry(path: Path | str | None = None) -> ProjectRegistry:
    return ProjectRegistry.load(path)


# START_FUNCTION_CONTRACT
# name: mask_api_endpoint
# purpose: Produce a display-safe transport endpoint with credentials and query
#          values removed before it reaches a browser DTO.
# inputs: context — immutable project context.
# returns: Safe endpoint display string.
# side_effects: None.
# emitted_logs: None.
# error_behavior: Never raises for a valid ProjectContext.
# END_FUNCTION_CONTRACT
def mask_api_endpoint(context: ProjectContext) -> str:
    if context.api_socket is not None:
        return f"unix://{context.api_socket}"
    parsed = urlsplit(context.api_url or "")
    return urlunsplit((parsed.scheme, parsed.netloc, parsed.path, "", ""))


# END_BLOCK_BUILDERS
