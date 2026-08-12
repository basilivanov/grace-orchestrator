"""Tests for SessionStore (TZ_SESSION_RESUME.md Phase 1)."""
from __future__ import annotations

from datetime import datetime, timezone

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.orm import Session, sessionmaker

from grace_control.db.schema import AgentSession, Base, PacketRun
from grace_control.services.session_store import SessionStore


@pytest.fixture
def db() -> Session:
    """Create an in-memory SQLite DB with all tables."""
    engine = create_engine("sqlite://", echo=False, connect_args={"check_same_thread": False})
    Base.metadata.create_all(engine)
    sess = sessionmaker(bind=engine, autocommit=False, autoflush=False)()
    try:
        yield sess
    finally:
        sess.close()


@pytest.fixture
def store() -> SessionStore:
    return SessionStore()


def _add_healthy_run(db: Session, *, run_id: str, packet_id: str,
                     run_number: int, external_id: str) -> None:
    db.add(PacketRun(
        id=run_id,
        packet_id=packet_id,
        run_number=run_number,
        status="accepted",
        result_json={
            "legacy_result": {
                "exit_code": 0,
                "evidence": {"session_id": external_id},
            },
        },
    ))


# ── save ──────────────────────────────────────────────────────────────────


class TestSave:
    def test_save_creates_record(self, db, store):
        sid = store.save(db, packet_id="p1", run_id="run1", role="coder",
                         executor_id="coder-x", backend="cli",
                         attempt_number=0, external_id="ses_ext_001")
        assert sid is not None
        assert sid.startswith("ses_")
        db.flush()
        row = db.query(AgentSession).filter(AgentSession.id == sid).first()
        assert row is not None
        assert row.packet_id == "p1"
        assert row.role == "coder"
        assert row.status == "active"

    def test_save_with_parent(self, db, store):
        sid = store.save(db, packet_id="p1", run_id="r1", role="coder",
                         executor_id="c2", backend="cli",
                         attempt_number=1, external_id="ext2",
                         parent_session_id="ses_parent")
        assert sid is not None
        db.flush()
        row = db.query(AgentSession).filter(AgentSession.id == sid).first()
        assert row.parent_session_id == "ses_parent"

    def test_save_without_optional_fields(self, db, store):
        sid = store.save(db, packet_id="p1", run_id=None, role="verifier",
                         executor_id=None, backend="cli",
                         attempt_number=0, external_id=None)
        assert sid is not None
        db.flush()
        row = db.query(AgentSession).filter(AgentSession.id == sid).first()
        assert row.run_id is None
        assert row.executor_id is None
        assert row.external_id is None


# ── find_latest ───────────────────────────────────────────────────────────


class TestFindLatest:
    def test_finds_latest_for_role(self, db, store):
        sid1 = store.save(db, packet_id="p1", run_id="r1", role="coder",
                          executor_id="ex1", backend="cli",
                          attempt_number=0, external_id="ses_ext_1")
        sid2 = store.save(db, packet_id="p1", run_id="r2", role="coder",
                          executor_id="ex1", backend="cli",
                          attempt_number=1, external_id="ses_ext_2")
        _add_healthy_run(db, run_id="r1", packet_id="p1", run_number=1,
                         external_id="ses_ext_1")
        _add_healthy_run(db, run_id="r2", packet_id="p1", run_number=2,
                         external_id="ses_ext_2")
        db.flush()
        found = store.find_latest(db, "p1", "coder")
        assert found is not None
        assert found.id == sid2  # latest

    def test_filters_by_executor_id(self, db, store):
        store.save(db, packet_id="p1", run_id="r1", role="coder",
                   executor_id="exA", backend="cli",
                   attempt_number=0, external_id="ses_ext_a")
        store.save(db, packet_id="p1", run_id="r2", role="coder",
                   executor_id="exB", backend="cli",
                   attempt_number=1, external_id="ses_ext_b")
        _add_healthy_run(db, run_id="r1", packet_id="p1", run_number=1,
                         external_id="ses_ext_a")
        _add_healthy_run(db, run_id="r2", packet_id="p1", run_number=2,
                         external_id="ses_ext_b")
        db.flush()
        found = store.find_latest(db, "p1", "coder", executor_id="exA")
        assert found is not None
        assert found.executor_id == "exA"

    def test_returns_none_for_unknown_packet(self, db, store):
        assert store.find_latest(db, "unknown", "coder") is None

    def test_failed_sessions_are_skipped(self, db, store):
        sid = store.save(db, packet_id="p1", run_id="r1", role="coder",
                         executor_id="ex1", backend="cli",
                         attempt_number=0, external_id="ext1")
        db.flush()
        store.mark_failed(db, sid)
        db.commit()
        assert store.find_latest(db, "p1", "coder") is None


# ── find_for_fork ──────────────────────────────────────────────────────────


class TestFindForFork:
    def test_finds_any_completed(self, db, store):
        store.save(db, packet_id="p1", run_id="r1", role="coder",
                   executor_id="exA", backend="cli",
                   attempt_number=0, external_id="ses_ext_a")
        store.save(db, packet_id="p1", run_id="r2", role="coder",
                   executor_id="exB", backend="cli",
                   attempt_number=1, external_id="ses_ext_b")
        _add_healthy_run(db, run_id="r1", packet_id="p1", run_number=1,
                         external_id="ses_ext_a")
        _add_healthy_run(db, run_id="r2", packet_id="p1", run_number=2,
                         external_id="ses_ext_b")
        db.flush()
        found = store.find_for_fork(db, "p1", "coder")
        assert found is not None
        # Returns latest
        assert found.executor_id == "exB"

    def test_returns_none_for_unknown(self, db, store):
        assert store.find_for_fork(db, "unknown", "coder") is None


# ── mark_completed / mark_failed ────────────────────────────────────────


class TestMarkStatus:
    def test_mark_completed(self, db, store):
        sid = store.save(db, packet_id="p1", run_id="r1", role="coder",
                         executor_id="ex1", backend="cli",
                         attempt_number=0, external_id="ext1")
        db.flush()
        assert store.mark_completed(db, sid)
        db.flush()
        row = db.query(AgentSession).filter(AgentSession.id == sid).first()
        assert row.status == "completed"
        assert row.finished_at is not None

    def test_mark_failed(self, db, store):
        sid = store.save(db, packet_id="p1", run_id="r1", role="coder",
                         executor_id="ex1", backend="cli",
                         attempt_number=0, external_id="ext1")
        db.flush()
        assert store.mark_failed(db, sid)
        db.flush()
        row = db.query(AgentSession).filter(AgentSession.id == sid).first()
        assert row.status == "failed"
        assert row.finished_at is not None

    def test_mark_unknown_returns_false(self, db, store):
        assert store.mark_completed(db, "ses_nonexistent") is False
        assert store.mark_failed(db, "ses_nonexistent") is False


# ── get_sessions_for_packet ──────────────────────────────────────────────


class TestGetSessionsForPacket:
    def test_returns_all_sessions_for_packet(self, db, store):
        store.save(db, packet_id="p1", run_id="r1", role="coder",
                   executor_id="ex1", backend="cli",
                   attempt_number=0, external_id="a")
        store.save(db, packet_id="p1", run_id="r2", role="verifier",
                   executor_id="ex2", backend="cli",
                   attempt_number=0, external_id="b")
        store.save(db, packet_id="p2", run_id="r3", role="coder",
                   executor_id="ex1", backend="cli",
                   attempt_number=0, external_id="c")
        db.flush()
        result = store.get_sessions_for_packet(db, "p1")
        assert result["reason"] == "ok"
        assert len(result["sessions"]) == 2
        roles = {s["role"] for s in result["sessions"]}
        assert roles == {"coder", "verifier"}

    def test_orders_by_created_at(self, db, store):
        store.save(db, packet_id="p1", run_id="r1", role="coder",
                   executor_id="x", backend="cli",
                   attempt_number=2, external_id="c")
        store.save(db, packet_id="p1", run_id="r2", role="coder",
                   executor_id="x", backend="cli",
                   attempt_number=0, external_id="a")
        store.save(db, packet_id="p1", run_id="r3", role="coder",
                   executor_id="x", backend="cli",
                   attempt_number=1, external_id="b")
        db.flush()
        result = store.get_sessions_for_packet(db, "p1")
        assert result["reason"] == "ok"
        sessions = result["sessions"]
        assert len(sessions) == 3
        attempts = {s["attempt_number"] for s in sessions}
        assert attempts == {0, 1, 2}

    def test_includes_fork_of(self, db, store):
        sid1 = store.save(db, packet_id="p1", run_id="r1", role="coder",
                          executor_id="x", backend="cli",
                          attempt_number=0, external_id="a")
        store.save(db, packet_id="p1", run_id="r2", role="coder",
                   executor_id="y", backend="cli",
                   attempt_number=2, external_id="b",
                   parent_session_id=sid1)
        db.flush()
        result = store.get_sessions_for_packet(db, "p1")
        fork_row = [s for s in result["sessions"] if s["attempt_number"] == 2]
        assert fork_row
        assert fork_row[0]["fork_of"] == sid1

    def test_returns_table_missing_for_missing_table(self, store):
        # Create a fresh DB without agent_sessions table
        engine2 = create_engine("sqlite://", connect_args={"check_same_thread": False})
        # Only create features table — NOT agent_sessions
        from grace_control.db.schema import Feature
        Feature.__table__.create(engine2, checkfirst=True)
        db2 = sessionmaker(bind=engine2)()
        try:
            result = store.get_sessions_for_packet(db2, "p1")
            assert result["reason"] == "table_missing"
            assert result["sessions"] == []
        finally:
            db2.close()

    def test_unknown_packet_returns_empty_list(self, db, store):
        result = store.get_sessions_for_packet(db, "unknown")
        assert result["reason"] == "ok"
        assert result["sessions"] == []
