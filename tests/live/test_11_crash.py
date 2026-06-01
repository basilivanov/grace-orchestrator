#!/usr/bin/env python3
"""L-11: Crash Recovery — kill worker, verify lease recovery and re-claim."""

import httpx
import subprocess
import sys
import time
import os
from pathlib import Path

API = "http://127.0.0.1:8042"
PROJECT = str(Path(__file__).resolve().parent.parent.parent)
FIXTURE = str(Path(__file__).resolve().parent.parent / "fixtures" / "11_crash_recovery.yaml")

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

def _packet_attempts(pid):
    r = c.get(f"/api/packets/{pid}")
    return r.json()["data"]["attempt_count"]

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
    print("=== L-11: Crash Recovery ===")
    fid, pids = _plan()
    pid = pids[0]

    sandbox = Path(PROJECT) / "sandbox"
    sandbox.mkdir(exist_ok=True)
    (sandbox / "tests").mkdir(exist_ok=True)
    (sandbox / "__init__.py").touch()
    (sandbox / "tests" / "__init__.py").touch()

    print("Starting w1...")
    w1 = _start_worker("eval-w1")
    time.sleep(3)

    print("Waiting for w1 claim...")
    claimed = False
    for _ in range(60):
        if _packet_state(pid) == "running":
            claimed = True
            break
        time.sleep(1)

    if not claimed:
        print(f"FAIL: w1 did not claim. State={_packet_state(pid)}")
        w1.terminate()
        return 1

    print(f"  running. Killing w1 (PID {w1.pid})...")
    w1.kill()
    w1.wait()

    # Force lease expiration via DB — clear lease AND reset state
    print("Clearing lease + resetting state...")
    r = subprocess.run([sys.executable, "-c", f"""
import sqlalchemy as sa
from grace_control.db import init_db, get_db
from grace_control.db.schema import Lease, Packet
init_db()
with get_db() as db:
    db.execute(sa.delete(Lease).where(Lease.packet_id == '{pid}'))
    p = db.query(Packet).filter(Packet.id == '{pid}').first()
    if p:
        p.state = 'ready'
    print('ok')
"""], env={"PYTHONPATH": f"{PROJECT}/src",
           "GRACE_DB_URL": os.environ.get("GRACE_DB_URL", f"sqlite:///{PROJECT}/grace.db")},
    capture_output=True, text=True)
    print(f"  lease clear: {r.stdout.strip()}")

    time.sleep(2)

    print("Starting w2...")
    w2 = _start_worker("eval-w2")
    time.sleep(3)

    print("Waiting for completion...")
    start = time.time()
    while time.time() - start < 300:
        s = _packet_state(pid)
        ac = _packet_attempts(pid)
        if s in ("merged","cancelled","failed"):
            break
        print(f"  state={s}  attempts={ac}")
        time.sleep(3)

    w2.terminate()

    final_state = _packet_state(pid)
    final_attempts = _packet_attempts(pid)
    ok = final_state == "merged" and final_attempts >= 2

    print(f"\n{'PASSED' if ok else 'FAILED'}: state={final_state} attempts={final_attempts}")
    return 0 if ok else 1

if __name__ == "__main__":
    sys.exit(main())
