"""
Shared fixtures for GRACE Control Plane tests.
"""
import os
import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient

from grace_control.api.main import app
from grace_control.config.settings import settings
from grace_control.db import get_db, init_db
from grace_control.db.schema import Feature, Lease, Packet, PacketRun, PacketState, Wave, Worker


@pytest.fixture(autouse=True)
def grace_settings_isolation():
    """Snapshot and restore global settings after every test.

    Prevents test-to-test leakage from direct mutations like
    ``settings.agent_runtime_fail_on_bad_git_root = True``.
    """
    snapshot = settings.model_dump()
    yield
    for k, v in snapshot.items():
        setattr(settings, k, v)


def _apply_test_settings() -> None:
    """Relax safety checks for test environments (no real git repos)."""
    from grace_control.config.settings import settings
    settings.agent_runtime_allow_non_git_scope_skip = True
    settings.agent_runtime_fail_on_bad_git_root = False


@pytest.fixture(autouse=True)
def grace_test_settings():
    _apply_test_settings()


@pytest.fixture
def db():
    """In-memory SQLite database."""
    os.environ["GRACE_CONTEXT_DISABLED"] = "true"
    init_db("sqlite:///:memory:")
    yield


@pytest.fixture
def e2e_db(tmp_path):
    """File-based SQLite for API tests."""
    os.environ["GRACE_CONTEXT_DISABLED"] = "true"
    db_url = f"sqlite:///{tmp_path}/test.db"
    os.environ["GRACE_DB_URL"] = db_url
    init_db(db_url)
    return db_url


@pytest_asyncio.fixture
async def api(tmp_path):
    """ASGI client with per-test unique DB."""
    os.environ["GRACE_CONTEXT_DISABLED"] = "true"
    db_url = f"sqlite:///{tmp_path}/test.db"
    os.environ["GRACE_DB_URL"] = db_url
    init_db(db_url)
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        yield c


def make_packet(db, *, pid, state=PacketState.DRAFT.value, fid="F1", wid="W01",
                attempt=0, max_att=3, profile="NORMAL"):
    """Helper: create a packet in the DB."""
    db.add(Packet(id=pid, feature_id=fid, wave_id=wid, slug=pid.lower(),
                  title=pid, spec_json={"scope": ["src/x.py"]},
                  state=state, attempt_count=attempt, max_attempts=max_att,
                  acceptance_profile=profile))


def make_feature(db, *, fid, status="NOT_STARTED"):
    db.add(Feature(id=fid, slug=fid.lower(), title=fid, spec_json={}, status=status))


def make_wave(db, *, wid, fid, order=1, status="NOT_STARTED"):
    db.add(Wave(id=wid, feature_id=fid, slug=wid.lower(), title=wid, order=order, status=status))


def make_lease(db, packet_id, worker_id, expires_delta=30):
    from datetime import UTC, datetime, timedelta
    db.add(Lease(packet_id=packet_id, worker_id=worker_id,
                 expires_at=datetime.now(UTC) + timedelta(minutes=expires_delta)))
