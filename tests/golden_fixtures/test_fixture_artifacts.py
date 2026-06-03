"""Tests for fixture artifact creation."""

import tempfile
from pathlib import Path

from grace_control.core.golden_fixtures import FixtureRun, create_fixture_artifacts


class TestArtifacts:
    def test_create_acceptance_report_artifact(self):
        run = FixtureRun(
            attempt=1,
            artifacts=[{"name": "acceptance_report.json", "type": "json",
                        "content_json": {"final_verdict": "accepted", "summary": "ok"}}],
        )
        with tempfile.TemporaryDirectory() as td:
            art_path = create_fixture_artifacts(Path(td), "pkt_test", run)
            assert art_path
            report_file = Path(art_path) / "acceptance_report.json"
            assert report_file.exists()
            import json
            data = json.loads(report_file.read_text())
            assert data["final_verdict"] == "accepted"

    def test_creates_stdout_log_artifact(self):
        run = FixtureRun(
            attempt=1,
            artifacts=[{"name": "stdout.log", "type": "log", "content": "pytest passed\n"}],
        )
        with tempfile.TemporaryDirectory() as td:
            art_path = create_fixture_artifacts(Path(td), "pkt_log", run)
            log_file = Path(art_path) / "stdout.log"
            assert log_file.exists()
            assert "pytest passed" in log_file.read_text()

    def test_artifact_run_path_format(self):
        run = FixtureRun(attempt=2)
        with tempfile.TemporaryDirectory() as td:
            art_path = create_fixture_artifacts(Path(td), "pkt_fmt", run)
            assert "attempt-0002" in art_path
            assert "pkt_fmt" in art_path
