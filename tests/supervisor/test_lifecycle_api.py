# AI_HEADER: tests for /api/admin/lifecycle/* GET/POST endpoints
import threading
import time
from pathlib import Path

import pytest
import uvicorn
from httpx import ASGITransport, AsyncClient

from grace_control.api.main import app
from grace_control.db import init_db
from grace_control.supervisor import Supervisor, SupervisorConfig, build_control_app

REPO_ROOT = Path(__file__).resolve().parents[2]
SRC_DIR = REPO_ROOT / "src"


def _free_socket(path: Path) -> None:
    if path.exists():
        path.unlink()


def _wait_for_socket(path: Path, timeout: float = 5.0) -> bool:
    deadline = time.time() + timeout
    while time.time() < deadline:
        if path.exists():
            return True
        time.sleep(0.05)
    return False


class _ServerThread:
    """Run a uvicorn server in a background thread with its own event loop."""

    def __init__(self, app, sock: Path) -> None:
        self._app = app
        self._sock = sock
        self._config = uvicorn.Config(
            app, uds=str(sock),
            log_level="warning", access_log=False,
            lifespan="off", loop="asyncio",
        )
        self._server = uvicorn.Server(self._config)
        self._thread: threading.Thread | None = None

    def start(self) -> None:
        self._thread = threading.Thread(target=self._server.run, daemon=True)
        self._thread.start()
        assert _wait_for_socket(self._sock, timeout=5.0)

    def stop(self) -> None:
        self._server.should_exit = True
        if self._thread is not None:
            self._thread.join(timeout=2.0)


@pytest.fixture
def supervisor_env(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """Start a real supervisor control app on a unix socket, no children."""
    monkeypatch.setenv("GRACE_CONTEXT_DISABLED", "true")
    db_url = f"sqlite:///{tmp_path}/test.db"
    monkeypatch.setenv("GRACE_DB_URL", db_url)
    init_db(db_url)

    cfg = SupervisorConfig(
        target_dir=tmp_path,
        source_dir=tmp_path,
        workers=0,
        watch=False,
        health_timeout=1.0,
        terminate_grace=1.0,
    )
    sup = Supervisor(cfg)

    sock = tmp_path / "supervisor.sock"
    _free_socket(sock)

    # Persist state so the lifecycle router sees a "running" supervisor
    (tmp_path / "supervisor.json").write_text(
        '{"version": 1, "api": null, "workers": []}'
    )

    control_app = build_control_app(sup)
    server = _ServerThread(control_app, sock)
    server.start()
    monkeypatch.setenv("GRACE_TARGET_DIR", str(tmp_path))

    yield tmp_path, sock

    server.stop()
    _free_socket(sock)


@pytest.mark.asyncio
async def test_lifecycle_restart_proxy(supervisor_env) -> None:
    """POST /api/admin/lifecycle/restart/workers reaches supervisor.sock."""
    tmp_path, sock = supervisor_env

    transport = ASGITransport(app=app)
    project_key = app.__dict__["state"].runtime_identity["project_key"]
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        r = await c.post(
            "/api/admin/lifecycle/restart/workers",
            json={"confirmation": {"intent": "confirm", "value": project_key}},
        )
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["ok"] is True
        assert body["response"]["target"] == "workers"


@pytest.mark.asyncio
async def test_lifecycle_restart_invalid_target(supervisor_env) -> None:
    tmp_path, _ = supervisor_env

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        r = await c.post("/api/admin/lifecycle/restart/bogus")
        assert r.status_code == 400
        assert "api|workers|all" in r.text


@pytest.mark.asyncio
async def test_lifecycle_cleanup_proxy(supervisor_env) -> None:
    """The pre-Control-Center cleanup alias is audited but unavailable."""
    tmp_path, _ = supervisor_env

    transport = ASGITransport(app=app)
    project_key = app.__dict__["state"].runtime_identity["project_key"]
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        r = await c.post(
            "/api/admin/lifecycle/cleanup",
            json={"confirmation": {"intent": "confirm", "value": project_key}},
        )
        assert r.status_code == 501, r.text
        assert r.json()["error_code"] == "CONTROL_UNAVAILABLE"


@pytest.mark.asyncio
async def test_lifecycle_reload_proxy(supervisor_env) -> None:
    tmp_path, _ = supervisor_env

    transport = ASGITransport(app=app)
    project_key = app.__dict__["state"].runtime_identity["project_key"]
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        r = await c.post(
            "/api/admin/lifecycle/reload",
            json={"confirmation": {"intent": "confirm", "value": project_key}},
        )
        assert r.status_code == 200
        assert r.json()["ok"] is True
        assert r.json()["response"] == {"ok": True, "watcher_primed": False}


@pytest.mark.asyncio
async def test_lifecycle_shutdown_proxy(supervisor_env) -> None:
    """The destructive pre-Control-Center shutdown alias is unavailable."""
    tmp_path, _ = supervisor_env

    transport = ASGITransport(app=app)
    project_key = app.__dict__["state"].runtime_identity["project_key"]
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        r = await c.post(
            "/api/admin/lifecycle/shutdown",
            json={"confirmation": {"intent": "confirm", "value": project_key}},
        )
        assert r.status_code == 501
        assert r.json()["error_code"] == "CONTROL_UNAVAILABLE"


@pytest.mark.asyncio
async def test_lifecycle_status_503_when_state_missing(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("GRACE_TARGET_DIR", str(tmp_path))
    # No supervisor.json + no supervisor.sock in tmp_path
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        r = await c.get("/api/admin/lifecycle/status")
        assert r.status_code == 503
        assert "supervisor" in r.text.lower()


@pytest.mark.asyncio
async def test_lifecycle_get_status(supervisor_env) -> None:
    """GET /api/admin/lifecycle/status returns supervisor_state + workers + sha."""
    tmp_path, _ = supervisor_env

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        r = await c.get("/api/admin/lifecycle/status")
        assert r.status_code == 200
        body = r.json()
        assert "supervisor_state" in body
        assert "db_workers" in body
        assert "code_sha" in body
        assert "fetched_at" in body


@pytest.mark.asyncio
async def test_lifecycle_get_health_full(supervisor_env) -> None:
    """GET /api/admin/lifecycle/health/full returns structured health summary."""
    tmp_path, _ = supervisor_env

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        r = await c.get("/api/admin/lifecycle/health/full")
        assert r.status_code == 200
        body = r.json()
        assert "healthy" in body
        assert "issues" in body
        assert "supervisor_alive" in body
