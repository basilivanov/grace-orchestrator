from __future__ import annotations

import pytest

from grace_control.runtime.agent_runtime_contract import (
    AgentRuntimeContract,
    AgentRuntimeFailureCode,
)
from grace_control.runtime.opencode_command_builder import OpenCodeCommandBuilder


def _contract(agent_name="test-agent", model="deepseek-v4-flash", **overrides) -> AgentRuntimeContract:
    kwargs = dict(
        runtime_run_id="r1",
        feature_id="feat_w4",
        packet_id="pkt_w4",
        role="coder",
        adapter="opencode",
        target_repo_root="/tmp/target",
        orchestrator_repo_root="/tmp/orch",
        worktree_root="/tmp/worktree",
        cwd="/tmp/worktree",
        agent_name=agent_name,
        model=model,
        runtime_artifacts_dir="/tmp/artifacts",
        timeout_seconds=600,
    )
    kwargs.update(overrides)
    return AgentRuntimeContract(**kwargs)


class TestOpenCodeCommandBuilder:

    def test_includes_dir_agent_model_json(self):
        contract = _contract()
        cmd = OpenCodeCommandBuilder().build(contract)
        assert cmd[0] == "opencode"
        assert cmd[1] == "run"
        assert "--dir" in cmd
        assert "--agent" in cmd
        assert "--model" in cmd
        assert "--format" in cmd
        assert cmd[cmd.index("--dir") + 1] == "/tmp/worktree"
        assert cmd[cmd.index("--agent") + 1] == "test-agent"
        assert cmd[cmd.index("--model") + 1] == "deepseek-v4-flash"
        assert cmd[cmd.index("--format") + 1] == "json"

    def test_does_not_include_attach_in_w4(self):
        contract = _contract()
        cmd = OpenCodeCommandBuilder().build(contract)
        assert "--attach" not in cmd
        assert "serve" not in cmd

    def test_fails_without_model(self):
        contract = _contract(model="")
        with pytest.raises(ValueError) as exc:
            OpenCodeCommandBuilder().build(contract)
        assert AgentRuntimeFailureCode.AGENT_RUNTIME_CONTRACT_INVALID in str(exc.value)

    def test_fails_without_agent(self):
        contract = _contract(agent_name="")
        with pytest.raises(ValueError) as exc:
            OpenCodeCommandBuilder().build(contract)
        assert AgentRuntimeFailureCode.AGENT_RUNTIME_CONTRACT_INVALID in str(exc.value)
