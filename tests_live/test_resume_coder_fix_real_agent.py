"""Live test: resume-coder-fix — coder resume/fix scenario."""

from __future__ import annotations

import argparse

import pytest

from tests_live.runner.wave_resume_runner import WaveResumeRunner


@pytest.mark.live_agent
def test_resume_coder_fix(api_url, target_dir, source_dir):
    args = argparse.Namespace(
        scenario="resume-coder-fix",
        timeout=1200,
        agent_profile="coder-deepseek-flask",
        architect_profile="architect-premium",
        max_waves=0,
        keep_artifacts=False,
        target_dir=str(target_dir),
        source_dir=str(source_dir),
        api_url=api_url,
    )
    runner = WaveResumeRunner(args)
    rc = runner.run()
    assert rc == 0, f"Runner failed: {runner.report.get('failures')}"
    assert runner.report.get("status") == "passed"
    assert runner.report.get("coder_runs", 0) >= 2
    assert runner.report.get("agent_session_resumes", 0) >= 1
