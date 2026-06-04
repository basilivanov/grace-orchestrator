"""Automated tests for merge fixture scenarios — runs via CLI."""

import subprocess
import json
import os
from pathlib import Path


def _run_fixture(fixture_name: str) -> dict:
    """Run a golden fixture via CLI and return the report."""
    run_id = f"test-{fixture_name.replace('_', '-')}"
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
    return {"error": r.stderr[:500], "stdout": r.stdout[:500]}


class TestMergeFixtureScenarios:
    def test_merge_clean_success_merges(self):
        report = _run_fixture("merge_clean_success")
        assert not report.get("validation_errors"), report["validation_errors"]
        assert report.get("stage_result", {}).get("success") is True
        assert report.get("status") == "passed"

    def test_merge_dirty_target_fails_closed(self):
        report = _run_fixture("merge_dirty_target_repo")
        sr = report.get("stage_result", {})
        assert sr.get("success") is False
        err = sr.get("error", "")
        assert "DIRTY" in err.upper(), f"Expected DIRTY error, got: {err}"

    def test_merge_missing_worktree_fails_clear(self):
        report = _run_fixture("merge_missing_worktree")
        sr = report.get("stage_result", {})
        assert sr.get("success") is False
        err = sr.get("error", "")
        assert "does not exist" in err.lower(), f"Expected 'does not exist', got: {err}"

    def test_merge_missing_branch_fails_clear(self):
        report = _run_fixture("merge_missing_branch")
        sr = report.get("stage_result", {})
        assert sr.get("success") is False
        err = sr.get("error", "")
        assert "does not exist" in err.lower() or "branch" in err.lower(), f"Expected branch error, got: {err}"

    def test_merge_no_changes_succeeds(self):
        report = _run_fixture("merge_no_changes")
        assert not report.get("validation_errors"), report["validation_errors"]
        assert report.get("status") == "passed"
        sr = report.get("stage_result", {})
        assert sr.get("success") is True
