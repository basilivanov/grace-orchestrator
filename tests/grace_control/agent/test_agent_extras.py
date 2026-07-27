"""W7-extras — tests for env-driven `extras:` field in agent profiles.

Covers:
  1. AgentProfile validation accepts list[str] extras, rejects string.
  2. AgentProfile.to_dict() round-trips extras.
  3. AgentRunService appends rendered extras when ${VAR} resolves.
  4. AgentRunService drops ${VAR} tokens when env var is unset.
  5. AgentRunService drops empty/whitespace-only tokens.
  6. AgentRunService passes through command unchanged when no extras set.
  7. AgentEnvBuilder.resolve() expands ${VAR} and leaves literals intact.
"""
from __future__ import annotations

import os
from pathlib import Path
from unittest.mock import patch

import pytest

from grace_control.config.agent_profiles import AgentProfile
from grace_control.config.settings import settings
from grace_control.services.agent_env_builder import AgentEnvBuilder
from grace_control.services.agent_run_service import AgentRunService
from grace_control.services.process_supervisor import ProcessResult


# ---------------------------------------------------------------------------
# AgentProfile validation
# ---------------------------------------------------------------------------


class TestAgentProfileExtras:
    def test_accepts_list_extras(self):
        profile = AgentProfile("foo", {
            "backend": "cli",
            "command": ["echo", "hi"],
            "extras": ["--flag", "${SOME_VAR}"],
        })
        assert profile.extras == ["--flag", "${SOME_VAR}"]

    def test_defaults_extras_to_empty_list(self):
        profile = AgentProfile("foo", {
            "backend": "cli",
            "command": ["echo", "hi"],
        })
        assert profile.extras == []

    def test_rejects_string_extras(self):
        with pytest.raises(ValueError, match="extras.*list of strings"):
            AgentProfile("foo", {
                "backend": "cli",
                "command": ["echo", "hi"],
                "extras": "--flag ${SOME_VAR}",
            })

    def test_rejects_non_list_extras(self):
        with pytest.raises(ValueError, match="extras.*list of strings"):
            AgentProfile("foo", {
                "backend": "cli",
                "command": ["echo", "hi"],
                "extras": {"--flag": "value"},
            })

    def test_rejects_non_string_token(self):
        with pytest.raises(ValueError, match="extras\\[1\\]"):
            AgentProfile("foo", {
                "backend": "cli",
                "command": ["echo", "hi"],
                "extras": ["--flag", 42],
            })

    def test_to_dict_includes_extras(self):
        profile = AgentProfile("foo", {
            "backend": "cli",
            "command": ["echo", "hi"],
            "extras": ["--flag", "value"],
        })
        d = profile.to_dict()
        assert d["extras"] == ["--flag", "value"]

    def test_to_dict_extras_empty_when_unset(self):
        profile = AgentProfile("foo", {
            "backend": "cli",
            "command": ["echo", "hi"],
        })
        d = profile.to_dict()
        assert d["extras"] == []


# ---------------------------------------------------------------------------
# AgentEnvBuilder.resolve()
# ---------------------------------------------------------------------------


class TestAgentEnvBuilderResolve:
    def test_expands_set_var(self):
        with patch.dict(os.environ, {"MY_VAR": "hello"}):
            assert AgentEnvBuilder().resolve("--flag ${MY_VAR}") == "--flag hello"

    def test_leaves_unset_var_as_literal(self):
        env = {k: v for k, v in os.environ.items() if k != "MY_UNSET_VAR"}
        with patch.dict(os.environ, env, clear=True):
            assert AgentEnvBuilder().resolve("--flag ${MY_UNSET_VAR}") == "--flag ${MY_UNSET_VAR}"

    def test_passes_through_literal(self):
        assert AgentEnvBuilder().resolve("--literal") == "--literal"


# ---------------------------------------------------------------------------
# AgentRunService extras integration (mocks supervisor to capture command)
# ---------------------------------------------------------------------------


def _fake_executor(extras=None, command=None, **extra):
    base = {
        "executor_id": "test-agent",
        "command": command or ["echo", "{packet_markdown}"],
        "model": "test-model",
        "effort": "medium",
        "cwd": "{worktree_path}",
        "timeout_seconds": 30,
        "env": {},
        "input_mode": "none",
        "input_template": "",
    }
    if extras is not None:
        base["extras"] = extras
    base.update(extra)
    return base


class TestAgentRunServiceExtras:
    @pytest.mark.asyncio
    async def test_localizes_project_root_env_to_worktree(self, tmp_path: Path):
        captured: dict = {}

        async def fake_run(
            self, command, cwd, env=None, timeout_seconds=600,
            stdin_text=None, **kwargs,
        ):
            captured["env"] = dict(env) if env else {}
            return ProcessResult(stdout="ok", stderr="", exit_code=0, duration_ms=10)

        parent_root = tmp_path / "merge-destination"
        worktree = tmp_path / "isolated-worktree"
        worktree.mkdir()
        with patch.dict(os.environ, {
            "GRACE_PROJECT_ROOT": str(parent_root),
            "GRACE_TARGET_REPO_ROOT": str(parent_root),
        }):
            with patch.object(
                __import__("grace_control.services.process_supervisor", fromlist=["ProcessSupervisor"]).ProcessSupervisor,
                "run", fake_run,
            ):
                service = AgentRunService()
                await service.run(
                    _fake_executor(),
                    packet_id="pkt-test",
                    worktree_path=worktree,
                    state_root=tmp_path,
                    packet_markdown="# hello",
                )

        assert captured["env"]["GRACE_PROJECT_ROOT"] == str(worktree.resolve())
        assert captured["env"]["GRACE_TARGET_REPO_ROOT"] == str(worktree.resolve())
        assert captured["env"]["GRACE_AGENT_WORKTREE"] == str(worktree.resolve())

    @pytest.mark.asyncio
    async def test_appends_extras_when_env_var_set(self, tmp_path: Path):
        captured: dict = {}

        async def fake_run(
            self, command, cwd, env=None, timeout_seconds=600,
            stdin_text=None, **kwargs,
        ):
            captured["command"] = list(command)
            captured["env"] = dict(env) if env else {}
            return ProcessResult(stdout="ok", stderr="", exit_code=0, duration_ms=10)

        with patch.dict(os.environ, {"OPENCODE_SERVER_URL": "http://127.0.0.1:4096",
                                     "OPENCODE_SERVER_PASSWORD": "secret123"}):
            with patch.object(
                __import__("grace_control.services.process_supervisor", fromlist=["ProcessSupervisor"]).ProcessSupervisor,
                "run", fake_run,
            ):
                service = AgentRunService()
                await service.run(
                    _fake_executor(extras=["--attach", "${OPENCODE_SERVER_URL}", "-p", "${OPENCODE_SERVER_PASSWORD}"]),
                    packet_id="pkt-test",
                    worktree_path=tmp_path,
                    state_root=tmp_path,
                    packet_markdown="# hello",
                )

        cmd = captured["command"]
        assert cmd[-4:] == ["--attach", "http://127.0.0.1:4096", "-p", "secret123"]

    @pytest.mark.asyncio
    async def test_drops_unresolved_env_var_tokens(self, tmp_path: Path):
        captured: dict = {}

        async def fake_run(
            self, command, cwd, env=None, timeout_seconds=600,
            stdin_text=None, **kwargs,
        ):
            captured["command"] = list(command)
            return ProcessResult(stdout="ok", stderr="", exit_code=0, duration_ms=10)

        env = {k: v for k, v in os.environ.items()
               if k not in ("OPENCODE_SERVER_URL", "OPENCODE_SERVER_PASSWORD")}
        with patch.dict(os.environ, env, clear=True):
            with patch.object(
                __import__("grace_control.services.process_supervisor", fromlist=["ProcessSupervisor"]).ProcessSupervisor,
                "run", fake_run,
            ):
                service = AgentRunService()
                await service.run(
                    _fake_executor(extras=["--attach", "${OPENCODE_SERVER_URL}", "-p", "${OPENCODE_SERVER_PASSWORD}"]),
                    packet_id="pkt-test",
                    worktree_path=tmp_path,
                    state_root=tmp_path,
                    packet_markdown="# hello",
                )

        cmd = captured["command"]
        assert "--attach" not in cmd
        assert "-p" not in cmd
        assert "${OPENCODE_SERVER_URL}" not in cmd
        assert "${OPENCODE_SERVER_PASSWORD}" not in cmd

    @pytest.mark.asyncio
    async def test_drops_empty_tokens(self, tmp_path: Path):
        captured: dict = {}

        async def fake_run(
            self, command, cwd, env=None, timeout_seconds=600,
            stdin_text=None, **kwargs,
        ):
            captured["command"] = list(command)
            return ProcessResult(stdout="ok", stderr="", exit_code=0, duration_ms=10)

        with patch.dict(os.environ, {"OPENCODE_SERVER_URL": "   "}, clear=False):
            with patch.object(
                __import__("grace_control.services.process_supervisor", fromlist=["ProcessSupervisor"]).ProcessSupervisor,
                "run", fake_run,
            ):
                service = AgentRunService()
                await service.run(
                    _fake_executor(extras=["--attach", "${OPENCODE_SERVER_URL}"]),
                    packet_id="pkt-test",
                    worktree_path=tmp_path,
                    state_root=tmp_path,
                    packet_markdown="# hello",
                )

        cmd = captured["command"]
        assert "--attach" not in cmd
        assert "   " not in cmd

    @pytest.mark.asyncio
    async def test_no_extras_means_no_appended_flags(self, tmp_path: Path):
        captured: dict = {}

        async def fake_run(
            self, command, cwd, env=None, timeout_seconds=600,
            stdin_text=None, **kwargs,
        ):
            captured["command"] = list(command)
            return ProcessResult(stdout="ok", stderr="", exit_code=0, duration_ms=10)

        with patch.dict(os.environ, {}, clear=True):
            with patch.object(
                __import__("grace_control.services.process_supervisor", fromlist=["ProcessSupervisor"]).ProcessSupervisor,
                "run", fake_run,
            ):
                service = AgentRunService()
                await service.run(
                    _fake_executor(extras=[]),
                    packet_id="pkt-test",
                    worktree_path=tmp_path,
                    state_root=tmp_path,
                    packet_markdown="# hello",
                )

        cmd = captured["command"]
        assert cmd == ["echo", "# hello"]

    @pytest.mark.asyncio
    async def test_partial_extras_when_one_var_set(self, tmp_path: Path):
        captured: dict = {}

        async def fake_run(
            self, command, cwd, env=None, timeout_seconds=600,
            stdin_text=None, **kwargs,
        ):
            captured["command"] = list(command)
            return ProcessResult(stdout="ok", stderr="", exit_code=0, duration_ms=10)

        env = {k: v for k, v in os.environ.items() if k != "OPENCODE_SERVER_PASSWORD"}
        env["OPENCODE_SERVER_URL"] = "http://example:9000"
        with patch.dict(os.environ, env, clear=True):
            with patch.object(
                __import__("grace_control.services.process_supervisor", fromlist=["ProcessSupervisor"]).ProcessSupervisor,
                "run", fake_run,
            ):
                service = AgentRunService()
                await service.run(
                    _fake_executor(extras=["--attach", "${OPENCODE_SERVER_URL}", "-p", "${OPENCODE_SERVER_PASSWORD}"]),
                    packet_id="pkt-test",
                    worktree_path=tmp_path,
                    state_root=tmp_path,
                    packet_markdown="# hello",
                )

        cmd = captured["command"]
        assert cmd[-2:] == ["--attach", "http://example:9000"]
        assert "-p" not in cmd

    @pytest.mark.asyncio
    async def test_standalone_flag_emitted_when_no_value_follows(self, tmp_path: Path):
        captured: dict = {}

        async def fake_run(
            self, command, cwd, env=None, timeout_seconds=600,
            stdin_text=None, **kwargs,
        ):
            captured["command"] = list(command)
            return ProcessResult(stdout="ok", stderr="", exit_code=0, duration_ms=10)

        with patch.dict(os.environ, {}, clear=True):
            with patch.object(
                __import__("grace_control.services.process_supervisor", fromlist=["ProcessSupervisor"]).ProcessSupervisor,
                "run", fake_run,
            ):
                service = AgentRunService()
                await service.run(
                    _fake_executor(extras=["--verbose", "--attach", "${UNSET_URL}"]),
                    packet_id="pkt-test",
                    worktree_path=tmp_path,
                    state_root=tmp_path,
                    packet_markdown="# hello",
                )

        cmd = captured["command"]
        assert "--verbose" in cmd
        assert "--attach" not in cmd
        assert "${UNSET_URL}" not in cmd

    @pytest.mark.asyncio
    async def test_backend_injects_settings_into_executor_env(self, tmp_path: Path):
        """When the profile's extras reference ${OPENCODE_SERVER_URL} (or
        OPENCODE_SERVER_PASSWORD), the backend injects the setting into
        the executor's env so the placeholder can resolve."""
        captured: dict = {}

        class FakeRunService:
            async def run(self, executor, **kw):
                captured["executor"] = executor
                return {"accepted": True, "domain_status": "completed", "exit_code": 0, "stdout": "ok"}

        with (
            patch.object(settings, "opencode_server_url", "http://from-settings:4096"),
            patch.object(settings, "opencode_server_password", "pw-from-settings"),
        ):
            from grace_control.agent.universal_cli_backend import UniversalCliAgentBackend
            backend = UniversalCliAgentBackend(FakeRunService())  # type: ignore[arg-type]
            from grace_control.agent.backend import ExecutionRequest
            req = ExecutionRequest(
                packet_id="pkt-inject",
                spec={},
                worktree_path=tmp_path,
                branch_name="test",
                executor={
                    "executor_id": "test",
                    "command": [
                        "opencode", "run",
                        "--attach", "${OPENCODE_SERVER_URL}",
                        "-p", "${OPENCODE_SERVER_PASSWORD}",
                    ],
                    "env": {"EXISTING": "keep"},
                },
            )
            await backend.run(req)

        env = captured["executor"]["env"]
        assert env["OPENCODE_SERVER_URL"] == "http://from-settings:4096"
        assert env["OPENCODE_SERVER_PASSWORD"] == "pw-from-settings"
        assert env["EXISTING"] == "keep"

    @pytest.mark.asyncio
    async def test_backend_does_not_inject_when_profile_does_not_reference(self, tmp_path: Path):
        """If the profile's command/extras do NOT reference OPENCODE_* vars,
        the backend must NOT inject them — otherwise `opencode run` picks
        them up from env and exits with "Session not found" (regression)."""
        captured: dict = {}

        class FakeRunService:
            async def run(self, executor, **kw):
                captured["executor"] = executor
                return {"accepted": True, "domain_status": "completed", "exit_code": 0, "stdout": "ok"}

        with (
            patch.object(settings, "opencode_server_url", "http://from-settings:4096"),
            patch.object(settings, "opencode_server_password", "pw-from-settings"),
        ):
            from grace_control.agent.universal_cli_backend import UniversalCliAgentBackend
            backend = UniversalCliAgentBackend(FakeRunService())  # type: ignore[arg-type]
            from grace_control.agent.backend import ExecutionRequest
            req = ExecutionRequest(
                packet_id="pkt-noinject",
                spec={},
                worktree_path=tmp_path,
                branch_name="test",
                executor={
                    "executor_id": "test",
                    # Profile does NOT use ${OPENCODE_SERVER_URL} anywhere
                    "command": ["opencode", "run", "--model", "{model}", "{packet_markdown}"],
                    "env": {"EXISTING": "keep"},
                },
            )
            await backend.run(req)

        env = captured["executor"]["env"]
        assert "OPENCODE_SERVER_URL" not in env
        assert "OPENCODE_SERVER_PASSWORD" not in env
        assert env["EXISTING"] == "keep"

    def test_project_config_opencode_section(self, tmp_path: Path):
        cfg = tmp_path / ".grace"
        cfg.mkdir(parents=True, exist_ok=True)
        config_path = cfg / "config.yaml"
        config_path.write_text(
            "opencode:\n"
            "  server_url: http://yaml:4096\n"
            "  server_password: yamlpw\n"
        )
        from grace_control.config.project_config import reset_cache, load_project_config
        reset_cache()
        pc = load_project_config(config_path)
        assert pc.opencode.server_url == "http://yaml:4096"
        assert pc.opencode.server_password == "yamlpw"

    @pytest.mark.asyncio
    async def test_backend_does_not_inject_when_settings_empty(self, tmp_path: Path):
        captured: dict = {}

        class FakeRunService:
            async def run(self, executor, **kw):
                captured["executor"] = executor
                return {"accepted": True, "domain_status": "completed", "exit_code": 0, "stdout": "ok"}

        with (
            patch.object(settings, "opencode_server_url", ""),
            patch.object(settings, "opencode_server_password", ""),
        ):
            from grace_control.agent.universal_cli_backend import UniversalCliAgentBackend
            backend = UniversalCliAgentBackend(FakeRunService())  # type: ignore[arg-type]
            from grace_control.agent.backend import ExecutionRequest
            req = ExecutionRequest(
                packet_id="pkt-noinject", spec={}, worktree_path=tmp_path, branch_name="test",
                executor={"executor_id": "test", "env": {"MY_VAR": "x"}},
            )
            await backend.run(req)

        env = captured["executor"]["env"]
        assert "OPENCODE_SERVER_URL" not in env
        assert "OPENCODE_SERVER_PASSWORD" not in env
        assert env["MY_VAR"] == "x"

    @pytest.mark.asyncio
    async def test_string_extras_kept_as_single_token(self, tmp_path: Path):
        # Defensive: even if `extras` slips through validation as a string,
        # the orchestrator wraps it as a single token rather than crashing.
        captured: dict = {}

        async def fake_run(
            self, command, cwd, env=None, timeout_seconds=600,
            stdin_text=None, **kwargs,
        ):
            captured["command"] = list(command)
            return ProcessResult(stdout="ok", stderr="", exit_code=0, duration_ms=10)

        with patch.dict(os.environ, {"OPENCODE_SERVER_URL": "http://x:1"}, clear=False):
            with patch.object(
                __import__("grace_control.services.process_supervisor", fromlist=["ProcessSupervisor"]).ProcessSupervisor,
                "run", fake_run,
            ):
                service = AgentRunService()
                await service.run(
                    _fake_executor(extras="--attach ${OPENCODE_SERVER_URL}"),
                    packet_id="pkt-test",
                    worktree_path=tmp_path,
                    state_root=tmp_path,
                    packet_markdown="# hello",
                )

        cmd = captured["command"]
        assert "--attach http://x:1" in cmd
