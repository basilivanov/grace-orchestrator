"""W13 — llm_runner regression tests: profile resolution, prompt delivery, stdout return."""
from __future__ import annotations
import asyncio
from pathlib import Path
import pytest
from grace_control.config.agent_profiles import reset_cache


@pytest.fixture(autouse=True)
def _reset_profile_cache():
    reset_cache()


def _setup_fake_agent(tmp_path, monkeypatch, exit_code=0, stdout='{"result": "ok"}'):
    fake = tmp_path / "agy"
    fake.write_text(f"#!/bin/sh\necho '{stdout}'\nexit {exit_code}\n")
    fake.chmod(0o755)
    monkeypatch.setenv("PATH", f"{tmp_path}:{Path('/usr/bin')}:{Path('/bin')}")


def test_run_llm_resolves_profile_and_returns_stdout(tmp_path, monkeypatch):
    """run_llm resolves a live profile and returns stdout from fake command."""
    _setup_fake_agent(tmp_path, monkeypatch)
    from grace_control.core.llm_runner import run_llm
    from grace_control.config.agent_profiles import load_agent_profiles

    profiles = load_agent_profiles()
    assert "coder_agy" in profiles

    async def _check():
        result = await run_llm("hello test", role="coder", model="m", cli="coder_agy", cwd=tmp_path)
        assert "ok" in result

    asyncio.run(_check())


def test_run_llm_fails_on_unknown_profile():
    """run_llm raises ValueError for unknown executor_id."""
    from grace_control.core.llm_runner import run_llm

    async def _check():
        with pytest.raises(ValueError, match="no agent profile"):
            await run_llm("test", role="coder", model="m", cli="no-such-executor")

    asyncio.run(_check())


def test_run_llm_empty_output_raises(tmp_path, monkeypatch):
    """run_llm raises RuntimeError when backend returns non-zero exit."""
    _setup_fake_agent(tmp_path, monkeypatch, exit_code=1, stdout="")
    from grace_control.core.llm_runner import run_llm

    async def _check():
        with pytest.raises(RuntimeError):
            await run_llm("test", role="coder", model="m", cli="coder_agy", cwd=tmp_path)

    asyncio.run(_check())
