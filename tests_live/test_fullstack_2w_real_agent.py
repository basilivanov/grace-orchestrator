"""Live test: fullstack-2w — two-wave backend + frontend."""

from __future__ import annotations

import argparse

import pytest

from tests_live.runner.wave_resume_runner import WaveResumeRunner


@pytest.mark.live_agent
def test_fullstack_2w(api_url, target_dir, source_dir):
    args = argparse.Namespace(
        scenario="fullstack-2w",
        api_url=api_url,
        target_dir=str(target_dir),
        source_dir=str(source_dir),
        agent_profile="coder-deepseek-flash",
        architect_profile="architect-premium",
        max_waves=0,
        timeout=1200,
        keep_artifacts=False,
    )
    runner = WaveResumeRunner(args)
    rc = runner.run()
    assert rc == 0, f"Runner failed: {runner.report.get('failures')}"
    assert runner.report.get("status") == "passed"
