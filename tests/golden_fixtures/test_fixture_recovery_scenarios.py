"""Automated tests for recovery fixture scenarios — runs via CLI."""

import subprocess
import json
import os
from pathlib import Path


def _run_fixture(fixture_name: str) -> dict:
    run_id = f"test-rec-{fixture_name.replace('_', '-')}"
    base_dir = f"/tmp/grace-fixtures/{run_id}"
    subprocess.run(["rm", "-rf", base_dir], capture_output=True)
    cmd = [
        ".venv/bin/grace", "golden", "fixture", "run-one",
        f"fixtures/golden/{fixture_name}.yaml",
        "--run-id", run_id,
        "--base-dir", base_dir,
        "--golden-fixture",
    ]
    env = os.environ.copy()
    env["GRACE_GOLDEN_FIXTURE"] = "1"
    r = subprocess.run(cmd, capture_output=True, text=True, timeout=60, cwd=Path(__file__).parent.parent.parent, env=env)
    report_path = Path(base_dir) / "reports" / "run-report.json"
    if report_path.exists():
        return json.loads(report_path.read_text())
    return {"error": r.stderr[:500], "stdout": r.stdout[:500], "raw": r.stderr + r.stdout}


class TestRecoveryFixtures:
    def test_recovery_coder_fail_once_retries_same(self):
        report = _run_fixture("recovery_coder_fail_once")
        assert not report.get("validation_errors"), report["validation_errors"]
        sr = report.get("stage_result", {})
        assert sr.get("recovery_action") == "retry_same_coder"

    def test_recovery_coder_fail_switch_model(self):
        report = _run_fixture("recovery_coder_fail_twice")
        assert not report.get("validation_errors"), report["validation_errors"]
        sr = report.get("stage_result", {})
        assert sr.get("recovery_action") == "switch_coder"

    def test_recovery_merge_dirty_true_blocker(self):
        report = _run_fixture("recovery_merge_dirty")
        assert not report.get("validation_errors"), report["validation_errors"]
        sr = report.get("stage_result", {})
        assert sr.get("recovery_action") == "block_feature"
        assert sr.get("failure_class") == "true_blocker"

    def test_recovery_missing_cli_blocker(self):
        report = _run_fixture("recovery_missing_cli")
        assert not report.get("validation_errors"), report["validation_errors"]
        sr = report.get("stage_result", {})
        assert sr.get("recovery_action") == "block_feature"
        assert sr.get("failure_class") == "true_blocker"

    def test_recovery_verifier_architect(self):
        report = _run_fixture("recovery_verifier_architect")
        assert not report.get("validation_errors"), report["validation_errors"]
        sr = report.get("stage_result", {})
        assert sr.get("recovery_action") == "return_to_architect"

    def test_recovery_profile_escalates_to_strict(self):
        report = _run_fixture("recovery_profile_escalates_to_strict")
        assert not report.get("validation_errors"), report["validation_errors"]
        sr = report.get("stage_result", {})
        assert sr.get("recovery_action") in ("return_to_architect", "block_feature")
