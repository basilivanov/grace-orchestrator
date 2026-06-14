from __future__ import annotations

import tempfile
from pathlib import Path

import pytest

from grace_control.runtime.agent_runtime_contract import AgentRuntimeFailureCode
from grace_control.runtime.runtime_diagnostics import (
    RuntimeDiagnosticsBuilder,
    RuntimeDiagnostics,
    build_read_model,
    RuntimeFailureReadModel,
)
from grace_control.runtime.runtime_scope_enforcer import RuntimeScopeEnforcer
from grace_control.runtime.runtime_diff_inspector import (
    RuntimeDiffInspector,
    RuntimeDiffInspectionResult,
    RuntimeDiffInspectionRequest,
)
from grace_control.core.runtime_trace import RuntimeTraceContext, generate_trace_id
from grace_control.core.runtime_artifacts import RuntimeArtifactStore
from grace_control.core.runtime_redaction import RuntimeRedactor


class TestDiagnosticsBuilder:

    def test_builds_diagnostics(self):
        diag = RuntimeDiagnosticsBuilder.build(
            runtime_run_id="r1",
            packet_id="pkt_w6",
            trace_id="trace_001",
            adapter="opencode",
            runtime_mode="direct",
            accepted=True,
            failure_code=None,
            duration_ms=1234,
            changed_files=["src/foo.py"],
            stdout_tail="output",
            stderr_tail="",
        )
        assert diag.packet_id == "pkt_w6"
        assert diag.accepted is True
        assert diag.changed_files == ["src/foo.py"]
        assert diag.stdout_tail == "output"

    def test_builds_diagnostics_with_failure(self):
        diag = RuntimeDiagnosticsBuilder.build(
            accepted=False,
            failure_code=AgentRuntimeFailureCode.AGENT_CHANGED_OUT_OF_SCOPE,
            failure_stage="scope_enforcement",
            out_of_scope_files=["outside/x.py"],
            changed_files=["outside/x.py"],
        )
        assert not diag.accepted
        assert diag.failure_code == AgentRuntimeFailureCode.AGENT_CHANGED_OUT_OF_SCOPE
        assert diag.out_of_scope_files == ["outside/x.py"]

    def test_persists_artifacts(self):
        with tempfile.TemporaryDirectory() as td:
            from grace_control.config.settings import settings as _s
            _s.runtime_artifacts_root = str(Path(td) / ".grace" / "runs")

            trace = RuntimeTraceContext(
                trace_id=generate_trace_id(),
                feature_id="feat_w6", packet_id="pkt_w6", wave_id="wave_w6",
                runtime_run_id="r1",
            )
            store = RuntimeArtifactStore()
            redactor = RuntimeRedactor()

            diag = RuntimeDiagnosticsBuilder.build(packet_id="pkt_w6", changed_files=["src/a.py"])
            scope = RuntimeScopeEnforcer.enforce(
                changed_files=["src/a.py"],
                allowed_scope=["src"], frozen_scope=[],
            )
            diff = RuntimeDiffInspectionResult(ok=True, changed_files=["src/a.py"], summary="ok")

            refs = RuntimeDiagnosticsBuilder.persist(diag, scope, diff, trace, "pkt_w6", store, redactor)
            names = {r.kind for r in refs}
            expected = {"runtime_diagnostics", "scope_enforcement", "diff_inspection", "changed_files"}
            missing = expected - names
            assert not missing, f"missing artifacts: {missing}"


class TestReadModel:

    def test_build_read_model_out_of_scope(self):
        diag = RuntimeDiagnosticsBuilder.build(
            accepted=False,
            failure_code=AgentRuntimeFailureCode.AGENT_CHANGED_OUT_OF_SCOPE,
            changed_files=["outside/x.py"],
            out_of_scope_files=["outside/x.py"],
        )
        model = build_read_model("pkt_w6", diagnostics=diag)
        assert model.packet_id == "pkt_w6"
        assert model.status == "failed"
        assert model.failure_code == AgentRuntimeFailureCode.AGENT_CHANGED_OUT_OF_SCOPE
        assert "outside" in model.title.lower()

    def test_build_read_model_success(self):
        model = build_read_model("pkt_w6")
        assert model.status == "unknown"
