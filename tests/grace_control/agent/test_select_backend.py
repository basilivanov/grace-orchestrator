"""Tests for grace_control.agent.select_backend() — settings-driven backend selection.

W7 (revised): 'cli' is the default backend, wrapping UniversalCliAgentBackend.
"""
import pytest

from grace_control.agent import (
    BACKEND_API,
    BACKEND_CLI,
    BACKEND_MOCK,
    select_backend,
)
from grace_control.agent.api_backend import ApiAgentBackend
from grace_control.agent.mock_backend import MockBackend
from grace_control.agent.universal_cli_backend import UniversalCliAgentBackend


def test_select_backend_legacy_raises_value_error():
    """W8: 'legacy' backend was removed — must raise ValueError."""
    with pytest.raises(ValueError, match="removed in W8"):
        select_backend("legacy")


def test_select_backend_cli_returns_cli():
    """Explicit 'cli' name returns UniversalCliAgentBackend."""
    backend = select_backend(BACKEND_CLI)
    assert isinstance(backend, UniversalCliAgentBackend)


def test_select_backend_api_returns_api():
    """Explicit 'api' name returns ApiAgentBackend."""
    backend = select_backend(BACKEND_API)
    assert isinstance(backend, ApiAgentBackend)


def test_select_backend_mock_returns_mock():
    """Explicit 'mock' name returns MockBackend."""
    backend = select_backend(BACKEND_MOCK)
    assert isinstance(backend, MockBackend)


def test_select_backend_unknown_raises():
    """Unknown backend name → ValueError."""
    with pytest.raises(ValueError, match="Unknown execution backend"):
        select_backend("not-a-backend")


def test_select_backend_default_reads_settings(monkeypatch):
    """Empty name → reads grace_control.config.settings.execution_backend."""
    from grace_control.config.settings import settings as cfg

    monkeypatch.setattr(cfg, "execution_backend", BACKEND_CLI)
    backend = select_backend()
    assert isinstance(backend, UniversalCliAgentBackend)

    monkeypatch.setattr(cfg, "execution_backend", BACKEND_API)
    backend = select_backend()
    assert isinstance(backend, ApiAgentBackend)

    monkeypatch.setattr(cfg, "execution_backend", BACKEND_MOCK)
    backend = select_backend()
    assert isinstance(backend, MockBackend)


def test_cli_backend_run_with_fake_command(tmp_path):
    """UniversalCliAgentBackend.run with a fake local command succeeds."""
    import asyncio
    from grace_control.agent.backend import ExecutionRequest

    async def _check():
        backend = select_backend(BACKEND_CLI)
        result = await backend.run(ExecutionRequest(
            packet_id="pkt-cli-test",
            spec={"role": "coder", "packet_markdown": "test"},
            worktree_path=tmp_path,
            branch_name="agent/test",
            executor={
                "executor_id": "test_echo",
                "command": ["echo", "hello-agent"],
                "model": "test-model",
                "effort": "low",
            },
            timeout_s=10,
        ))
        assert result.accepted is True
        assert "hello-agent" in result.stdout

    asyncio.run(_check())


def test_cli_backend_timeout_returns_timed_out(tmp_path):
    """UniversalCliAgentBackend handles timeout → domain_status='timeout'."""
    import asyncio
    from grace_control.agent.backend import ExecutionRequest

    async def _check():
        backend = select_backend(BACKEND_CLI)
        result = await backend.run(ExecutionRequest(
            packet_id="pkt-timeout",
            spec={},
            worktree_path=tmp_path,
            branch_name="agent/test",
            executor={
                "executor_id": "test_sleep",
                "command": ["sleep", "10"],
                "model": "t",
                "timeout_seconds": 1,
            },
            timeout_s=1,
        ))
        assert result.domain_status == "timeout"

    asyncio.run(_check())


def test_api_backend_run_with_mock_provider(tmp_path):
    """ApiAgentBackend.run with provider='mock' succeeds without subprocess."""
    import asyncio
    from grace_control.agent.backend import ExecutionRequest

    async def _check():
        backend = select_backend(BACKEND_API)
        result = await backend.run(ExecutionRequest(
            packet_id="pkt-api-mock",
            spec={"role": "coder", "packet_markdown": "# hello"},
            worktree_path=tmp_path,
            branch_name="agent/test",
            executor={"provider": "mock", "model": "mock-v1"},
            timeout_s=10,
        ))
        assert result.accepted is True
        assert "[mock:mock-v1]" in result.stdout

    asyncio.run(_check())


def test_mock_backend_run_succeeds(tmp_path):
    """MockBackend.run always returns accepted=True with a marker file."""
    import asyncio
    from grace_control.agent.backend import ExecutionRequest

    async def _check():
        backend = select_backend(BACKEND_MOCK)
        result = await backend.run(ExecutionRequest(
            packet_id="pkt-mock",
            spec={"attempt_count": 1},
            worktree_path=tmp_path / "wt",
            branch_name="agent/test",
            timeout_s=10,
        ))
        assert result.accepted is True
        assert (tmp_path / "wt" / ".mock_run.log").exists()
        assert "pkt-mock" in result.stdout

    asyncio.run(_check())
