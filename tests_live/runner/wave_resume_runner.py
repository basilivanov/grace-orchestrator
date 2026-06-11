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
            "watchdog_restarts": 0,
            "packet_state_changed_by_replay": False,
            "artifacts_dir": str(self.run_dir),
            "feature_id": None,
            "packet_ids": [],
            "failures": [],
            "live_log_path": str(self.run_dir / "runner.log"),
            "runner_pid": os.getpid(),
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

        # 2. Stage 0: context-builder (built-in, runs before API submission)
        context_bundle = self._run_stage0_context_builder()
        if self.report.get("failures"):
            self.report["status"] = "failed"
            self._write_report()
            return 1

        # 3. Connect to API
        if not self._check_api():
            print("[runner] API not reachable, starting supervisor...")
            self._start_api()

        # 4. Submit explicit waves (with context_bundle if Stage 0 ran)
        if context_bundle:
            feat_id = self._submit_feature(context_bundle=context_bundle)
        else:
            feat_id = self._submit_feature()

        if not feat_id and not context_bundle:
            self.report["status"] = "error"
            self._write_report()
            return 1

        # If all waves were consumed by Stage 0, skip worker and monitoring
        if not feat_id and context_bundle:
            self.report["status"] = "passed"
            self._write_report()
            return 0

        # 5. Start worker
        self._start_worker()

        # 6. Run waves/packets
        success = self._run_waves()

        # 7. Cleanup
        self._stop_worker()

        self.report["status"] = "passed" if success else "failed"
        self._write_report()
        return 0 if success else 1

    # ---- Fixture preparation ----
    def _prepare_fixture(self, fixture_app: str) -> bool:
        if not fixture_app:
            print("[runner] No fixture app — using target repo directly")
            return True
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
        env["GRACE_PROJECT_ROOT"] = str(self.source_dir.resolve())
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
        env["GRACE_PROJECT_ROOT"] = str(self.source_dir.resolve())
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

    # ---- Stage 0: Context builder (built-in, runs before API submission) ----
    def _run_stage0_context_builder(self) -> list[dict[str, Any]]:
        """Run Stage 0 context-builder: local, read-only, no branch/commit/acceptance.

        Returns list of context bundle info dicts (one per context-builder packet).
        On mutation or agent failure, records failure in self.report and returns [].
        """
        cb_config = self.scenario.get("context_builder", {})
        if not cb_config.get("enabled", False):
            return []

        waves = self.scenario.get("waves", [])
        if not waves:
            return []

        w0 = waves[0]
        cb_packets = [
            p for p in w0.get("packets", []) if p.get("role") == "context-builder"
        ]
        if not cb_packets:
            return []

        target_root = Path(self.target_repo_root or self.target_dir)
        if not target_root.exists() or not (target_root / ".git").exists():
            self.report["failures"].append(
                f"Stage 0: target repo not found or not a git repo: {target_root}"
            )
            return []

        from grace_control.config.agent_profiles import get_agent_profile

        profile = get_agent_profile("context-collector-flash")
        if not profile:
            self.report["failures"].append(
                "Stage 0: context-collector-flash profile not found"
            )
            return []

        # Pre-check: target repo must be clean before Stage 0
        status_check = subprocess.run(
            ["git", "status", "--short"],
            cwd=str(target_root),
            capture_output=True,
            text=True,
            timeout=10,
        ).stdout.strip()
        if status_check:
            self.report["failures"].append(
                f"Stage 0: target repo is dirty before context-builder: {status_check[:200]}"
            )
            return []

        bundle_infos: list[dict[str, Any]] = []

        for pkt in cb_packets:
            pkt_id = pkt["id"]
            bundle_dir = Path(
                f"/tmp/grace-context/{self.scenario_id}/{pkt_id}"
            )
            bundle_dir.mkdir(parents=True, exist_ok=True)
            bundle_path = bundle_dir / "context-bundle.md"

            # Write packet prompt to file (input: mode: file)
            packet_file = bundle_dir / "EXECUTION_PACKET.md"
            packet_file.write_text(pkt.get("prompt", ""))

            # Render command template from profile
            cmd_template = list(profile.command)
            rendered_cmd = []
            for part in cmd_template:
                part = part.replace(
                    "{model}", profile.model or "deepseek/deepseek-v4-flash"
                )
                part = part.replace("{effort}", profile.effort or "low")
                part = part.replace("{packet_path}", str(packet_file))
                rendered_cmd.append(part)

            # Inject --dir <worktree_path> (AgentRunService inject_dir logic)
            for i, part in enumerate(rendered_cmd):
                if part == "run":
                    rendered_cmd = (
                        rendered_cmd[: i + 1 ]
                        + ["--dir", str(target_root)]
                        + rendered_cmd[i + 1 :]
                    )
                    break

            # Save git baseline
            head_before = subprocess.run(
                ["git", "rev-parse", "HEAD"],
                cwd=str(target_root),
                capture_output=True,
                text=True,
                timeout=10,
            ).stdout.strip()

            # Run agent
            print(f"[runner] Stage 0: running {pkt_id}...")
            self.report["context_runs"] += 1
            self.report["real_agent_runs"] += 1
            start_t = time.time()

            try:
                result = subprocess.run(
                    rendered_cmd,
                    cwd=str(target_root),
                    capture_output=True,
                    text=True,
                    timeout=profile.timeout_seconds or 300,
                )
            except subprocess.TimeoutExpired:
                elapsed_ms = int((time.time() - start_t) * 1000)
                print(
                    f"[runner] Stage 0: {pkt_id} timed out after "
                    f"{profile.timeout_seconds}s ({elapsed_ms}ms)"
                )
                self.report["failures"].append(
                    f"Stage 0: {pkt_id} timed out ({profile.timeout_seconds}s)"
                )
                return []

            elapsed_ms = int((time.time() - start_t) * 1000)
            stdout = result.stdout or ""
            stderr = result.stderr or ""

            # Save agent outputs as artifacts
            (bundle_dir / "agent.stdout").write_text(stdout)
            if stderr:
                (bundle_dir / "agent.stderr").write_text(stderr)

            # Early-failure detection: non-zero exit code
            if result.returncode != 0:
                err_preview = (stderr[:500] if stderr else "exit code non-zero")
                print(
                    f"[runner] Stage 0: {pkt_id} agent failed "
                    f"(exit={result.returncode}): {err_preview[:120]}"
                )
                self.report["failures"].append(
                    f"Stage 0: {pkt_id} agent failed (exit={result.returncode})"
                )
                return []

            # ── Mutation detection ─────────────────────────────────────
            status_after = subprocess.run(
                ["git", "status", "--short"],
                cwd=str(target_root),
                capture_output=True,
                text=True,
                timeout=10,
            ).stdout.strip()

            head_after = subprocess.run(
                ["git", "rev-parse", "HEAD"],
                cwd=str(target_root),
                capture_output=True,
                text=True,
                timeout=10,
            ).stdout.strip()

            diff_failed = (
                subprocess.run(
                    ["git", "diff", "--exit-code"],
                    cwd=str(target_root),
                    capture_output=True,
                    text=True,
                    timeout=10,
                ).returncode
                != 0
            )

            has_mutations = bool(status_after) or (head_after != head_before) or diff_failed

            if has_mutations:
                # Save diff evidence
                diff_text = subprocess.run(
                    ["git", "diff"],
                    cwd=str(target_root),
                    capture_output=True,
                    text=True,
                    timeout=10,
                ).stdout
                (bundle_dir / "diff-evidence.txt").write_text(diff_text)

                # Cleanup: reset hard + clean untracked
                subprocess.run(
                    ["git", "reset", "--hard", "HEAD"],
                    cwd=str(target_root),
                    capture_output=True,
                    timeout=10,
                )
                subprocess.run(
                    ["git", "clean", "-fd"],
                    cwd=str(target_root),
                    capture_output=True,
                    timeout=10,
                )

                self.report["failures"].append(
                    f"CONTEXT_BUILDER_MUTATED_WORKTREE: "
                    f"{pkt_id} modified target repo"
                )
                return []

            # ── Parse bundle info from agent JSON output ───────────────
            bundle_info: dict[str, Any] = {
                "context_bundle_path": str(bundle_path),
                "context_bundle_url": f"file://{bundle_path}",
                "context_bundle_summary": "",
                "selected_files": pkt.get("scope", []),
                "truncated": False,
                "missing_context": False,
            }

            lines = [l for l in stdout.strip().split("\n") if l.strip()]
            if lines:
                last = lines[-1]
                try:
                    parsed = json.loads(last)
                    if isinstance(parsed, dict):
                        for key in (
                            "context_bundle_path",
                            "context_bundle_url",
                            "context_bundle_summary",
                            "selected_files",
                            "truncated",
                            "missing_context",
                            "warnings",
                        ):
                            if key in parsed:
                                bundle_info[key] = parsed[key]
                except (json.JSONDecodeError, ValueError):
                    pass

            print(
                f"[runner] Stage 0: {pkt_id} done ({elapsed_ms}ms, "
                f"selected={len(bundle_info.get('selected_files', []))} files)"
            )
            bundle_infos.append(bundle_info)

        return bundle_infos

    # ---- Feature submission ----
    def _submit_feature(
        self, context_bundle: list[dict] | None = None
    ) -> str | None:
        waves = self.scenario.get("waves", [])
        if self.max_waves and self.max_waves < len(waves):
            waves = waves[: self.max_waves]

        # Filter out context-builder packets (handled by Stage 0)
        cb_enabled = (
            self.scenario.get("context_builder", {}).get("enabled", False)
        )
        filtered_waves = []
        for wave in waves:
            wave_spec = {
                "title": wave["title"],
                "packets": [],
            }
            for pkt in wave.get("packets", []):
                if cb_enabled and pkt.get("role") == "context-builder":
                    continue
                pkt_spec = {
                    "title": pkt["id"],
                    "scope": pkt.get("scope", []),
                    "acceptance_profile": pkt.get("acceptance_profile", "NORMAL"),
                    "prompt": pkt.get("prompt", ""),
                }
                if "verification" in pkt:
                    pkt_spec["verification"] = pkt["verification"]
                wave_spec["packets"].append(pkt_spec)
            if wave_spec["packets"]:
                filtered_waves.append(wave_spec)
        waves = filtered_waves

        self.report["waves_requested"] = len(waves)

        # Build explicit feature spec
        feature_spec = {
            "title": f"Live: {self.scenario_id}",
            "waves": waves,
        }

        # Inject context_bundle into first remaining packet prompt
        if context_bundle and waves:
            first_wave = waves[0]
            if first_wave["packets"]:
                bundle_hint = json.dumps(
                    context_bundle[0]
                    if len(context_bundle) == 1
                    else context_bundle,
                    indent=2,
                )
                first_wave["packets"][0]["prompt"] += (
                    f"\n\n## Context Bundle\n{bundle_hint}"
                )
            feature_spec["context_bundle"] = context_bundle

        if not waves:
            print("[runner] All waves consumed by Stage 0 — nothing to submit")
            self.report["status"] = "passed"
            self._write_report()
            return None

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
                    self.report["watchdog_restarts"] = (
                        self.report.get("watchdog_restarts", 0) + 1
                    )
                    # Worker may have died too — restart if needed
                    if self.worker_proc and self.worker_proc.poll() is not None:
                        print("[runner] Worker also died, restarting...")
                        self._start_worker()
                        self.report["watchdog_restarts"] = (
                            self.report.get("watchdog_restarts", 0) + 1
                        )

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
**Runner PID:** {self.report.get('runner_pid', 'N/A')}

| Metric | Value |
|--------|-------|
| Waves | {self.report['waves_requested']} |
| Packets | {self.report['packets_total']} |
| Feature ID | {self.report.get('feature_id', 'N/A')} |
| Context runs | {self.report['context_runs']} |
| Coder runs | {self.report['coder_runs']} |
| Real agent runs | {self.report['real_agent_runs']} |
| Replays | acc={self.report['acceptance_replays']} ver={self.report['verifier_replays']} rev={self.report['reviewer_replays']} |
| Agent resumes | {self.report['agent_session_resumes']} |
| Watchdog restarts | {self.report.get('watchdog_restarts', 0)} |

## Failures
"""
        if self.report['failures']:
            for f in self.report['failures']:
                md += f"- {f}\n"
        else:
            md += "None\n"

        md += "\n## Artifacts\n"
        md += f"- Report: `{self.run_dir}`\n"
        md += f"- Live log: `{self.report.get('live_log_path', 'N/A')}`\n"
        md += f"- Context bundles: `/tmp/grace-context/{self.scenario_id}/`\n"
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
