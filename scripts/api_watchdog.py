#!/usr/bin/env python3
"""Watchdog: keep the GRACE API alive during live tests.

Usage:
    python scripts/api_watchdog.py &
    
Pings /health on loop. If API dies, restarts it and reaps orphan workers.
API env vars (GRACE_DATABASE_URL etc.) must be set before starting.
"""
import os, subprocess, sys, time
from pathlib import Path

API_URL = "http://127.0.0.1:8042/health"
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
    """Mark stale 'running' packets as 'failed' so the runner can retry."""
    import sqlite3, os
    db_url = os.environ.get("GRACE_DATABASE_URL", "sqlite:////tmp/grace-live-test.db")
    db_path = db_url.replace("sqlite:///", "", 1) if "sqlite:///" in db_url else "/tmp/grace-live-test.db"
    if not os.path.exists(db_path):
        return
    try:
        conn = sqlite3.connect(db_path)
        cur = conn.execute("UPDATE packets SET state='failed' WHERE state='running'")
        updated = cur.rowcount
        conn.commit()
        if updated:
            print(f"[watchdog] Stale packets cleaned: {updated}", flush=True)
        conn.close()
    except Exception as e:
        print(f"[watchdog] Cleanup error: {e}", flush=True)

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
            _cleanup_stale_packets()
        else:
            print("[watchdog] Cannot start API, retrying...", flush=True)
    time.sleep(5)
