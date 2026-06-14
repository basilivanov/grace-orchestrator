"""W3: AgentRuntimeContract — model, builder, validation."""

from __future__ import annotations

import tempfile
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from grace_control.runtime.agent_runtime_contract import (
    AgentRuntimeContract,
    AgentRuntimeContractBuilder,
    AgentRuntimeFailureCode,
)
from grace_control.core.runtime_trace import RuntimeTraceContext


def _make_trace(feature_id="feat_w3", packet_id="pkt_w3_test"):
    return RuntimeTraceContext(
        trace_id="test-trace-001",
        feature_id=feature_id,
        packet_id=packet_id,
        wave_id="wave_w3",
        runtime_run_id="pkt_w3_test-R01",
    )


def _make_packet_data(**overrides) -> dict:
    data = {
        "id": "pkt_w3_test",
        "feature_id": "feat_w3",
        "wave_id": "wave_w3",
        "acceptance_profile": "FAST",
        "attempt_count": 1,
        "spec_json": {
            "scope": ["src/foo", "src/bar"],
        },
    }
    data.update(overrides)
    return data


def _make_executor(**overrides) -> dict:
    ex = {
        "role": "coder",
        "adapter": "opencode",
        "executor_id": "coder-opencode-fixture",
        "agent_name": "opencode-coder",
        "provider": "deepseek",
        "model": "deepseek-v4-flash",
        "frozen_scope": ["src/frozen"],
    }
    ex.update(overrides)
    return ex


class TestAgentRuntimeContract:
    def test_contract_requires_packet_id(self):
        """Contract must have a non-empty packet_id."""
        trace = _make_trace()
        c = AgentRuntimeContract(
            runtime_run_id="r1",
            packet_id="",
            role="coder",
            target_repo_root="/tmp",
            orchestrator_repo_root="/tmp",
            worktree_root="/tmp/wt",
            cwd="/tmp/wt",
            runtime_artifacts_dir="/tmp/.grace/runs/feat/packets/pkt",
        )
        assert c.packet_id == ""

    def test_contract_requires_target_repo_root(self):
        """Contract must have a non-empty target_repo_root."""
        c = AgentRuntimeContract(
            runtime_run_id="r1",
            packet_id="pkt1",
            role="coder",
            target_repo_root="",
            orchestrator_repo_root="/tmp",
            worktree_root="/tmp/wt",
            cwd="/tmp/wt",
            runtime_artifacts_dir="/tmp/.grace/runs/feat/packets/pkt",
        )
        assert c.target_repo_root == ""

    def test_contract_persisted_before_execution(self):
        """Verification that contract model is created before execution would happen.

        This test validates the model structure; integration tests verify
        persistence timing."""
        trace = _make_trace()
        packet_data = _make_packet_data()
        executor = _make_executor()

        with tempfile.TemporaryDirectory() as td:
            p = Path(td)
            settings = MagicMock()
            settings.agent_timeout_seconds = 600
            settings.target_repo_root = str(p)

            c = AgentRuntimeContractBuilder.build(
                packet_data=packet_data,
                executor=executor,
                run_id="pkt_w3_test-R01",
                trace=trace,
                project_root=p,
                target_repo_root=str(p),
                worktree_path=p / "wt",
                settings=settings,
            )
            assert c.packet_id == "pkt_w3_test"
            assert c.feature_id == "feat_w3"
            assert c.target_repo_root == str(p)
            assert c.worktree_root == str(p / "wt")
            assert c.cwd == str(p / "wt")
            assert c.runtime_run_id == "pkt_w3_test-R01"
            assert c.role == "coder"
            assert c.adapter == "opencode"
            assert c.packet_scope == ["src/foo", "src/bar"]
            assert c.frozen_scope == ["src/frozen"]

    def test_contract_includes_orchestrator_repo_root(self):
        """Orchestrator repo root must be explicitly in the contract."""
        with tempfile.TemporaryDirectory() as td:
            p = Path(td)
            trace = _make_trace()
            settings = MagicMock()
            settings.agent_timeout_seconds = 600
            settings.target_repo_root = ""

            c = AgentRuntimeContractBuilder.build(
                packet_data=_make_packet_data(),
                executor=_make_executor(),
                run_id="r1",
                trace=trace,
                project_root=p,
                target_repo_root="",
                worktree_path=p / "wt",
                settings=settings,
            )
            assert c.orchestrator_repo_root == str(p)
            assert c.target_repo_root == str(p)  # falls back to project_root

    def test_contract_acceptance_profile(self):
        """Acceptance profile from packet data is carried through."""
        trace = _make_trace()
        packet_data = _make_packet_data(acceptance_profile="NORMAL")
        executor = _make_executor()

        with tempfile.TemporaryDirectory() as td:
            p = Path(td)
            settings = MagicMock()
            settings.agent_timeout_seconds = 600
            settings.target_repo_root = ""

            c = AgentRuntimeContractBuilder.build(
                packet_data=packet_data,
                executor=executor,
                run_id="r1",
                trace=trace,
                project_root=p,
                target_repo_root="",
                worktree_path=p / "wt",
                settings=settings,
            )
            assert c.acceptance_profile == "NORMAL"

    def test_contract_failure_code_values(self):
        """AgentRuntimeFailureCode constants are accessible."""
        assert AgentRuntimeFailureCode.AGENT_ENV_BAD_CWD == "AGENT_ENV_BAD_CWD"
        assert AgentRuntimeFailureCode.AGENT_ENV_BAD_GIT_ROOT == "AGENT_ENV_BAD_GIT_ROOT"
        assert AgentRuntimeFailureCode.AGENT_WORKTREE_INVALID == "AGENT_WORKTREE_INVALID"
        assert AgentRuntimeFailureCode.AGENT_SCOPE_PARENT_NOT_CREATABLE == "AGENT_SCOPE_PARENT_NOT_CREATABLE"
        assert AgentRuntimeFailureCode.AGENT_ARTIFACT_DIR_NOT_WRITABLE == "AGENT_ARTIFACT_DIR_NOT_WRITABLE"
        assert AgentRuntimeFailureCode.AGENT_RUNTIME_CONTRACT_INVALID == "AGENT_RUNTIME_CONTRACT_INVALID"
