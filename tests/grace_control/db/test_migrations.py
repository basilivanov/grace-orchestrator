"""Tests for additive SQLite migrations (TZ §6 last_heartbeat)."""
from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from grace_control.db import init_db
from grace_control.db.schema import Base


def test_feature_planning_runs_last_heartbeat_added_by_migration(tmp_path):
    """TZ §6: feature_planning_runs.last_heartbeat must be added by
    _run_sqlite_column_migrations on existing DBs that were created
    before this column existed."""
    db_path = tmp_path / "migrate.db"
    # 1) Bootstrap a fresh DB without last_heartbeat by creating the table
    # manually with the legacy schema (no last_heartbeat column).
    conn = sqlite3.connect(str(db_path))
    conn.execute("""
        CREATE TABLE feature_planning_runs (
            id VARCHAR PRIMARY KEY,
            feature_id VARCHAR NOT NULL,
            stage VARCHAR NOT NULL,
            status VARCHAR NOT NULL,
            started_at DATETIME,
            finished_at DATETIME,
            duration_ms INTEGER,
            executor_id VARCHAR,
            model VARCHAR,
            prompt TEXT,
            stdout_path VARCHAR,
            stderr_path VARCHAR,
            result_json JSON,
            error TEXT,
            trace_id VARCHAR,
            created_at DATETIME NOT NULL,
            updated_at DATETIME NOT NULL
        )
    """)
    conn.commit()
    conn.close()

    # 2) Init the project on the same DB. This must run migrations and
    # add the missing last_heartbeat column.
    init_db(f"sqlite:///{db_path}")
    Base.metadata.create_all(__import__("grace_control.db", fromlist=["engine"]).engine)

    # 3) Verify the column now exists.
    conn = sqlite3.connect(str(db_path))
    cols = {row[1] for row in conn.execute("PRAGMA table_info(feature_planning_runs)").fetchall()}
    conn.close()
    assert "last_heartbeat" in cols, f"missing last_heartbeat; got {sorted(cols)}"


def test_feature_planning_runs_fallback_create_includes_last_heartbeat(tmp_path):
    """The fallback CREATE TABLE for fresh DBs must also include
    last_heartbeat so a brand-new DB never needs the ALTER migration."""
    from grace_control.db import _SQLITE_TABLE_CREATIONS
    ddl = next(d for d in _SQLITE_TABLE_CREATIONS if "feature_planning_runs" in d)
    assert "last_heartbeat" in ddl, f"last_heartbeat missing from CREATE TABLE DDL: {ddl}"


def test_migration_is_idempotent(tmp_path):
    """Running the migration twice must not error."""
    db_path = tmp_path / "idem.db"
    init_db(f"sqlite:///{db_path}")
    Base.metadata.create_all(__import__("grace_control.db", fromlist=["engine"]).engine)
    # Re-init on the same path — migrations run again, must be no-op.
    init_db(f"sqlite:///{db_path}")
    conn = sqlite3.connect(str(db_path))
    cols = {row[1] for row in conn.execute("PRAGMA table_info(feature_planning_runs)").fetchall()}
    conn.close()
    assert "last_heartbeat" in cols
