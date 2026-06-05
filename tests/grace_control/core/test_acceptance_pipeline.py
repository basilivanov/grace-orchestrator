"""Tests for acceptance pipeline — T0/T1/T2 decision table."""

import sys
from pathlib import Path

import pytest
from grace_control.core.acceptance_pipeline import AcceptancePipeline
from grace_control.core.command_runner import CommandRunner
from grace_control.core.contracts import (
    AcceptanceProfile, AcceptanceReport, CommandResult, ExecutionPacketContract,
    FinalVerdict, PacketVerdict, ScopeViolation, EvidenceRequirement,
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
        verification={"t1": t1_cmds, "t2": t2_cmds},
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
        self.calls: list[str] = []
        self.call_cwds: list[Path | None] = []

    def run(self, command, *, cwd=None, timeout_s=None, output_dir=None):
        cmd_str = " ".join(command) if isinstance(command, list) else command
        self.calls.append(cmd_str)
        self.call_cwds.append(cwd)
        key = cmd_str
        if key in self._results:
            return self._results[key]
        return CommandResult(command=cmd_str, cwd=str(cwd or Path.cwd()), exit_code=0)


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
        assert r.final_verdict == FinalVerdict.ACCEPTED

    def test_t0_fails_out_of_scope(self):
        scope = FakeScope(violations=[ScopeViolation(path="apps/bad.tsx", reason="r", violation_type="out_of_scope")])
        p = _make_packet(profile=AcceptanceProfile.STRICT)
        r = _pipeline(packet=p, scope=scope).run(packet=p)
        assert r.final_verdict == FinalVerdict.REWORK_REQUIRED
        assert len(r.scope_violations) == 1

    def test_t0_fails_frozen_scope(self):
        scope = FakeScope(violations=[ScopeViolation(path="legacy/x.py", reason="r", violation_type="frozen_scope")])
        p = _make_packet(profile=AcceptanceProfile.STRICT)
        r = _pipeline(packet=p, scope=scope).run(packet=p)
        assert r.final_verdict == FinalVerdict.REWORK_REQUIRED

    def test_t0_fails_invalid_packet(self):
        p = ExecutionPacketContract(packet_id="", title="", allowed_write_scope=[], frozen_scope=[],
                                     acceptance_profile=AcceptanceProfile.NORMAL, verification={"t1": [["cmd"]]})
        r = _pipeline(packet=p).run(packet=p)
        assert r.final_verdict == FinalVerdict.REWORK_REQUIRED

    def test_t0_blocks_t1(self):
        scope = FakeScope(violations=[ScopeViolation(path="x", reason="r", violation_type="out_of_scope")])
        runner = FakeRunner()
        p = _make_packet(profile=AcceptanceProfile.STRICT)
        r = _pipeline(packet=p, scope=scope, runner=runner).run(packet=p)
        t1_called = any("python" in c for c in runner.calls)
        assert not t1_called or r.final_verdict == FinalVerdict.REWORK_REQUIRED

    def test_explicit_empty_t0_skips_default_commands_scope_clean(self):
        """Explicit t0: [] with clean scope → skip default py_compile, T0 passes."""
        runner = FakeRunner()
        p = ExecutionPacketContract(
            packet_id="p1", title="Test",
            allowed_write_scope=["sandbox/golden/"], frozen_scope=[],
            acceptance_profile=AcceptanceProfile.NORMAL,
            verification={"t0": [], "t1": [["echo", "ok"]]})
        r = _pipeline(packet=p, runner=runner).run(packet=p, changed_files=["sandbox/date_util.py"])
        assert r.final_verdict == FinalVerdict.ACCEPTED
        t0_called = any("py_compile" in c for c in runner.calls)
        assert not t0_called

    def test_explicit_empty_t0_scope_guard_still_runs(self):
        """Explicit t0: [] with out-of-scope change on STRICT profile → scope guard fails."""
        runner = FakeRunner()
        scope = FakeScope(violations=[ScopeViolation(path="src/core.py", reason="r", violation_type="out_of_scope")])
        p = ExecutionPacketContract(
            packet_id="p1", title="Test",
            allowed_write_scope=["sandbox/golden/"], frozen_scope=["legacy/"],
            acceptance_profile=AcceptanceProfile.STRICT,
            verification={"t0": [], "t1": [["echo", "ok"]]})
        r = _pipeline(packet=p, runner=runner, scope=scope).run(packet=p, changed_files=["src/core.py"])
        assert r.final_verdict == FinalVerdict.REWORK_REQUIRED
        assert r.scope_violations


class TestFAST:
    def test_fast_t0_passed_no_commands_accepted(self):
        r = _pipeline(packet=_make_packet(profile=AcceptanceProfile.FAST, t1=[])).run(packet=_make_packet(profile=AcceptanceProfile.FAST, t1=[]))
        assert r.final_verdict == FinalVerdict.ACCEPTED

    def test_fast_with_commands_passed(self):
        p = _make_packet(profile=AcceptanceProfile.FAST, t1=[["echo", "ok"]])
        runner = FakeRunner({"echo ok": CommandResult(command="echo ok", cwd="/", exit_code=0)})
        r = _pipeline(packet=p, runner=runner).run(packet=p)
        assert r.final_verdict == FinalVerdict.ACCEPTED

    def test_fast_with_commands_failed(self):
        p = _make_packet(profile=AcceptanceProfile.FAST, t1=[["false"]])
        runner = FakeRunner({"false": CommandResult(command="false", cwd="/", exit_code=1)})
        r = _pipeline(packet=p, runner=runner).run(packet=p)
        assert r.final_verdict == FinalVerdict.REWORK_REQUIRED

    def test_fast_skips_t2(self):
        r = _pipeline(packet=_make_packet(profile=AcceptanceProfile.FAST, t1=[])).run(packet=_make_packet(profile=AcceptanceProfile.FAST, t1=[]))
        assert r.final_verdict == FinalVerdict.ACCEPTED


class TestNORMAL:
    def test_normal_without_commands_blocked(self):
        r = _pipeline(packet=_make_packet(profile=AcceptanceProfile.NORMAL, t1=[])).run(packet=_make_packet(profile=AcceptanceProfile.NORMAL, t1=[]))
        assert r.final_verdict != FinalVerdict.ACCEPTED

    def test_normal_t1_failed_rework(self):
        p = _make_packet(profile=AcceptanceProfile.NORMAL, t1=[["false"]])
        runner = FakeRunner({"false": CommandResult(command="false", cwd="/", exit_code=1)})
        r = _pipeline(packet=p, runner=runner).run(packet=p)
        assert r.final_verdict == FinalVerdict.REWORK_REQUIRED

    def test_normal_t1_passed_no_t2_accepted(self):
        p = _make_packet(profile=AcceptanceProfile.NORMAL, t1=[["echo", "ok"]])
        runner = FakeRunner({"echo ok": CommandResult(command="echo ok", cwd="/", exit_code=0)})
        r = _pipeline(packet=p, runner=runner, evidence=FakeEvidence(has=True)).run(packet=p)
        assert r.final_verdict == FinalVerdict.ACCEPTED

    def test_normal_t2_failed_rework(self):
        p = _make_packet(profile=AcceptanceProfile.NORMAL, t1=[["echo", "ok"]], t2=[["false"]])
        runner = FakeRunner({"echo ok": CommandResult(command="echo ok", cwd="/", exit_code=0), "false": CommandResult(command="false", cwd="/", exit_code=1)})
        r = _pipeline(packet=p, runner=runner, evidence=FakeEvidence(has=True)).run(packet=p)
        assert r.final_verdict == FinalVerdict.REWORK_REQUIRED

    def test_normal_all_passed_accepted(self):
        p = _make_packet(profile=AcceptanceProfile.NORMAL, t1=[["echo", "ok"]], t2=[["echo", "full"]])
        runner = FakeRunner({"echo ok": CommandResult(command="echo ok", cwd="/", exit_code=0), "echo full": CommandResult(command="echo full", cwd="/", exit_code=0)})
        r = _pipeline(packet=p, runner=runner, evidence=FakeEvidence(has=True)).run(packet=p)
        assert r.final_verdict == FinalVerdict.ACCEPTED


class TestSTRICT:
    def test_strict_without_commands_blocked(self):
        r = _pipeline(packet=_make_packet(profile=AcceptanceProfile.STRICT, t1=[])).run(packet=_make_packet(profile=AcceptanceProfile.STRICT, t1=[]))
        assert r.final_verdict != FinalVerdict.ACCEPTED

    def test_strict_without_t2_blocked(self):
        p = _make_packet(profile=AcceptanceProfile.STRICT, t1=[["echo", "ok"]])
        runner = FakeRunner({"echo ok": CommandResult(command="echo ok", cwd="/", exit_code=0)})
        r = _pipeline(packet=p, runner=runner).run(packet=p)
        assert r.final_verdict != FinalVerdict.ACCEPTED

    def test_strict_t1_failed_rework(self):
        p = _make_packet(profile=AcceptanceProfile.STRICT, t1=[["false"]], t2=[["echo"]])
        runner = FakeRunner({"false": CommandResult(command="false", cwd="/", exit_code=1)})
        r = _pipeline(packet=p, runner=runner).run(packet=p)
        assert r.final_verdict == FinalVerdict.REWORK_REQUIRED

    def test_strict_t2_failed_rework(self):
        p = _make_packet(profile=AcceptanceProfile.STRICT, t1=[["echo", "ok"]], t2=[["false"]])
        runner = FakeRunner({"echo ok": CommandResult(command="echo ok", cwd="/", exit_code=0), "false": CommandResult(command="false", cwd="/", exit_code=1)})
        r = _pipeline(packet=p, runner=runner, evidence=FakeEvidence(has=True)).run(packet=p)
        assert r.final_verdict == FinalVerdict.REWORK_REQUIRED

    def test_strict_all_passed_accepted(self):
        p = _make_packet(profile=AcceptanceProfile.STRICT, t1=[["echo", "ok"]], t2=[["echo", "full"]])
        runner = FakeRunner({"echo ok": CommandResult(command="echo ok", cwd="/", exit_code=0), "echo full": CommandResult(command="echo full", cwd="/", exit_code=0)})
        r = _pipeline(packet=p, runner=runner, evidence=FakeEvidence(has=True)).run(packet=p)
        assert r.final_verdict == FinalVerdict.ACCEPTED


class TestReport:
    def test_accepted_has_no_violations(self):
        r = _pipeline(packet=_make_packet()).run(packet=_make_packet())
        assert r.scope_violations == []

    def test_accepted_has_t0_passed(self):
        r = _pipeline(packet=_make_packet()).run(packet=_make_packet())
        t0s = [s for s in r.stages if s.name.value == "T0_SCOPE_AND_LINT"]
        assert len(t0s) >= 1

    def test_non_accepted_has_summary(self):
        scope = FakeScope(violations=[ScopeViolation(path="x", reason="r", violation_type="out_of_scope")])
        p = _make_packet(profile=AcceptanceProfile.STRICT)
        r = _pipeline(packet=p, scope=scope).run(packet=p)
        assert r.final_verdict != FinalVerdict.ACCEPTED
        assert r.summary

    def test_to_dict_serializes(self):
        r = _pipeline(packet=_make_packet()).run(packet=_make_packet())
        d = r.to_dict()
        assert d["packet_id"] == "p1"

    def test_missing_evidence_blocks_strict(self):
        p = _make_packet(profile=AcceptanceProfile.STRICT, t1=[["echo", "ok"]], t2=[["echo", "full"]], expected_evidence=[EvidenceRequirement(id="missing-test", kind="command", required=True, pattern="nonexistent")])
        runner = FakeRunner({"echo ok": CommandResult(command="echo ok", cwd="/", exit_code=0), "echo full": CommandResult(command="echo full", cwd="/", exit_code=0)})
        r = _pipeline(packet=p, runner=runner).run(packet=p)
        assert r.final_verdict == FinalVerdict.BLOCKED

    def test_legacy_ok_false_blocks_accept(self):
        """legacy_result.ok=False is recorded on the report. T0/T1/T2 are authoritative
        (see acceptance_pipeline.run() — legacy_result is informational). The
        deterministic gates passed → ACCEPTED; legacy is surfaced for observability."""
        p = _make_packet(profile=AcceptanceProfile.FAST, t1=[])
        r = _pipeline(packet=p).run(packet=p, legacy_result={"ok": False, "domain_status": "runner_error"})
        assert r.legacy_ok is False
        assert r.legacy_domain_status == "runner_error"
        assert r.final_verdict == FinalVerdict.ACCEPTED

    def test_legacy_domain_status_rejected_blocks_accept(self):
        """legacy_result.domain_status=rejected is recorded. T0/T1/T2 are authoritative."""
        p = _make_packet(profile=AcceptanceProfile.FAST, t1=[])
        r = _pipeline(packet=p).run(packet=p, legacy_result={"ok": True, "domain_status": "rejected"})
        assert r.legacy_ok is True
        assert r.legacy_domain_status == "rejected"
        assert r.final_verdict == FinalVerdict.ACCEPTED

    def test_legacy_ok_true_domain_accepted_allowed(self):
        """legacy_result.ok=True and domain_status=accepted → can reach ACCEPTED if gates pass."""
        p = _make_packet(profile=AcceptanceProfile.FAST, t1=[])
        r = _pipeline(packet=p).run(packet=p, legacy_result={"ok": True, "domain_status": "accepted"})
        assert r.final_verdict == FinalVerdict.ACCEPTED
        assert r.legacy_domain_status == "accepted"
        assert r.legacy_ok is True

    def test_t1_command_cwd_is_worktree(self):
        """T1 command receives cwd=worktree_root (passed through run())."""
        runner = FakeRunner()
        p = _make_packet(profile=AcceptanceProfile.NORMAL, t1=[["echo", "ok"]])
        _pipeline(packet=p, runner=runner).run(packet=p, changed_files=["src/main.py"],
                                                worktree_path="/tmp/test-wt")
        assert len(runner.call_cwds) >= 1
        # T1 commands get cwd from worktree_root
        t1_cwds = [c for c in runner.call_cwds if c is not None]
        assert any(str(c) == "/tmp/test-wt" for c in t1_cwds)

    def test_t2_command_cwd_is_worktree(self):
        """T2 command receives cwd=worktree_root."""
        runner = FakeRunner()
        p = _make_packet(profile=AcceptanceProfile.STRICT, t1=[["echo", "ok"]], t2=[["echo", "full"]])
        _pipeline(packet=p, runner=runner).run(packet=p, changed_files=["src/main.py"],
                                                worktree_path="/tmp/test-wt2")
        assert len(runner.call_cwds) >= 2
        t2_cwds = [str(c) for c in runner.call_cwds if c is not None]
        assert "/tmp/test-wt2" in t2_cwds

    def test_fast_runs_t1_when_configured(self):
        """FAST profile still runs T1 commands if verification.t1 is set."""
        runner = FakeRunner()
        p = _make_packet(profile=AcceptanceProfile.FAST, t1=[["echo", "fast-t1"]])
        r = _pipeline(packet=p, runner=runner).run(packet=p, changed_files=["src/main.py"])
        assert r.final_verdict == FinalVerdict.ACCEPTED
        t1_called = any("fast-t1" in c for c in runner.calls)
        assert t1_called
