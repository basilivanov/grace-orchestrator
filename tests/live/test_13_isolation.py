#!/usr/bin/env python3
"""L-13: Multi-Feature Isolation — two features in parallel, no cross-contamination."""

import httpx
import subprocess
import sys
import time
import os
from pathlib import Path

API = "http://127.0.0.1:8042"
PROJECT = str(Path(__file__).resolve().parent.parent.parent)
FIXTURE_A = str(Path(__file__).resolve().parent.parent / "fixtures" / "13a_isolation_alpha.yaml")
FIXTURE_B = str(Path(__file__).resolve().parent.parent / "fixtures" / "13b_isolation_beta.yaml")

c = httpx.Client(base_url=API, timeout=10)

def _plan(path):
    import yaml
    spec = yaml.safe_load(Path(path).read_text())
    r = c.post("/api/architect/plan", json={"feature_spec": spec})
    if r.status_code != 200:
        print(f"FAIL: plan {r.status_code}: {r.text[:200]}")
        sys.exit(1)
    data = r.json()["data"]
    print(f"Feature: {data['feature_id']} | {len(data['packets'])} packets")
    return data["feature_id"], data["packets"]

def _packet_state(pid):
    r = c.get(f"/api/packets/{pid}")
    return r.json()["data"]["state"]

def _start_worker(wid):
    code = f"""
import os, sys, asyncio
sys.path.insert(0, "{PROJECT}/src")
os.environ["GRACE_ALLOW_SANDBOX_BYPASS"] = "true"
from pathlib import Path
from grace_control.db import init_db
from grace_control.worker.worker import Worker
init_db()
w = Worker(worker_id="{wid}", api_url="{API}",
           project_root=Path("{PROJECT}"),
           state_root=Path("{PROJECT}/.grace_state"),
           worktree_root=Path("{PROJECT}/.grace_worktrees"))
async def m(): await w.start()
asyncio.run(m())
"""
    env = {**os.environ, "PYTHONPATH": f"{PROJECT}/src",
           "GRACE_DB_URL": os.environ.get("GRACE_DB_URL", f"sqlite:///{PROJECT}/grace.db")}
    return subprocess.Popen([sys.executable, "-c", code], env=env,
                            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

def main():
    print("=== L-13: Multi-Feature Isolation ===")

    sandbox = Path(PROJECT) / "sandbox"
    sandbox.mkdir(exist_ok=True)
    (sandbox / "tests").mkdir(exist_ok=True)
    (sandbox / "__init__.py").touch()
    (sandbox / "tests" / "__init__.py").touch()

    print("Planning Alpha...")
    fid_a, pids_a = _plan(FIXTURE_A)
    print("Planning Beta...")
    fid_b, pids_b = _plan(FIXTURE_B)
    all_pids = pids_a + pids_b

    print("Starting 2 workers...")
    w1 = _start_worker("eval-w1")
    w2 = _start_worker("eval-w2")
    time.sleep(3)

    print("Waiting for completion...")
    start = time.time()
    while time.time() - start < 300:
        states = {}
        for p in all_pids:
            try:
                states[p] = _packet_state(p)
            except Exception:
                pass
        done = all(s in ("merged","failed","cancelled","rejected") for s in states.values()) if states else False
        if done:
            break
        status_a = states.get(pids_a[0], "?")
        status_b = states.get(pids_b[0], "?")
        print(f"  Alpha={status_a}  Beta={status_b}")
        time.sleep(3)

    w1.terminate()
    w2.terminate()

    a_ok = all(_packet_state(p) == "merged" for p in pids_a)
    b_ok = all(_packet_state(p) == "merged" for p in pids_b)
    ok = a_ok and b_ok

    print(f"\nAlpha merged: {a_ok}")
    print(f"Beta merged: {b_ok}")
    print(f"{'PASSED' if ok else 'FAILED'}")
    return 0 if ok else 1

if __name__ == "__main__":
    sys.exit(main())
