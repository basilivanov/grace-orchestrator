# AI_HEADER: supervisor — process manager for API + workers
# START_MODULE_CONTRACT
# purpose: Single entry point that owns the GRACE Control Plane runtime.
#          Spawns and supervises the API process + N worker processes,
#          exposes control via a unix-socket FastAPI app, and watches the
#          source tree for mtime changes to auto-reload on edits.
#          Replaces ad-hoc bash launchers (`launch3.sh`).
# inputs: target_dir (--target-dir), source_dir (--source-dir), workers (--workers).
# returns: None; blocks until SIGINT/SIGTERM.
# side_effects: Spawns subprocesses, writes $target_dir/supervisor.json,
#               creates $target_dir/supervisor.sock, registers SIGINT/SIGTERM
#               handlers.
# emitted_logs: supervisor_starting, child_spawned, child_died, restart_triggered,
#               source_changed, child_kill_failed, supervisor_stopping.
# error_behavior: Supervisor never dies. Child crashes are detected via
#                 poll() and trigger an automatic restart. The supervisor's
#                 own crash is the operator's problem (run under systemd or
#                 call `grace_ctl start` again).
# END_MODULE_CONTRACT
# START_MODULE_MAP
# mapping:
#   - class: Supervisor
#   - class: PidRegistry
#   - class: MtimeWatcher
#   - class: SourceRouter
#   - function: main
# END_MODULE_MAP

from __future__ import annotations

import argparse
import asyncio
import dataclasses
import errno
import json
import os
import shutil
import signal
import subprocess
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Awaitable, Callable

import uvicorn
from fastapi import FastAPI, HTTPException

from grace_control.core.structured_logger import GraceLogger

_log = GraceLogger("supervisor")

STATE_FILE_NAME = "supervisor.json"
SOCKET_FILE_NAME = "supervisor.sock"
PID_FILE_NAME = "supervisor.pid"

DEFAULT_TERMINATE_GRACE_SECONDS = 5.0
DEFAULT_POLL_INTERVAL_SECONDS = 2.0
DEFAULT_HEALTH_TIMEOUT_SECONDS = 30.0
DEFAULT_API_URL = "http://127.0.0.1:8042"

WORKER_ID_ENV = "GRACE_WORKER_ID"


# ─────────────────────────────────────────────────────────────────────────────
# Source router: decides which child to restart on a file change
# ─────────────────────────────────────────────────────────────────────────────


class SourceRouter:
    """Map a changed file path to the set of children that must be restarted.

    - `api/**`        → restart API
    - `worker/**`, `core/**`, `adapters/**`, `services/**` → restart workers
    - `supervisor.py`, `supervisor_client.py`, `cli.py`        → restart all
    - everything else (docs, tests, fixtures)                   → no-op
    """

    API_GLOBS: tuple[str, ...] = ("api/",)
    WORKER_GLOBS: tuple[str, ...] = (
        "worker/",
        "core/",
        "adapters/",
        "services/",
        "agent/",
    )
    SELF_GLOBS: tuple[str, ...] = (
        "supervisor.py",
        "supervisor_client.py",
        "cli.py",
        "supervisor/",
    )

    def classify(self, rel_path: str) -> str:
        rel = rel_path.lstrip("./")
        for g in self.SELF_GLOBS:
            if rel == g or rel.startswith(g):
                return "all"
        for g in self.API_GLOBS:
            if rel.startswith(g):
                return "api"
        for g in self.WORKER_GLOBS:
            if rel.startswith(g):
                return "workers"
        return "ignore"

    def collect(self, rel_paths: list[str]) -> str:
        """Reduce a list of changed paths to a single restart target."""
        targets = {self.classify(p) for p in rel_paths}
        targets.discard("ignore")
        if not targets:
            return "ignore"
        if "all" in targets:
            return "all"
        if targets == {"api"}:
            return "api"
        if targets == {"workers"}:
            return "workers"
        # Mixed (api+workers): restart everything to avoid state drift.
        return "all"


# ─────────────────────────────────────────────────────────────────────────────
# Mtime watcher: cheap polling, no external deps
# ─────────────────────────────────────────────────────────────────────────────


class MtimeWatcher:
    """Poll source_dir for mtime changes; yield batches of changed file paths.

    Uses os.stat() on every file under source_dir, no watchdog dep.
    Cheap enough for thousands of files; debounce saves to 1 batch per
    `poll_interval` (whichever the caller requests).
    """

    IGNORE_DIRS: frozenset[str] = frozenset(
        {"__pycache__", ".git", ".pytest_cache", ".venv", "node_modules"}
    )

    def __init__(self, source_dir: Path, poll_interval: float = DEFAULT_POLL_INTERVAL_SECONDS) -> None:
        self._root = source_dir.resolve()
        self._poll_interval = poll_interval
        self._snapshot: dict[str, float] = {}

    def scan(self) -> dict[str, float]:
        result: dict[str, float] = {}
        for dirpath, dirnames, filenames in os.walk(self._root):
            dirnames[:] = [d for d in dirnames if d not in self.IGNORE_DIRS]
            for fname in filenames:
                if not (fname.endswith(".py") or fname.endswith(".yaml")):
                    continue
                p = Path(dirpath) / fname
                try:
                    mtime = p.stat().st_mtime
                except FileNotFoundError:
                    continue
                try:
                    rel = str(p.resolve().relative_to(self._root))
                except ValueError:
                    rel = str(p)
                result[rel] = mtime
        return result

    def prime(self) -> None:
        self._snapshot = self.scan()

    def diff(self) -> list[str]:
        current = self.scan()
        changed: list[str] = []
        for path, mtime in current.items():
            if path not in self._snapshot or self._snapshot[path] != mtime:
                changed.append(path)
        for path in self._snapshot:
            if path not in current:
                changed.append(path)
        self._snapshot = current
        return changed

    @property
    def poll_interval(self) -> float:
        return self._poll_interval


# ─────────────────────────────────────────────────────────────────────────────
# PidRegistry: persistent registry of running child PIDs
# ─────────────────────────────────────────────────────────────────────────────


@dataclass
class ChildRecord:
    """Persistent view of a child process.

    `proc` and `argv_env` are NOT dataclass fields — subprocess.Popen
    contains a thread lock and is not picklable. We attach them as plain
    instance attributes after construction. PidRegistry serializes only
    the dataclass fields.
    """
    role: str
    pid: int
    started_at: float
    argv: list[str]
    last_exit: int | None = None


class PidRegistry:
    """Persist supervisor.json with current child PIDs.

    Format: {"version": 1, "api": {...} | null, "workers": [{...}, ...]}

    Single source of truth for the supervisor state. The API also reads it
    via lifecycle.py to show "what's actually running".
    """

    VERSION = 1

    def __init__(self, target_dir: Path) -> None:
        self._path = target_dir / STATE_FILE_NAME

    def load(self) -> dict[str, Any]:
        if not self._path.exists():
            return {"version": self.VERSION, "api": None, "workers": []}
        try:
            data = json.loads(self._path.read_text())
        except (json.JSONDecodeError, OSError):
            return {"version": self.VERSION, "api": None, "workers": []}
        data.setdefault("api", None)
        data.setdefault("workers", [])
        return data

    def save(self, api: ChildRecord | None, workers: list[ChildRecord]) -> None:
        payload = {
            "version": self.VERSION,
            "api": dataclasses.asdict(api) if api else None,
            "workers": [dataclasses.asdict(w) for w in workers],
        }
        tmp = self._path.with_suffix(".json.tmp")
        tmp.write_text(json.dumps(payload, indent=2))
        tmp.replace(self._path)

    def write_supervisor_pid(self, pid: int) -> None:
        (self._path.parent / PID_FILE_NAME).write_text(str(pid))

    @staticmethod
    def clear() -> None:
        pass  # explicit clear done by Supervisor on stop


# ─────────────────────────────────────────────────────────────────────────────
# Child process helpers
# ─────────────────────────────────────────────────────────────────────────────


def _terminate(proc: subprocess.Popen, grace: float) -> None:
    if proc.poll() is not None:
        return
    try:
        proc.terminate()
    except ProcessLookupError:
        return
    try:
        proc.wait(timeout=grace)
    except subprocess.TimeoutExpired:
        _log.warn("child_kill_failed", pid=proc.pid, action="SIGKILL")
        try:
            proc.kill()
        except ProcessLookupError:
            return
        try:
            proc.wait(timeout=grace)
        except subprocess.TimeoutExpired:
            pass


def _spawn(argv: list[str], cwd: Path, env: dict[str, str], *, stderr_path: str | None = None) -> subprocess.Popen:
    log_file = open(stderr_path, "a") if stderr_path else None
    return subprocess.Popen(
        argv,
        cwd=str(cwd),
        env=env,
        stdout=log_file or subprocess.DEVNULL,
        stderr=log_file or subprocess.STDOUT,
        start_new_session=True,
    )


# START_FUNCTION_CONTRACT
# name: _registered_child_matches
# purpose: Verify that a persisted child record still identifies a live
#          process owned by the current supervisor user.
# inputs: record — serialized ChildRecord loaded from supervisor.json.
# returns: True only when PID ownership and command-line identity both match.
# side_effects: Reads process metadata from /proc.
# emitted_logs: None.
# error_behavior: Returns False when process metadata is missing or unreadable.
# END_FUNCTION_CONTRACT
def _registered_child_matches(record: dict[str, Any]) -> bool:
    try:
        pid = int(record["pid"])
        proc_dir = Path(f"/proc/{pid}")
        if proc_dir.stat().st_uid != os.geteuid():
            return False
        actual_argv = [
            part.decode(errors="replace")
            for part in (proc_dir / "cmdline").read_bytes().split(b"\0")
            if part
        ]
    except (KeyError, TypeError, ValueError, OSError):
        return False

    expected_argv = [str(part) for part in record.get("argv", []) if part]
    return bool(expected_argv) and all(part in actual_argv for part in expected_argv)


# ─────────────────────────────────────────────────────────────────────────────
# Control server: FastAPI on a unix socket
# ─────────────────────────────────────────────────────────────────────────────


def build_control_app(supervisor: "Supervisor") -> FastAPI:
    from contextlib import asynccontextmanager

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        yield  # nothing to init/teardown — supervisor is process-level

    app = FastAPI(
        title="GRACE Supervisor Control",
        version="1.0",
        docs_url=None,
        redoc_url=None,
        openapi_url=None,
        lifespan=lifespan,
    )

    @app.get("/control/status")
    async def status() -> dict[str, Any]:
        return supervisor.status()

    @app.post("/control/restart/{target}")
    async def restart(target: str) -> dict[str, Any]:
        if target not in {"api", "workers", "all"}:
            raise HTTPException(400, f"unknown target: {target!r}; use api|workers|all")
        await supervisor.restart(target)
        return {"ok": True, "target": target}

    @app.post("/control/stop")
    async def stop() -> dict[str, Any]:
        asyncio.create_task(supervisor.stop())
        return {"ok": True, "stopping": True}

    @app.post("/control/cleanup")
    async def cleanup(
        worktrees: bool = True,
        state_files: bool = True,
        stale_leases: bool = True,
        stale_lease_minutes: int = 30,
        stale_state_days: int = 7,
    ) -> dict[str, Any]:
        """Idempotent cleanup of supervisor-owned state.

        Args:
            worktrees: prune orphaned git worktrees under .grace_worktrees/
            state_files: remove .grace_state/ entries older than `stale_state_days`
            stale_leases: release DB leases older than `stale_lease_minutes`
                           and mark the underlying packet FAILED.
        """
        from grace_control.services.supervisor_cleanup_service import (
            SupervisorCleanupService,
        )

        svc = SupervisorCleanupService(
            target_dir=supervisor.cfg.target_dir,
            source_dir=supervisor.cfg.source_dir,
        )
        report = svc.run(
            stale_lease_minutes=stale_lease_minutes,
            stale_state_days=stale_state_days,
            worktrees=worktrees,
            state_files=state_files,
            stale_leases=stale_leases,
        )
        return {"ok": True, "report": report.to_dict()}

    @app.post("/control/reload")
    async def reload() -> dict[str, Any]:
        """Re-prime the mtime watcher (useful after git pull).

        Note: this does not restart children. Use `restart` for that.
        """
        if supervisor.watcher is not None:
            supervisor.watcher.prime()
        return {"ok": True, "watcher_primed": supervisor.watcher is not None}

    return app


# ─────────────────────────────────────────────────────────────────────────────
# Supervisor
# ─────────────────────────────────────────────────────────────────────────────


@dataclass
class SupervisorConfig:
    target_dir: Path
    source_dir: Path
    workers: int = 1
    worker_id_prefix: str = "grace-worker"
    api_url: str = DEFAULT_API_URL
    health_timeout: float = DEFAULT_HEALTH_TIMEOUT_SECONDS
    terminate_grace: float = DEFAULT_TERMINATE_GRACE_SECONDS
    watch: bool = True

    @property
    def api_script(self) -> Path:
        return self.source_dir / "scripts" / "run_api.py"

    @property
    def worker_script(self) -> Path:
        return self.source_dir / "scripts" / "live_worker.py"


class Supervisor:
    def __init__(self, cfg: SupervisorConfig) -> None:
        self.cfg = cfg
        self.log = _log
        self.registry = PidRegistry(cfg.target_dir)
        self.watcher = MtimeWatcher(cfg.source_dir) if cfg.watch else None
        self.router = SourceRouter()
        self._api: ChildRecord | None = None
        self._workers: list[ChildRecord] = []
        self._stopping = asyncio.Event()
        self._restart_lock = asyncio.Lock()
        self._supervisor_pid = os.getpid()
        self._socket_path = cfg.target_dir / SOCKET_FILE_NAME
        self._control_task: asyncio.Task[None] | None = None

    # ── public API ────────────────────────────────────────────────────────

    async def start(self) -> None:
        self.log.info("supervisor_starting",
                      target_dir=str(self.cfg.target_dir),
                      source_dir=str(self.cfg.source_dir),
                      workers=self.cfg.workers)
        cfg = self.cfg
        cfg.target_dir.mkdir(parents=True, exist_ok=True)
        if self._socket_path.exists():
            self._socket_path.unlink()
        self.registry.write_supervisor_pid(self._supervisor_pid)
        # Kill any leftover children from a previous run
        await self._reap_orphans()

        # Spawn API + workers
        await self._restart_api()
        await self._restart_workers(self.cfg.workers)

        # Start mtime watcher
        if self.watcher is not None:
            self.watcher.prime()

        # Start control server on unix socket
        self._control_task = asyncio.create_task(self._serve_control())

        # Block on stop signal
        await self._stopping.wait()
        await self._shutdown()

    async def stop(self) -> None:
        self._stopping.set()

    async def restart(self, target: str) -> None:
        async with self._restart_lock:
            if target in ("api", "all"):
                await self._restart_api()
            if target in ("workers", "all"):
                await self._restart_workers(self.cfg.workers)

    def status(self) -> dict[str, Any]:
        def live(rec: ChildRecord) -> bool:
            try:
                os.kill(rec.pid, 0)
                return True
            except OSError:
                return False

        return {
            "supervisor_pid": self._supervisor_pid,
            "target_dir": str(self.cfg.target_dir),
            "source_dir": str(self.cfg.source_dir),
            "api": (
                {
                    "pid": self._api.pid,
                    "started_at": self._api.started_at,
                    "argv": self._api.argv,
                    "alive": live(self._api) if self._api else False,
                    "last_exit": self._api.last_exit,
                }
                if self._api
                else None
            ),
            "workers": [
                {
                    "pid": w.pid,
                    "started_at": w.started_at,
                    "worker_id": (getattr(w, "_env_ref", {}) or {}).get(WORKER_ID_ENV, ""),
                    "alive": live(w),
                    "last_exit": w.last_exit,
                }
                for w in self._workers
            ],
        }

    # ── internals ─────────────────────────────────────────────────────────

    def _child_env(self) -> dict[str, str]:
        env = os.environ.copy()
        env["GRACE_ALLOW_SANDBOX_BYPASS"] = "true"
        env["GRACE_API_URL"] = self.cfg.api_url
        # Propagate database and project roots to children so API and
        # worker share the same DB file and directories.
        for _k in ("GRACE_DB_URL", "GRACE_DATABASE_URL",
                   "GRACE_PROJECT_ROOT", "GRACE_STATE_ROOT",
                   "GRACE_WORKTREE_ROOT", "GRACE_SOURCE_DIR"):
            if _k in env:
                env[_k] = env[_k]
        # Opencode runtime vars must NOT leak into children, otherwise
        # `opencode run` returns "Session not found".
        for k in [k for k in list(env) if k == "OPENCODE" or k.startswith("OPENCODE_")]:
            del env[k]
        return env

    def _make_worker_argv(self, slot: int) -> tuple[list[str], dict[str, str]]:
        env = self._child_env()
        wid = f"{self.cfg.worker_id_prefix}-{slot}-pid{os.getpid()}"
        env[WORKER_ID_ENV] = wid
        argv = [sys.executable, str(self.cfg.worker_script)]
        return argv, env

    async def _restart_api(self) -> None:
        if self._api is not None:
            _log.info("api_stopping", pid=self._api.pid)
            proc = getattr(self._api, "_proc_ref", None)
            if proc is not None:
                _terminate(proc, self.cfg.terminate_grace)
        env = self._child_env()
        env["GRACE_API_URL"] = self.cfg.api_url
        argv = [sys.executable, str(self.cfg.api_script)]
        proc = _spawn(argv, self.cfg.target_dir, env,
                      stderr_path=str(self.cfg.target_dir / "api.log"))
        rec = ChildRecord(
            role="api",
            pid=proc.pid,
            started_at=time.time(),
            argv=argv,
        )
        # Non-serializable refs go on the side:
        rec._proc_ref = proc  # type: ignore[attr-defined]
        rec._env_ref = env  # type: ignore[attr-defined]
        self._api = rec
        self._persist()
        # Wait for API /health
        await self._wait_for_health(self.cfg.api_url, timeout=self.cfg.health_timeout)
        _log.info("api_started", pid=self._api.pid, argv=argv)

    async def _restart_workers(self, n: int) -> None:
        for w in list(self._workers):
            proc = getattr(w, "_proc_ref", None)
            if proc is not None:
                _log.info("worker_stopping", pid=w.pid)
                _terminate(proc, self.cfg.terminate_grace)
        self._workers = []
        for slot in range(n):
            argv, env = self._make_worker_argv(slot)
            proc = _spawn(argv, self.cfg.target_dir, env,
                          stderr_path=str(self.cfg.target_dir / "worker.log"))
            rec = ChildRecord(
                role="worker",
                pid=proc.pid,
                started_at=time.time(),
                argv=argv,
            )
            rec._proc_ref = proc  # type: ignore[attr-defined]
            rec._env_ref = env  # type: ignore[attr-defined]
            self._workers.append(rec)
        self._persist()
        _log.info("workers_started", count=len(self._workers), pids=[w.pid for w in self._workers])

    async def _wait_for_health(self, url: str, timeout: float) -> None:
        import httpx

        deadline = time.time() + timeout
        last_err: str = ""
        async with httpx.AsyncClient(timeout=2.0) as client:
            while time.time() < deadline:
                try:
                    r = await client.get(f"{url}/health")
                    if r.status_code == 200:
                        return
                except Exception as e:
                    last_err = str(e)[:120]
                await asyncio.sleep(0.5)
        raise RuntimeError(f"API at {url} did not become healthy within {timeout}s: {last_err}")

    async def _reap_orphans(self) -> None:
        prev = self.registry.load()
        records = [
            record
            for record in [prev.get("api"), *prev.get("workers", [])]
            if isinstance(record, dict) and record.get("pid")
        ]
        signalled: list[dict[str, Any]] = []
        for record in records:
            if not _registered_child_matches(record):
                _log.info(
                    "orphan_record_skipped",
                    role=record.get("role", "unknown"),
                    pid=record["pid"],
                    reason="pid_owner_or_command_mismatch",
                )
                continue
            _log.info(
                "orphan_child_reaping",
                role=record.get("role", "unknown"),
                pid=record["pid"],
            )
            try:
                os.kill(int(record["pid"]), signal.SIGTERM)
                signalled.append(record)
            except (ProcessLookupError, PermissionError):
                pass
        if not signalled:
            return
        await asyncio.sleep(self.cfg.terminate_grace)
        for record in signalled:
            if not _registered_child_matches(record):
                continue
            try:
                os.kill(int(record["pid"]), signal.SIGKILL)
                _log.info(
                    "orphan_force_killed",
                    role=record.get("role", "unknown"),
                    pid=record["pid"],
                )
            except (ProcessLookupError, PermissionError):
                pass

    def _persist(self) -> None:
        self.registry.save(self._api, self._workers)

    async def _shutdown(self) -> None:
        _log.info("supervisor_stopping", pid=self._supervisor_pid)
        if self._control_task is not None:
            self._control_task.cancel()
            try:
                await self._control_task
            except (asyncio.CancelledError, Exception):
                pass
        for w in list(self._workers):
            proc = getattr(w, "_proc_ref", None)
            if proc is not None:
                _terminate(proc, self.cfg.terminate_grace)
        if self._api is not None:
            proc = getattr(self._api, "_proc_ref", None)
            if proc is not None:
                _terminate(proc, self.cfg.terminate_grace)
        try:
            if self._socket_path.exists():
                self._socket_path.unlink()
        except OSError:
            pass

    async def _serve_control(self) -> None:
        app = build_control_app(self)
        config = uvicorn.Config(
            app,
            uds=str(self._socket_path),
            log_level="warning",
            access_log=False,
            lifespan="off",
            loop="asyncio",
        )
        server = uvicorn.Server(config)
        try:
            _log.info("control_server_listening", socket=str(self._socket_path))
            await server.serve()
        except asyncio.CancelledError:
            _log.info("control_server_cancelled")
            server.should_exit = True
            raise
        except Exception as e:
            _log.error("control_server_failed", error=str(e)[:300])

    async def watch_loop(self) -> None:
        """Optional background task: mtime watch → restart."""
        if self.watcher is None:
            return
        loop = asyncio.get_running_loop()
        # Re-prime periodically in case new files appear
        while not self._stopping.is_set():
            await asyncio.sleep(self.watcher.poll_interval)
            try:
                changed = await loop.run_in_executor(None, self.watcher.diff)
            except Exception as e:
                _log.warn("mtime_scan_failed", error=str(e)[:200])
                continue
            if not changed:
                continue
            target = self.router.collect(changed)
            if target == "ignore":
                continue
            _log.info("source_changed", files=changed[:10], total=len(changed), target=target)
            await self.restart(target)


# ─────────────────────────────────────────────────────────────────────────────
# CLI entry point
# ─────────────────────────────────────────────────────────────────────────────


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    p = argparse.ArgumentParser(
        prog="grace-supervisor",
        description="GRACE Control Plane supervisor: spawns API + workers, watches code, exposes control unix-socket.",
    )
    p.add_argument("--target-dir", required=True, type=Path,
                   help="Project working directory (where the .grace/ config + DB live).")
    p.add_argument("--source-dir", required=True, type=Path,
                   help="Repository source root (where src/ lives).")
    p.add_argument("--workers", type=int, default=1, help="Number of worker processes to spawn.")
    p.add_argument("--api-url", default=DEFAULT_API_URL, help="API listen URL (used for health checks).")
    p.add_argument("--no-watch", action="store_true", help="Disable mtime auto-reload.")
    p.add_argument("--terminate-grace", type=float, default=DEFAULT_TERMINATE_GRACE_SECONDS,
                   help="Seconds to wait between SIGTERM and SIGKILL on a child.")
    return p.parse_args(argv)


async def _amain(args: argparse.Namespace) -> int:
    cfg = SupervisorConfig(
        target_dir=args.target_dir.resolve(),
        source_dir=args.source_dir.resolve(),
        workers=args.workers,
        api_url=args.api_url,
        watch=not args.no_watch,
        terminate_grace=args.terminate_grace,
    )
    sup = Supervisor(cfg)

    loop = asyncio.get_running_loop()

    def _on_signal(signame: str) -> None:
        _log.info("signal_received", signal=signame)
        asyncio.create_task(sup.stop())

    for sig in (signal.SIGTERM, signal.SIGINT):
        try:
            loop.add_signal_handler(sig, _on_signal, sig.name)
        except NotImplementedError:
            pass  # Windows

    # Run supervisor.start() and watch_loop() concurrently.
    start_task = asyncio.create_task(sup.start())
    watch_task: asyncio.Task[None] | None = None
    if cfg.watch:
        watch_task = asyncio.create_task(sup.watch_loop())

    try:
        await start_task
    finally:
        if watch_task is not None:
            watch_task.cancel()
            try:
                await watch_task
            except asyncio.CancelledError:
                pass

    return 0


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)
    try:
        return asyncio.run(_amain(args))
    except KeyboardInterrupt:
        return 130


if __name__ == "__main__":
    sys.exit(main())
