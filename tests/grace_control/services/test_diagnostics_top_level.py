"""Tests for diagnostics surface at result_json.diagnostics top-level (TZ §6.6).

Before this fix, diagnostics lived under result_json.legacy_result.evidence,
which made them invisible to UI/admin/trace that consumed top-level.
"""
from __future__ import annotations

import json
import sqlite3
from datetime import UTC, datetime

import pytest

from grace_control.db import init_db
from grace_control.db.schema import PacketRun


@pytest.fixture
def _db(tmp_path):
    """Init a real on-disk SQLite so we can read result_json from a
    separate connection (verifying the JSON column was actually
    serialized, not just a transient in-memory ORM attribute)."""
    db_path = tmp_path / "diag.db"
    init_db(f"sqlite:///{db_path}")
    return db_path


def test_update_run_result_persists_diagnostics_top_level(_db):
    from grace_control.db import get_db
    from grace_control.services.evidence_service import EvidenceService

    run_id = "pkt_DIAG-R01"
    with get_db() as db:
        db.add(PacketRun(
            id=run_id, packet_id="pkt_DIAG", run_number=1,
            executor_id="test", worker_id="w1", status="rejected",
            started_at=datetime.now(UTC), finished_at=datetime.now(UTC),
            duration_ms=100,
        ))
        db.commit()

    EvidenceService().update_run_result(
        run_id=run_id, status="rejected",
        legacy_result={"ok": False, "stderr": "boom"},
        acceptance_report=None,  # .to_dict() is called only on truthy
        evidence_verifier_report={},
        reviewer_report={},
        evidence_path="",
        duration_ms=100,
        diagnostics={
            "failure_class": "session_not_found",
            "failure_stage": "agent_run",
            "stderr_tail": "Session not found: ses_xxx",
        },
    )

    conn = sqlite3.connect(str(_db))
    row = conn.execute(
        "SELECT result_json FROM packet_runs WHERE id=?", (run_id,),
    ).fetchone()
    conn.close()
    assert row is not None and row[0], f"no row found for {run_id}"
    payload = json.loads(row[0])
    assert "diagnostics" in payload, f"expected top-level diagnostics, got keys {list(payload)}"
    diag = payload["diagnostics"]
    assert diag["failure_class"] == "session_not_found"
    assert diag["failure_stage"] == "agent_run"
    assert diag["stderr_tail"].startswith("Session not found")


def test_update_run_result_omits_diagnostics_when_not_provided(_db):
    from grace_control.db import get_db
    from grace_control.services.evidence_service import EvidenceService

    run_id = "pkt_NODIAG-R01"
    with get_db() as db:
        db.add(PacketRun(
            id=run_id, packet_id="pkt_NODIAG", run_number=1,
            executor_id="test", worker_id="w1", status="accepted",
            started_at=datetime.now(UTC), finished_at=datetime.now(UTC),
            duration_ms=100,
        ))
        db.commit()

    EvidenceService().update_run_result(
        run_id=run_id, status="accepted",
        legacy_result={"ok": True},
        acceptance_report=None,
        evidence_verifier_report={},
        reviewer_report={},
        evidence_path="",
        duration_ms=100,
    )
    conn = sqlite3.connect(str(_db))
    row = conn.execute(
        "SELECT result_json FROM packet_runs WHERE id=?", (run_id,),
    ).fetchone()
    conn.close()
    payload = json.loads(row[0])
    # When no diagnostics are passed, key is simply absent.
    assert "diagnostics" not in payload
