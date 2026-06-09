import os
from unittest.mock import patch
from grace_control.config.settings import GraceSettings

def test_defaults():
    settings = GraceSettings()
    assert settings.dev_tools_enabled is False
    assert settings.dev_keep_failed_worktrees is False

def test_env_parsing():
    with patch.dict(os.environ, {
        "GRACE_DEV_TOOLS_ENABLED": "true",
        "GRACE_DEV_KEEP_FAILED_WORKTREES": "1"
    }):
        settings = GraceSettings()
        assert settings.dev_tools_enabled is True
        assert settings.dev_keep_failed_worktrees is True

    with patch.dict(os.environ, {
        "GRACE_DEV_TOOLS_ENABLED": "false",
        "GRACE_DEV_KEEP_FAILED_WORKTREES": "0"
    }):
        settings = GraceSettings()
        assert settings.dev_tools_enabled is False
        assert settings.dev_keep_failed_worktrees is False
