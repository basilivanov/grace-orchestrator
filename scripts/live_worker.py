#!/usr/bin/env python3
"""Start a single GRACE worker process.

Reads GRACE_WORKER_ID from env (set by the supervisor) so
that each spawned worker has a unique, traceable id. Falls back to
`worker-<pid>` for ad-hoc runs.

In production this script is launched by grace-supervisor, not by hand.
"""
import os
import sys
import asyncio
from pathlib import Path

# sys.path.insert(0, "src")  # disabled: use editable install from source_dir
os.environ.setdefault("GRACE_ALLOW_SANDBOX_BYPASS", "true")
# Honor either GRACE_DB_URL (set by supervisor) or GRACE_DATABASE_URL (env yaml).
# Fallback to a sane default ONLY if neither is set, so ad-hoc runs still work.
if "GRACE_DB_URL" not in os.environ and "GRACE_DATABASE_URL" in os.environ:
    os.environ["GRACE_DB_URL"] = os.environ["GRACE_DATABASE_URL"]
os.environ.setdefault("GRACE_DB_URL", f"sqlite:///{Path.cwd() / 'grace.db'}")

# Protect worker from OOM killer: only an agent run subprocess should
# be a candidate when memory runs out, not the worker or the API.
try:
    with open("/proc/self/oom_score_adj", "w") as _f:
        _f.write("-1000\n")
except OSError:
    pass

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
        state_root=Path(os.environ.get("GRACE_STATE_ROOT", str(project_root / ".grace" / "state"))),
        worktree_root=Path(os.environ.get("GRACE_WORKTREE_ROOT", str(project_root / ".grace" / "worktrees"))),
    )
    await w.start()


if __name__ == "__main__":
    asyncio.run(_main())
