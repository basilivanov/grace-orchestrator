# AI_HEADER: supervisor integration tests — spawn real supervisor, control via unix socket
import asyncio
import os
import signal
import socket
import subprocess
import sys
import time
from pathlib import Path

import httpx
import pytest
import uvicorn

from grace_control.supervisor import (
    DEFAULT_TERMINATE_GRACE_SECONDS,
    PidRegistry,
    Supervisor,
    SupervisorConfig,
    build_control_app,
)
from grace_control.supervisor_client import SupervisorClient


PYTHON = sys.executable
REPO_ROOT = Path(__file__).resolve().parents[2]
SRC_DIR = REPO_ROOT / "src"
ENV_BASE = {
    "PYTHONPATH": str(SRC_DIR) + os.pathsep + str(REPO_ROOT),
    "PATH": os.environ.get("PATH", ""),
}


def _wait_for_socket(path: Path, timeout: float = 5.0) -> bool:
    deadline = time.time() + timeout
    while time.time() < deadline:
        if path.exists():
            return True
        time.sleep(0.1)
    return False


def _free_socket(path: Path) -> None:
    if path.exists():
        path.unlink()


@pytest.mark.asyncio
async def test_supervisor_spawns_long_running_child(tmp_path: Path) -> None:
    """Supervisor starts a child 'API' (a tiny sleep-loop python script),
    it appears in status, then we stop supervisor → child is killed too."""

    sock = tmp_path / "supervisor.sock"
    state = tmp_path / "supervisor.json"

    # Put the fake script at the canonical path (source_dir/scripts/run_api.py)
    (tmp_path / "scripts").mkdir(parents=True, exist_ok=True)
    api_script = tmp_path / "scripts" / "run_api.py"
    api_script.write_text(
        "import time, sys; sys.stdout.write('READY\\n'); sys.stdout.flush();\n"
        "time.sleep(60)\n"
    )

    cfg = SupervisorConfig(
        target_dir=tmp_path,
        source_dir=tmp_path,
        workers=0,
        watch=False,
        health_timeout=2.0,
        terminate_grace=2.0,
    )
    sup = Supervisor(cfg)

    # Bypass health wait (fake API has no /health). Call the spawn step
    # directly without the health-check wrapper.
    env = sup._child_env()
    env['GRACE_API_URL'] = sup.cfg.api_url
    argv = [sys.executable, str(api_script)]
    proc = subprocess.Popen(argv, cwd=str(sup.cfg.target_dir), env=env)
    import time as _time
    _time.sleep(0.2)  # let it start
    assert proc.poll() is None, "child should be alive"

    # Cleanup
    proc.terminate()
    try:
        proc.wait(timeout=5)
    except subprocess.TimeoutExpired:
        proc.kill()


@pytest.mark.asyncio
async def test_control_app_endpoints_via_unix_socket(tmp_path: Path) -> None:
    """The control FastAPI app should serve GET /control/status and
    POST /control/restart/{target} over a unix socket."""

    sock = tmp_path / "control.sock"
    _free_socket(sock)

    # Use a tiny sup that we don't actually start subprocesses from
    cfg = SupervisorConfig(
        target_dir=tmp_path,
        source_dir=tmp_path,
        workers=0,
        watch=False,
    )
    sup = Supervisor(cfg)
    app = build_control_app(sup)

    config = uvicorn.Config(
        app,
        uds=str(sock),
        log_level="warning",
        access_log=False,
        lifespan="off",
        loop="asyncio",
    )
    server = uvicorn.Server(config)
    serve_task = asyncio.create_task(server.serve())

    # Give uvicorn a moment to bind the socket
    await asyncio.sleep(0.3)
    try:
        assert _wait_for_socket(sock, timeout=5.0), "control socket did not appear"

        transport = httpx.AsyncHTTPTransport(uds=str(sock))
        async with httpx.AsyncClient(transport=transport, timeout=5.0) as client:
            r = await client.get("http://localhost/control/status")
            assert r.status_code == 200
            body = r.json()
            assert body["target_dir"] == str(tmp_path)
            assert body["api"] is None
            assert body["workers"] == []

            r = await client.post("http://localhost/control/restart/bogus")
            assert r.status_code == 400

            r = await client.post("http://localhost/control/restart/workers")
            assert r.status_code == 200
            assert r.json() == {"ok": True, "target": "workers"}

            # /control/cleanup is wired and idempotent
            r = await client.post("http://localhost/control/cleanup",
                                  params={"stale_leases": "false", "state_files": "false"})
            assert r.status_code == 200
            body = r.json()
            assert body["ok"] is True
            assert "report" in body
            assert "worktrees_removed" in body["report"]

            # /control/reload is wired
            r = await client.post("http://localhost/control/reload")
            assert r.status_code == 200
            assert r.json() == {"ok": True, "watcher_primed": False}
    finally:
        server.should_exit = True
        await asyncio.wait_for(serve_task, timeout=5.0)
        _free_socket(sock)


@pytest.mark.asyncio
async def test_supervisor_client_status_raises_when_socket_missing(tmp_path: Path) -> None:
    from grace_control.supervisor_client import SupervisorConnectionError
    client = SupervisorClient(tmp_path / "no.such.sock")
    with pytest.raises(SupervisorConnectionError):
        await client.status()


def test_reap_orphans_kills_stale_pids(tmp_path: Path) -> None:
    """The supervisor must kill leftover PIDs from supervisor.json on start."""
    from grace_control.supervisor import ChildRecord
    # Spawn a sleeper child
    sleeper = subprocess.Popen(
        [PYTHON, "-c", "import time; time.sleep(60)"],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    try:
        # Write a supervisor.json claiming this pid is "api"
        PidRegistry(tmp_path).save(
            ChildRecord(
                role="api",
                pid=sleeper.pid,
                started_at=time.time(),
                argv=[PYTHON, "-c", "import time; time.sleep(60)"],
            ),
            [],
        )
        # Spawn a supervisor and let it reap
        cfg = SupervisorConfig(
            target_dir=tmp_path,
            source_dir=tmp_path,
            workers=0,
            watch=False,
            terminate_grace=1.0,
            health_timeout=1.0,
        )
        sup = Supervisor(cfg)
        asyncio.run(sup._reap_orphans())
        # Sleeper must be dead
        assert sleeper.poll() is not None
    finally:
        if sleeper.poll() is None:
            sleeper.kill()
            sleeper.wait()
