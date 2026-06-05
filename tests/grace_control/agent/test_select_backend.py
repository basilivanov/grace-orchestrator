"""Tests for grace_control.agent.select_backend() — settings-driven backend selection.

W7: added 'api' and 'mock' backends; W8: removed 'legacy' (raises ValueError).
"""
import pytest

from grace_control.agent import (
    BACKEND_API,
    BACKEND_MOCK,
    select_backend,
)
from grace_control.agent.api_backend import ApiAgentBackend
from grace_control.agent.mock_backend import MockBackend


def test_select_backend_legacy_raises_value_error():
    """W8: 'legacy' backend was removed — must raise ValueError."""
    with pytest.raises(ValueError, match="removed in W8"):
        select_backend("legacy")


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

    monkeypatch.setattr(cfg, "execution_backend", BACKEND_API)
    backend = select_backend()
    assert isinstance(backend, ApiAgentBackend)

    monkeypatch.setattr(cfg, "execution_backend", BACKEND_MOCK)
    backend = select_backend()
    assert isinstance(backend, MockBackend)


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
        assert result.domain_status == "accepted"
        assert "[mock:mock-v1]" in result.stdout

    asyncio.run(_check())


def test_api_backend_run_with_unknown_provider(tmp_path):
    """ApiAgentBackend.run with provider='openai' (no real adapter) returns rejected."""
    import asyncio
    from grace_control.agent.backend import ExecutionRequest

    async def _check():
        backend = select_backend(BACKEND_API)
        result = await backend.run(ExecutionRequest(
            packet_id="pkt-api-oai",
            spec={"role": "coder", "packet_markdown": "# hello"},
            worktree_path=tmp_path,
            branch_name="agent/test",
            executor={"provider": "openai", "model": "gpt-4o"},
            timeout_s=10,
        ))
        assert result.accepted is False
        assert "not yet implemented" in (result.reason or result.stderr).lower()

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
