from __future__ import annotations

from grace_control.runtime.agent_runtime_contract import (
    AgentRuntimeContract,
    AgentRuntimeFailureCode,
)


class OpenCodeCommandBuilder:

    def build(self, contract: AgentRuntimeContract) -> list[str]:
        if not contract.agent_name:
            raise ValueError(
                f"{AgentRuntimeFailureCode.AGENT_RUNTIME_CONTRACT_INVALID}: agent_name is required"
            )
        if not contract.model:
            raise ValueError(
                f"{AgentRuntimeFailureCode.AGENT_RUNTIME_CONTRACT_INVALID}: model is required"
            )

        cmd = [
            "opencode",
            "run",
            "--dir", contract.worktree_root,
            "--agent", contract.agent_name,
            "--model", contract.model,
            "--format", "json",
        ]
        return cmd
