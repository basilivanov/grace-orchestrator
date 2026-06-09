"""Live test: backend-1w — one-wave backend-only scenario."""

from __future__ import annotations

import argparse

import pytest

from tests_live.runner.wave_resume_runner import WaveResumeRunner


@pytest.mark.live_agent
def test_backend_1w(api_url, target_dir, source_dir):
    args = argparse.Namespace(
        scenario="backend-1w",
        api_url=api_url,
        target_dir=str(target_dir),
        source_dir=str(source_dir),
        agent_profile="coder-deepseek-flash",
        architect_profile="architect-premium",
        max_waves=0,
        timeout=600,
        keep_artifacts=False,
    )
    runner = WaveResumeRunner(args)
    rc = runner.run()
    assert rc == 0, f"Runner failed: {runner.report.get('failures')}"
    assert runner.report.get("status") == "passed"
    assert runner.report.get("coder_runs", 0) >= 1
