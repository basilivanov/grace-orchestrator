"""W13 — llm_runner regression tests: profile resolution, prompt delivery, stdout return."""
from __future__ import annotations
import asyncio
from pathlib import Path
import pytest
from grace_control.config.agent_profiles import reset_cache


@pytest.fixture(autouse=True)
def _reset_profile_cache():
    reset_cache()


def test_run_llm_resolves_profile_and_returns_stdout(tmp_path):
    """run_llm resolves 'opencode' profile and returns stdout from fake command."""
    import os
    fake_cli = tmp_path / "opencode"
    fake_cli.write_text("#!/bin/sh\necho '{\"result\": \"hello from test\"}'\n")
    fake_cli.chmod(0o755)
    os.environ["PATH"] = f"{tmp_path}:{os.environ.get('PATH', '')}"

    from grace_control.core.llm_runner import run_llm
    from grace_control.config.agent_profiles import load_agent_profiles

    profiles = load_agent_profiles()
    assert "opencode" in profiles, f"profiles keys: {list(profiles.keys())}"

    async def _check():
        result = await run_llm(
            "hello from test",
            role="architect",
            model="test-model",
            cli="opencode",
            cwd=tmp_path,
        )
        assert "hello from test" in result or "result" in result

    asyncio.run(_check())


def test_run_llm_fails_on_unknown_profile():
    """run_llm raises ValueError for unknown executor_id."""
    from grace_control.core.llm_runner import run_llm
    import pytest

    async def _check():
        with pytest.raises(ValueError, match="no agent profile"):
            await run_llm("test", role="coder", model="m", cli="no-such-executor")

    asyncio.run(_check())


def test_run_llm_empty_output_raises(tmp_path):
    """run_llm raises RuntimeError when backend returns non-zero exit."""
    fake = tmp_path / "opencode"
    fake.write_text("#!/bin/sh\necho ''\nexit 1\n")
    fake.chmod(0o755)
    import os
    os.environ["PATH"] = f"{tmp_path}:{os.environ.get('PATH', '')}"

    from grace_control.core.llm_runner import run_llm

    async def _check():
        with pytest.raises(RuntimeError):
            await run_llm("test", role="architect", model="m", cli="opencode", cwd=tmp_path)

    asyncio.run(_check())
