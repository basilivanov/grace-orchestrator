"""Alembic foundation tests for fresh and pre-Alembic SQLite databases."""
from __future__ import annotations

import os
import sqlite3
import subprocess
from pathlib import Path

from sqlalchemy import create_engine, inspect, text

from grace_control.db import init_db
from grace_control.db.schema import Base

_ADDITIVE_COLUMNS = (
    ("features", "degraded_reason"),
    ("packet_runs", "model"),
    ("packet_runs", "command_preview"),
    ("packet_runs", "prompt"),
    ("packet_runs", "tokens_in"),
    ("packet_runs", "tokens_out"),
    ("packet_runs", "cost_usd"),
    ("feature_planning_runs", "last_heartbeat"),
    ("leases", "claimed_attempt"),
    ("workers", "pid"),
)
_CANONICAL_STAGE_INDEXES = (
    "ix_stage_runs_packet_id",
    "ix_stage_runs_run_id",
    "ix_stage_runs_feature_id",
    "ix_stage_runs_wave_id",
    "ix_stage_runs_stage_key",
    "ix_stage_runs_trace_id",
)
_LEGACY_STAGE_INDEXES = (
    ("ix_stage_runs_packet", "packet_id"),
    ("ix_stage_runs_stage", "stage_key"),
    ("ix_stage_runs_status", "status"),
    ("ix_stage_runs_trace", "trace_id"),
)


def _db_url(db_path: Path) -> str:
    return f"sqlite:///{db_path}"


def _version(db_path: Path) -> list[tuple[str]]:
    with sqlite3.connect(db_path) as connection:
        return connection.execute("SELECT version_num FROM alembic_version").fetchall()


def _columns(db_path: Path, table_name: str) -> set[str]:
    with sqlite3.connect(db_path) as connection:
        return {row[1] for row in connection.execute(f"PRAGMA table_info({table_name})")}


def _index_names(db_path: Path, table_name: str) -> set[str]:
    with sqlite3.connect(db_path) as connection:
        return {row[1] for row in connection.execute(f"PRAGMA index_list({table_name})")}


def _create_legacy_fixture(
    db_path: Path,
    *,
    drop_additive_columns: bool = False,
    use_legacy_stage_indexes: bool = False,
) -> None:
    legacy_engine = create_engine(_db_url(db_path))
    Base.metadata.create_all(legacy_engine)
    with legacy_engine.begin() as connection:
        connection.execute(
            text(
                "INSERT INTO features "
                "(id, slug, title, spec_json, status, created_at, updated_at) "
                "VALUES ('legacy-f', 'legacy', 'Legacy', '{}', 'NOT_STARTED', "
                "'2026-01-01', '2026-01-01')"
            )
        )
        if drop_additive_columns:
            for table_name, column_name in _ADDITIVE_COLUMNS:
                connection.execute(text(f"ALTER TABLE {table_name} DROP COLUMN {column_name}"))
            for column_name in ("base_sha", "integration_base_sha"):
                connection.execute(text(f"ALTER TABLE packet_runs DROP COLUMN {column_name}"))
        if use_legacy_stage_indexes:
            for index_name in _CANONICAL_STAGE_INDEXES:
                connection.execute(text(f'DROP INDEX IF EXISTS "{index_name}"'))
            for index_name, column_name in _LEGACY_STAGE_INDEXES:
                connection.execute(
                    text(f'CREATE INDEX IF NOT EXISTS "{index_name}" ON stage_runs ("{column_name}")')
                )
    legacy_engine.dispose()


def test_empty_sqlite_gets_baseline_and_head(tmp_path):
    db_path = tmp_path / "empty.db"
    init_db(_db_url(db_path))

    assert set(Base.metadata.tables).issubset(set(inspect(__import__("grace_control.db", fromlist=["engine"]).engine).get_table_names()))
    assert _version(db_path) == [("0004_stale_base_recheck",)]
    assert {"base_sha", "integration_base_sha"}.issubset(_columns(db_path, "packet_runs"))


def test_empty_sqlite_can_be_created_by_alembic_cli(tmp_path):
    db_path = tmp_path / "cli-empty.db"
    db_url = _db_url(db_path)
    env = os.environ.copy()
    env["GRACE_DB_URL"] = db_url
    env["PYTHONPATH"] = "src"

    subprocess.run(
        ["alembic", "upgrade", "head"],
        cwd=Path(__file__).resolve().parents[3],
        env=env,
        capture_output=True,
        check=True,
        text=True,
    )

    with sqlite3.connect(db_path) as connection:
        tables = {
            row[0]
            for row in connection.execute(
                "SELECT name FROM sqlite_master "
                "WHERE type = 'table' AND name NOT LIKE 'sqlite_%'"
            )
        }
    assert tables - {"alembic_version"} == set(Base.metadata.tables)
    assert len(tables - {"alembic_version"}) == 14
    assert _version(db_path) == [("0004_stale_base_recheck",)]
    assert {"base_sha", "integration_base_sha"}.issubset(_columns(db_path, "packet_runs"))


def test_parallel_leases_table_has_required_indexes(tmp_path):
    db_path = tmp_path / "parallel-indexes.db"
    init_db(_db_url(db_path))

    indexes = _index_names(db_path, "parallel_leases")
    assert {
        "ix_parallel_leases_packet_id",
        "ix_parallel_leases_feature_wave",
        "ix_parallel_leases_worker_id",
        "ix_parallel_leases_expires_at",
    }.issubset(indexes)


def test_merge_leases_table_has_expiry_index(tmp_path):
    db_path = tmp_path / "merge-indexes.db"
    init_db(_db_url(db_path))

    indexes = _index_names(db_path, "merge_leases")
    assert "ix_merge_leases_expires_at" in indexes


def test_current_legacy_db_is_stamped_and_data_is_preserved(tmp_path):
    db_path = tmp_path / "legacy.db"
    _create_legacy_fixture(db_path)

    init_db(_db_url(db_path))

    with sqlite3.connect(db_path) as connection:
        assert connection.execute("SELECT id FROM features").fetchall() == [("legacy-f",)]
    assert _version(db_path) == [("0004_stale_base_recheck",)]


def test_legacy_fixture_missing_additive_columns_is_normalized(tmp_path):
    db_path = tmp_path / "legacy-additive.db"
    _create_legacy_fixture(db_path, drop_additive_columns=True)

    init_db(_db_url(db_path))

    for table_name, column_name in _ADDITIVE_COLUMNS:
        assert column_name in _columns(db_path, table_name)
    assert _version(db_path) == [("0004_stale_base_recheck",)]
    assert {"base_sha", "integration_base_sha"}.issubset(_columns(db_path, "packet_runs"))


def test_legacy_stage_indexes_are_normalized_before_stamp(tmp_path):
    db_path = tmp_path / "legacy-indexes.db"
    _create_legacy_fixture(db_path, use_legacy_stage_indexes=True)

    assert _index_names(db_path, "stage_runs") >= {name for name, _column in _LEGACY_STAGE_INDEXES}
    assert not _index_names(db_path, "stage_runs") & set(_CANONICAL_STAGE_INDEXES)

    init_db(_db_url(db_path))

    stage_indexes = _index_names(db_path, "stage_runs")
    assert set(_CANONICAL_STAGE_INDEXES).issubset(stage_indexes)
    assert not stage_indexes & {name for name, _column in _LEGACY_STAGE_INDEXES}
    assert _version(db_path) == [("0004_stale_base_recheck",)]


def test_events_only_database_is_not_detected_as_legacy_grace(tmp_path):
    db_path = tmp_path / "not-grace.db"
    engine = create_engine(_db_url(db_path))
    with engine.begin() as connection:
        connection.execute(text("CREATE TABLE events (id INTEGER PRIMARY KEY)"))

    from grace_control.db import _is_legacy_grace_db

    with engine.connect() as connection:
        assert not _is_legacy_grace_db(connection)
    engine.dispose()


def test_repeated_init_is_idempotent_and_skips_legacy_bridge(tmp_path, monkeypatch):
    db_path = tmp_path / "repeat.db"
    _create_legacy_fixture(db_path, drop_additive_columns=True)
    init_db(_db_url(db_path))

    import grace_control.db as db_module

    bridge_calls: list[object] = []
    monkeypatch.setattr(
        db_module,
        "_run_sqlite_column_migrations",
        lambda target: bridge_calls.append(target),
    )
    init_db(_db_url(db_path))

    assert bridge_calls == []
    assert _version(db_path) == [("0004_stale_base_recheck",)]


def test_alembic_current_reports_head_after_startup(tmp_path):
    db_path = tmp_path / "current.db"
    db_url = _db_url(db_path)
    init_db(db_url)

    env = os.environ.copy()
    env["GRACE_DB_URL"] = db_url
    env["PYTHONPATH"] = "src"
    result = subprocess.run(
        ["alembic", "current"],
        cwd=Path(__file__).resolve().parents[3],
        env=env,
        capture_output=True,
        check=True,
        text=True,
    )

    assert "0004_stale_base_recheck (head)" in result.stdout
