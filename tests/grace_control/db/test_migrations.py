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


def _db_url(db_path: Path) -> str:
    return f"sqlite:///{db_path}"


def _version(db_path: Path) -> list[tuple[str]]:
    with sqlite3.connect(db_path) as connection:
        return connection.execute("SELECT version_num FROM alembic_version").fetchall()


def _columns(db_path: Path, table_name: str) -> set[str]:
    with sqlite3.connect(db_path) as connection:
        return {row[1] for row in connection.execute(f"PRAGMA table_info({table_name})")}


def _create_legacy_fixture(db_path: Path, *, drop_additive_columns: bool = False) -> None:
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
    legacy_engine.dispose()


def test_empty_sqlite_gets_baseline_and_head(tmp_path):
    db_path = tmp_path / "empty.db"
    init_db(_db_url(db_path))

    assert set(Base.metadata.tables).issubset(set(inspect(__import__("grace_control.db", fromlist=["engine"]).engine).get_table_names()))
    assert _version(db_path) == [("0001_grace_legacy_baseline",)]


def test_current_legacy_db_is_stamped_and_data_is_preserved(tmp_path):
    db_path = tmp_path / "legacy.db"
    _create_legacy_fixture(db_path)

    init_db(_db_url(db_path))

    with sqlite3.connect(db_path) as connection:
        assert connection.execute("SELECT id FROM features").fetchall() == [("legacy-f",)]
    assert _version(db_path) == [("0001_grace_legacy_baseline",)]


def test_legacy_fixture_missing_additive_columns_is_normalized(tmp_path):
    db_path = tmp_path / "legacy-additive.db"
    _create_legacy_fixture(db_path, drop_additive_columns=True)

    init_db(_db_url(db_path))

    for table_name, column_name in _ADDITIVE_COLUMNS:
        assert column_name in _columns(db_path, table_name)
    assert _version(db_path) == [("0001_grace_legacy_baseline",)]


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
    assert _version(db_path) == [("0001_grace_legacy_baseline",)]


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

    assert "0001_grace_legacy_baseline (head)" in result.stdout
