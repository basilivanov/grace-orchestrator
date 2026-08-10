# ############################################################################
# AI_HEADER: db_init — Alembic-backed database initialization and sessions
# ############################################################################

# START_MODULE_CONTRACT
# purpose: Resolve the runtime database URL, bridge pre-Alembic GRACE SQLite
#          databases once, upgrade to Alembic head, and provide DB sessions.
# inputs: Optional SQLAlchemy database URL and runtime settings.
# returns: None from init_db; a transactional SQLAlchemy Session from get_db.
# side_effects: Creates database files, runs Alembic migrations, applies a
#               one-time legacy SQLite bridge, and writes structured logs.
# emitted_logs: db_init_start, legacy_bootstrap_start, legacy_indexes_normalized,
#               legacy_bootstrap_done, legacy_schema_incomplete,
#               alembic_upgrade_done, db_init_done.
# error_behavior: Propagates SQLAlchemy/Alembic failures; get_db raises
#                 RuntimeError before init_db has completed.
# END_MODULE_CONTRACT

# START_MODULE_MAP
# mapping:
#   - function: resolve_db_url
#   - function: init_db
#   - function: get_db
# END_MODULE_MAP

from __future__ import annotations

import os
from contextlib import contextmanager
from pathlib import Path

from sqlalchemy import create_engine, event, inspect, text
from sqlalchemy.engine import Connection, Engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import NullPool, StaticPool

from grace_control.core.structured_logger import GraceLogger

from .schema import Base

_log = GraceLogger("db_init")

engine = None
SessionLocal = None
_ALEMBIC_BASELINE_REVISION = "0001_grace_legacy_baseline"
# `parallel_leases` belongs to the post-baseline TZ03 revision.  The legacy
# bridge must verify the schema represented by 0001, not the current metadata.
_BASELINE_TABLES = frozenset(
    table_name for table_name in Base.metadata.tables if table_name != "parallel_leases"
)
_LEGACY_SIGNATURE_TABLES = frozenset({"features", "waves", "packets"})
_BASELINE_INDEXES: tuple[tuple[str, str, tuple[str, ...], bool], ...] = tuple(
    (
        index.name,
        table.name,
        tuple(column.name for column in index.columns),
        bool(index.unique),
    )
    for table in Base.metadata.tables.values()
    if table.name != "parallel_leases"
    for index in table.indexes
    if index.name
)
_SQLITE_LEGACY_INDEX_NAMES = frozenset(
    {
        "ix_stage_runs_packet",
        "ix_stage_runs_stage",
        "ix_stage_runs_status",
        "ix_stage_runs_trace",
    }
)


# START_BLOCK_RESOLUTION
# START_FUNCTION_CONTRACT
# name: resolve_db_url
# purpose: Resolve the runtime database URL using the GRACE DB override and settings.
# inputs:
#   db_url: Explicit SQLAlchemy URL, or None to use GRACE_DB_URL/settings.
# returns: Resolved SQLAlchemy database URL.
# side_effects: Reads GRACE_DB_URL and settings when db_url is None.
# emitted_logs: None.
# error_behavior: Uses the cwd SQLite fallback for empty or placeholder URLs.
# END_FUNCTION_CONTRACT
def resolve_db_url(db_url: str | None = None) -> str:
    if db_url is None:
        from grace_control.config.settings import settings

        db_url = os.getenv("GRACE_DB_URL") or settings.database_url
    if db_url is None or "PLACEHOLDER" in db_url:
        db_path = Path.cwd() / "grace.db"
        return f"sqlite:///{db_path}"
    return db_url


# END_BLOCK_RESOLUTION


# START_BLOCK_INIT
# START_FUNCTION_CONTRACT
# name: init_db
# purpose: Initialize the SQLAlchemy engine, bridge a pre-Alembic legacy DB when
#          required, upgrade it to Alembic head, and initialize SessionLocal.
# inputs:
#   db_url: SQLite or supported SQLAlchemy URL, or None for runtime resolution.
# returns: None.
# side_effects: Creates an engine, runs Alembic migrations, may perform the
#               private one-time SQLite legacy bootstrap, and initializes sessions.
# emitted_logs: db_init_start, legacy_bootstrap_start, legacy_indexes_normalized,
#               legacy_bootstrap_done, legacy_schema_incomplete,
#               alembic_upgrade_done, db_init_done.
# error_behavior: Propagates database and Alembic errors.
# END_FUNCTION_CONTRACT
def init_db(db_url: str | None = None) -> None:
    global engine, SessionLocal  # noqa: PLW0603

    resolved_db_url = resolve_db_url(db_url)
    is_sqlite = "sqlite" in resolved_db_url
    engine = create_engine(
        resolved_db_url,
        echo=False,
        connect_args={"check_same_thread": False} if is_sqlite else {},
        poolclass=(
            StaticPool
            if is_sqlite and ":memory:" in resolved_db_url
            else (NullPool if is_sqlite else None)
        ),
    )
    _log.info("db_init_start", db_dialect=engine.dialect.name, reason="alembic_startup")

    if is_sqlite:

        @event.listens_for(engine, "connect")
        def _set_wal(dbapi_conn, _rec):
            dbapi_conn.execute("PRAGMA journal_mode=WAL")

    SessionLocal = None
    _run_alembic_migrations(engine)
    SessionLocal = sessionmaker(bind=engine, autocommit=False, autoflush=False, expire_on_commit=False)
    _log.info("db_init_done", db_dialect=engine.dialect.name, reason="alembic_head")


# END_BLOCK_INIT


# START_BLOCK_MIGRATIONS
# Private one-time legacy bootstrap deltas. These are deliberately not a
# production migration mechanism: init_db invokes them only for a SQLite
# database with GRACE tables and no alembic_version table.
_SQLITE_COLUMN_MIGRATIONS: list[tuple[str, str, str]] = [
    ("features", "degraded_reason", "ALTER TABLE features ADD COLUMN degraded_reason TEXT"),
    ("packet_runs", "model", "ALTER TABLE packet_runs ADD COLUMN model VARCHAR"),
    ("packet_runs", "command_preview", "ALTER TABLE packet_runs ADD COLUMN command_preview JSON"),
    ("packet_runs", "prompt", "ALTER TABLE packet_runs ADD COLUMN prompt TEXT"),
    # TZ §6: heartbeat updater writes run.last_heartbeat every 5s for live
    # status in admin. Add column to existing DBs.
    (
        "feature_planning_runs",
        "last_heartbeat",
        "ALTER TABLE feature_planning_runs ADD COLUMN last_heartbeat DATETIME",
    ),
    ("leases", "claimed_attempt", "ALTER TABLE leases ADD COLUMN claimed_attempt INTEGER NOT NULL DEFAULT 0"),
    ("packet_runs", "tokens_in", "ALTER TABLE packet_runs ADD COLUMN tokens_in INTEGER"),
    ("packet_runs", "tokens_out", "ALTER TABLE packet_runs ADD COLUMN tokens_out INTEGER"),
    ("packet_runs", "cost_usd", "ALTER TABLE packet_runs ADD COLUMN cost_usd NUMERIC(10, 6)"),
    ("workers", "pid", "ALTER TABLE workers ADD COLUMN pid INTEGER"),
]

# Tables that may be missing on pre-Alembic databases. They remain private
# legacy helpers; new schema changes belong in a new Alembic revision.
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
    "CREATE UNIQUE INDEX IF NOT EXISTS uq_stage_metrics_period ON stage_metrics (stage_key, period_kind, period_start)",
]


def _alembic_config():
    from alembic.config import Config

    repo_root = Path(__file__).resolve().parents[3]
    config_path = repo_root / "alembic.ini"
    if not config_path.exists():
        config_path = Path.cwd() / "alembic.ini"
    if not config_path.exists():
        raise RuntimeError("Alembic configuration not found")
    return Config(str(config_path))


def _run_alembic_migrations(eng: Engine) -> None:
    from alembic import command

    config = _alembic_config()
    with eng.connect() as connection:
        config.attributes["connection"] = connection
        inspector = inspect(connection)
        pre_alembic = not inspector.has_table("alembic_version")
        legacy_grace = pre_alembic and _is_legacy_grace_db(connection)

        if legacy_grace:
            _log.info("legacy_bootstrap_start", reason="pre_alembic_grace_db")
            if connection.dialect.name == "sqlite":
                _run_sqlite_column_migrations(connection)
                _normalize_sqlite_legacy_indexes(connection)

            missing_tables, missing_columns = _baseline_schema_gaps(connection)
            if missing_columns:
                _verify_baseline_schema(connection)
            if missing_tables:
                # The baseline revision is idempotent for this bridge path and
                # creates only tables absent from the pre-Alembic database.
                command.upgrade(config, _ALEMBIC_BASELINE_REVISION)
                _verify_baseline_schema(connection)

            _verify_baseline_schema(connection)
            command.stamp(config, _ALEMBIC_BASELINE_REVISION)
            _log.info("legacy_bootstrap_done", reason="baseline_stamped")

        command.upgrade(config, "head")
        connection.commit()
        _log.info("alembic_upgrade_done", reason="head")


def _is_legacy_grace_db(connection: Connection) -> bool:
    tables = set(inspect(connection).get_table_names())
    return _LEGACY_SIGNATURE_TABLES.issubset(tables)


def _baseline_schema_gaps(connection: Connection) -> tuple[list[str], dict[str, list[str]]]:
    inspector = inspect(connection)
    existing_tables = set(inspector.get_table_names())
    missing_tables = sorted(_BASELINE_TABLES - existing_tables)
    missing_columns: dict[str, list[str]] = {}
    for table_name in sorted(_BASELINE_TABLES & existing_tables):
        actual_columns = {column["name"] for column in inspector.get_columns(table_name)}
        expected_columns = set(Base.metadata.tables[table_name].columns.keys())
        missing = sorted(expected_columns - actual_columns)
        if missing:
            missing_columns[table_name] = missing
    return missing_tables, missing_columns


def _verify_baseline_schema(connection: Connection) -> None:
    missing_tables, missing_columns = _baseline_schema_gaps(connection)
    missing_indexes = _baseline_index_gaps(connection)
    if missing_tables or missing_columns or missing_indexes:
        _log.error(
            "legacy_schema_incomplete",
            reason="baseline_check_failed",
            missing_tables=missing_tables,
            missing_columns=missing_columns,
            missing_indexes=missing_indexes,
        )
        raise RuntimeError(
            "Legacy GRACE database does not satisfy Alembic baseline: "
            f"missing_tables={missing_tables}, missing_columns={missing_columns}, "
            f"missing_indexes={missing_indexes}"
        )


def _baseline_index_gaps(connection: Connection) -> dict[str, list[str]]:
    inspector = inspect(connection)
    expected_by_table: dict[str, dict[str, tuple[tuple[str, ...], bool]]] = {}
    for index_name, table_name, columns, unique in _BASELINE_INDEXES:
        expected_by_table.setdefault(table_name, {})[index_name] = (columns, unique)

    missing_indexes: dict[str, list[str]] = {}
    for table_name, expected_indexes in expected_by_table.items():
        if not inspector.has_table(table_name):
            continue
        actual_indexes = {
            item["name"]: (tuple(item.get("column_names") or ()), bool(item.get("unique")))
            for item in inspector.get_indexes(table_name)
            if item.get("name")
        }
        missing = sorted(
            index_name
            for index_name, definition in expected_indexes.items()
            if actual_indexes.get(index_name) != definition
        )
        if missing:
            missing_indexes[table_name] = missing
    return missing_indexes


def _run_sqlite_column_migrations(target: Engine | Connection) -> None:
    """Apply known additive deltas to a pre-Alembic SQLite database once."""
    if target.dialect.name != "sqlite":
        return

    if isinstance(target, Engine):
        with target.begin() as connection:
            _apply_sqlite_legacy_deltas(connection)
        return

    if target.in_transaction():
        _apply_sqlite_legacy_deltas(target)
    else:
        with target.begin():
            _apply_sqlite_legacy_deltas(target)


def _apply_sqlite_legacy_deltas(connection: Connection) -> None:
    for ddl in _SQLITE_TABLE_CREATIONS:
        connection.execute(text(ddl))

    for table, column, ddl in _SQLITE_COLUMN_MIGRATIONS:
        inspector = inspect(connection)
        if not inspector.has_table(table):
            continue
        columns = {item["name"] for item in inspector.get_columns(table)}
        if column not in columns:
            connection.execute(text(ddl))


def _normalize_sqlite_legacy_indexes(connection: Connection) -> None:
    if connection.dialect.name != "sqlite":
        return

    inspector = inspect(connection)
    for index_name, table_name, columns, unique in _BASELINE_INDEXES:
        if not inspector.has_table(table_name):
            continue
        actual_indexes = {
            item["name"]: (tuple(item.get("column_names") or ()), bool(item.get("unique")))
            for item in inspector.get_indexes(table_name)
            if item.get("name")
        }
        expected_definition = (columns, unique)
        actual_definition = actual_indexes.get(index_name)
        if actual_definition == expected_definition:
            continue
        if actual_definition is not None:
            connection.execute(text(f"DROP INDEX IF EXISTS {_quote_identifier(index_name)}"))

        quoted_columns = ", ".join(_quote_identifier(column) for column in columns)
        unique_sql = "UNIQUE " if unique else ""
        connection.execute(
            text(
                f"CREATE {unique_sql}INDEX IF NOT EXISTS {_quote_identifier(index_name)} "
                f"ON {_quote_identifier(table_name)} ({quoted_columns})"
            )
        )

    for index_name in _SQLITE_LEGACY_INDEX_NAMES:
        connection.execute(text(f"DROP INDEX IF EXISTS {_quote_identifier(index_name)}"))

    _log.info("legacy_indexes_normalized", reason="canonical_index_set")


def _quote_identifier(identifier: str) -> str:
    return '"' + identifier.replace('"', '""') + '"'


# END_BLOCK_MIGRATIONS


# START_BLOCK_SESSION
# START_FUNCTION_CONTRACT
# name: get_db
# purpose: Yield a SQLAlchemy Session with automatic commit/rollback/close.
# inputs: None.
# returns: Session (yielded).
# side_effects: Commits on success, rolls back on exception, and closes the session.
# emitted_logs: None.
# error_behavior: Raises RuntimeError if init_db has not completed.
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


# END_BLOCK_SESSION
