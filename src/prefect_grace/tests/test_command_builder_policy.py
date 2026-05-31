"""
Integration tests for command builder with policy gate.
"""

import os
import pytest

from prefect_grace.policies import SandboxBypassDenied
from prefect_grace.tasks.codex_launcher_helpers.command_builder import (
    _build_exec_command,
    _build_resume_command,
    _uses_bypass_sandbox,
)
from pathlib import Path


class TestCommandBuilderPolicyIntegration:
    """Integration tests for command builder with policy enforcement."""

    def test_uses_bypass_sandbox_denied_by_default(self):
        """Verify bypass is denied by default."""
        with pytest.raises(SandboxBypassDenied):
            _uses_bypass_sandbox(
                sandbox="danger-full-access",
                approval="never",
                packet_id="test-packet",
                project_config=None,
            )

    def test_uses_bypass_sandbox_allowed_by_env(self, monkeypatch):
        """Verify bypass allowed by environment variable."""
        monkeypatch.setenv("GRACE_ALLOW_SANDBOX_BYPASS", "true")
        result = _uses_bypass_sandbox(
            sandbox="danger-full-access",
            approval="never",
            packet_id="test-packet",
            project_config=None,
        )
        assert result is True

    def test_uses_bypass_sandbox_allowed_by_config(self):
        """Verify bypass allowed by project config."""
        project_config = {"security": {"allow_sandbox_bypass": True}}
        result = _uses_bypass_sandbox(
            sandbox="danger-full-access",
            approval="never",
            packet_id="test-packet",
            project_config=project_config,
        )
        assert result is True

    def test_uses_bypass_sandbox_returns_false_for_normal_sandbox(self, monkeypatch):
        """Verify normal sandbox modes don't trigger bypass."""
        monkeypatch.setenv("GRACE_ALLOW_SANDBOX_BYPASS", "true")
        result = _uses_bypass_sandbox(
            sandbox="workspace-write",
            approval="never",
            packet_id="test-packet",
            project_config=None,
        )
        assert result is False

    def test_build_exec_command_with_bypass_allowed(self, monkeypatch, tmp_path):
        """Verify exec command includes bypass flag when allowed."""
        monkeypatch.setenv("GRACE_ALLOW_SANDBOX_BYPASS", "true")
        last_message_path = tmp_path / "last-message.md"

        command = _build_exec_command(
            codex_binary="codex1",
            workdir="/test/workdir",
            shared_model="claude-sonnet-4",
            reasoning="high",
            approval="never",
            sandbox="danger-full-access",
            last_message_path=last_message_path,
            packet_id="test-packet",
            project_config=None,
        )

        assert "--dangerously-bypass-approvals-and-sandbox" in command
        assert "--sandbox" not in command

    def test_build_exec_command_with_bypass_denied(self, tmp_path):
        """Verify exec command raises when bypass denied."""
        last_message_path = tmp_path / "last-message.md"

        with pytest.raises(SandboxBypassDenied):
            _build_exec_command(
                codex_binary="codex1",
                workdir="/test/workdir",
                shared_model="claude-sonnet-4",
                reasoning="high",
                approval="never",
                sandbox="danger-full-access",
                last_message_path=last_message_path,
                packet_id="test-packet",
                project_config=None,
            )

    def test_build_exec_command_normal_sandbox(self, tmp_path):
        """Verify exec command uses normal sandbox mode."""
        last_message_path = tmp_path / "last-message.md"

        command = _build_exec_command(
            codex_binary="codex1",
            workdir="/test/workdir",
            shared_model="claude-sonnet-4",
            reasoning="high",
            approval="never",
            sandbox="workspace-write",
            last_message_path=last_message_path,
            packet_id="test-packet",
            project_config=None,
        )

        assert "--dangerously-bypass-approvals-and-sandbox" not in command
        assert "--sandbox" in command
        assert "workspace-write" in command

    def test_build_resume_command_with_bypass_allowed(self, monkeypatch, tmp_path):
        """Verify resume command includes bypass flag when allowed."""
        monkeypatch.setenv("GRACE_ALLOW_SANDBOX_BYPASS", "true")
        last_message_path = tmp_path / "last-message.md"

        command = _build_resume_command(
            codex_binary="codex1",
            workdir="/test/workdir",
            shared_model="claude-sonnet-4",
            reasoning="high",
            approval="never",
            sandbox="danger-full-access",
            thread_id="thread-123",
            last_message_path=last_message_path,
            packet_id="test-packet",
            project_config=None,
        )

        assert "--dangerously-bypass-approvals-and-sandbox" in command
        assert "thread-123" in command

    def test_build_resume_command_with_bypass_denied(self, tmp_path):
        """Verify resume command raises when bypass denied."""
        last_message_path = tmp_path / "last-message.md"

        with pytest.raises(SandboxBypassDenied):
            _build_resume_command(
                codex_binary="codex1",
                workdir="/test/workdir",
                shared_model="claude-sonnet-4",
                reasoning="high",
                approval="never",
                sandbox="danger-full-access",
                thread_id="thread-123",
                last_message_path=last_message_path,
                packet_id="test-packet",
                project_config=None,
            )
