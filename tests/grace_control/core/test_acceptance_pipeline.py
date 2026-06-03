"""Tests for acceptance pipeline — T0/T1/T2 decision table."""

import sys
from pathlib import Path

import pytest
from grace_control.core.acceptance_pipeline import AcceptancePipeline
from grace_control.core.command_runner import CommandRunner
from grace_control.core.contracts import (
    AcceptanceProfile, AcceptanceReport, CommandResult, ExecutionPacketContract,
    PacketVerdict, ScopeViolation, VerificationSpec,
)
from grace_control.core.evidence import EvidenceCollector
from grace_control.core.scope_guard import ScopeGuard


def _make_packet(profile=AcceptanceProfile.NORMAL, t1=None, t2=None, **kw):
    t1_cmds = t1 if t1 is not None else [["python", "-c", "pass"]]
    t2_cmds = t2 or []
    return ExecutionPacketContract(
        packet_id="p1", title="Test",
        allowed_write_scope=["src/"], frozen_scope=["legacy/"],
        acceptance_profile=profile,
        verification=VerificationSpec(t1=t1_cmds, t2=t2_cmds),
        **kw,
    )


class FakeScope:
    def __init__(self, violations=None, changed=None):
        self._violations = violations or []
        self._changed = changed or ["src/main.py"]

    def get_changed_files(self, base_ref=None, head_ref=None):
        return self._changed

    def validate_changed_files(self, *, changed_files, allowed_write_scope, frozen_scope):
        return self._violations


class FakeRunner:
    def __init__(self, results=None):
        self._results = results or {}
        self.calls: list[list[str]] = []

    def run(self, command, *, cwd=None, timeout_s=None, output_dir=None):
        self.calls.append(list(command))
        key = " ".join(command)
        if key in self._results:
            return self._results[key]
        return CommandResult(command=list(command), cwd=str(cwd or Path.cwd()), exit_code=0)


class FakeEvidence:
    def __init__(self, has=True):
        self._has = has

    def collect_from_stage(self, stage):
        return [f"evidence:{stage.name.value}"]

    def has_required_evidence(self, *, expected_evidence, collected_evidence, acceptance_profile):
        return self._has


def _pipeline(*, packet=None, scope=None, runner=None, evidence=None):
    return AcceptancePipeline(
        repo_root=Path.cwd(),
        command_runner=runner or FakeRunner(),
        scope_guard=scope or FakeScope(violations=[]),
        evidence_collector=evidence or FakeEvidence(has=True),
    )


class TestT0:
    def test_t0_passes_clean(self):
        p = _make_packet()
        r = _pipeline(packet=p).run(packet=p, changed_files=["src/main.py"])
        assert r.final_verdict == PacketVerdict.ACCEPTED

    def test_t0_fails_out_of_scope(self):
        scope = FakeScope(violations=[ScopeViolation(path="apps/bad.tsx", reason="r", violation_type="out_of_scope")])
        r = _pipeline(packet=_make_packet(), scope=scope).run(packet=_make_packet())
        assert r.final_verdict == PacketVerdict.REWORK_REQUIRED
        assert len(r.scope_violations) == 1

    def test_t0_fails_frozen_scope(self):
        scope = FakeScope(violations=[ScopeViolation(path="legacy/x.py", reason="r", violation_type="frozen_scope")])
        r = _pipeline(packet=_make_packet(), scope=scope).run(packet=_make_packet())
        assert r.final_verdict == PacketVerdict.REWORK_REQUIRED

    def test_t0_fails_invalid_packet(self):
        p = ExecutionPacketContract(packet_id="", title="", allowed_write_scope=[], frozen_scope=[],
                                     acceptance_profile=AcceptanceProfile.NORMAL, verification=VerificationSpec(t1=[["cmd"]]))
        r = _pipeline(packet=p).run(packet=p)
        assert r.final_verdict == PacketVerdict.REWORK_REQUIRED

    def test_t0_blocks_t1(self):
        scope = FakeScope(violations=[ScopeViolation(path="x", reason="r", violation_type="out_of_scope")])
        runner = FakeRunner()
        r = _pipeline(packet=_make_packet(), scope=scope, runner=runner).run(packet=_make_packet())
        t1_called = any("python" in " ".join(c) for c in runner.calls)
        assert not t1_called or r.final_verdict == PacketVerdict.REWORK_REQUIRED


class TestFAST:
    def test_fast_t0_passed_no_commands_accepted(self):
        r = _pipeline(packet=_make_packet(profile=AcceptanceProfile.FAST, t1=[])).run(packet=_make_packet(profile=AcceptanceProfile.FAST, t1=[]))
        assert r.final_verdict == PacketVerdict.ACCEPTED

    def test_fast_with_commands_passed(self):
        p = _make_packet(profile=AcceptanceProfile.FAST, t1=[["echo", "ok"]])
        runner = FakeRunner({"echo ok": CommandResult(command=["echo", "ok"], cwd="/", exit_code=0)})
        r = _pipeline(packet=p, runner=runner).run(packet=p)
        assert r.final_verdict == PacketVerdict.ACCEPTED

    def test_fast_with_commands_failed(self):
        p = _make_packet(profile=AcceptanceProfile.FAST, t1=[["false"]])
        runner = FakeRunner({"false": CommandResult(command=["false"], cwd="/", exit_code=1)})
        r = _pipeline(packet=p, runner=runner).run(packet=p)
        assert r.final_verdict == PacketVerdict.REWORK_REQUIRED

    def test_fast_skips_t2(self):
        r = _pipeline(packet=_make_packet(profile=AcceptanceProfile.FAST, t1=[])).run(packet=_make_packet(profile=AcceptanceProfile.FAST, t1=[]))
        assert r.final_verdict == PacketVerdict.ACCEPTED


class TestNORMAL:
    def test_normal_without_commands_blocked(self):
        r = _pipeline(packet=_make_packet(profile=AcceptanceProfile.NORMAL, t1=[])).run(packet=_make_packet(profile=AcceptanceProfile.NORMAL, t1=[]))
        assert r.final_verdict != PacketVerdict.ACCEPTED

    def test_normal_t1_failed_rework(self):
        p = _make_packet(profile=AcceptanceProfile.NORMAL, t1=[["false"]])
        runner = FakeRunner({"false": CommandResult(command=["false"], cwd="/", exit_code=1)})
        r = _pipeline(packet=p, runner=runner).run(packet=p)
        assert r.final_verdict == PacketVerdict.REWORK_REQUIRED

    def test_normal_t1_passed_no_t2_accepted(self):
        p = _make_packet(profile=AcceptanceProfile.NORMAL, t1=[["echo", "ok"]])
        runner = FakeRunner({"echo ok": CommandResult(command=["echo", "ok"], cwd="/", exit_code=0)})
        r = _pipeline(packet=p, runner=runner, evidence=FakeEvidence(has=True)).run(packet=p)
        assert r.final_verdict == PacketVerdict.ACCEPTED

    def test_normal_t2_failed_rework(self):
        p = _make_packet(profile=AcceptanceProfile.NORMAL, t1=[["echo", "ok"]], t2=[["false"]])
        runner = FakeRunner({"echo ok": CommandResult(command=["echo", "ok"], cwd="/", exit_code=0), "false": CommandResult(command=["false"], cwd="/", exit_code=1)})
        r = _pipeline(packet=p, runner=runner, evidence=FakeEvidence(has=True)).run(packet=p)
        assert r.final_verdict == PacketVerdict.REWORK_REQUIRED

    def test_normal_all_passed_accepted(self):
        p = _make_packet(profile=AcceptanceProfile.NORMAL, t1=[["echo", "ok"]], t2=[["echo", "full"]])
        runner = FakeRunner({"echo ok": CommandResult(command=["echo", "ok"], cwd="/", exit_code=0), "echo full": CommandResult(command=["echo", "full"], cwd="/", exit_code=0)})
        r = _pipeline(packet=p, runner=runner, evidence=FakeEvidence(has=True)).run(packet=p)
        assert r.final_verdict == PacketVerdict.ACCEPTED


class TestSTRICT:
    def test_strict_without_commands_blocked(self):
        r = _pipeline(packet=_make_packet(profile=AcceptanceProfile.STRICT, t1=[])).run(packet=_make_packet(profile=AcceptanceProfile.STRICT, t1=[]))
        assert r.final_verdict != PacketVerdict.ACCEPTED

    def test_strict_without_t2_blocked(self):
        p = _make_packet(profile=AcceptanceProfile.STRICT, t1=[["echo", "ok"]])
        runner = FakeRunner({"echo ok": CommandResult(command=["echo", "ok"], cwd="/", exit_code=0)})
        r = _pipeline(packet=p, runner=runner).run(packet=p)
        assert r.final_verdict != PacketVerdict.ACCEPTED

    def test_strict_t1_failed_rework(self):
        p = _make_packet(profile=AcceptanceProfile.STRICT, t1=[["false"]], t2=[["echo"]])
        runner = FakeRunner({"false": CommandResult(command=["false"], cwd="/", exit_code=1)})
        r = _pipeline(packet=p, runner=runner).run(packet=p)
        assert r.final_verdict == PacketVerdict.REWORK_REQUIRED

    def test_strict_t2_failed_rework(self):
        p = _make_packet(profile=AcceptanceProfile.STRICT, t1=[["echo", "ok"]], t2=[["false"]])
        runner = FakeRunner({"echo ok": CommandResult(command=["echo", "ok"], cwd="/", exit_code=0), "false": CommandResult(command=["false"], cwd="/", exit_code=1)})
        r = _pipeline(packet=p, runner=runner, evidence=FakeEvidence(has=True)).run(packet=p)
        assert r.final_verdict == PacketVerdict.REWORK_REQUIRED

    def test_strict_all_passed_accepted(self):
        p = _make_packet(profile=AcceptanceProfile.STRICT, t1=[["echo", "ok"]], t2=[["echo", "full"]])
        runner = FakeRunner({"echo ok": CommandResult(command=["echo", "ok"], cwd="/", exit_code=0), "echo full": CommandResult(command=["echo", "full"], cwd="/", exit_code=0)})
        r = _pipeline(packet=p, runner=runner, evidence=FakeEvidence(has=True)).run(packet=p)
        assert r.final_verdict == PacketVerdict.ACCEPTED


class TestReport:
    def test_accepted_has_no_violations(self):
        r = _pipeline(packet=_make_packet()).run(packet=_make_packet())
        assert r.scope_violations == []

    def test_accepted_has_t0_passed(self):
        r = _pipeline(packet=_make_packet()).run(packet=_make_packet())
        t0s = [s for s in r.stages if s.name.value == "T0_SCOPE_AND_LINT"]
        assert len(t0s) >= 1

    def test_non_accepted_has_reasons(self):
        scope = FakeScope(violations=[ScopeViolation(path="x", reason="r", violation_type="out_of_scope")])
        r = _pipeline(packet=_make_packet(), scope=scope).run(packet=_make_packet())
        assert r.final_verdict != PacketVerdict.ACCEPTED

    def test_to_dict_serializes(self):
        r = _pipeline(packet=_make_packet()).run(packet=_make_packet())
        d = r.to_dict()
        assert d["packet_id"] == "p1"

    def test_missing_evidence_blocks_normal(self):
        p = _make_packet(profile=AcceptanceProfile.NORMAL, t1=[["echo", "ok"]], expected_evidence=["tests passed"])
        runner = FakeRunner({"echo ok": CommandResult(command=["echo", "ok"], cwd="/", exit_code=0)})
        r = _pipeline(packet=p, runner=runner, evidence=FakeEvidence(has=False)).run(packet=p)
        assert r.final_verdict == PacketVerdict.BLOCKED
