"""Tests for session resume hardening (TZ §6.4, §6.5)."""

from __future__ import annotations

import pytest

from grace_control.services.agent_run_service import _opencode_session_usable


# ── Pure helper: _opencode_session_usable ──────────────────────────────────


def test_empty_session_id_not_usable():
    assert _opencode_session_usable("") is False
    assert _opencode_session_usable(None) is False  # type: ignore[arg-type]


def test_short_session_id_not_usable():
    assert _opencode_session_usable("ses") is False
    assert _opencode_session_usable("ses_") is False
    assert _opencode_session_usable("ses_a") is False
    # ses_ab is 6 chars, which is the minimum.
    assert _opencode_session_usable("ses_ab") is True


def test_non_ses_prefixed_session_not_usable():
    assert _opencode_session_usable("abc_1234567") is False
    assert _opencode_session_usable("openses_1234567") is False
    assert _opencode_session_usable("ses") is False  # too short anyway


def test_well_formed_ses_id_usable():
    assert _opencode_session_usable("ses_a1b2c3d4") is True
    assert _opencode_session_usable("ses_xxxxxxxxxxxxxxxxx") is True


# ── Redaction helper (TZ §6.6) ────────────────────────────────────────────


def test_redact_bearer_token():
    from grace_control.adapters.packet_executor import _redact_secrets
    text = "Authorization: Bearer abc123def456ghi789jkl012mno345pqr"
    out = _redact_secrets(text)
    assert "abc123def456ghi789jkl012mno345pqr" not in out
    assert "REDACTED" in out


def test_redact_url_with_credentials():
    from grace_control.adapters.packet_executor import _redact_secrets
    text = "fetching from https://user:secret@api.example.com/path"
    out = _redact_secrets(text)
    assert "user:secret" not in out
    assert "REDACTED" in out or "***:***" in out


def test_redact_long_token():
    from grace_control.adapters.packet_executor import _redact_secrets
    text = "api_key=" + ("a" * 50)
    out = _redact_secrets(text)
    assert "a" * 50 not in out
    assert "REDACTED" in out


def test_redact_short_strings_unchanged():
    from grace_control.adapters.packet_executor import _redact_secrets
    text = "Error: file not found at /tmp/abc.txt"
    out = _redact_secrets(text)
    assert out == text  # No redactions needed


# ── Failure classifier (TZ §6.7) ──────────────────────────────────────────


def test_classify_session_not_found():
    from grace_control.adapters.packet_executor import classify_failure
    out = classify_failure("", "Error: Session not found", 1, "agent_run")
    assert out == "session_not_found"


def test_classify_auth_error_401():
    from grace_control.adapters.packet_executor import classify_failure
    out = classify_failure("", "401 Unauthorized: api key missing", 1, "agent_run")
    assert out == "auth_error"


def test_classify_timeout():
    from grace_control.adapters.packet_executor import classify_failure
    out = classify_failure("", "timeout reached", 0, "execution_timed_out")
    assert out == "timeout"


def test_classify_t1_failed():
    from grace_control.adapters.packet_executor import classify_failure
    out = classify_failure("tests failed", "pytest", 1, "t1_stage_failed")
    assert out == "t1_failed"


def test_classify_unknown():
    from grace_control.adapters.packet_executor import classify_failure
    out = classify_failure("", "something happened", 1, "weird_stage")
    assert out == "unknown"


def test_classify_agent_commit_failed():
    from grace_control.adapters.packet_executor import classify_failure
    out = classify_failure("", "git commit failed: nothing to commit", 1, "agent_run")
    assert out == "agent_commit_failed"
