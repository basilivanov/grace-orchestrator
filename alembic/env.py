# ############################################################################
# AI_HEADER: alembic_env — Alembic runtime configuration for GRACE schema
# ############################################################################

# START_MODULE_CONTRACT
# purpose: Configure Alembic with GRACE metadata and the runtime database URL,
#          supporting both CLI connections and an injected init_db connection.
# inputs: Alembic Config, GRACE_DB_URL, and GraceSettings.
# returns: None from migration runner functions.
# side_effects: Opens database connections and executes Alembic migrations.
# emitted_logs: alembic_offline_done, alembic_online_done.
# error_behavior: Propagates configuration, connection, and migration errors.
# END_MODULE_CONTRACT

# START_MODULE_MAP
# mapping:
#   - function: run_migrations_offline
#   - function: run_migrations_online
# END_MODULE_MAP

from __future__ import annotations

import sys
from pathlib import Path

from sqlalchemy import engine_from_config, pool
from sqlalchemy.engine import Connection, Engine

from alembic import context

_config = context.config
_repo_root = (
    Path(_config.config_file_name).resolve().parent
    if _config.config_file_name
    else Path.cwd()
)
_source_root = _repo_root / "src"
if str(_source_root) not in sys.path:
    sys.path.insert(0, str(_source_root))

from grace_control.core.structured_logger import GraceLogger  # noqa: E402
from grace_control.db import resolve_db_url  # noqa: E402
from grace_control.db.schema import Base  # noqa: E402

_log = GraceLogger("alembic_env")
target_metadata = Base.metadata


# START_BLOCK_CONFIG
def _set_runtime_url() -> str:
    database_url = resolve_db_url()
    _config.set_main_option("sqlalchemy.url", database_url.replace("%", "%%"))
    return database_url


def _run_online_migrations(connection: Connection) -> None:
    context.configure(
        connection=connection,
        target_metadata=target_metadata,
        compare_type=True,
    )
    with context.begin_transaction():
        context.run_migrations()


# END_BLOCK_CONFIG


# START_BLOCK_RUNNERS
# START_FUNCTION_CONTRACT
# name: run_migrations_offline
# purpose: Render Alembic migrations without opening a database connection.
# inputs: Runtime Alembic configuration and resolved GRACE database URL.
# returns: None.
# side_effects: Writes migration SQL through Alembic's configured output stream.
# emitted_logs: alembic_offline_done.
# error_behavior: Propagates URL and migration rendering errors.
# END_FUNCTION_CONTRACT
def run_migrations_offline() -> None:
    database_url = _set_runtime_url()
    context.configure(
        url=database_url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )
    with context.begin_transaction():
        context.run_migrations()
    _log.info("alembic_offline_done", reason="sql_rendered")


# START_FUNCTION_CONTRACT
# name: run_migrations_online
# purpose: Execute Alembic migrations using an injected or CLI-created connection.
# inputs: Optional connection in Alembic Config attributes; otherwise runtime URL.
# returns: None.
# side_effects: Opens a connection when needed and executes schema migrations.
# emitted_logs: alembic_online_done.
# error_behavior: Propagates engine, connection, and migration errors.
# END_FUNCTION_CONTRACT
def run_migrations_online() -> None:
    injected_connection = _config.attributes.get("connection")
    if injected_connection is not None:
        if isinstance(injected_connection, Engine):
            with injected_connection.connect() as connection:
                _run_online_migrations(connection)
        else:
            _run_online_migrations(injected_connection)
        _log.info("alembic_online_done", reason="injected_connection")
        return

    _set_runtime_url()
    connectable = engine_from_config(
        _config.get_section(_config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )
    with connectable.connect() as connection:
        _run_online_migrations(connection)
    connectable.dispose()
    _log.info("alembic_online_done", reason="runtime_connection")


# END_BLOCK_RUNNERS


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
