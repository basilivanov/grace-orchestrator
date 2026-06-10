#!/usr/bin/env python3
"""Watchdog: keep the GRACE API alive during live tests.

Usage:
    python scripts/api_watchdog.py &
    
Pings /health on loop. If API dies, restarts it and reaps orphan workers.
API env vars (GRACE_DATABASE_URL etc.) must be set before starting.
"""
import os, subprocess, sys, time
from pathlib import Path

API_URL = "http://127.0.0.1:8042/health/liveness"
SCRIPT = Path(__file__).resolve().parent / "run_api.py"

def _alive() -> bool:
    import urllib.request
    try:
        r = urllib.request.urlopen(API_URL, timeout=5)
        return r.status == 200
    except Exception:
        return False

def _start() -> subprocess.Popen | None:
    if not SCRIPT.exists():
        return None
    env = os.environ.copy()
    return subprocess.Popen(
        [sys.executable, str(SCRIPT)],
        env=env,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )

def _cleanup_stale_packets():
    """Cancel stale 'running' packets via the API so the runner can retry."""
    import urllib.request, json
    try:
        req = urllib.request.Request(
            "http://127.0.0.1:8042/api/packets/",
            method="GET",
        )
        with urllib.request.urlopen(req, timeout=10) as resp:
            data = json.loads(resp.read())
        for pkt in data.get("data", []):
            if pkt.get("state") == "running":
                pid = pkt["id"]
                cancel_req = urllib.request.Request(
                    f"http://127.0.0.1:8042/api/packets/{pid}/cancel",
                    data=json.dumps({"reason": "watchdog restart"}).encode(),
                    headers={"Content-Type": "application/json"},
                    method="POST",
                )
                with urllib.request.urlopen(cancel_req, timeout=10) as cresp:
                    print(f"[watchdog] Cancelled stale packet {pid}: {cresp.status}", flush=True)
    except Exception as e:
        print(f"[watchdog] Cleanup warning: {e}", flush=True)

proc: subprocess.Popen | None = None
while True:
    if not _alive():
        print(f"[watchdog] API down at {time.strftime('%H:%M:%S')}", flush=True)
        if proc:
            try:
                proc.terminate()
                proc.wait(timeout=5)
            except Exception:
                pass
        proc = _start()
        if proc:
            print(f"[watchdog] Restarted PID {proc.pid}", flush=True)
            time.sleep(3)
        else:
            print("[watchdog] Cannot start API, retrying...", flush=True)
    time.sleep(5)
