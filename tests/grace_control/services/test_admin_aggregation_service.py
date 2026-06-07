"""Unit tests for AdminAggregationService (TZ_ADMIN_PANEL.md).

Asserts:
1. get_overview returns stats / health / recent_events / blocked / workers.
2. get_packet_detail returns packet, worker, model, started_at, elapsed, runs.
3. get_packet_blocking_decision returns null for non-blocking states.
4. get_packet_blocking_decision returns decided_by / action / reason / last_failure.
5. get_packet_runs returns is_running + elapsed_seconds.
6. get_packet_run includes command_preview / prompt / model / artifacts_summary.
7. get_packet_evidence reads acceptance_report.stages with T0/T1/T2.
8. get_packet_artifacts builds a tree with sizes.
9. get_artifact_file path-traversal safe (target must be inside evidence_dir).
10. get_packet_logs returns lines / total / truncated / source_file.
11. get_packet_sessions returns reason="table_missing" when agent_sessions absent.
12. get_feature_summary groups packets by wave.
13. search finds packets / features / runs by substring.
14. get_system_health returns supervisor_alive / workers_alive / db_ok / code_sha.
15. get_workers returns active workers with current_packet_id.
16. fmtSize / fmtTime / fmtElapsed helpers (TZ §Helpers).
17. _classify_artifact classifies by extension.
18. Forward-compat: blocked_decision reads recovery_* events for decided_by.
19. Forward-compat: evidence tab handles empty stages (planned T2_BROWSER/T3_VISUAL).
20. _detect_decision_component returns "feature_recovery" / "recovery_controller" / "acceptance_pipeline".
"""
import os
import re
from datetime import datetime, timedelta
from pathlib import Path

import pytest

from grace_control.db import get_db, init_db
from grace_control.db.schema import (
    Event, Feature, Packet, PacketRun, PacketState, Wave, Worker,
)
from grace_control.services.admin_aggregation_service import (
    AdminAggregationService, _classify_artifact, _elapsed_seconds, _is_running,
)


# ── Fixtures ────────────────────────────────────────────────────────────────


@pytest.fixture
def db_url(tmp_path, monkeypatch):
    url = f"sqlite:///{tmp_path}/admin_svc_test.db"
    monkeypatch.setenv("GRACE_DB_URL", url)
    monkeypatch.setenv("GRACE_CONTEXT_DISABLED", "true")
    init_db(url)
    return url


@pytest.fixture
def svc():
    return AdminAggregationService()


@pytest.fixture
def session():
    """Yield a session inside a get_db() context manager."""
    with get_db() as db:
        yield db


def _seed_rejected_packet(
    session,
    state: str = "rejected",
    run_status: str = "rejected",
    recovery: dict | None = None,
    spec_json: dict | None = None,
    evidence_path: str = "",
):
    """Seed Feature/Wave/Packet/PacketRun + events for a rejected packet."""
    session.add(Feature(id="F1", slug="f1", title="Feature 1", spec_json={}, status="IN_PROGRESS"))
    session.add(Wave(id="W01", feature_id="F1", slug="w01", title="Wave 1", order=1, status="IN_PROGRESS"))
    session.add(Packet(
        id="p1", feature_id="F1", wave_id="W01", slug="p1", title="My Packet",
        spec_json=spec_json or {},
        state=state, attempt_count=1, max_attempts=3, acceptance_profile="NORMAL",
    ))
    rj = {
        "acceptance_report": {
            "final_verdict": "rejected",
            "summary": "ruff failed on src/x.py",
            "stages": [
                {"name": "T0_SCOPE_AND_LINT", "status": "passed", "commands": []},
                {"name": "T1_TARGETED_TESTS", "status": "failed",
                 "blocking_issues": ["ruff: E501 line too long"],
                 "commands": [
                     {"command": "ruff check src/", "exit_code": 1,
                      "stderr": "src/x.py:1:1: E501 line too long\n" * 50},
                 ]},
            ],
        },
    }
    if recovery:
        rj["recovery"] = recovery
    session.add(PacketRun(
        id="p1-1", packet_id="p1", run_number=1, executor_id="exec-A",
        worker_id="w-1", model="deepseek/deepseek-v4-flash",
        status=run_status, duration_ms=1234,
        command_preview=["opencode", "run", "--model", "deepseek-v4-flash"],
        prompt="Implement the login screen",
        started_at=datetime(2026, 6, 7, 10, 0, 0),
        finished_at=datetime(2026, 6, 7, 10, 0, 5),
        evidence_path=evidence_path,
        result_json=rj,
    ))
    session.add(Event(
        event_type="recovery_decision_made", entity_type="packet", entity_id="p1",
        payload_json={"component": "feature_recovery",
                      "action": "BLOCK_FEATURE", "reason": "max_attempts"},
        trace_id="trace-1",
        timestamp=datetime(2026, 6, 7, 10, 0, 4),
    ))
    session.commit()


# ── 1. overview ────────────────────────────────────────────────────────────


def test_overview_shape(db_url, svc, session):
    out = svc.get_overview(session)
    assert "stats" in out
    assert "health" in out
    assert "recent_events" in out
    assert "blocked" in out
    assert "workers" in out
    assert "fetched_at" in out
    assert "by_state" in out["stats"]
    assert "features" in out["stats"]


def test_overview_blocked_lists_blocked_packets(db_url, svc, session):
    session.add(Feature(id="F1", slug="f1", title="F1", spec_json={}, status="IN_PROGRESS"))
    session.add(Wave(id="W1", feature_id="F1", slug="w1", title="W1", order=1, status="IN_PROGRESS"))
    session.add(Packet(id="p_blocked", feature_id="F1", wave_id="W1", slug="p",
                       title="Blocked P", spec_json={}, state="blocked_recoverable",
                       attempt_count=3, max_attempts=3))
    session.commit()
    out = svc.get_overview(session)
    assert any(p["id"] == "p_blocked" for p in out["blocked"])


def test_overview_workers_include_current_packet(db_url, svc, session):
    session.add(Worker(id="w-1", status="active", current_packet_id="p-1",
                       last_heartbeat=datetime.utcnow(), started_at=datetime.utcnow()))
    session.commit()
    out = svc.get_overview(session)
    assert any(w["id"] == "w-1" and w["current_packet_id"] == "p-1" for w in out["workers"])


# ── 2. packet detail ───────────────────────────────────────────────────────


def test_packet_detail_includes_worker_model_elapsed(db_url, svc, session):
    _seed_rejected_packet(session)
    out = svc.get_packet_detail(session, "p1")
    assert out is not None
    assert out["packet"]["id"] == "p1"
    assert out["worker_id"] == "w-1"
    assert out["model"] == "deepseek/deepseek-v4-flash"
    assert out["started_at"] is not None
    assert out["elapsed_seconds"] is not None
    assert out["is_running"] is False
    assert len(out["runs_summary"]) == 1
    assert out["recommendation"] in ("retry", "manual", "none")


def test_packet_detail_returns_none_for_missing(db_url, svc, session):
    out = svc.get_packet_detail(session, "missing")
    assert out is None


# ── 3-4. blocking decision ─────────────────────────────────────────────────


def test_blocking_decision_null_for_running(db_url, svc, session):
    session.add(Feature(id="F", slug="f", title="F", spec_json={}, status="IN_PROGRESS"))
    session.add(Wave(id="W", feature_id="F", slug="w", title="W", order=1, status="IN_PROGRESS"))
    session.add(Packet(id="p_running", feature_id="F", wave_id="W", slug="p",
                       title="running", spec_json={}, state="running"))
    session.commit()
    out = svc.get_packet_blocking_decision(session, "p_running")
    assert out is None


def test_blocking_decision_populated_for_rejected(db_url, svc, session):
    _seed_rejected_packet(session, state="rejected",
                          recovery={"action": "BLOCK_FEATURE", "reason": "max_attempts"})
    out = svc.get_packet_blocking_decision(session, "p1")
    assert out is not None
    assert out["has_blocking"] is True
    assert out["state"] == "rejected"
    assert out["action"] == "BLOCK_FEATURE"
    assert out["reason"] == "max_attempts"
    assert out["decided_by"] == "feature_recovery"
    assert out["last_failure"] is not None
    assert "ruff" in out["last_failure"]["summary"]
    assert any("E501" in i for i in out["last_failure"]["blocking_issues"])
    assert out["last_failure"]["command_preview"] == [
        "opencode", "run", "--model", "deepseek-v4-flash",
    ]


# ── 5-6. runs ──────────────────────────────────────────────────────────────


def test_packet_runs_returns_one_with_model(db_url, svc, session):
    _seed_rejected_packet(session)
    out = svc.get_packet_runs(session, "p1")
    assert len(out["runs"]) == 1
    r = out["runs"][0]
    assert r["model"] == "deepseek/deepseek-v4-flash"
    assert r["duration_ms"] == 1234
    assert r["is_running"] is False


def test_packet_run_includes_command_preview_and_prompt(db_url, svc, session):
    _seed_rejected_packet(session)
    out = svc.get_packet_run(session, "p1", "1")
    assert out is not None
    assert out["model"] == "deepseek/deepseek-v4-flash"
    assert out["command_preview"] == ["opencode", "run", "--model", "deepseek-v4-flash"]
    assert out["prompt"] == "Implement the login screen"
    assert "artifacts_summary" in out
    assert out["artifacts_summary"]["total_size"] == 0  # no evidence dir


# ── 7. evidence ────────────────────────────────────────────────────────────


def test_evidence_reads_acceptance_stages(db_url, svc, session):
    _seed_rejected_packet(session)
    out = svc.get_packet_evidence(session, "p1", run_id="1")
    assert out["verdict"] == "rejected"
    assert len(out["stages"]) == 2
    t1 = next(s for s in out["stages"] if s["name"] == "T1_TARGETED_TESTS")
    assert t1["status"] == "failed"
    assert t1["commands_summary"]["failed"] == 1
    assert t1["commands_summary"]["passed"] == 0
    assert t1["commands_summary"]["total"] == 1
    assert any("E501" in i for i in t1["blocking_issues"])


def test_evidence_empty_stages_yields_no_stages(db_url, svc, session):
    out = svc.get_packet_evidence(session, "missing", run_id="1")
    assert out["stages"] == []


# ── 8-9. artifacts ─────────────────────────────────────────────────────────


def test_artifact_tree_with_sizes(db_url, svc, session, tmp_path):
    ev = tmp_path / "ev" / "p1-1"
    ev.mkdir(parents=True)
    (ev / "a.txt").write_text("hello")
    (ev / "b.png").write_bytes(b"\x89PNG\r\n\x1a\n")
    (ev / "sub").mkdir()
    (ev / "sub" / "c.json").write_text("{}")
    _seed_rejected_packet(session, evidence_path=str(ev))
    out = svc.get_packet_artifacts(session, "p1", "1")
    assert len(out["tree"]) >= 1
    flat = _flatten_tree(out["tree"])
    names = {n["name"] for n in flat}
    assert "a.txt" in names
    assert "b.png" in names
    assert "c.json" in names
    txt = next(n for n in flat if n["name"] == "a.txt")
    assert txt["size"] == 5
    assert txt["kind"] == "log"


def test_artifact_file_path_traversal_blocked(db_url, svc, session, tmp_path):
    ev = tmp_path / "ev" / "p1-1"
    ev.mkdir(parents=True)
    (ev / "ok.txt").write_text("ok")
    _seed_rejected_packet(session, evidence_path=str(ev))
    out = svc.get_artifact_file(session, "p1", "1", "../../../etc/passwd")
    assert out is None


def test_artifact_file_returns_text_content(db_url, svc, session, tmp_path):
    ev = tmp_path / "ev" / "p1-1"
    ev.mkdir(parents=True)
    (ev / "log.txt").write_text("hello\nworld\n")
    _seed_rejected_packet(session, evidence_path=str(ev))
    out = svc.get_artifact_file(session, "p1", "1", "log.txt")
    assert out is not None
    content, ctype = out
    assert ctype.startswith("text/")
    assert b"hello" in content
    assert b"world" in content


# ── 10. logs ───────────────────────────────────────────────────────────────


def test_logs_returns_lines(db_url, svc, session, tmp_path):
    ev = tmp_path / "ev" / "p1-1"
    ev.mkdir(parents=True)
    (ev / "agent_output.log").write_text("line1\nline2\nline3\n")
    _seed_rejected_packet(session, evidence_path=str(ev))
    out = svc.get_packet_logs(session, "p1", "1", stream="agent", tail=10)
    assert out["lines"] == ["line1", "line2", "line3"]
    assert out["total"] == 3
    assert out["truncated"] is False
    assert "agent_output.log" in out["source_file"]


def test_logs_filter_regex(db_url, svc, session, tmp_path):
    ev = tmp_path / "ev" / "p1-1"
    ev.mkdir(parents=True)
    (ev / "agent_output.log").write_text("INFO ok\nERROR bad\nINFO ok2\n")
    _seed_rejected_packet(session, evidence_path=str(ev))
    out = svc.get_packet_logs(session, "p1", "1", stream="agent",
                              tail=10, filter_regex=r"ERROR")
    assert out["lines"] == ["ERROR bad"]


def test_logs_tail_truncates(db_url, svc, session, tmp_path):
    ev = tmp_path / "ev" / "p1-1"
    ev.mkdir(parents=True)
    (ev / "agent_output.log").write_text("\n".join(f"line{i}" for i in range(50)))
    _seed_rejected_packet(session, evidence_path=str(ev))
    out = svc.get_packet_logs(session, "p1", "1", stream="agent", tail=10)
    assert len(out["lines"]) == 10
    assert out["total"] == 50
    assert out["truncated"] is True


# ── 11. sessions (forward-compat) ──────────────────────────────────────────


def test_sessions_returns_table_missing_when_no_table(db_url, svc, session):
    out = svc.get_packet_sessions(session, "p1")
    assert out["reason"] == "table_missing"
    assert out["sessions"] == []


# ── 12. feature summary ────────────────────────────────────────────────────


def test_feature_summary_groups_packets_by_wave(db_url, svc, session):
    session.add(Feature(id="F1", slug="f1", title="Feature", spec_json={}, status="IN_PROGRESS"))
    session.add(Wave(id="W1", feature_id="F1", slug="w1", title="Wave 1", order=1, status="IN_PROGRESS"))
    session.add(Wave(id="W2", feature_id="F1", slug="w2", title="Wave 2", order=2, status="IN_PROGRESS"))
    session.add(Packet(id="p1", feature_id="F1", wave_id="W1", slug="p1", title="P1",
                       spec_json={}, state="ready"))
    session.add(Packet(id="p2", feature_id="F1", wave_id="W2", slug="p2", title="P2",
                       spec_json={}, state="running"))
    session.commit()
    out = svc.get_feature_summary(session, "F1")
    assert out["feature"]["id"] == "F1"
    waves_by_id = {w["id"]: w for w in out["waves"]}
    assert len(waves_by_id["W1"]["packets"]) == 1
    assert len(waves_by_id["W2"]["packets"]) == 1


def test_feature_summary_missing_returns_none(db_url, svc, session):
    out = svc.get_feature_summary(session, "missing")
    assert out is None


# ── 12a. features tree (powers Overview main view) ────────────────────────


def test_features_tree_empty_returns_empty_list(db_url, svc, session):
    out = svc.get_features_tree(session)
    assert out == {"features": []}


def test_features_tree_returns_features_with_waves_and_packets_with_slugs(
    db_url, svc, session,
):
    _seed_tree(session)
    out = svc.get_features_tree(session)
    assert len(out["features"]) == 1
    feat = out["features"][0]
    assert feat["slug"] == "tree-feat"
    assert len(feat["waves"]) == 2
    for wave in feat["waves"]:
        assert "slug" in wave
        for pkt in wave["packets"]:
            # id+slug contract: UI shows them adjacent
            assert "id" in pkt and "slug" in pkt
            assert "max_attempts" in pkt


def test_features_tree_aggregates_attention_counts_per_feature_and_wave(
    db_url, svc, session,
):
    """UI uses feature/wave attention_count to render the calm
    "N needs attention" meta line. These counters must:
      - count only failed/rejected/blocked (not draft/running)
      - roll up to the parent feature
      - be 0 for clean features."""
    _seed_tree(session)
    out = svc.get_features_tree(session)
    feat = out["features"][0]
    # Tree has 1 rejected packet (p_tree_svc_1) and 1 draft packet (p_tree_svc_2)
    assert feat["total_packets"] == 2
    assert feat["attention_count"] == 1, (
        f"feature should aggregate 1 rejected packet, got "
        f"{feat['attention_count']}"
    )
    assert feat["wave_count"] == 2

    # Wave 1 (DEGRADED) has 1 rejected packet
    w1 = feat["waves"][0]
    assert w1["total_packets"] == 1
    assert w1["attention_count"] == 1

    # Wave 2 (NOT_STARTED) has 1 draft packet — no attention
    w2 = feat["waves"][1]
    assert w2["total_packets"] == 1
    assert w2["attention_count"] == 0


def test_features_tree_clean_feature_has_zero_attention(db_url, svc, session):
    """A feature with no failed/rejected/blocked packets should have
    attention_count = 0 — the UI then hides the 'needs attention' text."""
    f = Feature(
        id="F_CLEAN_SVC", slug="clean-feat", title="Clean Feature",
        spec_json={}, status="IN_PROGRESS",
    )
    w = Wave(id="W_CLEAN_SVC", feature_id=f.id, slug="clean-wave",
             title="Clean Wave", order=1, status="NOT_STARTED")
    p = Packet(id="p_clean_svc", feature_id=f.id, wave_id=w.id,
               slug="clean-pkt", title="Clean Packet",
               spec_json={"role": "coder"},
               state="draft", attempt_count=0, max_attempts=5)
    session.add_all([f, w, p])
    session.commit()

    out = svc.get_features_tree(session)
    feat = out["features"][0]
    assert feat["attention_count"] == 0
    assert feat["waves"][0]["attention_count"] == 0


# ── 12c. wave detail (right-pane Wave mode) ───────────────────────────

def test_get_wave_detail_returns_wave_with_packets_and_counts(
    db_url, svc, session,
):
    """get_wave_detail returns the wave header, feature context, per-state
    counts, and the list of packets with timing data. Used by the
    right pane when only wave_id is selected."""
    _seed_tree(session)
    out = svc.get_wave_detail(session, "F_TREE_SVC", "W_TREE_SVC_1")
    assert out is not None
    assert out["wave"]["id"] == "W_TREE_SVC_1"
    assert out["wave"]["title"] == "Tree Wave 1"
    assert out["wave"]["order"] == 1
    assert out["wave"]["status"] == "DEGRADED"
    assert out["feature"]["id"] == "F_TREE_SVC"
    # 1 rejected packet in wave 1
    assert out["counts"]["all"] == 1
    assert out["counts"]["failed"] == 1
    assert out["counts"]["attention"] == 1
    assert out["counts"]["running"] == 0
    assert out["counts"]["done"] == 0
    # Packet list
    assert len(out["packets"]) == 1
    p = out["packets"][0]
    assert p["id"] == "p_tree_svc_1"
    assert p["state"] == "rejected"
    assert p["attempt_count"] == 2
    assert "started_at" in p
    assert "duration_seconds" in p


def test_get_wave_detail_clean_wave_has_zero_attention(
    db_url, svc, session,
):
    """A wave with only draft/running packets has attention=0."""
    _seed_tree(session)
    out = svc.get_wave_detail(session, "F_TREE_SVC", "W_TREE_SVC_2")
    assert out is not None
    assert out["wave"]["id"] == "W_TREE_SVC_2"
    assert out["counts"]["all"] == 1
    assert out["counts"]["failed"] == 0
    assert out["counts"]["attention"] == 0


def test_get_wave_detail_returns_none_for_missing_wave(
    db_url, svc, session,
):
    """Missing wave returns None (UI shows 'Wave not found' banner)."""
    _seed_tree(session)
    assert svc.get_wave_detail(session, "F_TREE_SVC", "W_NOPE") is None
    # And for a wave that exists but belongs to a different feature
    assert svc.get_wave_detail(session, "F_NOPE", "W_TREE_SVC_1") is None


def _seed_tree(session):
    """Seed a 1-feature / 2-wave / 2-packet tree for /features endpoint tests."""
    f = Feature(
        id="F_TREE_SVC", slug="tree-feat", title="Tree Feature",
        spec_json={}, status="IN_PROGRESS",
    )
    w1 = Wave(id="W_TREE_SVC_1", feature_id=f.id, slug="tree-wave-1",
              title="Tree Wave 1", order=1, status="DEGRADED")
    w2 = Wave(id="W_TREE_SVC_2", feature_id=f.id, slug="tree-wave-2",
              title="Tree Wave 2", order=2, status="NOT_STARTED")
    p1 = Packet(id="p_tree_svc_1", feature_id=f.id, wave_id=w1.id,
                slug="tree-pkt-1", title="Tree Packet 1",
                spec_json={"role": "coder"},
                state="rejected", attempt_count=2, max_attempts=5)
    p2 = Packet(id="p_tree_svc_2", feature_id=f.id, wave_id=w2.id,
                slug="tree-pkt-2", title="Tree Packet 2",
                spec_json={"role": "coder"},
                state="draft", attempt_count=0, max_attempts=5)
    session.add_all([f, w1, w2, p1, p2])
    session.commit()


# ── 12b. state machine (operator-console lifecycle) ──────────────────────


def test_state_machine_draft_has_pending_steps(db_url, svc, session):
    """For a draft packet: created=done, claimed/reviewed/result=pending."""
    _seed_state_machine_packet(session, state="draft", runs=[])
    detail = svc.get_packet_detail(session, "sm1")
    sm = detail["state_machine"]
    assert len(sm["steps"]) == 4
    assert [s["key"] for s in sm["steps"]] == ["created", "claimed", "reviewed", "result"]
    assert sm["steps"][0]["state"] == "done"
    assert sm["steps"][0]["label"] == "Created"
    assert sm["steps"][1]["state"] == "pending"
    assert sm["steps"][2]["state"] == "pending"
    assert sm["steps"][3]["state"] == "current"
    assert sm["steps"][3]["label"] == "Draft"


def test_state_machine_rejected_has_failed_reviewed_and_result(db_url, svc, session):
    """For a rejected packet: created/claimed=done, reviewed=failed, result=failed."""
    _seed_state_machine_packet(
        session, state="rejected",
        runs=[("r1", "rejected", "w-1", 1000)],
        attempt_count=3, max_attempts=3,
    )
    detail = svc.get_packet_detail(session, "sm1")
    sm = detail["state_machine"]
    assert sm["steps"][0]["state"] == "done"
    assert sm["steps"][1]["state"] == "done"
    assert sm["steps"][1]["meta"] == "w-1"
    assert sm["steps"][2]["state"] == "failed"
    assert "3/3" in sm["steps"][2]["meta"]
    assert "rejected" in sm["steps"][2]["meta"]
    assert sm["steps"][3]["state"] == "failed"
    assert sm["steps"][3]["label"] == "Rejected"


def test_state_machine_running_keeps_claimed_current(db_url, svc, session):
    """For a running packet: claimed=current."""
    _seed_state_machine_packet(
        session, state="running",
        runs=[("r1", "running", "w-7", None)],
        attempt_count=1, max_attempts=3,
    )
    detail = svc.get_packet_detail(session, "sm1")
    sm = detail["state_machine"]
    assert sm["steps"][1]["state"] == "current"
    assert sm["steps"][1]["meta"] == "w-7"


def test_state_machine_blocked_uses_blocked_class(db_url, svc, session):
    """For a blocked packet: result step uses 'blocked' state, not 'failed'."""
    _seed_state_machine_packet(
        session, state="blocked",
        runs=[("r1", "blocked", "w-1", 1000)],
        attempt_count=3, max_attempts=3,
    )
    detail = svc.get_packet_detail(session, "sm1")
    sm = detail["state_machine"]
    assert sm["steps"][3]["state"] == "blocked"
    assert sm["steps"][3]["label"] == "Blocked"


def test_state_machine_accepted_uses_done(db_url, svc, session):
    """For an accepted packet: result is done with label 'Accepted'."""
    _seed_state_machine_packet(
        session, state="accepted",
        runs=[("r1", "accepted", "w-1", 1000)],
        attempt_count=1, max_attempts=3,
    )
    detail = svc.get_packet_detail(session, "sm1")
    sm = detail["state_machine"]
    assert sm["steps"][3]["state"] == "done"
    assert sm["steps"][3]["label"] == "Accepted"


def test_state_machine_falls_back_to_events_when_no_runs(db_url, svc, session):
    """Legacy packets (no PacketRun) should still get claimed/reviewed from events."""
    f = Feature(id="LEG_F", slug="leg-feat", title="Legacy Feature",
                spec_json={}, status="IN_PROGRESS")
    w = Wave(id="LEG_W", feature_id=f.id, slug="leg-wave",
             title="Legacy Wave", order=1, status="DEGRADED")
    p = Packet(
        id="leg1", feature_id=f.id, wave_id=w.id,
        slug="leg-pkt", title="Legacy Packet",
        spec_json={"role": "coder"},
        state="rejected", attempt_count=3, max_attempts=3,
    )
    session.add_all([f, w, p])
    # Add only events, no PacketRun
    base = datetime(2026, 6, 7, 8, 0, 0)
    session.add(Event(
        event_type="packet_claimed", entity_type="packet", entity_id=p.id,
        payload_json={"component": "supervisor", "worker_id": "w-legacy"},
        timestamp=base,
    ))
    session.add(Event(
        event_type="packet_transition", entity_type="packet", entity_id=p.id,
        payload_json={"component": "feature_recovery", "reason": "release:rejected"},
        timestamp=base + timedelta(seconds=30),
    ))
    session.commit()
    detail = svc.get_packet_detail(session, "leg1")
    sm = detail["state_machine"]
    # claimed: derived from packet_claimed event
    assert sm["steps"][1]["state"] == "done"
    assert sm["steps"][1]["meta"] == "w-legacy"
    # reviewed: derived from packet_transition event
    assert sm["steps"][2]["state"] == "failed"
    assert "rejected" in sm["steps"][2]["meta"]


def _seed_state_machine_packet(
    session, *, state: str, runs: list[tuple[str, str, str, int | None]],
    attempt_count: int = 0, max_attempts: int = 3,
) -> None:
    """Seed a packet + optional runs for state machine tests.

    runs: list of (run_id, status, worker_id, duration_ms_or_none).
    duration_ms is informational; started/finished are auto-computed.
    """
    f = Feature(id="SM_F", slug="sm-feat", title="SM Feature",
                spec_json={}, status="IN_PROGRESS")
    w = Wave(id="SM_W", feature_id=f.id, slug="sm-wave",
             title="SM Wave", order=1, status="IN_PROGRESS")
    p = Packet(
        id="sm1", feature_id=f.id, wave_id=w.id,
        slug="sm-pkt", title="SM Packet",
        spec_json={"role": "coder"},
        state=state, attempt_count=attempt_count, max_attempts=max_attempts,
    )
    session.add_all([f, w, p])
    base = datetime(2026, 6, 7, 10, 0, 0)
    for i, (rid, status, worker_id, dur_ms) in enumerate(runs):
        started = base + timedelta(minutes=i)
        finished = started + timedelta(seconds=2) if dur_ms is not None else None
        session.add(PacketRun(
            id=rid, packet_id=p.id, run_number=i + 1,
            executor_id=f"exec-{i}",
            worker_id=worker_id,
            model="deepseek/deepseek-v4-flash",
            status=status,
            duration_ms=dur_ms or 0,
            started_at=started,
            finished_at=finished,
            result_json={},
        ))
    session.commit()


# ── 13. search ─────────────────────────────────────────────────────────────


def test_search_finds_packet_by_title(db_url, svc, session):
    _seed_rejected_packet(session)
    out = svc.search(session, "My Packet")
    assert any(r["kind"] == "packet" and r["id"] == "p1" for r in out["results"])


def test_search_finds_run_by_executor(db_url, svc, session):
    _seed_rejected_packet(session)
    out = svc.search(session, "exec-A")
    assert any(r["kind"] == "run" and r["executor_id"] == "exec-A" for r in out["results"])


def test_search_empty_query_returns_empty(db_url, svc, session):
    out = svc.search(session, "")
    assert out["results"] == []


# ── 14-15. system health / workers ────────────────────────────────────────


def test_system_health_shape(db_url, svc, monkeypatch):
    monkeypatch.delenv("GRACE_TARGET_DIR", raising=False)
    out = svc.get_system_health()
    assert "supervisor_alive" in out
    assert "workers_alive" in out
    assert "db_ok" in out
    assert "code_sha" in out
    assert "version" in out
    assert out["api_alive"] is True


def test_workers_listing(db_url, svc, session):
    session.add(Worker(id="w-A", status="active", current_packet_id="p-1",
                       last_heartbeat=datetime.utcnow(),
                       started_at=datetime.utcnow()))
    session.commit()
    out = svc.get_workers(session)
    assert any(w["id"] == "w-A" and w["current_packet_id"] == "p-1"
               for w in out["workers"])


# ── 16. helpers ────────────────────────────────────────────────────────────


def test_elapsed_seconds_with_finished():
    started = datetime(2026, 1, 1, 10, 0, 0)
    finished = datetime(2026, 1, 1, 10, 0, 30)
    assert _elapsed_seconds(started, finished) == 30


def test_elapsed_seconds_none_when_no_started():
    assert _elapsed_seconds(None, None) is None


def test_is_running_with_active_status():
    started = datetime.utcnow()
    assert _is_running(None, started, None) is True
    assert _is_running("rejected", started, datetime.utcnow()) is False


def test_classify_artifact():
    assert _classify_artifact("foo.png") == "image"
    assert _classify_artifact("foo.JPG") == "image"
    assert _classify_artifact("foo.log") == "log"
    assert _classify_artifact("foo.json") == "json"
    assert _classify_artifact("foo.har") == "har"
    assert _classify_artifact("foo.bin") == "file"


# ── 17. decision component detection ───────────────────────────────────────


def test_decision_component_feature_recovery(db_url, svc, session):
    _seed_rejected_packet(session, recovery={"action": "BLOCK_FEATURE"})
    out = svc.get_packet_blocking_decision(session, "p1")
    assert out["decided_by"] == "feature_recovery"


def test_decision_component_recovery_controller(db_url, svc, session):
    """No recovery event but rejected state — defaults to acceptance_pipeline."""
    session.add(Feature(id="F", slug="f", title="F", spec_json={}, status="IN_PROGRESS"))
    session.add(Wave(id="W", feature_id="F", slug="w", title="W", order=1, status="IN_PROGRESS"))
    session.add(Packet(id="p_rej", feature_id="F", wave_id="W", slug="p",
                       title="rej", spec_json={}, state="rejected"))
    session.add(PacketRun(
        id="p_rej-1", packet_id="p_rej", run_number=1, status="rejected",
        duration_ms=10, result_json={},
        started_at=datetime.utcnow(), finished_at=datetime.utcnow(),
    ))
    session.commit()
    out = svc.get_packet_blocking_decision(session, "p_rej")
    assert out["decided_by"] == "acceptance_pipeline"


# ── helpers ────────────────────────────────────────────────────────────────


def _flatten_tree(nodes):
    out = []
    for n in nodes:
        if n["type"] == "file":
            out.append(n)
        else:
            out.extend(_flatten_tree(n.get("children", [])))
    return out
