#!/usr/bin/env python3
"""Start a single GRACE worker process.

Reads GRACE_WORKER_ID from env (set by `grace_ctl start` / supervisor) so
that each spawned worker has a unique, traceable id. Falls back to
`worker-<pid>` for ad-hoc runs.

In production this script is launched by grace-supervisor, not by hand.
"""
import os
import sys
import asyncio
from pathlib import Path

sys.path.insert(0, "src")
os.environ.setdefault("GRACE_ALLOW_SANDBOX_BYPASS", "true")
os.environ.setdefault("GRACE_DB_URL", "sqlite:////tmp/grace_live.db")

from grace_control.db import init_db
from grace_control.worker.worker import Worker

DEFAULT_API_URL = "http://127.0.0.1:8042"


def _resolve_worker_id() -> str:
    explicit = os.environ.get("GRACE_WORKER_ID")
    if explicit:
        return explicit
    # Ad-hoc: still unique, for `python scripts/live_worker.py` from shell.
    return f"worker-adhoc-{os.getpid()}"


async def _main() -> None:
    worker_id = _resolve_worker_id()
    api_url = os.environ.get("GRACE_API_URL", DEFAULT_API_URL)
    project_root = Path(os.environ.get("GRACE_PROJECT_ROOT", "."))
    w = Worker(
        worker_id=worker_id,
        api_url=api_url,
        project_root=project_root,
        state_root=Path(os.environ.get("GRACE_STATE_ROOT", project_root / ".grace_state")),
        worktree_root=Path(os.environ.get("GRACE_WORKTREE_ROOT", project_root / ".grace_worktrees")),
    )
    await w.start()


if __name__ == "__main__":
    asyncio.run(_main())
