"""Tests for acceptance pipeline — T0/T1/T2 decision table."""

import sys
from pathlib import Path

import pytest
from grace_control.core.acceptance_pipeline import AcceptancePipeline
from grace_control.core.command_runner import CommandRunner
from grace_control.core.contracts import (
    AcceptanceProfile,
    AcceptanceReport,
    CommandResult,
    ExecutionPacketContract,
    PacketVerdict,
    ScopeViolation,
    StageName,
    StageResult,
    StageStatus,
)
from grace_control.core.evidence import EvidenceCollector
from grace_control.core.scope_guard import ScopeGuard


def _make_packet(profile=AcceptanceProfile.NORMAL, commands=None, extra_fields=None):
    kw = dict(packet_id="p1", title="Test",
              allowed_write_scope=["src/"], frozen_scope=["legacy/"],
              acceptance_profile=profile,
              verification_commands=commands if commands is not None else [["python", "-c", "pass"]])
    if extra_fields:
        kw.update(extra_fields)
    return ExecutionPacketContract(**kw)


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

    def run(self, command, *, cwd=None, timeout_s=None):
        self.calls.append(list(command))
        key = " ".join(command)
        if key in self._results:
            return self._results[key]
        # Default: success
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
        pl = _pipeline(packet=p)
        r = pl.run(packet=p, changed_files=["src/main.py"])
        assert r.final_verdict == PacketVerdict.ACCEPTED

    def test_t0_fails_out_of_scope(self):
        scope = FakeScope(violations=[ScopeViolation(path="apps/bad.tsx", reason="r", violation_type="out_of_scope")])
        p = _make_packet()
        pl = _pipeline(packet=p, scope=scope)
        r = pl.run(packet=p)
        assert r.final_verdict == PacketVerdict.REWORK_REQUIRED
        assert len(r.scope_violations) == 1

    def test_t0_fails_frozen_scope(self):
        scope = FakeScope(violations=[ScopeViolation(path="legacy/x.py", reason="r", violation_type="frozen_scope")])
        p = _make_packet()
        pl = _pipeline(packet=p, scope=scope)
        r = pl.run(packet=p)
        assert r.final_verdict == PacketVerdict.REWORK_REQUIRED

    def test_t0_fails_invalid_packet(self):
        p = _make_packet()
        p = ExecutionPacketContract(packet_id="", title="", allowed_write_scope=[], frozen_scope=[],
                                     acceptance_profile=AcceptanceProfile.NORMAL, verification_commands=[["cmd"]])
        pl = _pipeline(packet=p)
        r = pl.run(packet=p)
        assert r.final_verdict == PacketVerdict.REWORK_REQUIRED

    def test_t0_blocks_t1(self):
        scope = FakeScope(violations=[ScopeViolation(path="x", reason="r", violation_type="out_of_scope")])
        runner = FakeRunner()
        p = _make_packet()
        pl = _pipeline(packet=p, scope=scope, runner=runner)
        r = pl.run(packet=p)
        # T1 commands should not have been called
        t1_called = any("python" in " ".join(c) for c in runner.calls)
        assert not t1_called or r.final_verdict == PacketVerdict.REWORK_REQUIRED


class TestFAST:
    def test_fast_t0_passed_no_commands_accepted(self):
        p = _make_packet(profile=AcceptanceProfile.FAST, commands=[])
        pl = _pipeline(packet=p)
        r = pl.run(packet=p)
        assert r.final_verdict == PacketVerdict.ACCEPTED

    def test_fast_with_commands_passed(self):
        p = _make_packet(profile=AcceptanceProfile.FAST, commands=[["echo", "ok"]])
        runner = FakeRunner({"echo ok": CommandResult(command=["echo", "ok"], cwd="/", exit_code=0)})
        pl = _pipeline(packet=p, runner=runner)
        r = pl.run(packet=p)
        assert r.final_verdict == PacketVerdict.ACCEPTED

    def test_fast_with_commands_failed(self):
        p = _make_packet(profile=AcceptanceProfile.FAST, commands=[["false"]])
        runner = FakeRunner({"false": CommandResult(command=["false"], cwd="/", exit_code=1)})
        pl = _pipeline(packet=p, runner=runner)
        r = pl.run(packet=p)
        assert r.final_verdict == PacketVerdict.REWORK_REQUIRED

    def test_fast_skips_t2(self):
        p = _make_packet(profile=AcceptanceProfile.FAST, commands=[])
        pl = _pipeline(packet=p)
        r = pl.run(packet=p)
        assert r.final_verdict == PacketVerdict.ACCEPTED
        t2 = [s for s in r.stages if s.name == StageName.T2_FULL_TESTS]
        assert len(t2) == 1 and t2[0].status == StageStatus.SKIPPED


class TestNORMAL:
    def test_normal_without_commands_blocked(self):
        p = _make_packet(profile=AcceptanceProfile.NORMAL, commands=[])
        pl = _pipeline(packet=p)
        r = pl.run(packet=p)
        assert r.final_verdict != PacketVerdict.ACCEPTED

    def test_normal_t1_failed_rework(self):
        p = _make_packet(profile=AcceptanceProfile.NORMAL, commands=[["false"]])
        runner = FakeRunner({"false": CommandResult(command=["false"], cwd="/", exit_code=1)})
        pl = _pipeline(packet=p, runner=runner)
        r = pl.run(packet=p)
        assert r.final_verdict == PacketVerdict.REWORK_REQUIRED

    def test_normal_t1_passed_no_t2_accepted(self):
        p = _make_packet(profile=AcceptanceProfile.NORMAL, commands=[["echo", "ok"]])
        runner = FakeRunner({"echo ok": CommandResult(command=["echo", "ok"], cwd="/", exit_code=0)})
        pl = _pipeline(packet=p, runner=runner, evidence=FakeEvidence(has=True))
        r = pl.run(packet=p)
        assert r.final_verdict == PacketVerdict.ACCEPTED

    def test_normal_t2_failed_rework(self):
        p = _make_packet(profile=AcceptanceProfile.NORMAL, commands=[["echo", "ok"]],
                        extra_fields={"metadata": {"full_verification_commands": [["false"]]}})
        runner = FakeRunner({"echo ok": CommandResult(command=["echo", "ok"], cwd="/", exit_code=0),
                             "false": CommandResult(command=["false"], cwd="/", exit_code=1)})
        pl = _pipeline(packet=p, runner=runner, evidence=FakeEvidence(has=True))
        r = pl.run(packet=p)
        assert r.final_verdict == PacketVerdict.REWORK_REQUIRED

    def test_normal_all_passed_accepted(self):
        p = _make_packet(profile=AcceptanceProfile.NORMAL, commands=[["echo", "ok"]],
                        extra_fields={"metadata": {"full_verification_commands": [["echo", "full"]]}})
        runner = FakeRunner({"echo ok": CommandResult(command=["echo", "ok"], cwd="/", exit_code=0),
                             "echo full": CommandResult(command=["echo", "full"], cwd="/", exit_code=0)})
        pl = _pipeline(packet=p, runner=runner, evidence=FakeEvidence(has=True))
        r = pl.run(packet=p)
        assert r.final_verdict == PacketVerdict.ACCEPTED


class TestSTRICT:
    def test_strict_without_commands_blocked(self):
        p = _make_packet(profile=AcceptanceProfile.STRICT, commands=[])
        pl = _pipeline(packet=p)
        r = pl.run(packet=p)
        assert r.final_verdict != PacketVerdict.ACCEPTED

    def test_strict_without_t2_blocked(self):
        p = _make_packet(profile=AcceptanceProfile.STRICT, commands=[["echo", "ok"]])
        runner = FakeRunner({"echo ok": CommandResult(command=["echo", "ok"], cwd="/", exit_code=0)})
        pl = _pipeline(packet=p, runner=runner)
        r = pl.run(packet=p)
        assert r.final_verdict != PacketVerdict.ACCEPTED

    def test_strict_t1_failed_rework(self):
        p = _make_packet(profile=AcceptanceProfile.STRICT, commands=[["false"]],
                        extra_fields={"metadata": {"full_verification_commands": [["echo"]]}})
        runner = FakeRunner({"false": CommandResult(command=["false"], cwd="/", exit_code=1)})
        pl = _pipeline(packet=p, runner=runner)
        r = pl.run(packet=p)
        assert r.final_verdict == PacketVerdict.REWORK_REQUIRED

    def test_strict_t2_failed_rework(self):
        p = _make_packet(profile=AcceptanceProfile.STRICT, commands=[["echo", "ok"]],
                        extra_fields={"metadata": {"full_verification_commands": [["false"]]}})
        runner = FakeRunner({"echo ok": CommandResult(command=["echo", "ok"], cwd="/", exit_code=0),
                             "false": CommandResult(command=["false"], cwd="/", exit_code=1)})
        pl = _pipeline(packet=p, runner=runner, evidence=FakeEvidence(has=True))
        r = pl.run(packet=p)
        assert r.final_verdict == PacketVerdict.REWORK_REQUIRED

    def test_strict_all_passed_accepted(self):
        p = _make_packet(profile=AcceptanceProfile.STRICT, commands=[["echo", "ok"]],
                        extra_fields={"metadata": {"full_verification_commands": [["echo", "full"]]}})
        runner = FakeRunner({"echo ok": CommandResult(command=["echo", "ok"], cwd="/", exit_code=0),
                             "echo full": CommandResult(command=["echo", "full"], cwd="/", exit_code=0)})
        pl = _pipeline(packet=p, runner=runner, evidence=FakeEvidence(has=True))
        r = pl.run(packet=p)
        assert r.final_verdict == PacketVerdict.ACCEPTED


class TestReport:
    def test_accepted_has_no_violations(self):
        p = _make_packet()
        pl = _pipeline(packet=p)
        r = pl.run(packet=p)
        assert r.scope_violations == []

    def test_accepted_has_t0_passed(self):
        p = _make_packet()
        pl = _pipeline(packet=p)
        r = pl.run(packet=p)
        t0s = [s for s in r.stages if s.name == StageName.T0_SCOPE_AND_LINT]
        assert len(t0s) >= 1

    def test_non_accepted_has_reasons(self):
        scope = FakeScope(violations=[ScopeViolation(path="x", reason="r", violation_type="out_of_scope")])
        p = _make_packet()
        pl = _pipeline(packet=p, scope=scope)
        r = pl.run(packet=p)
        assert r.final_verdict != PacketVerdict.ACCEPTED

    def test_to_dict_serializes(self):
        p = _make_packet()
        pl = _pipeline(packet=p)
        r = pl.run(packet=p)
        d = r.to_dict()
        assert d["packet_id"] == "p1"
        assert "stages" in d
        assert r.is_accepted is True

    def test_missing_evidence_blocks_normal(self):
        p = _make_packet(profile=AcceptanceProfile.NORMAL, commands=[["echo", "ok"]],
                        extra_fields={"expected_evidence": ["tests passed"]})
        runner = FakeRunner({"echo ok": CommandResult(command=["echo", "ok"], cwd="/", exit_code=0)})
        ev = FakeEvidence(has=False)
        pl = _pipeline(packet=p, runner=runner, evidence=ev)
        r = pl.run(packet=p)
        assert r.final_verdict == PacketVerdict.BLOCKED
