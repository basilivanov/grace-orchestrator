#!/usr/bin/env python3
"""real_loop_smoke.py — harness for real-loop orchestrator smoke tests.

Thin wrapper over GRACE HTTP API. No internal service calls.
All paths/ports via CLI args or env. No hardcoded absolute paths.
"""

import argparse
import json
import os
import subprocess
import sys
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

REQUESTS_AVAILABLE = False
try:
    import requests
    REQUESTS_AVAILABLE = True
except ImportError:
    pass

YAML_AVAILABLE = False
try:
    import yaml
    YAML_AVAILABLE = True
except ImportError:
    pass


# ---------------------------------------------------------------------------
# Fixture specs (maps scenario name -> fixture YAML path relative to repo root)
# ---------------------------------------------------------------------------
FIXTURE_SPECS = {
    "one-wave-basic-backend": "tests/fixtures/01_backend_simple.yaml",
    "two-wave-recovery-resume": "tests/fixtures/03_fullstack_two_waves.yaml",
    "backend-frontend-browser-smoke": "tests/fixtures/02_frontend_screenshot.yaml",
}


def load_fixture(fixture_rel: str, source_dir: Path) -> dict:
    path = (source_dir / fixture_rel).resolve()
    if not path.exists():
        print(f"[smoke] ERROR: fixture not found: {path}")
        sys.exit(1)
    if YAML_AVAILABLE:
        return yaml.safe_load(path.read_text())
    import json as _json
    return _json.loads(path.read_text())


# ---------------------------------------------------------------------------
# HTTP helpers (stdlib only — no requests dependency)
# ---------------------------------------------------------------------------
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
        print(f"[smoke] HTTP {e.code} on {method} {path}: {err_body[:200]}")
        return {"_error": f"HTTP {e.code}", "_detail": err_body[:500]}
    except urllib.error.URLError as e:
        print(f"[smoke] URL error on {method} {path}: {e.reason}")
        return {"_error": str(e.reason)}
    except Exception as e:
        print(f"[smoke] Error on {method} {path}: {e}")
        return {"_error": str(e)}


def _get(base: str, path: str, timeout: int = 30) -> dict:
    return _api_call(base, "GET", path, timeout=timeout)


def _post(base: str, path: str, body: dict | None = None, timeout: int = 30) -> dict:
    return _api_call(base, "POST", path, body=body, timeout=timeout)


# ---------------------------------------------------------------------------
# Smoke runner
# ---------------------------------------------------------------------------
class SmokeRunner:
    def __init__(self, args: argparse.Namespace):
        self.api = args.api_url
        self.target_project = Path(args.target_project).resolve()
        self.run_dir = Path(args.run_dir)
        self.run_dir.mkdir(parents=True, exist_ok=True)
        self.profile = args.profile
        self.scenario = args.scenario
        self.source_dir = Path(args.source_dir).resolve() if args.source_dir else Path.cwd()
        self.timeout_s = int(args.timeout) * 60
        self.verbose = args.verbose
        self.worker_proc: subprocess.Popen | None = None

        # Collected data for the report
        self.feature_id: str | None = None
        self.packet_ids: list[str] = []
        self.run_ids: list[str] = []
        self.wave_count: int = 0
        self.t0_result: str = "N/A"
        self.t1_result: str = "N/A"
        self.t2_result: str = "N/A"
        self.verifier_result: str = "N/A"
        self.reviewer_result: str = "N/A"
        self.failures: list[str] = []
        self.bugs_fixed: list[str] = []
        self.replay_evidence: list[str] = []
        self.blockers: list[str] = []
        self.trace_data: list[dict] = []

    def log(self, msg: str):
        print(f"[smoke] {msg}")

    def log_verbose(self, msg: str):
        if self.verbose:
            print(f"[smoke:debug] {msg}")

    def save_artifact(self, name: str, content: str):
        path = self.run_dir / name
        path.write_text(content)
        self.log_verbose(f"saved artifact: {path}")

    def save_json_artifact(self, name: str, data):
        self.save_artifact(name, json.dumps(data, indent=2, default=str))

    # ---- Worker management ----
    def start_worker(self):
        self.log("starting worker subprocess ...")
        env = os.environ.copy()
        env.setdefault("GRACE_DB_URL", "sqlite:////tmp/grace-smoke.db")
        env.setdefault("GRACE_API_URL", self.api)
        env.setdefault("GRACE_WORKER_ID", f"smoke-w-{os.getpid()}")
        env.setdefault("GRACE_DEV_TOOLS_ENABLED", "1")
        env.setdefault("GRACE_DEV_KEEP_FAILED_WORKTREES", "1")

        worker_script = self.source_dir / "scripts" / "live_worker.py"
        if not worker_script.exists():
            self.log(f"ERROR: worker script not found: {worker_script}")
            return False

        try:
            self.worker_proc = subprocess.Popen(
                [sys.executable, str(worker_script)],
                env=env,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.PIPE,
            )
            self.log(f"worker started, PID: {self.worker_proc.pid}")
            time.sleep(2)
            return True
        except Exception as e:
            self.log(f"ERROR starting worker: {e}")
            return False

    def stop_worker(self):
        if self.worker_proc:
            self.log("stopping worker ...")
            self.worker_proc.terminate()
            try:
                self.worker_proc.wait(timeout=10)
            except subprocess.TimeoutExpired:
                self.worker_proc.kill()
                self.worker_proc.wait()
            self.log("worker stopped")

    # ---- Feature submission ----
    def submit_feature(self) -> bool:
        fixture_path = FIXTURE_SPECS.get(self.scenario)
        if not fixture_path:
            self.log(f"ERROR: unknown scenario '{self.scenario}'")
            self.log(f"Available: {', '.join(FIXTURE_SPECS.keys())}")
            return False

        spec = load_fixture(fixture_path, self.source_dir)
        self.wave_count = len(spec.get("waves", []))
        self.save_json_artifact("01-feature-spec.json", spec)

        self.log(f"submitting feature via /api/architect/plan ...")
        resp = _post(self.api, "/api/architect/plan", body={"feature_spec": spec}, timeout=120)
        self.save_json_artifact("02-plan-response.json", resp)

        if "_error" in resp:
            self.failures.append(f"Feature submission failed: {resp['_error']}")
            return False

        data = resp.get("data", {})
        self.feature_id = data.get("feature_id")
        self.packet_ids = data.get("packet_ids", [])
        if not self.packet_ids:
            self.packet_ids = [p["id"] for p in data.get("packet_summaries", [])]

        if self.feature_id:
            self.log(f"feature created: {self.feature_id}")
            self.log(f"packets: {', '.join(self.packet_ids)}")
            self.save_artifact("03-feature-id.txt", self.feature_id)
            self.save_artifact("04-packet-ids.txt", "\n".join(self.packet_ids))
            return True
        else:
            self.failures.append("Feature created but no feature_id in response")
            return False

    # ---- Polling ----
    def poll_until_done(self) -> bool:
        if not self.feature_id:
            return False

        start = time.time()
        deadline = start + self.timeout_s
        all_done = False
        last_state = {}

        self.log(f"polling packets every 5s (timeout: {self.timeout_s}s) ...")

        while time.time() < deadline:
            all_done = True
            for pid in self.packet_ids:
                resp = _get(self.api, f"/api/packets/{pid}", timeout=10)
                self.save_json_artifact(f"05-packet-{pid}.json", resp)

                if "_error" in resp:
                    self.failures.append(f"Cannot poll packet {pid}: {resp['_error']}")
                    continue

                data = resp.get("data", {})
                state = data.get("state", "unknown")
                last_state[pid] = state

                self.log_verbose(f"  {pid} state={state} attempt={data.get('attempt_count', 0)}")

                # Collect run IDs if available
                runs = data.get("runs", [])
                for run in runs:
                    rid = run.get("id", run.get("run_id", ""))
                    if rid and rid not in self.run_ids:
                        self.run_ids.append(rid)

                if state in ("accepted", "merged"):
                    self.log(f"  {pid} -> {state} ✓")
                elif state in ("failed", "rejected", "cancelled"):
                    self.log(f"  {pid} -> {state} ✗")
                    self.failures.append(f"Packet {pid} ended in state {state}")
                    # Collect failure details from trace
                    trace_resp = _get(self.api, f"/api/trace/packets/{pid}", timeout=10)
                    if "_error" not in trace_resp:
                        self.trace_data.append(trace_resp)
                        self.save_json_artifact(f"06-trace-{pid}.json", trace_resp)
                elif state in ("draft", "pending"):
                    all_done = False
                else:
                    all_done = False

            if all_done:
                self.log("all packets reached terminal state")
                # Final traces
                for pid in self.packet_ids:
                    trace_resp = _get(self.api, f"/api/trace/packets/{pid}", timeout=10)
                    if "_error" not in trace_resp:
                        self.trace_data.append(trace_resp)
                        self.save_json_artifact(f"06-trace-{pid}.json", trace_resp)
                return len(self.failures) == 0

            time.sleep(5)

        self.log("TIMEOUT: not all packets completed within time limit")
        self.blockers.append(f"Polling timeout after {self.timeout_s}s")
        self.save_artifact("07-last-states.json", json.dumps(last_state, indent=2))
        return False

    def collect_artifacts(self):
        """Fetch acceptance reports, evidence, and run logs for each run."""
        for rid in self.run_ids:
            # Find the parent packet_id
            pid = None
            for p in self.packet_ids:
                if rid.startswith(p) or p in rid:
                    pid = p
                    break
            if not pid:
                pid = rid.rsplit("-", 1)[0] if "-" in rid else self.packet_ids[0]

            # Acceptance report
            ar = _get(self.api, f"/api/packets/{pid}/runs/{rid}/evidence", timeout=10)
            if "_error" not in ar:
                self.save_json_artifact(f"08-evidence-{pid}-{rid}.json", ar)
                # Parse for T0/T1/T2 results
                accept_data = ar.get("data", ar)
                stages = accept_data.get("stages", accept_data.get("acceptance_stages", []))
                for stage in stages:
                    name = stage.get("stage", stage.get("name", ""))
                    result = stage.get("result", stage.get("status", ""))
                    if "T0" in name.upper() or "lint" in name.lower():
                        self.t0_result = f"{name}={result}"
                    elif "T1" in name.upper() or "unit" in name.lower() or "test" in name.lower():
                        self.t1_result = f"{name}={result}"
                    elif "T2" in name.upper() or "smoke" in name.lower() or "e2e" in name.lower():
                        self.t2_result = f"{name}={result}"
                    elif "verifier" in name.lower():
                        self.verifier_result = f"{name}={result}"
                    elif "reviewer" in name.lower():
                        self.reviewer_result = f"{name}={result}"

            # Logs
            logs = _get(self.api, f"/api/packets/{pid}/runs/{rid}/logs", timeout=10)
            if "_error" not in logs:
                self.save_json_artifact(f"09-logs-{pid}-{rid}.json", logs)

        # Feature trace
        if self.feature_id:
            ft = _get(self.api, f"/api/trace/features/{self.feature_id}", timeout=10)
            if "_error" not in ft:
                self.save_json_artifact("10-feature-trace.json", ft)

    # ---- Report ----
    def write_report(self):
        today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        report_path = Path("docs/work") / f"report-real-loop-orchestrator-smoke-{today}.md"
        report_path.parent.mkdir(parents=True, exist_ok=True)

        # Get commit sha
        sha = "unknown"
        try:
            sha = subprocess.check_output(
                ["git", "rev-parse", "HEAD"], stderr=subprocess.DEVNULL, text=True
            ).strip()
        except Exception:
            pass

        verdict = "PASS" if not self.failures and not self.blockers else "FAIL"

        report = f"""# Real-Loop Orchestrator Smoke Report

**Date:** {today}
**Commit:** {sha}
**Verdict:** {verdict}

## Summary

| Field | Value |
|-------|-------|
| Scenario | {self.scenario} |
| Profile | {self.profile} |
| Target project | {self.target_project} |
| Feature ID | {self.feature_id or 'N/A'} |
| Wave count | {self.wave_count} |
| Packets | {', '.join(self.packet_ids) if self.packet_ids else 'N/A'} |
| Run IDs | {', '.join(self.run_ids) if self.run_ids else 'N/A'} |
| Run dir | {self.run_dir} |

## Stage Results

| Stage | Result |
|-------|--------|
| T0 (lint/type/compile) | {self.t0_result} |
| T1 (unit/integration) | {self.t1_result} |
| T2 (smoke/e2e) | {self.t2_result} |
| Verifier | {self.verifier_result} |
| Reviewer | {self.reviewer_result} |

## Failures Found

"""
        if self.failures:
            for f in self.failures:
                report += f"- {f}\n"
        else:
            report += "None\n"

        report += """
## Bugs Fixed

"""
        if self.bugs_fixed:
            for b in self.bugs_fixed:
                report += f"- {b}\n"
        else:
            report += "None\n"

        report += """
## Replay / Resume Evidence

"""
        if self.replay_evidence:
            for e in self.replay_evidence:
                report += f"- {e}\n"
        else:
            report += "None\n"

        report += """
## Remaining Blockers

"""
        if self.blockers:
            for b in self.blockers:
                report += f"- {b}\n"
        else:
            report += "None\n"

        # Trace summary
        report += """
## Trace Summary

"""
        if self.trace_data:
            for td in self.trace_data:
                data = td.get("data", td)
                pid = data.get("packet_id", data.get("id", "?"))
                state = data.get("state", "?")
                stages = data.get("stages", [])
                stage_summary = "; ".join(
                    f"{s.get('stage', s.get('name', '?'))}: {s.get('result', s.get('status', '?'))}"
                    for s in stages
                ) if stages else "no stage data"
                report += f"- **{pid}** (state={state}): {stage_summary}\n"
        else:
            report += "No trace data collected.\n"

        report += f"""
## Artifacts

All smoke artifacts are under `{self.run_dir}`.

## Notes

- This report was generated automatically by `scripts/real_loop_smoke.py`.
- Environment secrets have been excluded.
- See `{self.run_dir}` for full request/response payloads.
"""

        report_path.write_text(report)
        self.log(f"report written: {report_path}")

    # ---- Run ----
    def run(self) -> int:
        self.log("=" * 60)
        self.log(f"SMOKE: {self.scenario} (profile={self.profile}, timeout={self.timeout_s}s)")
        self.log("=" * 60)

        if not self.submit_feature():
            self.log("FAIL: feature submission failed")
            self.collect_artifacts()
            self.write_report()
            return 1

        if not self.start_worker():
            self.failures.append("Worker start failed")
            self.write_report()
            return 1

        try:
            success = self.poll_until_done()
        finally:
            self.stop_worker()

        self.collect_artifacts()
        self.write_report()

        if success:
            self.log("=" * 60)
            self.log("SMOKE PASSED")
            self.log("=" * 60)
            return 0
        else:
            self.log("=" * 60)
            self.log("SMOKE FAILED")
            self.log("=" * 60)
            return 1


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------
def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    p = argparse.ArgumentParser(description="GRACE real-loop smoke harness")
    p.add_argument("--scenario", required=True, choices=list(FIXTURE_SPECS.keys()),
                   help="Smoke scenario name")
    p.add_argument("--run-dir", required=True,
                   help="Run artifact directory (e.g. <work-root>/runs/<ts>-<scenario>)")
    p.add_argument("--api-url", default="http://127.0.0.1:8042",
                   help="GRACE API URL")
    p.add_argument("--target-project", required=True,
                   help="Target fixture project path")
    p.add_argument("--profile", default="NORMAL", choices=["FAST", "NORMAL", "STRICT"],
                   help="Acceptance profile")
    p.add_argument("--source-dir", default="",
                   help="Repo source dir (default: cwd)")
    p.add_argument("--timeout", default="30",
                   help="Max run time in minutes")
    p.add_argument("--verbose", action="store_true",
                   help="Verbose output")
    return p.parse_args(argv)


def main():
    args = parse_args()
    if not args.source_dir:
        args.source_dir = str(Path.cwd())
    runner = SmokeRunner(args)
    sys.exit(runner.run())


if __name__ == "__main__":
    main()
