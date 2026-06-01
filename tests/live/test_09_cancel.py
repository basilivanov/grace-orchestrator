#!/usr/bin/env python3
"""L-09: Cancel Running — cancel a claimed packet, verify second worker picks up the other."""

import httpx
import subprocess
import sys
import time
import os
from pathlib import Path

API = "http://127.0.0.1:8042"
PROJECT = str(Path(__file__).resolve().parent.parent.parent)
FIXTURE = str(Path(__file__).resolve().parent.parent / "fixtures" / "09_cancel_running.yaml")

c = httpx.Client(base_url=API, timeout=10)

def _plan():
    import yaml
    spec = yaml.safe_load(Path(FIXTURE).read_text())
    r = c.post("/api/architect/plan", json={"feature_spec": spec})
    if r.status_code != 200:
        print(f"FAIL: plan {r.status_code}: {r.text[:200]}")
        sys.exit(1)
    data = r.json()["data"]
    fid = data["feature_id"]
    pids = data["packets"]
    print(f"Feature: {fid} | {len(pids)} packets")
    return fid, pids

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
    print("=== L-09: Cancel Running ===")
    fid, pids = _plan()
    slow_id, fast_id = pids[0], pids[1]

    sandbox = Path(PROJECT) / "sandbox"
    sandbox.mkdir(exist_ok=True)
    (sandbox / "tests").mkdir(exist_ok=True)
    (sandbox / "__init__.py").touch()
    (sandbox / "tests" / "__init__.py").touch()

    print("Starting w1...")
    w1 = _start_worker("eval-w1")
    time.sleep(3)

    print("Waiting for w1 to claim slow packet...")
    claimed = False
    for _ in range(120):
        s = _packet_state(slow_id)
        if s == "running":
            claimed = True
            break
        time.sleep(0.5)

    if not claimed:
        print(f"FAIL: w1 did not claim. State={_packet_state(slow_id)}")
        w1.terminate()
        return 1

    print("  slow=running — cancelling NOW")
    r = c.post(f"/api/packets/{slow_id}/cancel", json={"reason": "test"})
    cancelled = r.status_code == 200
    print(f"  {'Cancel OK' if cancelled else f'Cancel {r.status_code}: {r.text[:80]}'}")

    print("Starting w2...")
    w2 = _start_worker("eval-w2")
    time.sleep(3)

    print("Waiting for completion...")
    start = time.time()
    while time.time() - start < 300:
        ss = _packet_state(slow_id)
        fs = _packet_state(fast_id)
        if ss in ("cancelled","merged","failed","rejected") and fs in ("cancelled","merged","failed","rejected"):
            break
        print(f"  slow={ss}  fast={fs}")
        time.sleep(3)

    w1.terminate()
    w2.terminate()

    slow_state = _packet_state(slow_id)
    fast_state = _packet_state(fast_id)
    ok = fast_state == "merged"
    ok = ok and (slow_state == "cancelled" if cancelled else slow_state in ("merged","failed"))

    print(f"\n{'PASSED' if ok else 'FAILED'}: slow={slow_state} fast={fast_state}")
    return 0 if ok else 1

if __name__ == "__main__":
    sys.exit(main())
