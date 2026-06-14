from __future__ import annotations

import pytest

from grace_control.runtime.agent_runtime_contract import AgentRuntimeContract
from grace_control.runtime.opencode_attach_command_builder import OpenCodeAttachCommandBuilder


def _contract(agent_name="test-agent", model="deepseek-v4-flash", **overrides) -> AgentRuntimeContract:
    kwargs = dict(
        runtime_run_id="r1", feature_id="feat_w5", packet_id="pkt_w5",
        role="coder", adapter="opencode",
        target_repo_root="/tmp/target", orchestrator_repo_root="/tmp/orch",
        worktree_root="/tmp/worktree", cwd="/tmp/worktree",
        agent_name=agent_name, model=model,
        runtime_artifacts_dir="/tmp/artifacts", timeout_seconds=600,
    )
    kwargs.update(overrides)
    return AgentRuntimeContract(**kwargs)


class TestOpenCodeAttachCommandBuilder:

    def test_has_attach_url(self):
        cmd = OpenCodeAttachCommandBuilder().build(_contract(), "http://127.0.0.1:4096")
        assert "--attach" in cmd
        assert "http://127.0.0.1:4096" in cmd
        assert cmd[cmd.index("--attach") + 1] == "http://127.0.0.1:4096"

    def test_has_dir_agent_model_format(self):
        cmd = OpenCodeAttachCommandBuilder().build(_contract(), "http://127.0.0.1:4096")
        assert cmd[0] == "opencode"
        assert cmd[1] == "run"
        assert "--dir" in cmd
        assert cmd[cmd.index("--dir") + 1] == "/tmp/worktree"
        assert cmd[cmd.index("--agent") + 1] == "test-agent"
        assert cmd[cmd.index("--model") + 1] == "deepseek-v4-flash"
        assert cmd[cmd.index("--format") + 1] == "json"

    def test_does_not_include_serve(self):
        cmd = OpenCodeAttachCommandBuilder().build(_contract(), "http://127.0.0.1:4096")
        assert "serve" not in cmd

    def test_fails_without_model(self):
        with pytest.raises(ValueError):
            OpenCodeAttachCommandBuilder().build(_contract(model=""), "http://127.0.0.1:4096")

    def test_fails_without_agent(self):
        with pytest.raises(ValueError):
            OpenCodeAttachCommandBuilder().build(_contract(agent_name=""), "http://127.0.0.1:4096")

    def test_binary_from_settings(self):
        from grace_control.config.settings import settings as _s
        original = _s.opencode_binary
        try:
            _s.opencode_binary = "my-opencode"
            cmd = OpenCodeAttachCommandBuilder().build(_contract(), "http://127.0.0.1:4096")
            assert cmd[0] == "my-opencode"
        finally:
            _s.opencode_binary = original
