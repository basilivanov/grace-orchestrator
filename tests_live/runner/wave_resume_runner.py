#!/usr/bin/env python3
"""Wave resume runner — real-agent wave resume testing harness.

Runs declarative scenarios against a live GRACE API using real agents.
Supports replay/resume for different failure modes.

Usage:
    python -m tests_live.runner.wave_resume_runner --scenario backend-1w
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from tests_live.runner.scenario_loader import (
    check_live_agent_env,
    load_scenario,
)

FIXTURES_DIR = Path(__file__).resolve().parent.parent / "fixtures" / "apps"


def _api_url(base: str, path: str) -> str:
    return f"{base.rstrip('/')}{path}"


def _api_call(
    base: str,
    method: str,
    path: str,
    body: dict | None = None,
    timeout: int = 30,
) -> dict:
    url = _api_url(base, path)
    data = json.dumps(body).encode() if body else None
    req = urllib.request.Request(
        url,
        data=data,
        method=method,
        headers={"Content-Type": "application/json"} if body else {},
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return json.loads(resp.read().decode())
    except urllib.error.HTTPError as e:
        err_body = e.read().decode() if e.fp else str(e)
        print(f"[runner] HTTP {e.code} on {method} {path}: {err_body[:200]}")
        return {"_error": f"HTTP {e.code}", "_detail": err_body[:500]}
    except urllib.error.URLError as e:
        print(f"[runner] URL error on {method} {path}: {e.reason}")
        return {"_error": str(e.reason)}
    except Exception as e:
        print(f"[runner] Error on {method} {path}: {e}")
        return {"_error": str(e)}


class WaveResumeRunner:
    def __init__(self, args: argparse.Namespace):
        self.api_url = args.api_url
        self.scenario_id = args.scenario
        self.target_dir = Path(args.target_dir)
        self.source_dir = Path(args.source_dir)
        self.agent_profile = args.agent_profile
        self.architect_profile = args.architect_profile
        self.workspace_mode = args.workspace_mode
        self.target_repo_root = args.target_repo_root
        self.max_waves = args.max_waves
        self.timeout_s = args.timeout
        self.keep_artifacts = args.keep_artifacts
        self.worker_proc: subprocess.Popen | None = None

        self.scenario = load_scenario(self.scenario_id)
        self.run_ts = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
        self.run_dir = (
            Path(".grace")
            / "live-tests"
            / self.scenario_id
            / self.run_ts
        )
        self.run_dir.mkdir(parents=True, exist_ok=True)

        # Reporting counters
        self.report: dict[str, Any] = {
            "scenario_id": self.scenario_id,
            "status": "running",
            "waves_requested": 0,
            "packets_total": 0,
            "real_agent_runs": 0,
            "context_runs": 0,
            "architect_runs": 0,
            "coder_runs": 0,
            "acceptance_replays": 0,
            "verifier_replays": 0,
            "reviewer_replays": 0,
            "agent_session_resumes": 0,
            "packet_state_changed_by_replay": False,
            "artifacts_dir": str(self.run_dir),
            "feature_id": None,
            "packet_ids": [],
            "failures": [],
        }

    # ---- Public API ----
    def run(self) -> int:
        ok, msg = check_live_agent_env()
        if not ok:
            print(f"[runner] SKIP: {msg}")
            self.report["status"] = "skipped"
            self._write_report()
            return 0

        # 1. Copy fixture app to target dir
        fixture_app = self.scenario.get("fixture_app", "")
        if not self._prepare_fixture(fixture_app):
            self.report["status"] = "error"
            self._write_report()
            return 1

        # 2. Connect to API
        if not self._check_api():
            print("[runner] API not reachable, starting supervisor...")
            self._start_api()

        # 3. Submit explicit waves
        feat_id = self._submit_feature()
        if not feat_id:
            self.report["status"] = "error"
            self._write_report()
            return 1

        # 4. Start worker
        self._start_worker()

        # 5. Run waves/packets
        success = self._run_waves()

        # 6. Cleanup
        self._stop_worker()

        self.report["status"] = "passed" if success else "failed"
        self._write_report()
        return 0 if success else 1

    # ---- Fixture preparation ----
    def _prepare_fixture(self, fixture_app: str) -> bool:
        src = FIXTURES_DIR / fixture_app
        if not src.exists():
            print(f"[runner] Fixture app not found: {src}")
            return False
        dst = self.target_dir / fixture_app
        if dst.exists():
            shutil.rmtree(dst)
        shutil.copytree(src, dst)
        print(f"[runner] Fixture copied: {src} -> {dst}")
        # Initialize target repo as a clean git repository
        import subprocess
        subprocess.run(["git", "init", "-b", "main"], cwd=str(dst), stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        subprocess.run(["git", "config", "user.email", "test@grace"], cwd=str(dst), stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        subprocess.run(["git", "config", "user.name", "Test Agent"], cwd=str(dst), stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        subprocess.run(["git", "add", "-A"], cwd=str(dst), stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        subprocess.run(["git", "commit", "-q", "-m", "initial commit"], cwd=str(dst), stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        return True

    # ---- API management ----
    def _check_api(self) -> bool:
        for attempt in range(6):
            resp = _api_call(self.api_url, "GET", "/health/liveness", timeout=5)
            if "_error" not in resp and resp.get("status") == "ok":
                return True
            if attempt < 5:
                print(f"[runner] API not ready, retrying in 5s ({attempt+1}/5)")
                time.sleep(5)
        return False

    def _start_api(self) -> None:
        api_script = self.source_dir / "scripts" / "run_api.py"
        if not api_script.exists():
            print(f"[runner] API script not found: {api_script}")
            return
        # Clear any stale process on the API port
        import socket
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            if s.connect_ex(("127.0.0.1", 8042)) == 0:
                print("[runner] Port 8042 in use, waiting for release...")
                time.sleep(3)
        db_url = os.environ.get("GRACE_DATABASE_URL", "sqlite:////tmp/grace-live-test.db")
        env = os.environ.copy()
        env["GRACE_DATABASE_URL"] = db_url
        env.setdefault("GRACE_DEV_TOOLS_ENABLED", "1")
        env.setdefault("GRACE_DEV_KEEP_FAILED_WORKTREES", "1")
        if self.workspace_mode:
            env["GRACE_WORKSPACE_MODE"] = self.workspace_mode
        if self.target_repo_root:
            env["GRACE_TARGET_REPO_ROOT"] = self.target_repo_root
        if self.agent_profile:
            env["GRACE_LIVE_EXECUTOR_PROFILE"] = self.agent_profile
        subprocess.Popen(
            [sys.executable, str(api_script)],
            env=env,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        print("[runner] API started, waiting...")
        for _ in range(15):
            if self._check_api():
                return
            time.sleep(2)
        print("[runner] API failed to start")

    # ---- Worker management ----
    def _start_worker(self) -> None:
        worker_script = self.source_dir / "scripts" / "live_worker.py"
        if not worker_script.exists():
            print(f"[runner] Worker script not found: {worker_script}")
            return
        db_url = os.environ.get("GRACE_DATABASE_URL", "sqlite:////tmp/grace-live-test.db")
        env = os.environ.copy()
        env["GRACE_DATABASE_URL"] = db_url
        env.setdefault("GRACE_API_URL", self.api_url)
        env.setdefault("GRACE_WORKER_ID", f"live-wr-{os.getpid()}")
        env.setdefault("GRACE_DEV_TOOLS_ENABLED", "1")
        env.setdefault("GRACE_DEV_KEEP_FAILED_WORKTREES", "1")
        if self.workspace_mode:
            env["GRACE_WORKSPACE_MODE"] = self.workspace_mode
        if self.target_repo_root:
            env["GRACE_TARGET_REPO_ROOT"] = self.target_repo_root
        if self.agent_profile:
            env["GRACE_LIVE_EXECUTOR_PROFILE"] = self.agent_profile
        log_file = open("/tmp/runner_worker.log", "a")
        self.worker_proc = subprocess.Popen(
            [sys.executable, str(worker_script)],
            env=env,
            stdout=log_file,
            stderr=log_file,
        )
        print(f"[runner] Worker started, PID: {self.worker_proc.pid}")

    def _stop_worker(self) -> None:
        if self.worker_proc:
            self.worker_proc.terminate()
            try:
                self.worker_proc.wait(timeout=10)
            except subprocess.TimeoutExpired:
                self.worker_proc.kill()
                self.worker_proc.wait()

    # ---- Feature submission ----
    def _submit_feature(self) -> str | None:
        waves = self.scenario.get("waves", [])
        if self.max_waves and self.max_waves < len(waves):
            waves = waves[: self.max_waves]

        self.report["waves_requested"] = len(waves)

        # Build explicit feature spec
        feature_spec = {
            "title": f"Live: {self.scenario_id}",
            "waves": [],
        }
        for wave in waves:
            wave_spec = {
                "title": wave["title"],
                "packets": [],
            }
            for pkt in wave.get("packets", []):
                pkt_spec = {
                    "title": pkt["id"],
                    "scope": pkt.get("scope", []),
                    "acceptance_profile": "NORMAL",
                    "prompt": pkt.get("prompt", ""),
                }
                if "verification" in pkt:
                    pkt_spec["verification"] = pkt["verification"]
                wave_spec["packets"].append(pkt_spec)
            feature_spec["waves"].append(wave_spec)

        print(f"[runner] Submitting {len(waves)} wave(s)...")
        resp = _api_call(
            self.api_url,
            "POST",
            "/api/architect/plan",
            body={"feature_spec": feature_spec},
            timeout=120,
        )

        if "_error" in resp:
            print(f"[runner] Feature submission failed: {resp['_error']}")
            self.report["failures"].append(f"Feature submission: {resp['_error']}")
            return None

        data = resp.get("data", {})
        feat_id = data.get("feature_id")
        self.report["feature_id"] = feat_id
        self.report["packet_ids"] = data.get("packet_ids", [])
        self.report["packets_total"] = len(self.report["packet_ids"])

        self._save_artifact("01-feature-response.json", json.dumps(resp, indent=2))
        print(f"[runner] Feature: {feat_id}, packets: {self.report['packet_ids']}")
        return feat_id

    # ---- Wave execution ----
    def _run_waves(self) -> bool:
        if not self.report["packet_ids"]:
            return False

        print("[runner] Monitoring packets...")
        all_ok = True
        waited = 0
        deadline = time.time() + self.timeout_s
        terminal_states = {"accepted", "merged", "failed", "rejected", "cancelled"}

        while time.time() < deadline:
            remaining = []
            api_dead = False
            for pid in self.report["packet_ids"]:
                resp = _api_call(
                    self.api_url, "GET", f"/api/packets/{pid}", timeout=10
                )
                if "_error" in resp:
                    api_dead = True
                    remaining.append(pid)
                    continue

                data = resp.get("data", {})
                state = data.get("state", "unknown")

                if state in terminal_states:
                    self._handle_packet_result(pid, data)
                    if state in ("failed", "rejected"):
                        pass  # handled via retry/replay
                else:
                    remaining.append(pid)

            if api_dead:
                # Try restarting the API if it went down
                if self._check_api():
                    print("[runner] API recovered")
                else:
                    print("[runner] API down, restarting...")
                    self._start_api()
                    # Worker may have died too — restart if needed
                    if self.worker_proc and self.worker_proc.poll() is not None:
                        print("[runner] Worker also died, restarting...")
                        self._start_worker()

            if not remaining:
                print("[runner] All packets in terminal state")
                break

            time.sleep(5)
            waited += 5

        if remaining:
            print(f"[runner] TIMEOUT: {remaining} not completed")
            self.report["failures"].append(f"Timeout after {self.timeout_s}s")
            all_ok = False

        return all_ok and not self.report["failures"]

    def _handle_packet_result(self, pid: str, data: dict) -> None:
        state = data.get("state", "unknown")
        print(f"[runner] {pid} -> {state}")

        if state in ("accepted", "merged"):
            self.report["coder_runs"] += 1
            self.report["real_agent_runs"] += 1
            return

        if state in ("failed", "rejected"):
            self.report["failures"].append(f"{pid}: {state}")

            # Always try replay first (for T0/T1/T2/verifier/reviewer failures)
            runs = data.get("runs", [])
            replay_attempted = False
            if runs:
                last_run = runs[-1]
                run_id = last_run.get("id", last_run.get("run_id"))
                if run_id:
                    replay_attempted = self._try_replay(pid, run_id)

            if not replay_attempted:
                attempts = data.get("attempt_count", 0)
                if attempts >= data.get("max_attempts", 3):
                    print(f"[runner] {pid}: max attempts reached, giving up")
                else:
                    print(f"[runner] {pid}: waiting for retry attempt {attempts+1}")

    def _try_replay(self, pid: str, run_id: str) -> bool:
        """Try dev replay endpoints for a failed run."""
        for endpoint in [
            f"/api/dev/runs/{run_id}/replay-acceptance",
            f"/api/dev/runs/{run_id}/rerun-verifier",
            f"/api/dev/runs/{run_id}/rerun-reviewer",
        ]:
            resp = _api_call(self.api_url, "POST", endpoint, body={}, timeout=60)
            if "_error" not in resp:
                status = resp.get("data", {}).get("status", resp.get("status", ""))
                print(f"[runner] Replay {endpoint}: {status}")
                self.report["acceptance_replays"] += 1
                return True
        return False

    # ---- Artifacts ----
    def _save_artifact(self, name: str, content: str) -> None:
        path = self.run_dir / name
        path.write_text(content)

    def _write_report(self) -> None:
        report_path = self.run_dir / "summary.json"
        report_path.write_text(
            json.dumps(self.report, indent=2, default=str)
        )
        print(f"[runner] Report: {report_path}")
        # Also write markdown summary
        md_path = self.run_dir / "summary.md"
        md = f"""# Live Test Report: {self.scenario_id}

**Status:** {self.report['status']}
**Timestamp:** {self.run_ts}

| Metric | Value |
|--------|-------|
| Waves | {self.report['waves_requested']} |
| Packets | {self.report['packets_total']} |
| Feature ID | {self.report.get('feature_id', 'N/A')} |
| Coder runs | {self.report['coder_runs']} |
| Replays | acc={self.report['acceptance_replays']} ver={self.report['verifier_replays']} rev={self.report['reviewer_replays']} |
| Agent resumes | {self.report['agent_session_resumes']} |

## Failures
"""
        if self.report['failures']:
            for f in self.report['failures']:
                md += f"- {f}\n"
        else:
            md += "None\n"

        md += "\n## Artifacts\n"
        md += f"`{self.run_dir}`\n"
        md_path.write_text(md)


# ---- CLI ----
def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Wave resume testing runner")
    p.add_argument("--scenario", required=True, help="Scenario id (file name without .yaml)")
    p.add_argument("--api-url", default="http://127.0.0.1:8042", help="GRACE API URL")
    p.add_argument(
        "--target-dir",
        default="/tmp/grace-live-test",
        help="Target directory for fixture app copy",
    )
    p.add_argument(
        "--source-dir",
        default=".",
        help="GRACE orchestrator source directory",
    )
    p.add_argument(
        "--agent-profile",
        default="coder-deepseek-flash",
        help="Agent profile for coder",
    )
    p.add_argument(
        "--architect-profile",
        default="architect-premium",
        help="Agent profile for architect",
    )
    p.add_argument("--max-waves", type=int, default=0, help="Limit number of waves")
    p.add_argument("--timeout", type=int, default=600, help="Max run time in seconds")
    p.add_argument("--keep-artifacts", action="store_true", help="Preserve artifacts")
    p.add_argument("--workspace-mode", default=None, help="Workspace mode override")
    p.add_argument("--target-repo-root", default=None, help="Target repo root override")
    return p.parse_args(argv)


def main() -> None:
    args = parse_args()
    if args.source_dir == ".":
        args.source_dir = str(Path.cwd())
    runner = WaveResumeRunner(args)
    sys.exit(runner.run())


if __name__ == "__main__":
    main()
