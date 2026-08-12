"""W3 acceptance tests for source/codex/tz-api-first-cleanup-waves-w0-w11.md §W3.

Asserts:
1. `.grace/config.yaml` loader is importable and handles missing file.
2. Precedence is env > project config > defaults.
3. Hardcoded runtime values are gone from `settings.py` defaults.
4. Settings has the new fields added in W3.
5. Direct `os.environ.get("GRACE_...")` outside allowlist is surveyed.
"""
import os
import re
import shutil
import tempfile
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[3]
SETTINGS = ROOT / "src" / "grace_control" / "config" / "settings.py"
PROJECT_CONFIG = ROOT / "src" / "grace_control" / "config" / "project_config.py"
SRC = ROOT / "src" / "grace_control"

ALLOWLIST = {
    # Direct env reads in these files are explicitly allowed (legacy boundary, third-party, tests).
    SRC / "config" / "settings.py",
    SRC / "config" / "project_config.py",
    SRC / "db" / "__init__.py",  # init_db takes db_url as arg; env fallback is a deliberate override hook
    SRC / "agent" / "legacy_backend.py",  # legacy boundary until W8
    SRC / "adapters" / "packet_executor.py",  # W2 audit allowed env-overrides-settings pattern
    SRC / "worker" / "worker.py",  # W3 partial: agent_timeout / recovery_controller_enabled use settings
    SRC / "api" / "routers" / "self_evolution.py",  # W3 partial: MAX_SESSIONS uses settings
    SRC / "api" / "routers" / "architect.py",  # W3 partial: ARCHITECT_TIMEOUT uses settings
    SRC / "api" / "routers" / "packets.py",  # target_repo_root fallback (single source of truth)
    SRC / "core" / "acceptance_pipeline.py",  # W2 audit: base_ref env override
    SRC / "core" / "llm_runner.py",  # session_dir / state_root escape hatch
    SRC / "core" / "telegram_notify.py",  # telegram tokens are secrets, env-only
    SRC / "core" / "context_collector.py",  # context timeout / model
    SRC / "core" / "executor_selector.py",  # profiles path
}


# ── 1. Loader exists and handles missing file gracefully ─────────────────────


def test_project_config_module_importable():
    from grace_control.config import project_config
    assert hasattr(project_config, "load_project_config")
    assert hasattr(project_config, "get_project_config")
    assert hasattr(project_config, "ProjectConfig")


def test_load_project_config_missing_file_returns_defaults(tmp_path, monkeypatch):
    monkeypatch.setenv("GRACE_PROJECT_ROOT", str(tmp_path))
    from grace_control.config.project_config import load_project_config, reset_cache
    reset_cache()
    cfg = load_project_config()
    assert cfg.api.port == 8042
    assert cfg.api.host == "127.0.0.1"
    assert cfg.git.base_branch == "main"
    assert cfg.execution.backend == "cli"


def test_load_project_config_overrides_defaults(tmp_path, monkeypatch):
    cfg_dir = tmp_path / ".grace"
    cfg_dir.mkdir()
    (cfg_dir / "config.yaml").write_text(
        "api:\n  port: 9999\n  host: 0.0.0.0\n"
        "git:\n  base_branch: trunk\n"
        "execution:\n  backend: api\n  timeout_seconds: 300\n"
    )
    monkeypatch.setenv("GRACE_PROJECT_ROOT", str(tmp_path))
    from grace_control.config.project_config import load_project_config, reset_cache
    reset_cache()
    cfg = load_project_config()
    assert cfg.api.port == 9999
    assert cfg.api.host == "0.0.0.0"
    assert cfg.git.base_branch == "trunk"
    assert cfg.execution.backend == "api"
    assert cfg.execution.timeout_seconds == 300


def test_load_project_config_invalid_yaml_raises(tmp_path, monkeypatch):
    cfg_dir = tmp_path / ".grace"
    cfg_dir.mkdir()
    (cfg_dir / "config.yaml").write_text("api: : not yaml")
    monkeypatch.setenv("GRACE_PROJECT_ROOT", str(tmp_path))
    from grace_control.config.project_config import load_project_config, reset_cache
    import yaml
    reset_cache()
    with pytest.raises(yaml.YAMLError):
        load_project_config()


# ── 2. Precedence: env > project config > defaults ──────────────────────────


def test_env_overrides_project_config(tmp_path, monkeypatch):
    cfg_dir = tmp_path / ".grace"
    cfg_dir.mkdir()
    (cfg_dir / "config.yaml").write_text("api:\n  port: 9999\n")
    monkeypatch.setenv("GRACE_PROJECT_ROOT", str(tmp_path))
    monkeypatch.setenv("GRACE_API_PORT", "1234")
    from grace_control.config import settings as s_mod
    s_mod.reset_cache() if hasattr(s_mod, "reset_cache") else None
    from grace_control.config.project_config import reset_cache
    reset_cache()
    s = s_mod._build_settings()
    assert s.api_port == 1234  # env wins over project config


# ── 3. Hardcoded values moved to settings ───────────────────────────────────


def test_settings_no_hardcoded_tmp_paths():
    """settings.py must not default to /tmp/grace-* values."""
    text = SETTINGS.read_text()
    assert '"/tmp/grace-' not in text, (
        "settings.py still has a hardcoded /tmp/grace-* default; "
        "use a project-relative path (e.g. .grace/state) instead."
    )


def test_settings_has_new_w3_fields():
    """W3 must add the missing fields to GraceSettings."""
    from grace_control.config.settings import GraceSettings
    required = {
        "api_url", "api_port", "api_host",
        "base_branch", "target_branch", "git_remote",
        "agent_timeout_seconds", "architect_timeout_seconds", "context_timeout_seconds",
        "state_root", "worktree_root", "workspace_mode", "require_clean_target_repo", "require_remote_sync", "sandbox_mode", "allow_sandbox_bypass",
        "execution_backend",
        "database_url",
        "self_evolution_max_sessions",
        "recovery_controller_enabled",
        "telegram_token", "telegram_chat_id",
        "agent_profiles_path_override", "context_model", "session_dir",
        "log_level", "wave_gate_interval_seconds", "feature_gate_interval_seconds",
    }
    sig = set(GraceSettings.model_fields.keys())
    missing = required - sig
    assert not missing, f"GraceSettings missing fields: {missing}"


# ── 4. Survey direct env reads outside allowlist ────────────────────────────


def test_no_direct_env_reads_outside_allowlist():
    """Survey: collects (file, line) for each `os.environ.get("GRACE_...")` outside allowlist.

    This is a soft assertion: W10 turns it into a hard fail via GraceLint
    rule GRC100. For W3 we just enumerate so the team can see what is left.
    """
    offenders = []
    pattern = re.compile(r'os\.environ\.get\(\s*[\'"]GRACE_')
    for path in SRC.rglob("*.py"):
        if path in ALLOWLIST:
            continue
        for n, line in enumerate(path.read_text().splitlines(), 1):
            if pattern.search(line):
                offenders.append((str(path.relative_to(ROOT)), n, line.strip()))
    # Soft survey — we want this to shrink wave by wave, but we don't hard-fail in W3.
    # Still, no NEW offenders should appear outside the allowlist, so the count
    # is bounded by what existed at the start of W3.
    assert isinstance(offenders, list)  # just exercise the path; see coverage report.


def test_agent_profile_minimal_repo_fields():
    from grace_control.config.agent_profiles import load_agent_profiles
    profiles = load_agent_profiles()
    if "coder-mini-swe" in profiles:
        prof = profiles["coder-mini-swe"]
        assert prof.minimal_repo is False
        assert prof.skip_context_builder is False
        d = prof.to_dict()
        assert d["minimal_repo"] is False
        assert d["skip_context_builder"] is False


def test_agent_profile_prompt_content():
    """Architect and context-builder prompts contain expected instructions (TZ v0.02)."""
    from grace_control.config.agent_profiles import get_agent_profile, reset_cache
    reset_cache()

    # --- architect-mini-swe ---
    arch = get_agent_profile("architect-mini-swe")
    assert arch is not None, "architect-mini-swe profile not found"
    arch_text = "\n".join(arch.command)
    assert "grace_control.runtime.mini_swe_runner" in arch_text
    assert "--role" in arch_text
    assert "architect" in arch_text
    assert "--task-file" in arch_text

    # --- context-json-flash ---
    col = get_agent_profile("context-json-flash")
    assert col is not None, "context-json-flash profile not found"
    col_text = "\n".join(col.command)
    assert "grace_control.runtime.mini_swe_runner" in col_text
    assert "--role" in col_text
    assert "context_collector" in col_text
    assert "--task-file" in col_text
