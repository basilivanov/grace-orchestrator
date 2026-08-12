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


# ── W7 profile validation ──────────────────────────────────────────────


def test_agent_profile_rejects_string_command():
    """AgentProfile rejects string `command` with clear ValueError."""
    from grace_control.config.agent_profiles import AgentProfile
    import pytest
    with pytest.raises(ValueError, match="must be a list"):
        AgentProfile("bad_exec", {"command": "agy"})


def test_agent_profile_accepts_list_command():
    """AgentProfile accepts list command."""
    from grace_control.config.agent_profiles import AgentProfile
    p = AgentProfile("ok", {"command": ["agy", "run", "--model", "{model}"]})
    assert p.command == ["agy", "run", "--model", "{model}"]


# ── Env builder ────────────────────────────────────────────────────────


def test_env_builder_inherits_path():
    """AgentEnvBuilder.build() must include PATH from parent env."""
    from grace_control.services.agent_env_builder import AgentEnvBuilder
    import os
    env = AgentEnvBuilder().build({})
    assert "PATH" in env


# ── Exit code handling ─────────────────────────────────────────────────


def test_run_service_exit_zero_accepted():
    """Exit code 0 → accepted=True, domain_status='completed'."""
    import asyncio
    from pathlib import Path
    from grace_control.services.agent_run_service import AgentRunService
    svc = AgentRunService()

    async def _check():
        result = await svc.run(
            {"command": ["echo", "ok"], "model": "t", "effort": "low"},
            packet_id="p-exit-0", worktree_path=Path("."), state_root=Path("/tmp"),
            packet_markdown="", timeout_seconds=5,
        )
        assert result["accepted"] is True
        assert result["domain_status"] == "completed"

    asyncio.run(_check())


def test_run_service_exit_nonzero_rejected():
    """Exit code != 0 → accepted=False, domain_status='failed'."""
    import asyncio
    from pathlib import Path
    from grace_control.services.agent_run_service import AgentRunService
    svc = AgentRunService()

    async def _check():
        result = await svc.run(
            {"command": ["sh", "-c", "exit 1"], "model": "t", "effort": "low"},
            packet_id="p-exit-1", worktree_path=Path("."), state_root=Path("/tmp"),
            packet_markdown="", timeout_seconds=5,
        )
        assert result["accepted"] is False
        assert result["domain_status"] == "failed"

    asyncio.run(_check())


# ── Stdin input mode ───────────────────────────────────────────────────


def test_stdin_input_mode_sends_markdown():
    """stdin mode sends packet_markdown to subprocess stdin."""
    import asyncio
    from pathlib import Path
    from grace_control.services.agent_run_service import AgentRunService
    svc = AgentRunService()

    async def _check():
        result = await svc.run(
            {
                "command": ["cat"],
                "model": "t", "effort": "low",
                "input_mode": "stdin",
                "input_template": "{packet_markdown}",
            },
            packet_id="p-stdin", worktree_path=Path("/tmp"), state_root=Path("/tmp"),
            packet_markdown="hello from stdin", timeout_seconds=5,
        )
        assert "hello from stdin" in result.get("stdout", ""), f"stdout={result['stdout']!r} stderr={result['stderr']!r}"

    asyncio.run(_check())


# ── W12: evidence_dir ──────────────────────────────────────────────────


def test_agent_artifacts_written_to_evidence_dir(tmp_path):
    """When run_dir is provided, stdout/stderr artifacts go there."""
    import asyncio
    from pathlib import Path
    from grace_control.services.agent_run_service import AgentRunService
    svc = AgentRunService()
    ed = tmp_path / "evidence"
    ed.mkdir(parents=True)

    async def _check():
        result = await svc.run(
            {"command": ["echo", "hello-artifact"], "model": "t", "effort": "low"},
            packet_id="p-evd", worktree_path=Path("."), state_root=Path("/tmp"),
            packet_markdown="", timeout_seconds=5, run_dir=ed,
        )
        assert result["accepted"] is True
        so = ed / "agent_stdout.log"
        assert so.exists(), f"stdout not at {so}, artifacts: {result['artifacts']}"
        assert "hello-artifact" in so.read_text()

    asyncio.run(_check())


def test_executor_request_passes_evidence_dir(tmp_path):
    """ExecutionRequest.evidence_dir is passed through to artifact collector."""
    import asyncio
    from pathlib import Path
    from grace_control.agent.backend import ExecutionRequest
    from grace_control.services.agent_run_service import AgentRunService

    ed = tmp_path / "runs" / "R01"
    svc = AgentRunService()

    async def _check():
        result = await svc.run(
            {"command": ["echo", "evidence-ok"], "model": "t", "effort": "low"},
            packet_id="pkt-evidence", worktree_path=Path("."),
            state_root=Path("/tmp"), packet_markdown="",
            timeout_seconds=5, run_dir=ed,
        )
        so = ed / "agent_stdout.log"
        assert so.exists(), f"stdout not found at {so}"
        assert "evidence-ok" in so.read_text()
        assert result["accepted"] is True

    asyncio.run(_check())
