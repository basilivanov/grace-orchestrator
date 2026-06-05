"""Tests for the P0/P1/P2 fixes from source/codex/review-2026-06-05-refactor-audit.md."""

import asyncio
import os
from datetime import datetime, timedelta
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from grace_control.core.contracts import (
    AcceptanceProfile,
    ExecutionPacketContract,
)
from grace_control.core.state_machine import StateTransitionError
from grace_control.db import get_db, init_db
from grace_control.db.schema import Feature, Lease, Packet, PacketState, Wave, Worker
from grace_control.services.merge_service import MergeResult, MergeService
from grace_control.services.packet_service import (
    ClaimResult,
    PacketNotFoundError,
    PacketService,
)


# ── P0#1: MergeService.transition persists MERGED ──────────────────────────


def _make_accepted_packet(db, pid="p-merge-1"):
    db.add(Packet(
        id=pid, feature_id="F1", wave_id="W01", slug=pid,
        title=pid, spec_json={},
        state=PacketState.ACCEPTED.value,
        attempt_count=1, max_attempts=3,
        acceptance_profile=AcceptanceProfile.NORMAL.value,
    ))


def test_p0_1_merge_transitions_packet_to_merged(db):
    """MergeService.merge_packet must persist packets.state='merged' (P0#1)."""
    from grace_control.services.git_service import GitResult

    with get_db() as session:
        _make_accepted_packet(session)
        session.commit()

    git = MagicMock()
    git.validate_repo.return_value = MagicMock(is_git=True, is_clean=True, current_branch="main")
    git.checkout.return_value = GitResult(True, "stdout", "", 0)
    git.fetch.return_value = GitResult(True, "", "", 0)
    git.merge.return_value = GitResult(True, "Merge made", "", 0)
    git.push.return_value = GitResult(True, "", "", 0)
    git.current_sha.return_value = "abcdef1234567890"

    svc = MergeService(git=git)
    result = asyncio.run(svc.merge_packet(
        packet_id="p-merge-1",
        target_repo_root="/tmp/repo",
        branch_name="agent/p-merge-1/attempt-0001",
        target_branch="main",
    ))

    assert result.success is True

    with get_db() as session:
        packet = session.query(Packet).filter_by(id="p-merge-1").first()
        assert packet is not None
        assert packet.state == PacketState.MERGED.value


# ── P0#2: SQLite migration adds features.degraded_reason ──────────────────


def test_p0_2_sqlite_migration_adds_degraded_reason(tmp_path, monkeypatch):
    """init_db must ALTER TABLE features ADD COLUMN degraded_reason when missing."""
    db_path = tmp_path / "old_grace.db"
    db_url = f"sqlite:///{db_path}"

    # First init creates the schema WITHOUT the new column (simulate pre-refactor DB).
    from sqlalchemy import create_engine, text
    from grace_control.db.schema import Base
    eng = create_engine(db_url)
    Base.metadata.create_all(eng)
    with eng.begin() as conn:
        # Manually drop the new column to simulate the old schema.
        # SQLite stores table info in sqlite_master; we can rebuild without it.
        conn.execute(text("ALTER TABLE features RENAME TO _features_old"))
        conn.execute(text(
            "CREATE TABLE features ("
            "id VARCHAR PRIMARY KEY, slug VARCHAR NOT NULL, title VARCHAR NOT NULL, "
            "description TEXT, spec_json JSON NOT NULL, status VARCHAR NOT NULL, "
            "created_at DATETIME NOT NULL, updated_at DATETIME NOT NULL)"
        ))
        # Copy any pre-existing rows (likely empty).
        conn.execute(text(
            "INSERT INTO features (id, slug, title, spec_json, status, created_at, updated_at) "
            "SELECT id, slug, title, spec_json, status, created_at, updated_at FROM _features_old"
        ))
        conn.execute(text("DROP TABLE _features_old"))
    eng.dispose()

    # Now run init_db on the old DB — migration must add the missing column.
    init_db(db_url)

    # Verify the column exists.
    eng = create_engine(db_url)
    from sqlalchemy import inspect
    insp = inspect(eng)
    cols = {c["name"] for c in insp.get_columns("features")}
    assert "degraded_reason" in cols
    eng.dispose()


def test_p0_2_migration_idempotent(tmp_path):
    """Migration is a no-op when the column already exists (idempotent)."""
    db_path = tmp_path / "fresh_grace.db"
    db_url = f"sqlite:///{db_path}"

    # First init — column is created via create_all.
    init_db(db_url)
    # Second init — migration should be a no-op (no error).
    init_db(db_url)

    from sqlalchemy import create_engine, inspect
    eng = create_engine(db_url)
    insp = inspect(eng)
    cols = {c["name"] for c in insp.get_columns("features")}
    assert "degraded_reason" in cols
    eng.dispose()


# ── P0#3: PacketService.claim returns ClaimResult (not detached ORM) ───────


def _make_ready_packet(db, pid="p-claim-1", spec=None):
    db.add(Packet(
        id=pid, feature_id="F1", wave_id="W01", slug=pid,
        title=pid, spec_json=spec or {"scope": ["src/x.py"]},
        state=PacketState.READY.value,
        attempt_count=0, max_attempts=3,
        acceptance_profile=AcceptanceProfile.NORMAL.value,
    ))
    db.add(Worker(id="w-1", status="idle"))


def test_p0_3_claim_returns_claim_result_dto(db):
    """claim() must return ClaimResult dataclass, not detached ORM Lease (P0#3)."""
    with get_db() as session:
        _make_ready_packet(session)
        session.commit()

    svc = PacketService()
    result = asyncio.run(svc.claim("p-claim-1", "w-1"))

    # Returned object is a frozen dataclass — survives session close.
    assert isinstance(result, ClaimResult)
    assert result.packet_id == "p-claim-1"
    assert result.worker_id == "w-1"
    assert result.attempt == 1
    assert isinstance(result.lease_id, int)
    assert isinstance(result.expires_at, datetime)
    assert result.spec == {"scope": ["src/x.py"]}

    # All fields are still readable after the service's session has closed.
    pid = result.packet_id
    wid = result.worker_id
    exp = result.expires_at
    assert pid and wid and exp


def test_p0_3_claim_dto_is_frozen(db):
    """ClaimResult must be frozen — callers cannot mutate it."""
    with get_db() as session:
        _make_ready_packet(session)
        session.commit()

    svc = PacketService()
    result = asyncio.run(svc.claim("p-claim-1", "w-1"))

    with pytest.raises((AttributeError, Exception)):
        result.packet_id = "mutated"  # type: ignore[misc]


# ── P1#4: PacketService.cancel ────────────────────────────────────────────


def _make_running_packet(db, pid="p-cancel-1", worker_id="w-1"):
    db.add(Packet(
        id=pid, feature_id="F1", wave_id="W01", slug=pid,
        title=pid, spec_json={},
        state=PacketState.RUNNING.value,
        attempt_count=1, max_attempts=3,
        acceptance_profile=AcceptanceProfile.NORMAL.value,
    ))
    db.add(Worker(id=worker_id, status="active", current_packet_id=pid))
    db.add(Lease(packet_id=pid, worker_id=worker_id,
                 expires_at=datetime.utcnow() + timedelta(minutes=15)))


def test_p1_4_cancel_running_releases_lease(db):
    """PacketService.cancel: RUNNING → CANCELLED, lease removed, worker reset (P1#4)."""
    with get_db() as session:
        _make_running_packet(session)
        session.commit()

    svc = PacketService()
    result = asyncio.run(svc.cancel("p-cancel-1", "user requested"))

    assert result.state == PacketState.CANCELLED.value
    assert result.previous_state == PacketState.RUNNING.value
    assert result.packet_id == "p-cancel-1"

    with get_db() as session:
        lease = session.query(Lease).filter_by(packet_id="p-cancel-1").first()
        assert lease is None
        worker = session.query(Worker).filter_by(id="w-1").first()
        assert worker.current_packet_id is None


def test_p1_4_cancel_from_ready(db):
    """Cancel works from READY (not only RUNNING)."""
    with get_db() as session:
        session.add(Packet(
            id="p-cancel-r", feature_id="F1", wave_id="W01", slug="p-cancel-r",
            title="p-cancel-r", spec_json={},
            state=PacketState.READY.value,
            attempt_count=0, max_attempts=3,
            acceptance_profile=AcceptanceProfile.NORMAL.value,
        ))
        session.commit()

    svc = PacketService()
    result = asyncio.run(svc.cancel("p-cancel-r", "abort"))
    assert result.state == PacketState.CANCELLED.value
    assert result.previous_state == PacketState.READY.value


def test_p1_4_cancel_blocked_final_raises(db):
    """Cancel against BLOCKED_FINAL must raise StateTransitionError."""
    with get_db() as session:
        session.add(Packet(
            id="p-cancel-bf", feature_id="F1", wave_id="W01", slug="p-cancel-bf",
            title="p-cancel-bf", spec_json={},
            state=PacketState.BLOCKED_FINAL.value,
            attempt_count=3, max_attempts=3,
            acceptance_profile=AcceptanceProfile.NORMAL.value,
        ))
        session.commit()

    svc = PacketService()
    with pytest.raises(StateTransitionError):
        asyncio.run(svc.cancel("p-cancel-bf", "abort"))


def test_p1_4_cancel_missing_packet_raises(db):
    """Cancel against non-existent packet_id → PacketNotFoundError."""
    svc = PacketService()
    with pytest.raises(PacketNotFoundError):
        asyncio.run(svc.cancel("does-not-exist", "abort"))


def test_p1_4_cancel_dto_survives_session_close(db):
    """CancelResult is a frozen DTO; fields are readable after session close."""
    with get_db() as session:
        session.add(Packet(
            id="p-cancel-dto", feature_id="F1", wave_id="W01", slug="p-cancel-dto",
            title="p-cancel-dto", spec_json={},
            state=PacketState.RUNNING.value,
            attempt_count=1, max_attempts=3,
            acceptance_profile=AcceptanceProfile.NORMAL.value,
        ))
        session.commit()

    svc = PacketService()
    result = asyncio.run(svc.cancel("p-cancel-dto", "abort"))

    # Read fields outside any session — must not raise DetachedInstanceError.
    pid = result.packet_id
    state = result.state
    prev = result.previous_state
    reason = result.reason
    assert pid == "p-cancel-dto"
    assert state == "cancelled"
    assert prev == "running"
    assert reason == "abort"


# ── P1#5: wave_gate does NOT open next wave on all-BLOCKED_FINAL ──────────


def test_p1_5_blocked_final_does_not_open_next_wave(db):
    """wave_gate: a wave of all BLOCKED_FINAL must NOT promote next-wave DRAFTs (P1#5)."""
    with get_db() as session:
        session.add(Feature(id="F1", slug="f1", title="F1", spec_json={}, status="IN_PROGRESS"))
        session.add(Wave(id="W01", feature_id="F1", slug="w01", title="W01", order=1))
        session.add(Wave(id="W02", feature_id="F1", slug="w02", title="W02", order=2))
        for i in range(3):
            session.add(Packet(
                id=f"p-bf-{i}", feature_id="F1", wave_id="W01",
                slug=f"p-bf-{i}", title=f"p-bf-{i}", spec_json={},
                state=PacketState.BLOCKED_FINAL.value,
                attempt_count=3, max_attempts=3,
                acceptance_profile=AcceptanceProfile.NORMAL.value,
            ))
        for i in range(2):
            session.add(Packet(
                id=f"p-next-{i}", feature_id="F1", wave_id="W02",
                slug=f"p-next-{i}", title=f"p-next-{i}", spec_json={},
                state=PacketState.DRAFT.value,
                attempt_count=0, max_attempts=3,
                acceptance_profile=AcceptanceProfile.NORMAL.value,
            ))
        session.commit()

    from grace_control.core.wave_gate import check_wave_gates
    gated = check_wave_gates()
    assert gated == 0

    with get_db() as session:
        drafts = session.query(Packet).filter_by(wave_id="W02").all()
        for p in drafts:
            assert p.state == PacketState.DRAFT.value


def test_p1_5_merged_cancelled_opens_next_wave(db):
    """Wave gate DOES promote next-wave DRAFTs when current wave is all MERGED/CANCELLED."""
    with get_db() as session:
        session.add(Feature(id="F2", slug="f2", title="F2", spec_json={}, status="IN_PROGRESS"))
        session.add(Wave(id="W11", feature_id="F2", slug="w11", title="W11", order=1))
        session.add(Wave(id="W12", feature_id="F2", slug="w12", title="W12", order=2))
        for i, st in enumerate([PacketState.MERGED, PacketState.CANCELLED]):
            session.add(Packet(
                id=f"p-ok-{i}", feature_id="F2", wave_id="W11",
                slug=f"p-ok-{i}", title=f"p-ok-{i}", spec_json={},
                state=st.value,
                attempt_count=1, max_attempts=3,
                acceptance_profile=AcceptanceProfile.NORMAL.value,
            ))
        session.add(Packet(
            id="p-next-2", feature_id="F2", wave_id="W12",
            slug="p-next-2", title="p-next-2", spec_json={},
            state=PacketState.DRAFT.value,
            attempt_count=0, max_attempts=3,
            acceptance_profile=AcceptanceProfile.NORMAL.value,
        ))
        session.commit()

    from grace_control.core.wave_gate import check_wave_gates
    gated = check_wave_gates()
    assert gated == 1

    with get_db() as session:
        promoted = session.query(Packet).filter_by(id="p-next-2").first()
        assert promoted.state == PacketState.READY.value


# ── P1#6: T0 scope paths resolved against worktree cwd ────────────────────


def test_p1_6_t0_uses_worktree_only_files(tmp_path):
    """T0 lint must include a file that exists only in the worktree, not in
    the project root (P1#6)."""
    project_root = tmp_path / "project"
    worktree = tmp_path / "worktree"
    project_root.mkdir()
    worktree.mkdir()

    # Create src/ in both, with different files.
    (project_root / "src").mkdir()
    (worktree / "src").mkdir()
    (project_root / "src" / "old_file.py").write_text("print('old')\n")
    (worktree / "src" / "new_file.py").write_text("print('new')\n")

    from grace_control.core.acceptance_pipeline import AcceptancePipeline
    pipe = AcceptancePipeline(repo_root=project_root)

    commands = pipe._build_t0_commands(
        packet=ExecutionPacketContract(
            packet_id="p1", title="t", allowed_write_scope=["src/"],
            frozen_scope=[], acceptance_profile=AcceptanceProfile.NORMAL,
            verification={"t1": []},
        ),
        changed_files=["src/new_file.py"],
        cwd=worktree,
    )

    joined = " ".join(" ".join(cmd) for cmd in commands)
    assert "new_file.py" in joined, f"worktree-only file missing from T0 commands: {commands}"
    assert "old_file.py" not in joined, f"project-only file leaked into T0 commands: {commands}"


# ── P1#7: GitService.worktree_remove + MergeService.cleanup_worktree ──────


def test_p1_7_git_service_worktree_remove(tmp_path):
    """GitService.worktree_remove runs `git worktree remove --force` (P1#7)."""
    repo = tmp_path / "repo"
    repo.mkdir()
    import subprocess
    subprocess.run(["git", "init", "--initial-branch=main"], cwd=repo, check=True, capture_output=True)
    subprocess.run(["git", "-C", str(repo), "config", "user.email", "t@t"], check=True, capture_output=True)
    subprocess.run(["git", "-C", str(repo), "config", "user.name", "t"], check=True, capture_output=True)
    (repo / "f").write_text("x")
    subprocess.run(["git", "-C", str(repo), "add", "."], check=True, capture_output=True)
    subprocess.run(["git", "-C", str(repo), "commit", "-m", "init"], check=True, capture_output=True)

    wt = tmp_path / "wt"
    subprocess.run(["git", "-C", str(repo), "worktree", "add", str(wt), "-b", "feat"], check=True, capture_output=True)
    assert wt.exists()

    from grace_control.services.git_service import GitService
    svc = GitService()
    result = svc.worktree_remove(repo, wt, force=True)
    assert result.success is True
    # And the worktree list no longer mentions it.
    listed = subprocess.run(["git", "-C", str(repo), "worktree", "list"], capture_output=True, text=True)
    assert str(wt) not in listed.stdout


# ── P2#8: legacy_branch_name + legacy_prepare_worktree ─────────────────────


def test_p2_8_legacy_branch_name_format():
    """P2#8: branch format lives in legacy_backend, single source of truth."""
    from grace_control.agent.legacy_backend import (
        LEGACY_BRANCH_FORMAT,
        legacy_branch_name,
    )
    assert legacy_branch_name("pkt-1", "attempt-0001") == "agent/default/pkt-1/attempt-0001"
    assert LEGACY_BRANCH_FORMAT == "agent/default/{packet_id}/{attempt_slug}"

    # packet_materializer still re-exports it for back-compat.
    from grace_control.services.packet_materializer import BRANCH_FORMAT
    assert BRANCH_FORMAT == LEGACY_BRANCH_FORMAT


def test_p2_8_legacy_prepare_worktree_idempotent(tmp_path):
    """legacy_prepare_worktree never raises on missing worktree/branch."""
    from grace_control.agent.legacy_backend import legacy_prepare_worktree
    project_root = tmp_path / "project"
    project_root.mkdir()
    # No git init — function must still complete without raising.
    wt_path, branch = legacy_prepare_worktree(project_root, "p-1", "attempt-0001")
    assert wt_path == project_root / "p-1-attempt-0001"
    assert branch == "agent/default/p-1/attempt-0001"


# ── P2#9: LegacyPrefectBackend forwards request.spec.base_ref ──────────────


def test_p2_9_legacy_backend_forwards_base_ref():
    """LegacyPrefectBackend must forward request.spec.base_ref (P2#9)."""
    from grace_control.agent.backend import ExecutionRequest
    from grace_control.agent.legacy_backend import LegacyPrefectBackend

    fake_e2e = MagicMock(ok=True, domain_status="accepted", worktree_path="/tmp/wt",
                        branch_name="agent/p/1", errors=[], registry_reason="")

    with patch("grace_control.agent.legacy_backend.run_e2e_packet", return_value=fake_e2e) as mock_run:
        backend = LegacyPrefectBackend()
        asyncio.run(backend.run(ExecutionRequest(
            packet_id="p-1", spec={"base_ref": "main", "attempt_count": 1},
            worktree_path=Path("/tmp/wt"), branch_name="agent/p/1", timeout_s=10,
        )))

    # base_ref= kwarg must be passed through, not hard-coded to "HEAD".
    assert mock_run.called
    _, kwargs = mock_run.call_args
    assert kwargs.get("base_ref") == "main"


# ── P2#10: settings.* used in api/main.py + packet_executor.py ─────────────


def test_p2_10_settings_used_in_main_lifespan(monkeypatch):
    """api/main.py lifespan must read from settings (P2#10)."""
    import grace_control.api.main as api_main
    # If lifespan still reads os.environ directly, this would not exist.
    src = Path(api_main.__file__).read_text()
    assert "from grace_control.config.settings import settings" in src
    assert "init_db(settings.database_url)" in src
    assert "settings.wave_gate_interval_seconds" in src
    assert "settings.feature_gate_interval_seconds" in src
    assert "settings.api_port" in src
    # And no more hard-coded `os.environ.get("GRACE_DB_URL")` in main.py.
    assert 'os.environ.get("GRACE_DB_URL")' not in src
    assert "asyncio.sleep(30)" not in src  # magic number removed
    assert "asyncio.sleep(60)" not in src  # magic number removed


def test_p2_10_settings_used_in_packet_executor():
    """packet_executor must prefer settings.agent_timeout_seconds + base_branch."""
    import grace_control.adapters.packet_executor as pe
    src = Path(pe.__file__).read_text()
    # Both legacy env-var fallbacks must defer to settings defaults.
    assert 'os.environ.get("GRACE_BASE_REF", settings.base_branch)' in src
    assert 'os.environ.get("GRACE_AGENT_TIMEOUT", str(settings.agent_timeout_seconds))' in src


# ── Followup (review-2026-06-05-5198516-followup.md): merge atomicity ───────


def test_followup_5198516_merge_fails_when_transition_fails(db):
    """If PacketService.transition raises, MergeService must return success=False.

    Review `source/codex/review-2026-06-05-5198516-followup.md` §1:
    git merge can succeed but DB transition can fail; the service must
    surface that as a failed merge, not a successful one.
    """
    from grace_control.services.git_service import GitResult

    with get_db() as session:
        _make_accepted_packet(session, pid="p-merge-fail")
        session.commit()

    git = MagicMock()
    git.validate_repo.return_value = MagicMock(is_git=True, is_clean=True, current_branch="main")
    git.checkout.return_value = GitResult(True, "stdout", "", 0)
    git.fetch.return_value = GitResult(True, "", "", 0)
    git.merge.return_value = GitResult(True, "Merge made", "", 0)
    git.push.return_value = GitResult(True, "", "", 0)
    git.current_sha.return_value = "deadbeef12345678"

    # Inject a PacketService stub whose transition always raises.
    fake_packets = MagicMock()
    fake_packets.transition = AsyncMock(side_effect=StateTransitionError("simulated DB failure"))
    svc = MergeService(git=git, packets=fake_packets)

    result = asyncio.run(svc.merge_packet(
        packet_id="p-merge-fail",
        target_repo_root="/tmp/repo",
        branch_name="agent/p-merge-fail/attempt-0001",
        target_branch="main",
    ))

    assert result.success is False
    assert "state transition failed" in result.error
    assert "simulated DB failure" in result.error
    assert result.commit_sha == "deadbeef12345678"  # git SHA still recorded
    # And the DB packet must still be ACCEPTED — the failure prevented the transition.
    with get_db() as session:
        packet = session.query(Packet).filter_by(id="p-merge-fail").first()
        assert packet.state == PacketState.ACCEPTED.value


def test_followup_5198516_merge_router_returns_409_on_transition_failure(api, monkeypatch):
    """API /merge must return 409 when git succeeded but DB transition failed."""
    import asyncio
    from grace_control.services.git_service import GitResult

    with get_db() as session:
        _make_accepted_packet(session, pid="p-merge-api-409")
        session.commit()

    # Stub MergeService so we control success/failure without a real git repo.
    async def _stub_merge_packet(self, **kwargs):
        return MergeResult(
            False, kwargs["packet_id"], "cafef00d", "/tmp/repo",
            kwargs["branch_name"], kwargs["target_branch"],
            error="state transition failed: simulated",
        )

    monkeypatch.setattr(MergeService, "merge_packet", _stub_merge_packet)

    async def _call():
        return await api.post(
            "/api/packets/p-merge-api-409/merge",
            json={
                "worktree_path": "/tmp/wt",
                "branch_name": "agent/p-merge-api-409/attempt-0001",
                "target_branch": "main",
                "target_repo_root": "/tmp/repo",
            },
        )

    resp = asyncio.run(_call())

    assert resp.status_code == 409, resp.text
    body = resp.json()
    assert "merge_failed" in body.get("detail", {}), body
    assert "state transition failed" in body["detail"]["merge_failed"]
    assert body["detail"]["packet_id"] == "p-merge-api-409"

    # DB must still show ACCEPTED — no MERGED transition.
    with get_db() as session:
        packet = session.query(Packet).filter_by(id="p-merge-api-409").first()
        assert packet.state == PacketState.ACCEPTED.value
