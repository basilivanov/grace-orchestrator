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


# ── SessionStore usability lookup (TZ §6.5) ─────────────────────────────────


@pytest.fixture
def _db():
    from grace_control.db import init_db
    init_db("sqlite:///:memory:")


def _make_session(db, external_id: str, packet_id: str = "pkt_T1",
                   role: str = "coder", executor_id: str = "coder-opencode-fixture"):
    from grace_control.db.schema import AgentSession
    s = AgentSession(
        id=f"ses_internal_{external_id[-6:]}",
        external_id=external_id,
        packet_id=packet_id,
        run_id=f"{packet_id}-R01",
        role=role,
        executor_id=executor_id,
        backend="cli",
        attempt_number=1,
        status="completed",
    )
    db.add(s)
    db.commit()
    return s


def _make_run(db, *, packet_id: str, run_number: int, status: str,
                result_json: dict):
    from grace_control.db.schema import PacketRun
    from datetime import datetime, UTC
    r = PacketRun(
        id=f"{packet_id}-R{run_number:02d}",
        packet_id=packet_id,
        run_number=run_number,
        executor_id="coder-opencode-fixture",
        worker_id="worker-test",
        status=status,
        result_json=result_json,
        started_at=datetime.now(UTC),
        finished_at=datetime.now(UTC),
        duration_ms=100,
    )
    db.add(r)
    db.commit()
    return r


def test_usability_reads_exit_code_from_legacy_result(_db):
    """exit_code lives under result_json.legacy_result.exit_code, not at
    the top level. Without this fix the helper returned False silently."""
    from grace_control.db import get_db
    with get_db() as db:
        _make_run(db, packet_id="pkt_U1", run_number=1, status="rejected",
                   result_json={
                       "legacy_result": {
                           "exit_code": 1,
                           "stderr": "Session not found",
                           "evidence": {"session_id": "ses_deadbeef01"},
                       },
                   })
        _make_session(db, external_id="ses_deadbeef01", packet_id="pkt_U1")
        from grace_control.services.session_store import (
            _session_run_status_usable,
        )
        assert _session_run_status_usable(db, "ses_deadbeef01") is False


def test_usability_true_for_clean_session(_db):
    from grace_control.db import get_db
    with get_db() as db:
        _make_run(db, packet_id="pkt_U2", run_number=1, status="accepted",
                   result_json={
                       "legacy_result": {
                           "exit_code": 0,
                           "stderr": "",
                           "evidence": {"session_id": "ses_clean0001"},
                       },
                   })
        _make_session(db, external_id="ses_clean0001", packet_id="pkt_U2")
        from grace_control.services.session_store import (
            _session_run_status_usable,
        )
        assert _session_run_status_usable(db, "ses_clean0001") is True


def test_usability_reads_session_id_from_diagnostics_top_level(_db):
    """After TZ §6.6 diagnostics surface is at result_json.diagnostics
    top-level. Helper must also check this location."""
    from grace_control.db import get_db
    with get_db() as db:
        _make_run(db, packet_id="pkt_U3", run_number=1, status="accepted",
                   result_json={
                       "diagnostics": {
                           "session_id": "ses_top001",
                           "stderr_tail": "",
                       },
                       "legacy_result": {"exit_code": 0, "stderr": ""},
                   })
        _make_session(db, external_id="ses_top001", packet_id="pkt_U3")
        from grace_control.services.session_store import (
            _session_run_status_usable,
        )
        assert _session_run_status_usable(db, "ses_top001") is True


def test_usability_false_on_session_not_found_in_stderr(_db):
    from grace_control.db import get_db
    with get_db() as db:
        _make_run(db, packet_id="pkt_U4", run_number=1, status="rejected",
                   result_json={
                       "legacy_result": {
                           "exit_code": 1,
                           "stderr": "Error: Session not found: ses_ghost00",
                           "evidence": {"session_id": "ses_ghost0000"},
                       },
                   })
        _make_session(db, external_id="ses_ghost0000", packet_id="pkt_U4")
        from grace_control.services.session_store import (
            _session_run_status_usable,
        )
        assert _session_run_status_usable(db, "ses_ghost0000") is False


def test_find_latest_skips_unusable_session(_db):
    """If the latest run for a session failed, find_latest must skip it."""
    from grace_control.db import get_db
    from grace_control.services.session_store import SessionStore
    with get_db() as db:
        _make_session(db, external_id="ses_dead00002", packet_id="pkt_F1")
        _make_run(db, packet_id="pkt_F1", run_number=1, status="rejected",
                   result_json={
                       "legacy_result": {
                           "exit_code": 1,
                           "stderr": "Session not found",
                           "evidence": {"session_id": "ses_dead00002"},
                       },
                   })
        store = SessionStore()
        result = store.find_latest(db, "pkt_F1", "coder")
        assert result is None


def test_find_for_fork_skips_unusable_session(_db):
    """find_for_fork must apply the same usability filter (TZ §6.5)."""
    from grace_control.db import get_db
    from grace_control.services.session_store import SessionStore
    with get_db() as db:
        _make_session(db, external_id="ses_dead00003", packet_id="pkt_F2",
                       executor_id="coder-old-executor")
        _make_run(db, packet_id="pkt_F2", run_number=1, status="failed",
                   result_json={
                       "legacy_result": {
                           "exit_code": 1,
                           "stderr": "Session not found",
                           "evidence": {"session_id": "ses_dead00003"},
                       },
                   })
        store = SessionStore()
        result = store.find_for_fork(db, "pkt_F2", "coder")
        assert result is None


def test_find_for_fork_returns_usable_session(_db):
    """A healthy session must be returned by find_for_fork."""
    from grace_control.db import get_db
    from grace_control.services.session_store import SessionStore
    with get_db() as db:
        _make_session(db, external_id="ses_alive0001", packet_id="pkt_F3",
                       executor_id="coder-old")
        _make_run(db, packet_id="pkt_F3", run_number=1, status="accepted",
                   result_json={
                       "legacy_result": {
                           "exit_code": 0,
                           "stderr": "",
                           "evidence": {"session_id": "ses_alive0001"},
                       },
                   })
        store = SessionStore()
        result = store.find_for_fork(db, "pkt_F3", "coder")
        assert result is not None
        assert result.external_id == "ses_alive0001"


# ── session_resume in returned dict (TZ §6.4 follow-up) ────────────────────
# Reviewer found that AgentRunService.run() used to stash the resume
# decision on self._last_session_resume (a side-channel that the
# executor never actually read). The fix: include the decision in the
# returned dict so it lands in ExecutionResult.evidence and is lifted
# into result_json.diagnostics.session_resume.


class _FakeSupervisorResult:
    def __init__(self, stdout="", stderr="", exit_code=0, timed_out=False, duration_ms=0):
        self.stdout = stdout
        self.stderr = stderr
        self.exit_code = exit_code
        self.timed_out = timed_out
        self.duration_ms = duration_ms


def _stub_supervisor(monkeypatch, out: _FakeSupervisorResult):
    """Replace ProcessSupervisor on a fresh AgentRunService instance."""
    from grace_control.services.agent_run_service import AgentRunService
    svc = AgentRunService()
    monkeypatch.setattr(svc._supervisor, "run", _async_return(out))
    return svc


def _async_return(value):
    async def _coro(*args, **kwargs):
        return value
    return _coro


def test_session_resume_used_false_when_resume_safe_false(monkeypatch, tmp_path):
    """resume_mode=on_retry + resume_safe=false + sid set =>
    result["session_resume"]["used"] == False and reason indicates
    why resume was skipped."""
    import asyncio
    out = _FakeSupervisorResult(exit_code=0, stdout="ok", duration_ms=10)
    svc = _stub_supervisor(monkeypatch, out)
    executor = {
        "executor_id": "coder-opencode-fixture",
        "backend": "opencode",
        "command": ["opencode", "run"],
        "extras": [],
        "env": {},
        "model": "opencode/gpt-5",
        "effort": "low",
        "cwd": "{worktree_path}",
        "input_mode": "none",
        "input_template": "",
        "resume_mode": "on_retry",
        "resume_flag": "--session",
        "fork_flag": "--fork",
        "resume_safe": False,
        "validate_session_before_use": True,
        "inject_dir": False,
    }
    result = asyncio.run(svc.run(
        executor,
        packet_id="pkt_SR1",
        worktree_path=tmp_path,
        state_root=tmp_path,
        packet_markdown="# task",
        resume_session_id="ses_deadbeef01",
        fork=False,
    ))
    assert "session_resume" in result
    decision = result["session_resume"]
    assert decision["used"] is False
    assert decision["session_id"] == "ses_deadbeef01"
    assert decision["reason"] == "profile_not_resume_safe"


def test_session_resume_used_true_when_all_gates_pass(monkeypatch, tmp_path):
    import asyncio
    out = _FakeSupervisorResult(exit_code=0, stdout="ok", duration_ms=10)
    svc = _stub_supervisor(monkeypatch, out)
    executor = {
        "executor_id": "coder-opencode-fixture",
        "backend": "opencode",
        "command": ["opencode", "run"],
        "extras": [],
        "env": {},
        "model": "opencode/gpt-5",
        "effort": "low",
        "cwd": "{worktree_path}",
        "input_mode": "none",
        "input_template": "",
        "resume_mode": "on_retry",
        "resume_flag": "--session",
        "fork_flag": "--fork",
        "resume_safe": True,
        "validate_session_before_use": True,
        "inject_dir": False,
    }
    result = asyncio.run(svc.run(
        executor,
        packet_id="pkt_SR2",
        worktree_path=tmp_path,
        state_root=tmp_path,
        packet_markdown="# task",
        resume_session_id="ses_alivecafe01",
        fork=False,
    ))
    decision = result["session_resume"]
    assert decision["used"] is True
    assert decision["reason"] == "injected"


def test_session_resume_used_false_when_resume_mode_never(monkeypatch, tmp_path):
    import asyncio
    out = _FakeSupervisorResult(exit_code=0, stdout="ok", duration_ms=10)
    svc = _stub_supervisor(monkeypatch, out)
    executor = {
        "executor_id": "coder-deepseek-flash",
        "backend": "cli",
        "command": ["ds", "run"],
        "extras": [],
        "env": {},
        "model": "deepseek/deepseek-v4-flash",
        "effort": "low",
        "cwd": "{worktree_path}",
        "input_mode": "none",
        "input_template": "",
        "resume_mode": "never",
        "resume_safe": True,
        "validate_session_before_use": True,
        "inject_dir": False,
    }
    result = asyncio.run(svc.run(
        executor,
        packet_id="pkt_SR3",
        worktree_path=tmp_path,
        state_root=tmp_path,
        packet_markdown="# task",
        resume_session_id="ses_shouldnotbeused",
        fork=False,
    ))
    decision = result["session_resume"]
    assert decision["used"] is False
    assert decision["reason"] == "disabled_for_profile"
    assert decision["requested"] is False


# ── Diagnostics surface lifts session_resume (TZ §6.4) ─────────────────────


def test_extract_diagnostics_lifts_session_resume_from_evidence():
    """If a backend stores session_resume in result.evidence (the
    canonical path now), _extract_diagnostics must lift it to the
    top-level diagnostics surface."""
    from pathlib import Path
    from grace_control.adapters.packet_executor import _extract_diagnostics
    from grace_control.agent.backend import ExecutionResult

    er = ExecutionResult(
        accepted=True,
        domain_status="completed",
        worktree_path=Path("/tmp"),
        branch_name="",
        commit_sha="",
        stdout="",
        stderr="",
        duration_ms=10,
        evidence={
            "stdout_tail": "ok",
            "stderr_tail": "",
            "exit_code": 0,
            "duration_ms": 10,
            "failure_class": "unknown",
            "failure_stage": "agent_run",
            "session_resume": {
                "requested": True,
                "session_id": "ses_deadbeef01",
                "used": False,
                "reason": "profile_not_resume_safe",
            },
        },
    )
    diag = _extract_diagnostics(er)
    assert "session_resume" in diag
    assert diag["session_resume"]["used"] is False
    assert diag["session_resume"]["reason"] == "profile_not_resume_safe"
    # Other keys lifted too
    assert diag["stderr_tail"] == ""
    assert diag["failure_class"] == "unknown"
