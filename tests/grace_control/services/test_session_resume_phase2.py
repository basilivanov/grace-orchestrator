"""Tests for session resume — Phase 2 CLI Integration (TZ_SESSION_RESUME.md)."""
from __future__ import annotations

from pathlib import Path

import pytest

from grace_control.services.agent_run_service import _extract_session_id, _SESSION_PATTERNS


# ── _extract_session_id ──────────────────────────────────────────────────


class TestExtractSessionId:
    def test_agy_conversation_id(self):
        stdout = "Running...\nConversation ID: conv_001\nDone."
        assert _extract_session_id(stdout, "agy") == "conv_001"

    def test_no_match_returns_none(self):
        assert _extract_session_id("no session here", "agy") is None

    def test_empty_stdout(self):
        assert _extract_session_id("", "agy") is None

    def test_unknown_backend_has_no_provider_parser(self):
        assert _extract_session_id("Conversation ID: conv_unknown", "unknown_backend") is None


# ── SESSION_PATTERNS ────────────────────────────────────────────────────


class TestSessionPatterns:
    def test_all_backends_have_patterns(self):
        assert "agy" in _SESSION_PATTERNS
        assert set(_SESSION_PATTERNS) == {"agy"}

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
            "resume_safe": True,
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
            "command": ["agy", "run"],
            "resume_mode": "on_retry",
            "resume_flag": "--conversation",
            "backend": "agy",
            "model": "test",
            "role": "coder",
            "cwd": str(Path.cwd()),
            "resume_safe": True,
        }
        out = await svc.run(
            executor, packet_id="p1", worktree_path=Path.cwd(), state_root=Path.cwd(),
            packet_markdown="test", timeout_seconds=10,
            resume_session_id="conv_001",
        )
        cmd = out.get("command_preview", [])
        assert "--conversation" in cmd
        assert "conv_001" in cmd

    @pytest.mark.asyncio
    async def test_fork_injects_fork_flag(self):
        from grace_control.services.agent_run_service import AgentRunService
        svc = AgentRunService()
        executor = {
            "command": ["agy", "run"],
            "resume_mode": "on_fork",
            "resume_flag": "--conversation",
            "fork_flag": "--fork",
            "backend": "agy",
            "model": "test",
            "role": "coder",
            "cwd": str(Path.cwd()),
            "resume_safe": True,
        }
        out = await svc.run(
            executor, packet_id="p1", worktree_path=Path.cwd(), state_root=Path.cwd(),
            packet_markdown="test", timeout_seconds=10,
            resume_session_id="conv_001", fork=True,
        )
        cmd = out.get("command_preview", [])
        assert "--conversation" in cmd
        assert "conv_001" in cmd
        assert "--fork" in cmd

    @pytest.mark.asyncio
    async def test_resume_mode_never_skips_injection(self):
        from grace_control.services.agent_run_service import AgentRunService
        svc = AgentRunService()
        executor = {
            "command": ["agy", "run"],
            "resume_mode": "never",
            "resume_flag": "--conversation",
            "backend": "agy",
            "model": "test",
            "role": "verifier",
            "cwd": str(Path.cwd()),
        }
        out = await svc.run(
            executor, packet_id="p1", worktree_path=Path.cwd(), state_root=Path.cwd(),
            packet_markdown="test", timeout_seconds=10,
            resume_session_id="conv_001",
        )
        cmd = out.get("command_preview", [])
        assert "--conversation" not in cmd

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
            "resume_safe": True,
        }
        out = await svc.run(
            executor, packet_id="p1", worktree_path=Path.cwd(), state_root=Path.cwd(),
            packet_markdown="test", timeout_seconds=10,
            resume_session_id="conv_001",
        )
        cmd = out.get("command_preview", [])
        assert "--conversation" in cmd
        assert "conv_001" in cmd
