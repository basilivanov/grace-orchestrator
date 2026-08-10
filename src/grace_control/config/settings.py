# ############################################################################
# AI_HEADER: settings
# ROLE: Centralized settings for GRACE Control Plane — Pydantic BaseSettings.
# ############################################################################

# START_MODULE_CONTRACT
# purpose: Single source of truth for runtime configuration. Reads from env vars
#          with GRACE_ prefix. Falls back to safe defaults for local dev.
# inputs: Environment variables (GRACE_API_URL, GRACE_API_PORT, etc.).
# returns: Singleton `settings` instance.
# side_effects: Reads environment at import time.
# emitted_logs: None.
# error_behavior: Validates types; raises on invalid values.
# END_MODULE_CONTRACT

# START_MODULE_MAP
# mapping:
#   - class: GraceSettings
#   - instance: settings
#   - function: get_max_concurrency
#   - function: get_parallel_runtime_config
#   - function: parallel_runtime_safety_error
# END_MODULE_MAP

from __future__ import annotations

import os
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

from grace_control.config.project_config import ProjectConfig, get_project_config


class GraceSettings(BaseSettings):
    """Centralized settings — env vars override defaults (GRACE_* prefix).

    Precedence (highest to lowest):
      1. Environment variables (`GRACE_*`).
      2. `.grace/config.yaml` (loaded by `grace_control.config.project_config`).
      3. Safe local defaults declared on this class.

    To set a value at a lower layer, leave the corresponding env var unset
    and put it in `.grace/config.yaml`. See
    `docs/grace/CONFIGURATION.md` for the schema and the rationale.
    """

    model_config = SettingsConfigDict(
        env_prefix="GRACE_",
        env_file=None,
        extra="ignore",
        case_sensitive=False,
    )

    # ── API ──
    api_url: str = "http://127.0.0.1:8042"
    api_port: int = 8042
    api_host: str = "127.0.0.1"

    # ── Git / Merge ──
    target_repo_root: str = ""
    base_branch: str = "main"
    target_branch: str = "main"
    git_remote: str = "origin"

    # ── Agent execution ──
    agent_timeout_seconds: int = 600
    architect_timeout_seconds: int = 120
    context_timeout_seconds: int = 60
    state_root: str = ".grace/state"
    worktree_root: str = ".grace/worktrees"
    workspace_mode: str = "full_git_worktree"
    require_clean_target_repo: bool = True
    require_remote_sync: bool = False
    sandbox_mode: str = "danger-full-access"
    allow_sandbox_bypass: bool = False
    execution_backend: str = "cli"  # "cli" | "api" | "mock" — see grace_control.agent.select_backend

    # ── Database ──
    database_url: str = "sqlite:///./grace.db"

    # ── Self-evolution ──
    self_evolution_max_sessions: int = 3

    # ── Recovery / observability ──
    recovery_controller_enabled: bool = False

    # ── W01: Lease fencing & renewal ──
    lease_ttl_seconds: int = 300            # 5 min — lease lifetime
    lease_renew_interval_seconds: int = 30   # heartbeat renews every 30s
    lease_expiration_grace_seconds: int = 30  # grace period before scanner reclaims

    # TZ03: runtime scope/key guard for safe parallel claims.  The existing
    # GRACE_MAX_CONCURRENCY=1 path remains the backward-compatible default.
    parallel_scope_guard_enabled: bool = True
    max_concurrency: int = 1
    merge_serialization_enabled: bool = True
    merge_lease_ttl_seconds: int = 300
    integration_recheck_on_stale_base: bool = True

    # ── Telegram (optional notification channel) ──
    telegram_token: str = ""
    telegram_chat_id: str = ""

    # ── Agent profiles / LLM ──
    agent_profiles_path_override: str = ""  # empty = use packaged default
    context_model: str = "deepseek/deepseek-v4-flash"
    session_dir: str = ""
    planning_logs_root: str = "/tmp/grace_planning_logs"

    # ── Profiles ──
    @property
    def agent_profiles_path(self) -> Path:
        if self.agent_profiles_path_override:
            return Path(self.agent_profiles_path_override)
        return Path(__file__).parent / "agent_profiles.yaml"

    # ── Logging ──
    log_level: str = "INFO"

    # ── Wave gate ──
    wave_gate_interval_seconds: int = 30
    feature_gate_interval_seconds: int = 60

    # ── API auth (W14.2) ──
    api_auth_enabled: bool = False
    api_auth_token: str = ""
    api_auth_allow_unauthenticated_localhost: bool = True
    api_auth_public_openapi: bool = False

    # ── Runtime observability (W1) ──
    runtime_observability_enabled: bool = True
    runtime_debug_payload_capture_enabled: bool = False
    runtime_artifacts_root: str = ".grace/runs"
    runtime_debug_max_preview_chars: int = 500
    runtime_redact_secrets: bool = True

    # ── W3 Agent Runtime Selftest ──
    agent_runtime_selftest_enabled: bool = True
    agent_runtime_require_opencode_auth: bool = False
    agent_runtime_require_model_config: bool = False
    agent_runtime_fail_on_bad_cwd: bool = True
    agent_runtime_fail_on_bad_git_root: bool = True
    agent_runtime_fail_on_dirty_worktree: bool = False

    # ── W4 OpenCode Direct Runtime Adapter ──
    agent_runtime_use_opencode_adapter: bool = False
    opencode_binary: str = "opencode"
    opencode_direct_timeout_seconds: int = 1800
    opencode_process_kill_grace_seconds: int = 5
    opencode_json_events_required: bool = True
    opencode_capture_raw_events: bool = True

    # ── W5 OpenCode Serve/Attach ──
    opencode_runtime_mode: str = "direct"
    opencode_server_host: str = "127.0.0.1"
    opencode_server_port: int = 4096
    opencode_server_url: str = ""
    opencode_server_password: str = ""
    opencode_server_start_timeout_seconds: int = 20
    opencode_server_health_timeout_seconds: int = 5
    opencode_server_restart_on_unhealthy: bool = True
    opencode_server_log_path: str = ".grace/opencode-server.log"
    opencode_server_pid_path: str = ".grace/opencode-server.pid"

    # ── W6 Post-run Scope Enforcement + Diagnostics ──
    agent_runtime_fail_on_no_changes: bool = False

    # ── W7 Runtime Hardening ──
    agent_runtime_allow_non_git_scope_skip: bool = False
    opencode_server_kill_grace_seconds: int = 5

    # ── W10 Reviewer Rework Packets ──
    agent_runtime_rework_packets_enabled: bool = True

    # ── Dev tools / replay ──
    dev_tools_enabled: bool = False
    dev_keep_failed_worktrees: bool = False


# Class-level defaults, captured AFTER the class is defined and BEFORE
# pydantic-settings ever resolves env vars. We use this to decide whether
# the env layer has touched a field.
_BASE_DEFAULTS: dict[str, object] = {
    name: field.default
    for name, field in GraceSettings.model_fields.items()
    if hasattr(field, "default")
}


def _apply_project_fallbacks(target: GraceSettings, project: ProjectConfig) -> None:
    """Copy project-config values into `target` only when env did not touch them.

    Precedence is env > .grace/config.yaml > safe_local_defaults. Pydantic-
    settings has already populated `target` from env vars (or from the class
    defaults if env is silent), so we overwrite only fields whose current
    value still equals the env-less default.
    """
    project_overrides = {
        "api_host": project.api.host,
        "api_port": project.api.port,
        "database_url": project.database.url,
        "base_branch": project.git.base_branch,
        "target_branch": project.git.target_branch,
        "agent_timeout_seconds": project.execution.timeout_seconds,
        "state_root": project.execution.state_root,
        "worktree_root": project.execution.worktree_root,
        "workspace_mode": project.execution.workspace_mode,
        "require_clean_target_repo": project.execution.require_clean_target_repo,
        "require_remote_sync": project.execution.require_remote_sync,
        "execution_backend": project.execution.backend,
        "sandbox_mode": project.safety.sandbox_mode,
        "opencode_server_url": project.opencode.server_url,
        "opencode_server_password": project.opencode.server_password,
        "target_repo_root": project.execution.target_repo_root,
    }
    for field_name, project_value in project_overrides.items():
        if field_name not in _BASE_DEFAULTS:
            continue
        if getattr(target, field_name) == _BASE_DEFAULTS[field_name]:
            object.__setattr__(target, field_name, project_value)


def _build_settings() -> GraceSettings:
    """Build a GraceSettings with env > .grace/config.yaml > defaults applied."""
    s = GraceSettings()
    _apply_project_fallbacks(s, get_project_config())
    return s


settings = _build_settings()


# START_FUNCTION_CONTRACT
# name: get_max_concurrency
# purpose: Resolve the canonical GRACE_MAX_CONCURRENCY runtime setting.
# inputs: Environment variable GRACE_MAX_CONCURRENCY or settings default.
# returns: At least one configured worker slot.
# side_effects: Reads the process environment through the config boundary.
# emitted_logs: None.
# error_behavior: Raises ValueError when GRACE_MAX_CONCURRENCY is not an integer.
# END_FUNCTION_CONTRACT
def get_max_concurrency() -> int:
    return max(1, int(os.environ.get("GRACE_MAX_CONCURRENCY", str(settings.max_concurrency))))


# START_FUNCTION_CONTRACT
# name: get_parallel_runtime_config
# purpose: Resolve the effective multi-worker safety settings from the canonical
#          settings object and explicit GRACE environment overrides.
# inputs: None.
# returns: Dict containing effective concurrency and all required safety guards.
# side_effects: Reads process environment through the settings boundary.
# emitted_logs: None.
# error_behavior: Raises ValueError when a boolean override is malformed.
# END_FUNCTION_CONTRACT
def get_parallel_runtime_config() -> dict[str, object]:
    def _bool_setting(name: str, fallback: bool) -> bool:
        raw = os.environ.get(name)
        if raw is None:
            return bool(fallback)
        normalized = raw.strip().lower()
        if normalized not in {"true", "false", "1", "0", "yes", "no", "on", "off"}:
            raise ValueError(f"{name} must be a boolean")
        return normalized in {"true", "1", "yes", "on"}

    return {
        "max_concurrency": get_max_concurrency(),
        "scope_guard_enabled": _bool_setting(
            "GRACE_PARALLEL_SCOPE_GUARD_ENABLED",
            settings.parallel_scope_guard_enabled,
        ),
        "merge_serialization_enabled": _bool_setting(
            "GRACE_MERGE_SERIALIZATION_ENABLED",
            settings.merge_serialization_enabled,
        ),
        "integration_recheck_on_stale_base": _bool_setting(
            "GRACE_INTEGRATION_RECHECK_ON_STALE_BASE",
            settings.integration_recheck_on_stale_base,
        ),
    }


# START_FUNCTION_CONTRACT
# name: parallel_runtime_safety_error
# purpose: Fail closed when a multi-worker execution request lacks a required
#          scope/key or serialized-merge safety guard.
# inputs: worker_count — optional number of worker processes being started.
# returns: None for a safe configuration, otherwise a typed safety reason.
# side_effects: Reads canonical runtime settings.
# emitted_logs: None.
# error_behavior: Raises ValueError for malformed boolean configuration.
# END_FUNCTION_CONTRACT
def parallel_runtime_safety_error(worker_count: int | None = None) -> str | None:
    config = get_parallel_runtime_config()
    max_concurrency = int(config["max_concurrency"])
    effective_workers = max_concurrency if worker_count is None else max(1, int(worker_count))
    if max_concurrency <= 1 or effective_workers <= 1:
        return None
    if not bool(config["scope_guard_enabled"]):
        return "parallel_safety_disabled:GRACE_PARALLEL_SCOPE_GUARD_ENABLED=false"
    if not bool(config["merge_serialization_enabled"]):
        return "parallel_safety_disabled:GRACE_MERGE_SERIALIZATION_ENABLED=false"
    if not bool(config["integration_recheck_on_stale_base"]):
        return "parallel_safety_disabled:GRACE_INTEGRATION_RECHECK_ON_STALE_BASE=false"
    return None
