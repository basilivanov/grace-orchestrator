"""Integration tests for the admin v2 router (TZ_ADMIN_PANEL.md).

Asserts:
1. /api/admin/overview returns stats / health / recent_events / blocked / workers.
2. /api/admin/packet/{id}/detail returns worker_id / model / started_at / elapsed.
3. /api/admin/packet/{id}/detail returns 404 for missing packets.
4. /api/admin/packet/{id}/blocking_decision returns null for non-blocking states.
5. /api/admin/packet/{id}/blocking_decision returns 200 with has_blocking for rejected.
6. /api/admin/packet/{id}/timeline returns events with payload.
7. /api/admin/packet/{id}/runs returns runs list with model.
8. /api/admin/packet/{id}/runs/{run_id} returns full run with command_preview.
9. /api/admin/packet/{id}/runs/{run_id}/evidence returns stages.
10. /api/admin/packet/{id}/sessions returns {sessions, reason: "table_missing"}.
11. /api/admin/packet/{id}/runs/{run_id}/artifacts returns tree.
12. /api/admin/packet/{id}/runs/{run_id}/artifacts/file path-traversal → 403.
13. /api/admin/packet/{id}/runs/{run_id}/logs returns lines.
14. /api/admin/feature/{id}/summary returns feature + waves.
15. /api/admin/search returns results by packet title.
16. /api/admin/system/health returns shape.
17. /api/admin/system/workers returns shape.
18. POST /api/admin/packet/{id}/resume|delete|stop → 501 with planned: v2.
19. /admin returns the SPA shell HTML.
20. /static/admin.css and /static/admin.js are served.
21. /openapi.json contains all admin endpoints.
22. Blocking decision's decided_by is populated from recovery_* event.
"""
import os
from datetime import datetime
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from grace_control.api.main import app
from grace_control.db import get_db, init_db
from grace_control.db.schema import (
    Event, Feature, Packet, PacketRun, Wave,
)


# ── Fixtures ────────────────────────────────────────────────────────────────


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("GRACE_CONTEXT_DISABLED", "true")
    db_url = f"sqlite:///{tmp_path}/admin_router_test.db"
    monkeypatch.setenv("GRACE_DB_URL", db_url)
    init_db(db_url)
    return TestClient(app)


def _seed_rejected(client, evidence_path: str = ""):
    with get_db() as db:
        db.add(Feature(id="F1", slug="f1", title="Feature 1", spec_json={}, status="IN_PROGRESS"))
        db.add(Wave(id="W01", feature_id="F1", slug="w01", title="Wave 1", order=1, status="IN_PROGRESS"))
        db.add(Packet(
            id="p1", feature_id="F1", wave_id="W01", slug="p1", title="My Packet",
            spec_json={"role": "coder"},
            state="rejected", attempt_count=1, max_attempts=3, acceptance_profile="NORMAL",
        ))
        rj = {
            "acceptance_report": {
                "final_verdict": "rejected",
                "summary": "ruff failed on src/x.py",
                "stages": [
                    {"name": "T0_SCOPE_AND_LINT", "status": "passed", "commands": []},
                    {"name": "T1_TARGETED_TESTS", "status": "failed",
                     "blocking_issues": ["ruff: E501 line too long"],
                     "commands": [{"command": "ruff check src/", "exit_code": 1,
                                   "stderr": "E501\n" * 50}]},
                ],
            },
            "recovery": {"action": "BLOCK_FEATURE", "reason": "max_attempts reached",
                         "current_executor_id": "exec-A"},
        }
        db.add(PacketRun(
            id="p1-1", packet_id="p1", run_number=1, executor_id="exec-A",
            worker_id="w-1", model="deepseek/deepseek-v4-flash",
            status="rejected", duration_ms=1234,
            command_preview=["opencode", "run", "--model", "deepseek-v4-flash"],
            prompt="Implement login",
            started_at=datetime(2026, 6, 7, 10, 0, 0),
            finished_at=datetime(2026, 6, 7, 10, 0, 5),
            evidence_path=evidence_path,
            result_json=rj,
        ))
        db.add(Event(
            event_type="recovery_decision_made", entity_type="packet", entity_id="p1",
            payload_json={"component": "feature_recovery", "action": "BLOCK_FEATURE",
                          "reason": "max_attempts"},
            trace_id="trace-1",
            timestamp=datetime(2026, 6, 7, 10, 0, 4),
        ))
        db.commit()


def _seed_features_tree(client):
    """One feature with two waves, each with one packet — for /features endpoint tests."""
    with get_db() as db:
        db.add(Feature(
            id="F_TREE", slug="feature-tree-test", title="Feature Tree Test",
            spec_json={}, status="IN_PROGRESS",
        ))
        db.add(Wave(
            id="W_TREE_1", feature_id="F_TREE", slug="wave-tree-1",
            title="Wave Tree 1", order=1, status="DEGRADED",
        ))
        db.add(Wave(
            id="W_TREE_2", feature_id="F_TREE", slug="wave-tree-2",
            title="Wave Tree 2", order=2, status="NOT_STARTED",
        ))
        db.add(Packet(
            id="p_tree_1", feature_id="F_TREE", wave_id="W_TREE_1",
            slug="tree-packet-one", title="Tree Packet One",
            spec_json={"role": "coder"},
            state="rejected", attempt_count=2, max_attempts=5,
            acceptance_profile="NORMAL",
        ))
        db.add(Packet(
            id="p_tree_2", feature_id="F_TREE", wave_id="W_TREE_2",
            slug="tree-packet-two", title="Tree Packet Two",
            spec_json={"role": "coder"},
            state="draft", attempt_count=0, max_attempts=5,
            acceptance_profile="NORMAL",
        ))
        db.commit()


# ── 1. overview ────────────────────────────────────────────────────────────


def test_overview_shape(client):
    r = client.get("/api/admin/overview")
    assert r.status_code == 200
    body = r.json()
    for k in ("stats", "health", "recent_events", "blocked", "workers", "fetched_at"):
        assert k in body
    assert "by_state" in body["stats"]


# ── 1a. features tree (used by Overview main view) ─────────────────────────


def test_features_tree_empty(client):
    r = client.get("/api/admin/features")
    assert r.status_code == 200
    body = r.json()
    assert "features" in body
    assert isinstance(body["features"], list)


def test_features_tree_includes_waves_and_packets_with_slugs(client):
    """Each feature → waves → packets must include id+slug so UI can show them together."""
    _seed_features_tree(client)
    r = client.get("/api/admin/features")
    body = r.json()
    assert len(body["features"]) >= 1
    feat = body["features"][0]
    assert "id" in feat and "slug" in feat and "title" in feat
    assert "status" in feat
    assert isinstance(feat["waves"], list) and len(feat["waves"]) >= 1
    wave = feat["waves"][0]
    assert "id" in wave and "slug" in wave and "title" in wave and "order" in wave
    assert isinstance(wave["packets"], list) and len(wave["packets"]) >= 1
    pkt = wave["packets"][0]
    # id+slug together is the contract — UI shows them adjacent.
    assert "id" in pkt and "slug" in pkt
    assert "state" in pkt
    assert "attempt_count" in pkt and "max_attempts" in pkt


# ── 2-5. packet detail / blocking decision ─────────────────────────────────


def test_packet_detail_returns_worker_model_elapsed(client):
    _seed_rejected(client)
    r = client.get("/api/admin/packet/p1/detail")
    assert r.status_code == 200
    body = r.json()
    assert body["packet"]["id"] == "p1"
    assert body["worker_id"] == "w-1"
    assert body["model"] == "deepseek/deepseek-v4-flash"
    assert body["started_at"] is not None
    assert body["elapsed_seconds"] is not None
    assert body["is_running"] is False
    assert body["recommendation"] in ("retry", "manual", "none")
    # state_machine: 4-step lifecycle for operator console
    sm = body["state_machine"]
    assert "steps" in sm and len(sm["steps"]) == 4
    assert [s["key"] for s in sm["steps"]] == ["created", "claimed", "reviewed", "result"]
    # For a rejected packet, reviewed=failed and result=failed
    assert sm["steps"][2]["state"] == "failed"
    assert sm["steps"][3]["state"] == "failed"
    assert sm["steps"][3]["label"] == "Rejected"


def test_packet_detail_404_for_missing(client):
    r = client.get("/api/admin/packet/missing/detail")
    assert r.status_code == 404


def test_blocking_decision_rejected_returns_200(client):
    _seed_rejected(client)
    r = client.get("/api/admin/packet/p1/blocking_decision")
    assert r.status_code == 200
    body = r.json()
    assert body["has_blocking"] is True
    assert body["state"] == "rejected"
    assert body["action"] == "BLOCK_FEATURE"
    assert body["reason"] == "max_attempts reached"
    assert body["decided_by"] == "feature_recovery"
    assert body["last_failure"] is not None
    assert body["last_failure"]["command_preview"] == [
        "opencode", "run", "--model", "deepseek-v4-flash",
    ]


def test_blocking_decision_running_returns_has_blocking_false(client):
    with get_db() as db:
        db.add(Feature(id="F", slug="f", title="F", spec_json={}, status="IN_PROGRESS"))
        db.add(Wave(id="W", feature_id="F", slug="w", title="W", order=1, status="IN_PROGRESS"))
        db.add(Packet(id="p_running", feature_id="F", wave_id="W", slug="p",
                      title="running", spec_json={}, state="running"))
        db.commit()
    r = client.get("/api/admin/packet/p_running/blocking_decision")
    assert r.status_code == 200
    assert r.json()["has_blocking"] is False


# ── 6. timeline ────────────────────────────────────────────────────────────


def test_timeline_returns_events(client):
    _seed_rejected(client)
    r = client.get("/api/admin/packet/p1/timeline?limit=10")
    assert r.status_code == 200
    body = r.json()
    assert "events" in body
    assert any(e["event_type"] == "recovery_decision_made" for e in body["events"])


# ── 7-8. runs ──────────────────────────────────────────────────────────────


def test_packet_runs_returns_list(client):
    _seed_rejected(client)
    r = client.get("/api/admin/packet/p1/runs")
    assert r.status_code == 200
    body = r.json()
    assert len(body["runs"]) == 1
    assert body["runs"][0]["model"] == "deepseek/deepseek-v4-flash"


def test_packet_run_returns_full_data(client):
    _seed_rejected(client)
    r = client.get("/api/admin/packet/p1/runs/1")
    assert r.status_code == 200
    body = r.json()
    assert body["model"] == "deepseek/deepseek-v4-flash"
    assert body["command_preview"] == ["opencode", "run", "--model", "deepseek-v4-flash"]
    assert body["prompt"] == "Implement login"
    assert "artifacts_summary" in body


def test_packet_run_404_for_missing(client):
    r = client.get("/api/admin/packet/p1/runs/999")
    assert r.status_code == 404


# ── 9. evidence ────────────────────────────────────────────────────────────


def test_run_evidence_returns_stages(client):
    _seed_rejected(client)
    r = client.get("/api/admin/packet/p1/runs/1/evidence")
    assert r.status_code == 200
    body = r.json()
    assert body["verdict"] == "rejected"
    assert any(s["name"] == "T1_TARGETED_TESTS" for s in body["stages"])


# ── 10. sessions ───────────────────────────────────────────────────────────


def test_sessions_returns_table_missing(client):
    _seed_rejected(client)
    # Table exists by default (create_all). Drop it to exercise
    # the forward-compat table_missing path.
    from sqlalchemy import text as _t
    with get_db() as db:
        db.execute(_t("DROP TABLE IF EXISTS agent_sessions"))
        db.commit()
    r = client.get("/api/admin/packet/p1/sessions")
    assert r.status_code == 200
    body = r.json()
    assert body["reason"] == "table_missing"
    assert body["sessions"] == []


# ── 11-13. artifacts + logs ────────────────────────────────────────────────


def test_artifacts_returns_tree(client, tmp_path):
    ev = tmp_path / "ev" / "p1-1"
    ev.mkdir(parents=True)
    (ev / "log.txt").write_text("hello")
    (ev / "image.png").write_bytes(b"\x89PNG\r\n\x1a\n")
    _seed_rejected(client, evidence_path=str(ev))
    r = client.get("/api/admin/packet/p1/runs/1/artifacts")
    assert r.status_code == 200
    body = r.json()
    assert len(body["tree"]) >= 2
    flat = _flatten(body["tree"])
    names = {n["name"] for n in flat}
    assert "log.txt" in names
    assert "image.png" in names


def test_artifact_file_path_traversal_returns_403(client, tmp_path):
    ev = tmp_path / "ev" / "p1-1"
    ev.mkdir(parents=True)
    (ev / "ok.txt").write_text("ok")
    _seed_rejected(client, evidence_path=str(ev))
    r = client.get("/api/admin/packet/p1/runs/1/artifacts/file",
                   params={"path": "../../../etc/passwd"})
    assert r.status_code == 403


def test_artifact_file_returns_content(client, tmp_path):
    ev = tmp_path / "ev" / "p1-1"
    ev.mkdir(parents=True)
    (ev / "log.txt").write_text("hello world\n")
    _seed_rejected(client, evidence_path=str(ev))
    r = client.get("/api/admin/packet/p1/runs/1/artifacts/file",
                   params={"path": "log.txt"})
    assert r.status_code == 200
    assert "hello" in r.text


def test_logs_returns_lines(client, tmp_path):
    ev = tmp_path / "ev" / "p1-1"
    ev.mkdir(parents=True)
    (ev / "agent_output.log").write_text("INFO ok\nERROR bad\n")
    _seed_rejected(client, evidence_path=str(ev))
    r = client.get("/api/admin/packet/p1/runs/1/logs",
                   params={"stream": "agent", "tail": 10, "filter": "ERROR"})
    assert r.status_code == 200
    body = r.json()
    assert body["lines"] == ["ERROR bad"]


# ── 14-17. feature / search / system ──────────────────────────────────────


def test_feature_summary(client):
    _seed_rejected(client)
    r = client.get("/api/admin/feature/F1/summary")
    assert r.status_code == 200
    body = r.json()
    assert body["feature"]["id"] == "F1"
    assert len(body["waves"]) == 1
    assert len(body["waves"][0]["packets"]) == 1


def test_feature_summary_404(client):
    r = client.get("/api/admin/feature/missing/summary")
    assert r.status_code == 404


def test_search_finds_packet_by_title(client):
    _seed_rejected(client)
    r = client.get("/api/admin/search", params={"q": "My Packet"})
    assert r.status_code == 200
    body = r.json()
    assert any(r2["kind"] == "packet" and r2["id"] == "p1" for r2 in body["results"])


def test_search_finds_run_by_executor(client):
    _seed_rejected(client)
    r = client.get("/api/admin/search", params={"q": "exec-A"})
    assert r.status_code == 200
    body = r.json()
    assert any(r2["kind"] == "run" and r2["executor_id"] == "exec-A" for r2 in body["results"])


def test_system_health_shape(client):
    r = client.get("/api/admin/system/health")
    assert r.status_code == 200
    body = r.json()
    for k in ("supervisor_alive", "workers_alive", "db_ok", "code_sha", "version"):
        assert k in body


def test_system_workers_shape(client):
    r = client.get("/api/admin/system/workers")
    assert r.status_code == 200
    assert "workers" in r.json()


# ── 18. planned stubs ──────────────────────────────────────────────────────


def test_resume_stub_returns_501(client):
    r = client.post("/api/admin/packet/p1/resume")
    assert r.status_code == 501
    body = r.json()
    assert body["error"] == "not_implemented"
    assert body["planned"] == "v2"
    assert "doc" in body


def test_delete_stub_returns_501(client):
    r = client.post("/api/admin/packet/p1/delete")
    assert r.status_code == 501
    body = r.json()
    assert body["planned"] == "v2"


def test_stop_stub_returns_501(client):
    r = client.post("/api/admin/packet/p1/stop")
    assert r.status_code == 501
    body = r.json()
    assert body["planned"] == "v2"


# ── 19-20. SPA shell + static ─────────────────────────────────────────────


def test_admin_shell_serves_html(client):
    r = client.get("/admin")
    assert r.status_code == 200
    assert "text/html" in r.headers["content-type"]
    assert "<html" in r.text
    assert "/static/admin.css" in r.text
    assert "/static/admin.js" in r.text


def test_admin_static_assets_served(client):
    r = client.get("/static/admin.css")
    assert r.status_code == 200
    assert "text/css" in r.headers["content-type"] or "css" in r.headers.get("content-type", "")
    r = client.get("/static/admin.js")
    assert r.status_code == 200
    body = r.text
    assert "window.setHealth" in body
    assert "window.api" in body
    assert "window.replayStage" in body


def test_packet_detail_template_smoke(client):
    """Template smoke: /admin with packet_id shows PIPELINE, CURRENT RUN, and stage rows."""
    _seed_rejected(client)
    r = client.get("/admin?packet_id=p1")
    assert r.status_code == 200
    html = r.text
    assert "Pipeline" in html
    assert "CURRENT RUN" in html
    assert "pipeline-card" in html
    assert "Materialized" in html
    assert "Executor selected" in html
    assert "Coder run" in html
    assert "Started" in html or "started" in html
    assert "Duration" in html or "duration" in html
    assert "Attempt" in html or "attempt" in html
    assert "Worker" in html or "worker" in html


def test_packet_detail_aggregation_finished_at(client):
    """Aggregation DTO exposes finished_at from last run."""
    _seed_rejected(client)
    r = client.get("/api/admin/packet/p1/detail")
    assert r.status_code == 200
    body = r.json()
    assert "finished_at" in body
    assert body["finished_at"] is not None
    assert body["is_running"] is False


def test_pipeline_visible_rows_collapses_normal_skipped():
    """pipeline_visible_rows collapses NORMAL skipped T0/T1/T2/verifier into one row."""
    from grace_control.ui.admin_template_filters import pipeline_visible_rows
    stages = [
        {"key": "materialized", "label": "Materialized", "status": "done", "started_at": "2026-06-10T10:00:00Z", "finished_at": "2026-06-10T10:00:00Z", "duration_ms": 0, "meta": "p1"},
        {"key": "executor", "label": "Executor selected", "status": "done", "started_at": "2026-06-10T10:00:01Z", "finished_at": "2026-06-10T10:00:01Z", "duration_ms": 0, "meta": "coder-x"},
        {"key": "coder_run", "label": "Coder run", "status": "done", "started_at": "2026-06-10T10:00:02Z", "finished_at": "2026-06-10T10:00:30Z", "duration_ms": 28000, "meta": "w-1"},
        {"key": "t0", "label": "T0 scope/lint", "status": "skipped", "meta": "no separate run (NORMAL profile)"},
        {"key": "t1", "label": "T1 tests", "status": "skipped", "meta": "no separate run (NORMAL profile)"},
        {"key": "t2", "label": "T2 smoke/e2e", "status": "skipped", "meta": "no separate run (NORMAL profile)"},
        {"key": "verifier", "label": "Evidence verifier", "status": "skipped", "meta": "not in profile (NORMAL)"},
        {"key": "reviewer", "label": "Reviewer gate", "status": "done", "meta": "REJECTED"},
        {"key": "merge", "label": "Merge", "status": "skipped", "meta": "not reached"},
    ]
    rows = pipeline_visible_rows(stages, packet_state="rejected", acceptance_profile="NORMAL")
    labels = [r["label"] for r in rows]
    assert "Skipped by NORMAL profile" in labels
    assert "T0 scope/lint" not in labels  # collapsed
    assert "T1 tests" not in labels
    assert "Materialized" in labels
    assert "Coder run" in labels
    # Verify meta_label
    for r in rows:
        if r["label"] == "Skipped by NORMAL profile":
            assert r["meta_label"] == "Stages"
        if r["label"] == "Materialized":
            assert r["meta_label"] == "Meta"


def test_pipeline_visible_rows_hides_pending_reviewer_merge():
    """pipeline_visible_rows hides pending unreached reviewer/merge stages."""
    from grace_control.ui.admin_template_filters import pipeline_visible_rows
    stages = [
        {"key": "materialized", "label": "Materialized", "status": "done", "meta": "p1"},
        {"key": "executor", "label": "Executor selected", "status": "done", "meta": "executor"},
        {"key": "coder_run", "label": "Coder run", "status": "running", "meta": "w-1"},
        {"key": "reviewer", "label": "Reviewer gate", "status": "pending", "meta": ""},
        {"key": "merge", "label": "Merge", "status": "pending", "meta": ""},
    ]
    rows = pipeline_visible_rows(stages, packet_state="running", acceptance_profile="NORMAL")
    labels = [r["label"] for r in rows]
    assert "Reviewer gate" not in labels
    assert "Merge" not in labels
    assert "Coder run" in labels
    assert "Materialized" in labels


def test_pipeline_visible_rows_meta_label():
    """pipeline_visible_rows sets correct meta_label per key."""
    from grace_control.ui.admin_template_filters import pipeline_visible_rows
    stages = [
        {"key": "materialized", "label": "Materialized", "status": "done", "meta": "p1"},
        {"key": "executor", "label": "Executor selected", "status": "done", "meta": "executor"},
        {"key": "coder_run", "label": "Coder run", "status": "done", "meta": "w-1"},
    ]
    rows = pipeline_visible_rows(stages, packet_state="accepted", acceptance_profile="NORMAL")
    labels = {r["label"]: r["meta_label"] for r in rows}
    assert labels.get("Materialized") == "Meta"
    assert labels.get("Executor selected") == "Meta"
    assert labels.get("Coder run") == "Worker"


def test_pipeline_visible_rows_adds_terminal_for_cancelled():
    """pipeline_visible_rows adds a Cancelled/Final state row for cancelled packets."""
    from grace_control.ui.admin_template_filters import pipeline_visible_rows
    stages = [
        {"key": "materialized", "label": "Materialized", "status": "done", "meta": ""},
        {"key": "executor", "label": "Executor selected", "status": "done", "meta": ""},
        {"key": "coder_run", "label": "Coder run", "status": "done", "meta": ""},
    ]
    rows = pipeline_visible_rows(stages, packet_state="cancelled", acceptance_profile="NORMAL")
    labels = [r["label"] for r in rows]
    assert "Final state" in labels
    assert any("cancelled" in (r.get("meta") or "").lower() for r in rows)


# ── 21. OpenAPI contains admin endpoints ──────────────────────────────────


def test_openapi_contains_admin_endpoints(client):
    r = client.get("/openapi.json")
    assert r.status_code == 200
    paths = r.json()["paths"]
    must_have = [
        "/api/admin/overview",
        "/api/admin/packet/{packet_id}/detail",
        "/api/admin/packet/{packet_id}/blocking_decision",
        "/api/admin/packet/{packet_id}/timeline",
        "/api/admin/packet/{packet_id}/runs",
        "/api/admin/packet/{packet_id}/runs/{run_id}",
        "/api/admin/packet/{packet_id}/runs/{run_id}/evidence",
        "/api/admin/packet/{packet_id}/sessions",
        "/api/admin/packet/{packet_id}/runs/{run_id}/artifacts",
        "/api/admin/packet/{packet_id}/runs/{run_id}/artifacts/file",
        "/api/admin/packet/{packet_id}/runs/{run_id}/logs",
        "/api/admin/feature/{feature_id}/summary",
        "/api/admin/search",
        "/api/admin/system/health",
        "/api/admin/system/workers",
        "/api/admin/packet/{packet_id}/resume",
        "/api/admin/packet/{packet_id}/delete",
        "/api/admin/packet/{packet_id}/stop",
        "/admin",
    ]
    for p in must_have:
        assert p in paths, f"OpenAPI missing {p}"


# ── helpers ────────────────────────────────────────────────────────────────


def _flatten(nodes):
    out = []
    for n in nodes:
        if n["type"] == "file":
            out.append(n)
        else:
            out.extend(_flatten(n.get("children", [])))
    return out
