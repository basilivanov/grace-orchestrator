#!/usr/bin/env python3
"""Run golden test via API directly — no CLI, no zombie workers, fast-fail."""
import argparse
import json
import os
import subprocess
import sys
import time
from pathlib import Path

import httpx
import yaml

TERMINAL = frozenset(("merged", "failed", "rejected", "blocked", "cancelled", "accepted"))
DEADLINE_S = int(os.environ.get("GRACE_GOLDEN_TIMEOUT", "1200"))


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("feature_file", help="Path to golden test YAML")
    parser.add_argument("--workers", type=int, default=1)
    parser.add_argument("--api-url", default="http://localhost:8042")
    parser.add_argument("--db-url", default=None)
    parser.add_argument("--state-root", default=None)
    parser.add_argument("--start-api", action="store_true", help="Start API before test")
    parser.add_argument("--resume", action="store_true", help="Resume existing test (reuse state, skip timestamp)")
    args = parser.parse_args()

    feature_path = Path(args.feature_file).resolve()
    spec = yaml.safe_load(feature_path.read_text())

    if args.resume:
        run_slug = feature_path.stem
    else:
        run_slug = f"{feature_path.stem}-{int(time.time()) % 100000}"
        spec["title"] = f"{spec.get('title', run_slug)} #{run_slug}"

    state_root = args.state_root or f"/tmp/grace-eval/{run_slug}"
    db_url = args.db_url or f"sqlite:///{state_root}/grace.db"

    api_url = args.api_url

    # 1. Start API if requested
    if args.start_api:
        subprocess.run(["fuser", "-k", "8042/tcp"], capture_output=True)
        if not args.resume:
            os.makedirs(state_root, exist_ok=True)
            os.makedirs(f"{state_root}/worktrees", exist_ok=True)
        api_env = {**os.environ, "GRACE_DB_URL": db_url, "GRACE_AGENT_TIMEOUT": "1200",
                   "GRACE_CONTEXT_DISABLED": "true", "PYTHONDONTWRITEBYTECODE": "1",
                   "GRACE_ALLOW_DIRTY_TARGET_MERGE": "true"}
        api_proc = subprocess.Popen(
            [sys.executable, "scripts/run_api.py"],
            env=api_env,
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        )
        print("Waiting for API...", end="", flush=True)
        for _ in range(20):
            time.sleep(0.5)
            try:
                httpx.get(f"{api_url}/api/packets/claim", timeout=2)
                print(" ready")
                break
            except Exception:
                print(".", end="", flush=True)
        else:
            print(" FAILED")
            sys.exit(1)

    # 2. Architect plan
    print(f"POST /api/architect/plan  ({feature_path.name})")
    t0 = time.time()
    c = httpx.Client(base_url=api_url, timeout=30)
    try:
        r = c.post("/api/architect/plan", json={"feature_spec": spec})
        r.raise_for_status()
    except httpx.HTTPError as e:
        print(f"  [FAIL] {e}  ({time.time()-t0:.1f}s)")
        if args.start_api:
            api_proc.terminate()
        sys.exit(1)
    data = r.json()["data"]
    fid = data["feature_id"]
    pids = data["packets"]
    print(f"  [OK] {fid} — {len(pids)} packets  ({time.time()-t0:.1f}s)")

    if not pids:
        print("No packets to execute")
        sys.exit(1)

    # 3. Register worker
    c.post("/api/workers/register", json={"worker_id": "golden-w0"})

    # 4. Spawn worker subprocess
    worker_env = {
        **os.environ,
        "PYTHONDONTWRITEBYTECODE": "1",
        "PYTHONPATH": f"{Path.cwd()}/src",
        "GRACE_DB_URL": db_url,
        "GRACE_TARGET_REPO_ROOT": str(Path.cwd()),
        "GRACE_STATE_ROOT": state_root,
        "GRACE_WORKTREE_ROOT": f"{state_root}/worktrees",
        "GRACE_BASE_REF": os.environ.get("GRACE_BASE_REF", "main"),
        "GRACE_ALLOW_SANDBOX_BYPASS": "true",
    }
    worker = subprocess.Popen(
        [sys.executable, "-c", f"""
import os, sys, asyncio
sys.path.insert(0, "{Path.cwd()}/src")
os.environ["GRACE_ALLOW_SANDBOX_BYPASS"] = "true"
from grace_control.db import init_db
from grace_control.worker.worker import Worker
init_db()
w = Worker(worker_id="golden-w0", api_url="{api_url}")
async def m(): await w.start()
asyncio.run(m())
"""],
        env=worker_env,
    )

    # 5. Poll results
    print("\nPolling ", end="", flush=True)
    start = time.time()
    states: dict[str, str] = {}
    prev = ""

    while time.time() - start < DEADLINE_S:
        time.sleep(2)

        # Worker died?
        rc = worker.poll()
        if rc is not None:
            print(f" [worker died rc={rc}]")

        # Fetch states
        for pid in pids:
            try:
                r = c.get(f"/api/packets/{pid}", timeout=5)
                states[pid] = r.json()["data"]["state"]
            except Exception:
                pass

        # Print only on state change
        current = " ".join(states.get(pid, "?") for pid in pids)
        if current != prev:
            prev = current
            print(f"\n  {current}", end="", flush=True)

        # All terminal?
        if states and all(s in TERMINAL for s in states.values()):
            break

    elapsed = time.time() - start
    print(f"\nDone in {elapsed:.0f}s")

    worker.terminate()
    try:
        worker.wait(timeout=5)
    except subprocess.TimeoutExpired:
        worker.kill()

    # 6. Report
    passed = all(states.get(pid) == "merged" for pid in pids)
    print(f"{'PASSED' if passed else 'FAILED'}")
    for pid in pids:
        print(f"  {states.get(pid, '?'):10s} {pid[-50:]}")
    sys.exit(0 if passed else 1)


if __name__ == "__main__":
    main()
