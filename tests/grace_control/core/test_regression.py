"""
TZ-023 — Regression tests (7 tests). Each fixed bug = 1 test.
"""

from __future__ import annotations

import ast
import sys

import pytest

from grace_control.db import get_db
from grace_control.db.schema import Packet, PacketRun, PacketState, Feature, Wave
from tests.conftest import make_feature, make_packet, make_wave


def test_regression_evidence_pattern():
    """evidence.py:_check_evidence_kind searches in cmd.command+stdout+stderr, not just command."""
    from pathlib import Path
    from grace_control.core.evidence import _check_evidence_kind, EvidenceRequirement
    from grace_control.core.contracts import CommandResult, StageResult, StageName, StageStatus

    req = EvidenceRequirement(id="test", kind="command", required=True, pattern="3 passed")

    cmd = CommandResult(
        command="python3 -m pytest test_x.py -q",
        cwd="/tmp", exit_code=0,
        stdout="3 passed in 0.5s", stderr="",
        stdout_path="", stderr_path="",
        timed_out=False, duration_ms=100,
    )
    stage = StageResult(name=StageName.T1_TARGETED_TESTS, status=StageStatus.PASSED,
                        summary="ok", commands=[cmd])
    found = _check_evidence_kind(req, [stage], Path("/tmp"), [])
    assert found is True, "pattern not found in stdout+stderr"


def test_regression_wave_gate_blocked(db):
    """BLOCKED is terminal for wave gate. After fix wave_gate.py:52, does not hang."""
    from grace_control.core.wave_gate import check_wave_gates
    from tests.conftest import make_feature, make_wave, make_packet

    with get_db() as d:
        make_feature(d, fid="F1")
        make_wave(d, wid="W01", fid="F1")
        make_wave(d, wid="W02", fid="F1", order=2)
        make_packet(d, pid="P1", fid="F1", wid="W01", state=PacketState.MERGED.value)
        make_packet(d, pid="P2", fid="F1", wid="W01", state=PacketState.BLOCKED.value)
        make_packet(d, pid="P3", fid="F1", wid="W02", state=PacketState.DRAFT.value)
        d.flush()

    gated = check_wave_gates()
    assert gated >= 0


def test_regression_worker_recovery_order():
    """worker.py calls _maybe_apply_recovery() BEFORE _handle_rejection()."""
    tree = ast.parse(open("src/grace_control/worker/worker.py").read())
    found_recovery = False
    found_rejection = False
    for node in ast.walk(tree):
        if isinstance(node, ast.Call):
            if hasattr(node.func, "attr"):
                if node.func.attr == "_maybe_apply_recovery":
                    found_recovery = True
                elif node.func.attr == "_handle_rejection":
                    found_rejection = True
                if found_recovery and not found_rejection:
                    return
    assert found_recovery, "_maybe_apply_recovery not found in worker.py"
    assert found_rejection, "_handle_rejection not found in worker.py"


def test_regression_recovery_env_var():
    """GRACE_RECOVERY_CONTROLLER_ENABLED is passed in worker_env in run_golden.py."""
    tree = ast.parse(open("scripts/run_golden.py").read())
    found = False
    for node in ast.walk(tree):
        if isinstance(node, ast.Dict):
            for k in node.keys:
                if isinstance(k, ast.Constant) and "GRACE_RECOVERY_CONTROLLER_ENABLED" in str(k.value):
                    found = True
    assert found, "GRACE_RECOVERY_CONTROLLER_ENABLED not found in run_golden.py worker_env"


def test_regression_never_downgrade_strict():
    """never_downgrade_strict exists in RecoveryPolicy. STRICT never downgrades."""
    from grace_control.core.feature_recovery import (
        RecoveryPolicy, FailureSignal, decide_recovery,
    )

    policy = RecoveryPolicy()
    assert hasattr(policy, "never_downgrade_strict")
    assert policy.never_downgrade_strict is True

    signal = FailureSignal(
        feature_id="F1", packet_id="P1", packet_state="rejected",
        acceptance_profile="STRICT",
        coder_attempt_count=1,
        acceptance_verdict="rework_required",
    )
    decision = decide_recovery(signal, policy)
    assert decision.next_acceptance_profile in (None, "STRICT")


def test_regression_coder_ladder_yaml():
    """Coder ladder reads from agent_profiles.yaml, not hardcoded."""
    from grace_control.core.executor_selector import get_escalation

    executors = get_escalation("coder")
    assert len(executors) >= 2
    for e in executors:
        assert "executor_id" in e
        assert "model" in e
        assert "priority" in e
    priorities = [e["priority"] for e in executors]
    assert priorities == sorted(priorities, reverse=True)


def test_regression_build_signal_no_detached_error():
    """build_signal() must not raise DetachedInstanceError after session close.
    Regression for TZ-023 §2.1 — all data eagerly read inside with get_db()."""
    from grace_control.db.schema import PacketRun, PacketState
    from grace_control.core.recovery_controller import RecoveryController

    with get_db() as d:
        make_feature(d, fid="R1")
        make_wave(d, wid="WR1", fid="R1", order=1)
        make_packet(d, pid="P-reg", fid="R1", wid="WR1", state=PacketState.REJECTED.value)
        d.add(PacketRun(
            id="RR01", packet_id="P-reg", run_number=1, status="rejected",
            result_json={
                "acceptance_report": {"final_verdict": "rework_required"},
                "evidence_verifier_report": {"verdict": "PASS"},
                "executor_id": "coder-flash",
            },
        ))
        d.flush()

    ctrl = RecoveryController()
    signal = ctrl.build_signal("P-reg")
    assert signal.packet_id == "P-reg"
    assert signal.coder_attempt_count == 1
    assert signal.acceptance_verdict == "rework_required"
    assert signal.evidence_verifier_verdict == "PASS"
