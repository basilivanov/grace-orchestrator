"""Tests for session resume — Phase 2 CLI Integration (TZ_SESSION_RESUME.md)."""
from __future__ import annotations

from pathlib import Path

import pytest

from grace_control.services.agent_run_service import _extract_session_id, _SESSION_PATTERNS


# ── _extract_session_id ──────────────────────────────────────────────────


class TestExtractSessionId:
    def test_opencode_json_mode(self):
        stdout = '{"session_id": "ses_abc123", "result": "ok"}'
        assert _extract_session_id(stdout, "opencode") == "ses_abc123"

    def test_opencode_default_mode(self):
        stdout = "Some text\nSession: ses_xyz789\nMore text"
        assert _extract_session_id(stdout, "opencode") == "ses_xyz789"

    def test_opencode_default_no_prefix(self):
        stdout = "Session: abc123"
        assert _extract_session_id(stdout, "opencode") == "abc123"

    def test_agy_conversation_id(self):
        stdout = "Running...\nConversation ID: conv_001\nDone."
        assert _extract_session_id(stdout, "agy") == "conv_001"

    def test_fallback_cli_patterns(self):
        stdout = '{"session_id": "ses_fallback", "other": 1}'
        assert _extract_session_id(stdout, "cli") == "ses_fallback"

    def test_no_match_returns_none(self):
        assert _extract_session_id("no session here", "opencode") is None

    def test_empty_stdout(self):
        assert _extract_session_id("", "opencode") is None

    def test_json_dict_without_session_id(self):
        assert _extract_session_id('{"foo": 1}', "opencode") is None

    def test_json_array(self):
        assert _extract_session_id('[{"session_id": "a"}]', "opencode") is None

    def test_unknown_backend_uses_cli_fallback(self):
        stdout = "Session: ses_unknown_backend"
        assert _extract_session_id(stdout, "unknown_backend") == "ses_unknown_backend"

    def test_session_id_in_json_with_pipe_delimiters(self):
        stdout = (
            'INFO piped output | 1 | 2 | {"session_id": "ses_piped"} ...'
        )
        assert _extract_session_id(stdout, "cli") == "ses_piped"


# ── SESSION_PATTERNS ────────────────────────────────────────────────────


class TestSessionPatterns:
    def test_all_backends_have_patterns(self):
        assert "opencode" in _SESSION_PATTERNS
        assert "agy" in _SESSION_PATTERNS
        assert "cli" in _SESSION_PATTERNS

    def test_opencode_patterns_are_compiled(self):
        for pat in _SESSION_PATTERNS["opencode"]:
            assert hasattr(pat, "search")

    def test_agy_patterns_are_compiled(self):
        for pat in _SESSION_PATTERNS["agy"]:
            assert hasattr(pat, "search")


# ── AgentRunService resume flag injection ────────────────────────────────


class TestResumeFlagInjection:
    """Integration-style test: resume flags end up in command."""

    @pytest.mark.asyncio
    async def test_no_resume_when_not_requested(self):
        from grace_control.services.agent_run_service import AgentRunService
        svc = AgentRunService()
        executor = {
            "command": ["echo", "hello"],
            "resume_mode": "never",
            "backend": "cli",
            "model": "test",
            "role": "coder",
            "cwd": str(Path.cwd()),
        }
        out = await svc.run(
            executor, packet_id="p1", worktree_path=Path.cwd(), state_root=Path.cwd(),
            packet_markdown="test", timeout_seconds=10,
        )
        cmd = out.get("command_preview", [])
        assert "--session" not in cmd
        assert "--fork" not in cmd

    @pytest.mark.asyncio
    async def test_resume_injects_session_flag(self):
        from grace_control.services.agent_run_service import AgentRunService
        svc = AgentRunService()
        executor = {
            "command": ["echo", "hello"],
            "resume_mode": "on_retry",
            "resume_flag": "--session",
            "backend": "cli",
            "model": "test",
            "role": "coder",
            "cwd": str(Path.cwd()),
        }
        out = await svc.run(
            executor, packet_id="p1", worktree_path=Path.cwd(), state_root=Path.cwd(),
            packet_markdown="test", timeout_seconds=10,
            resume_session_id="ses_001",
        )
        cmd = out.get("command_preview", [])
        assert "--session" in cmd
        assert "ses_001" in cmd

    @pytest.mark.asyncio
    async def test_fork_injects_fork_flag(self):
        from grace_control.services.agent_run_service import AgentRunService
        svc = AgentRunService()
        executor = {
            "command": ["echo", "hello"],
            "resume_mode": "on_fork",
            "resume_flag": "--session",
            "fork_flag": "--fork",
            "backend": "cli",
            "model": "test",
            "role": "coder",
            "cwd": str(Path.cwd()),
        }
        out = await svc.run(
            executor, packet_id="p1", worktree_path=Path.cwd(), state_root=Path.cwd(),
            packet_markdown="test", timeout_seconds=10,
            resume_session_id="ses_001", fork=True,
        )
        cmd = out.get("command_preview", [])
        assert "--session" in cmd
        assert "ses_001" in cmd
        assert "--fork" in cmd

    @pytest.mark.asyncio
    async def test_resume_mode_never_skips_injection(self):
        from grace_control.services.agent_run_service import AgentRunService
        svc = AgentRunService()
        executor = {
            "command": ["echo", "hello"],
            "resume_mode": "never",
            "resume_flag": "--session",
            "backend": "cli",
            "model": "test",
            "role": "verifier",
            "cwd": str(Path.cwd()),
        }
        out = await svc.run(
            executor, packet_id="p1", worktree_path=Path.cwd(), state_root=Path.cwd(),
            packet_markdown="test", timeout_seconds=10,
            resume_session_id="ses_001",
        )
        cmd = out.get("command_preview", [])
        assert "--session" not in cmd

    @pytest.mark.asyncio
    async def test_session_id_in_result(self):
        from grace_control.services.agent_run_service import AgentRunService
        svc = AgentRunService()
        executor = {
            "command": ["echo", '{"session_id":"ses_echo"}'],
            "resume_mode": "never",
            "backend": "opencode",
            "model": "test",
            "role": "coder",
            "cwd": str(Path.cwd()),
        }
        out = await svc.run(
            executor, packet_id="p1", worktree_path=Path.cwd(), state_root=Path.cwd(),
            packet_markdown="test", timeout_seconds=10,
        )
        assert out.get("session_id") == "ses_echo"

    @pytest.mark.asyncio
    async def test_agy_conversation_flag(self):
        from grace_control.services.agent_run_service import AgentRunService
        svc = AgentRunService()
        executor = {
            "command": ["echo", "hello"],
            "resume_mode": "on_retry",
            "resume_flag": "--conversation",
            "backend": "agy",
            "model": "gemini",
            "role": "coder",
            "cwd": str(Path.cwd()),
        }
        out = await svc.run(
            executor, packet_id="p1", worktree_path=Path.cwd(), state_root=Path.cwd(),
            packet_markdown="test", timeout_seconds=10,
            resume_session_id="conv_001",
        )
        cmd = out.get("command_preview", [])
        assert "--conversation" in cmd
        assert "conv_001" in cmd
