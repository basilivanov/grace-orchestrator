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
        db_url = os.environ.get("GRACE_DB_URL")
    if db_url is None:
        db_path = Path.cwd() / "grace.db"
        db_url = f"sqlite:///{db_path}"

    engine = create_engine(
        db_url,
        echo=False,
        connect_args={"check_same_thread": False} if "sqlite" in db_url else {},
    )
    if "sqlite" in db_url:
        from sqlalchemy import event
        @event.listens_for(engine, "connect")
        def _set_wal(dbapi_conn, _rec):
            dbapi_conn.execute("PRAGMA journal_mode=WAL")
    SessionLocal = sessionmaker(bind=engine, autocommit=False, autoflush=False)
    Base.metadata.create_all(engine)
    _run_sqlite_column_migrations(engine)

#END_BLOCK_INIT

#START_BLOCK_MIGRATIONS
# Per-column additive migrations for SQLite. Kept here (not in Alembic) until
# Alembic is introduced — these are idempotent ALTERs that are safe to run on
# every startup. Each entry: (table, column, SQL DDL fragment).
_SQLITE_COLUMN_MIGRATIONS: list[tuple[str, str, str]] = [
    ("features", "degraded_reason", "ALTER TABLE features ADD COLUMN degraded_reason TEXT"),
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
