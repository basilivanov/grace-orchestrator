"""Tests for AgentProfile.to_dict() — TZ §6 profile passthrough.

Reviewer found that to_dict() was missing workspace_mode, resume_safe,
validate_session_before_use, workspace_scope_safety — fields packet_executor
and agent_run_service read via executor.get(...). Without these fields
in the dict, the executor silently fell back to settings defaults.
"""
from __future__ import annotations

import pytest

from grace_control.config.agent_profiles import AgentProfile


def _prof(extras: dict) -> AgentProfile:
    raw = {
        "backend": "cli",
        "command": ["opencode", "run"],
        "extras": [],
        "model": "gpt-test",
        "effort": "low",
        "cwd": "{worktree_path}",
        "timeout_seconds": 120,
        "minimal_repo": False,
        "skip_context_builder": True,
        "env": {},
        "input": {"mode": "none", "template": ""},
        "resume_mode": "never",
        "resume_flag": "--session",
        "fork_flag": "--fork",
        "inject_dir": False,
        "multimodal": False,
    }
    raw.update(extras)
    return AgentProfile("test-executor", raw)


def test_to_dict_includes_workspace_mode():
    p = _prof({"workspace_mode": "full_git_worktree"})
    d = p.to_dict()
    assert d["workspace_mode"] == "full_git_worktree"


def test_to_dict_includes_resume_safe_default_false():
    p = _prof({})
    d = p.to_dict()
    assert d["resume_safe"] is False


def test_to_dict_includes_resume_safe_true_when_set():
    p = _prof({"resume_safe": True})
    d = p.to_dict()
    assert d["resume_safe"] is True


def test_to_dict_includes_validate_session_before_use_default_true():
    p = _prof({})
    d = p.to_dict()
    assert d["validate_session_before_use"] is True


def test_to_dict_includes_workspace_scope_safety_default():
    p = _prof({})
    d = p.to_dict()
    assert d["workspace_scope_safety"] == "default"


def test_to_dict_includes_workspace_scope_safety_unsafe_allowed():
    p = _prof({"workspace_scope_safety": "unsafe_allowed_for_fixture"})
    d = p.to_dict()
    assert d["workspace_scope_safety"] == "unsafe_allowed_for_fixture"


def test_to_dict_passes_all_through_for_real_yaml_coder_opencode_fixture():
    """Reproduce the live config used in coder-opencode-fixture: every
    TZ §6 knob set in YAML must reach the executor dict."""
    p = _prof({
        "workspace_mode": "full_git_worktree",
        "resume_safe": False,
        "validate_session_before_use": True,
        "workspace_scope_safety": "default",
    })
    d = p.to_dict()
    assert d["workspace_mode"] == "full_git_worktree"
    assert d["resume_safe"] is False
    assert d["validate_session_before_use"] is True
    assert d["workspace_scope_safety"] == "default"
