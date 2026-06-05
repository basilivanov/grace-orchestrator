"""Tests for grace_control.agent.select_backend() — settings-driven backend selection."""

import pytest

from grace_control.agent import (
    BACKEND_LEGACY,
    BACKEND_NEW,
    select_backend,
)
from grace_control.agent.legacy_backend import LegacyPrefectBackend
from grace_control.agent.new_backend import NewDirectBackend


def test_select_backend_legacy_returns_legacy():
    """Explicit 'legacy' name returns LegacyPrefectBackend."""
    backend = select_backend(BACKEND_LEGACY)
    assert isinstance(backend, LegacyPrefectBackend)


def test_select_backend_new_returns_new():
    """Explicit 'new' name returns NewDirectBackend (stub)."""
    backend = select_backend(BACKEND_NEW)
    assert isinstance(backend, NewDirectBackend)


def test_select_backend_unknown_raises():
    """Unknown backend name → ValueError."""
    with pytest.raises(ValueError, match="Unknown execution backend"):
        select_backend("not-a-backend")


def test_select_backend_default_reads_settings(monkeypatch):
    """Empty name → reads grace_control.config.settings.execution_backend."""
    # Import the instance, not the submodule. The package has both
    # `grace_control.config.settings` (the module) and a `settings` attribute
    # (the GraceSettings instance); bare `from grace_control.config import
    # settings` resolves to the submodule.
    from grace_control.config import GraceSettings
    from grace_control.config.settings import settings as cfg

    monkeypatch.setattr(cfg, "execution_backend", BACKEND_NEW)
    backend = select_backend()
    assert isinstance(backend, NewDirectBackend)

    monkeypatch.setattr(cfg, "execution_backend", BACKEND_LEGACY)
    backend = select_backend()
    assert isinstance(backend, LegacyPrefectBackend)


def test_new_backend_run_returns_not_implemented():
    """NewDirectBackend.run() returns accepted=False with reason."""
    import asyncio
    from pathlib import Path

    from grace_control.agent.backend import ExecutionRequest

    async def _check():
        backend = select_backend(BACKEND_NEW)
        result = await backend.run(ExecutionRequest(
            packet_id="pkt-x", spec={}, worktree_path=Path("/tmp"),
            branch_name="agent/x", timeout_s=10,
        ))
        assert result.accepted is False
        assert "not yet implemented" in result.reason.lower()
        assert result.domain_status == "failed"

    asyncio.run(_check())
