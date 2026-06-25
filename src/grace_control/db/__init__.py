# ############################################################################
# AI_HEADER: db_init
# ROLE: Database initialization and session management for GRACE Control Plane.
# ############################################################################

# START_MODULE_CONTRACT
# purpose: Provide init_db for database setup and get_db session context manager.
# inputs: db_url (optional), SQLite path.
# returns: None (init_db), Session (get_db context manager).
# side_effects: Creates SQLite file and all tables on init_db.
# emitted_logs: None.
# error_behavior: Raises RuntimeError if get_db called before init_db.
# END_MODULE_CONTRACT

# START_MODULE_MAP
# mapping:
#   - function: init_db
#   - function: get_db
# END_MODULE_MAP

from __future__ import annotations

import os
from contextlib import contextmanager
from pathlib import Path

from sqlalchemy import create_engine, inspect, text
from sqlalchemy.pool import NullPool, StaticPool
from sqlalchemy.orm import Session, sessionmaker

from .schema import Base

engine = None
SessionLocal = None

#START_BLOCK_INIT
# START_FUNCTION_CONTRACT
# name: init_db
# purpose: Initialize SQLAlchemy engine, session factory, and create all tables.
# inputs:
#   db_url: SQLite URL or None (defaults to sqlite:///{cwd}/grace.db).
# returns: None.
# side_effects: Creates engine, SessionLocal, Base.metadata.create_all, runs
#               SQLite migrations for columns added after the DB was created.
# emitted_logs: None.
# error_behavior: None at this level (SQLAlchemy handles connection errors).
# END_FUNCTION_CONTRACT
def init_db(db_url: str | None = None) -> None:
    global engine, SessionLocal  # noqa: PLW0603

    if db_url is None:
        from grace_control.config.settings import settings
        db_url = os.environ.get("GRACE_DB_URL") or settings.database_url
    if db_url is None or "PLACEHOLDER" in db_url:
        db_path = Path.cwd() / "grace.db"
        db_url = f"sqlite:///{db_path}"

    engine = create_engine(
        db_url,
        echo=False,
        connect_args={"check_same_thread": False} if "sqlite" in db_url else {},
        poolclass=StaticPool if "sqlite" in db_url and ":memory:" in str(db_url) else (NullPool if "sqlite" in db_url else None),
    )
    if "sqlite" in db_url:
        from sqlalchemy import event
        @event.listens_for(engine, "connect")
        def _set_wal(dbapi_conn, _rec):
            dbapi_conn.execute("PRAGMA journal_mode=WAL")
    SessionLocal = sessionmaker(bind=engine, autocommit=False, autoflush=False, expire_on_commit=False)
    Base.metadata.create_all(engine)
    _run_sqlite_column_migrations(engine)

#END_BLOCK_INIT

#START_BLOCK_MIGRATIONS
# Per-column additive migrations for SQLite. Kept here (not in Alembic) until
# Alembic is introduced — these are idempotent ALTERs that are safe to run on
# every startup. Each entry: (table, column, SQL DDL fragment).
_SQLITE_COLUMN_MIGRATIONS: list[tuple[str, str, str]] = [
    ("features", "degraded_reason", "ALTER TABLE features ADD COLUMN degraded_reason TEXT"),
    ("packet_runs", "model", "ALTER TABLE packet_runs ADD COLUMN model VARCHAR"),
    ("packet_runs", "command_preview", "ALTER TABLE packet_runs ADD COLUMN command_preview JSON"),
    ("packet_runs", "prompt", "ALTER TABLE packet_runs ADD COLUMN prompt TEXT"),
    # TZ §6: heartbeat updater writes run.last_heartbeat every 5s for live
    # status in admin. Add column to existing DBs.
    ("feature_planning_runs", "last_heartbeat",
     "ALTER TABLE feature_planning_runs ADD COLUMN last_heartbeat DATETIME"),
    ("leases", "claimed_attempt",
     "ALTER TABLE leases ADD COLUMN claimed_attempt INTEGER NOT NULL DEFAULT 0"),
    ("packet_runs", "tokens_in", "ALTER TABLE packet_runs ADD COLUMN tokens_in INTEGER"),
    ("packet_runs", "tokens_out", "ALTER TABLE packet_runs ADD COLUMN tokens_out INTEGER"),
    ("packet_runs", "cost_usd", "ALTER TABLE packet_runs ADD COLUMN cost_usd NUMERIC(10, 6)"),
    ("workers", "pid", "ALTER TABLE workers ADD COLUMN pid INTEGER"),
]
# Tables that may be missing on existing DBs (added after initial create_all).
_SQLITE_TABLE_CREATIONS: list[str] = [
    # Note: must include last_heartbeat for brand-new DBs (CREATE TABLE has
    # no separate column-migration step).
    "CREATE TABLE IF NOT EXISTS feature_planning_runs (id VARCHAR PRIMARY KEY, feature_id VARCHAR NOT NULL, stage VARCHAR NOT NULL, status VARCHAR NOT NULL, started_at DATETIME, finished_at DATETIME, duration_ms INTEGER, last_heartbeat DATETIME, executor_id VARCHAR, model VARCHAR, prompt TEXT, stdout_path VARCHAR, stderr_path VARCHAR, result_json JSON, error TEXT, trace_id VARCHAR, created_at DATETIME NOT NULL, updated_at DATETIME NOT NULL)",
    "CREATE TABLE IF NOT EXISTS stage_runs (id TEXT PRIMARY KEY, packet_id TEXT NOT NULL, run_id TEXT, feature_id TEXT NOT NULL, wave_id TEXT NOT NULL, stage_key TEXT NOT NULL, attempt_number INTEGER NOT NULL DEFAULT 1, loop_round INTEGER NOT NULL DEFAULT 1, parent_stage_run_id TEXT, started_at DATETIME, finished_at DATETIME, duration_ms INTEGER, last_heartbeat DATETIME, status TEXT NOT NULL DEFAULT 'pending', error TEXT, executor_id TEXT, worker_id TEXT, model TEXT, prompt_hash TEXT, command_preview JSON, tokens_in INTEGER, tokens_out INTEGER, cost_usd NUMERIC(10,6), stdout_path TEXT, stderr_path TEXT, result_path TEXT, artifacts_dir TEXT, trace_id TEXT, recovery_reason TEXT, created_at DATETIME NOT NULL, updated_at DATETIME NOT NULL)",
    "CREATE INDEX IF NOT EXISTS ix_stage_runs_packet ON stage_runs(packet_id)",
    "CREATE INDEX IF NOT EXISTS ix_stage_runs_stage ON stage_runs(stage_key)",
    "CREATE INDEX IF NOT EXISTS ix_stage_runs_status ON stage_runs(status)",
    "CREATE INDEX IF NOT EXISTS ix_stage_runs_trace ON stage_runs(trace_id)",
    "CREATE TABLE IF NOT EXISTS stage_metrics (id INTEGER PRIMARY KEY AUTOINCREMENT, stage_key TEXT NOT NULL, period_kind TEXT NOT NULL, period_start DATETIME NOT NULL, period_end DATETIME NOT NULL, count INTEGER NOT NULL, p50_ms INTEGER, p95_ms INTEGER, avg_ms INTEGER, max_ms INTEGER, min_ms INTEGER, success_count INTEGER NOT NULL DEFAULT 0, failure_count INTEGER NOT NULL DEFAULT 0, success_rate NUMERIC(5,4), avg_tokens_in INTEGER, avg_tokens_out INTEGER, avg_cost_usd NUMERIC(10,6), total_cost_usd NUMERIC(10,6), avg_idle_seconds INTEGER, computed_at DATETIME NOT NULL)",
    "CREATE UNIQUE INDEX IF NOT EXISTS uq_stage_metrics_period ON stage_metrics (stage_key, period_kind, period_start)"
]


def _run_sqlite_column_migrations(eng) -> None:
    """Inspect existing tables and apply missing column ALTERs.

    Only runs on SQLite. No-op on other dialects. Runs AFTER
    Base.metadata.create_all so brand-new DBs already have all columns.
    """
    if not eng.dialect.name == "sqlite":
        return
    insp = inspect(eng)
    with eng.begin() as conn:
        # Create missing tables first
        for ddl in _SQLITE_TABLE_CREATIONS:
            conn.execute(text(ddl))
        # Then apply column migrations
        for table, column, ddl in _SQLITE_COLUMN_MIGRATIONS:
            if not insp.has_table(table):
                continue
            cols = {c["name"] for c in insp.get_columns(table)}
            if column in cols:
                continue
            conn.execute(text(ddl))
#END_BLOCK_MIGRATIONS


#START_BLOCK_SESSION
# START_FUNCTION_CONTRACT
# name: get_db
# purpose: Yield a SQLAlchemy Session with automatic commit/rollback/close.
# inputs: None.
# returns: Session (yielded).
# side_effects: Commits on success, rollbacks on exception.
# emitted_logs: None.
# error_behavior: Raises RuntimeError if init_db not called first.
# END_FUNCTION_CONTRACT
@contextmanager
def get_db() -> Session:
    if SessionLocal is None:
        raise RuntimeError("Database not initialized. Call init_db() first.")
    db = SessionLocal()
    try:
        yield db
        db.commit()
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()

#END_BLOCK_SESSION
