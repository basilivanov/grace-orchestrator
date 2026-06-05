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
# END_MODULE_MAP

from __future__ import annotations

from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict


class GraceSettings(BaseSettings):
    """Centralized settings — env vars override defaults (GRACE_* prefix)."""

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

    # ── Agent execution ──
    agent_timeout_seconds: int = 600
    state_root: str = "/tmp/grace-eval"
    sandbox_mode: str = "danger-full-access"

    # ── Database ──
    database_url: str = "sqlite:///./grace.db"

    # ── Profiles ──
    @property
    def agent_profiles_path(self) -> Path:
        return Path(__file__).parent / "agent_profiles.yaml"

    # ── Logging ──
    log_level: str = "INFO"

    # ── Wave gate ──
    wave_gate_interval_seconds: int = 30
    feature_gate_interval_seconds: int = 60


settings = GraceSettings()
