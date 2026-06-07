"""Tests for session resume, cleanup, and extraction — follow-up review c23970b."""
from __future__ import annotations

import pytest
from pathlib import Path
from unittest.mock import patch, MagicMock

from grace_control.config.agent_profiles import load_agent_profiles, AgentProfile
from grace_control.services.agent_run_service import _extract_session_id


class TestAgentProfileResumeFields:
    """AgentProfile.to_dict() must include session resume fields."""

    def test_coder_deepseek_flash_has_resume_fields(self):
        p = load_agent_profiles().get("coder-deepseek-flash")
        assert p is not None, "coder-deepseek-flash profile not found"
        d = p.to_dict()
        assert d["resume_mode"] == "on_retry"
        assert d["resume_flag"] == "--session"
        assert d["fork_flag"] == "--fork"
        assert d["inject_dir"] is True
        assert d["backend"] == "cli"

    def test_verifier_cheap_never_resumes(self):
        p = load_agent_profiles().get("verifier-cheap")
        assert p is not None
        d = p.to_dict()
        assert d["resume_mode"] == "never"

    def test_context_collector_never_resumes(self):
        p = load_agent_profiles().get("context-collector-flash")
        assert p is not None
        d = p.to_dict()
        assert d["resume_mode"] == "never"

    def test_coder_agy_has_resume_flag(self):
        p = load_agent_profiles().get("coder_agy")
        assert p is not None
        d = p.to_dict()
        assert d["resume_mode"] == "on_retry"
        assert d["resume_flag"] == "--conversation"


class TestSessionExtraction:
    """Session ID extraction from agent stdout."""

    def test_opencode_json_session_id(self):
        stdout = '{"session_id": "ses_abc123"}'
        sid = _extract_session_id(stdout, "opencode")
        assert sid == "ses_abc123"

    def test_opencode_text_session(self):
        stdout = "Session: ses_xyz789\nDone."
        sid = _extract_session_id(stdout, "opencode")
        assert sid == "ses_xyz789"

    def test_agy_conversation_id(self):
        stdout = "Conversation ID: conv_12345\nTask complete."
        sid = _extract_session_id(stdout, "agy")
        assert sid == "conv_12345"

    def test_cli_fallback_to_json(self):
        stdout = '{"session_id": "ses_cli_test"}'
        sid = _extract_session_id(stdout, "cli")
        assert sid == "ses_cli_test"

    def test_no_session_id(self):
        assert _extract_session_id("No session here", "opencode") is None
        assert _extract_session_id("", "cli") is None


class TestMaintenanceStaleDetection:
    """Maintenance worktree stale detection from packet state."""

    def _make_service(self, tmp_path, packet_states=None):
        from grace_control.services.maintenance_service import MaintenanceService
        wt_root = tmp_path / "worktrees"
        wt_root.mkdir()
        return MaintenanceService(
            state_root=tmp_path / "state",
            worktree_root=wt_root,
            project_root=tmp_path,
        ), wt_root

    def test_stale_detection_from_attempt_slug(self, tmp_path: Path):
        svc, wt_root = self._make_service(tmp_path, {"pkt_abc": "merged"})
        (wt_root / "pkt_abc-attempt-0001").mkdir()
        entries = svc._list_worktrees({"pkt_abc": "merged"})
        assert len(entries) == 1
        assert entries[0].slug == "pkt_abc-attempt-0001"
        assert entries[0].is_stale is True
        assert entries[0].packet_state == "merged"

    def test_active_packet_not_stale(self, tmp_path: Path):
        svc, wt_root = self._make_service(tmp_path, {"pkt_abc": "running"})
        (wt_root / "pkt_abc-attempt-0002").mkdir()
        entries = svc._list_worktrees({"pkt_abc": "running"})
        assert len(entries) == 1
        assert entries[0].is_stale is False

    def test_unknown_packet_not_terminal(self, tmp_path: Path):
        svc, wt_root = self._make_service(tmp_path, {})
        (wt_root / "pkt_xyz-attempt-0001").mkdir()
        entries = svc._list_worktrees({})
        assert len(entries) == 1
        assert entries[0].is_stale is False
        assert entries[0].packet_state is None

    def test_multiple_terminal_states(self, tmp_path: Path):
        svc, wt_root = self._make_service(tmp_path, {
            "pkt_a": "rejected",
            "pkt_b": "failed",
            "pkt_c": "blocked_final",
        })
        for s in ["pkt_a-attempt-0001", "pkt_b-attempt-0003", "pkt_c-attempt-0001"]:
            (wt_root / s).mkdir()
        entries = svc._list_worktrees({
            "pkt_a": "rejected",
            "pkt_b": "failed",
            "pkt_c": "blocked_final",
        })
        assert len(entries) == 3
        assert all(e.is_stale for e in entries)
        assert all(e.is_stale for e in entries)


class TestTerminalStateCleanup:
    """TerminalStateCleanup on fast reject."""
    pass  # Placeholder — hard to unit-test without real git worktrees.


class TestRecoveryDecisionAudit:
    """Session resume audit fields in result_json."""
    pass  # Placeholder — tested via integration in adapter tests.
