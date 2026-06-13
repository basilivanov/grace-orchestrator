"""Tests for reviewer_gate evidence bundle."""
from __future__ import annotations

import json
import tempfile
from pathlib import Path

import pytest

from grace_control.core.reviewer_gate import (
    _build_reviewer_evidence_bundle,
    _render_reviewer_evidence_bundle,
    _serialize_acceptance_report,
    _load_patch_preview,
    _redact_secrets,
    MAX_REVIEWER_PATCH_CHARS,
)


class FakeStageResult:
    def __init__(self, name="T0", status="passed", summary=""):
        self.name = FakeName(name)
        self.status = FakeName(status)
        self.summary = summary


class FakeName:
    def __init__(self, v): self.value = v


class FakeAcceptanceReport:
    def __init__(self, verdict="accepted", stages=None, summary="ok",
                 scope_violations=None):
        self.final_verdict = FakeName(verdict)
        self.stages = stages or []
        self.summary = summary
        self.scope_violations = scope_violations or []


class TestReviewerEvidenceBundle:

    def test_bundle_includes_worktree_and_run_dir(self):
        bundle = _build_reviewer_evidence_bundle(
            worktree_path=Path("/opt/solarsage-astro/.grace/worktrees/pkt-test"),
            run_dir=Path("/opt/solarsage-astro/.grace/state/runs/R01"),
        )
        assert bundle["worktree_path"] == "/opt/solarsage-astro/.grace/worktrees/pkt-test"
        assert bundle["run_dir"] == "/opt/solarsage-astro/.grace/state/runs/R01"

    def test_rendered_includes_paths(self):
        bundle = {
            "worktree_path": "/opt/wt",
            "run_dir": "/opt/run",
        }
        result = _render_reviewer_evidence_bundle(bundle)
        assert "Worktree path: /opt/wt" in result
        assert "Run directory: /opt/run" in result

    def test_bundle_includes_acceptance_report_json(self):
        report = FakeAcceptanceReport(
            verdict="accepted",
            stages=[
                FakeStageResult("T0_SCOPE_AND_LINT", "passed", "scope clean"),
                FakeStageResult("T1_TARGETED_TESTS", "passed", "tests ok"),
            ],
        )
        bundle = _build_reviewer_evidence_bundle(acceptance_report=report)
        ar = bundle["acceptance_report"]
        assert ar["final_verdict"] == "accepted"
        assert len(ar["stages"]) == 2
        assert ar["stages"][0]["name"] == "T0_SCOPE_AND_LINT"

    def test_rendered_includes_compact_json(self):
        report = FakeAcceptanceReport(
            verdict="accepted",
            stages=[FakeStageResult("T0", "passed", "ok")],
        )
        bundle = _build_reviewer_evidence_bundle(acceptance_report=report)
        result = _render_reviewer_evidence_bundle(bundle)
        assert '"final_verdict": "accepted"' in result

    def test_acceptance_serialization_truncates_stage_summaries(self):
        long_summary = "x" * 1000
        report = FakeAcceptanceReport(
            verdict="accepted",
            stages=[FakeStageResult("T0", "passed", long_summary)],
        )
        ar = _serialize_acceptance_report(report)
        assert len(ar["stages"][0]["summary"]) <= 500

    def test_acceptance_serialization_caps_stages(self):
        stages = [FakeStageResult(f"T{i}", "passed") for i in range(30)]
        report = FakeAcceptanceReport(stages=stages)
        ar = _serialize_acceptance_report(report)
        assert len(ar["stages"]) <= 20

    def test_acceptance_serialization_caps_scope_violations(self):
        violations = [f"violation-{i}" for i in range(20)]
        report = FakeAcceptanceReport(scope_violations=violations)
        ar = _serialize_acceptance_report(report)
        assert len(ar["scope_violations"]) <= 10

    def test_patch_preview_found_in_worktree(self):
        with tempfile.TemporaryDirectory() as tmp:
            wt = Path(tmp) / "worktree"
            wt.mkdir()
            (wt / "agent.patch").write_text("diff --git a/file.py b/file.py\n+new line\n")
            text, truncated = _load_patch_preview(worktree_path=wt, run_dir=None)
            assert text is not None
            assert "new line" in text

    def test_patch_preview_truncated(self):
        with tempfile.TemporaryDirectory() as tmp:
            wt = Path(tmp) / "worktree"
            wt.mkdir()
            content = "x" * (MAX_REVIEWER_PATCH_CHARS + 100)
            (wt / "agent.patch").write_text(content)
            text, truncated = _load_patch_preview(worktree_path=wt, run_dir=None)
            assert truncated
            assert len(text) == MAX_REVIEWER_PATCH_CHARS

    def test_bundle_falls_back_to_changed_files_when_no_patch(self):
        bundle = _build_reviewer_evidence_bundle(
            changed_files=["apps/api/app/services/llm/russian.py"],
        )
        assert "changed_files" in bundle
        assert "patch_preview" not in bundle
        assert "apps/api/app/services/llm/russian.py" in str(bundle["changed_files"])

    def test_reviewer_redacts_tokens(self):
        text = "API_KEY=sk-abcdef1234567890 secret here"
        result = _redact_secrets(text)
        assert "sk-abcdef" not in result
        assert "REDACTED" in result

        text2 = "Authorization: Bearer eyJhbGciOiJIUzI1NiJ9.token"
        result2 = _redact_secrets(text2)
        assert "eyJhbGci" not in result2

    def test_evidence_paths_in_bundle(self):
        bundle = _build_reviewer_evidence_bundle(
            artifacts=[
                "/opt/run/t0/cmd_001_stdout.log",
                "/opt/run/t1/cmd_001_stdout.log",
                "/opt/run/acceptance_report.json",
            ],
        )
        assert len(bundle.get("evidence_paths", [])) == 3

    def test_none_acceptance_serializes_none(self):
        ar = _serialize_acceptance_report(None)
        assert ar is None

    def test_no_crash_on_missing_patch(self):
        with tempfile.TemporaryDirectory() as tmp:
            wt = Path(tmp) / "noworktree"
            text, truncated = _load_patch_preview(worktree_path=wt, run_dir=None)
            assert text is None

    def test_bundle_empty_works(self):
        bundle = _build_reviewer_evidence_bundle()
        result = _render_reviewer_evidence_bundle(bundle)
        assert isinstance(result, str)
        assert len(result) >= 0

    def test_rendered_includes_diff_preview(self):
        with tempfile.TemporaryDirectory() as tmp:
            wt = Path(tmp) / "wt"
            wt.mkdir()
            (wt / "agent.patch").write_text("+added line")
            bundle = _build_reviewer_evidence_bundle(worktree_path=wt)
            result = _render_reviewer_evidence_bundle(bundle)
            assert "+added line" in result
            assert "Agent diff preview" in result
            assert "truncated=false" in result


class FakePacket:
    def __init__(self, pid="pkt_test123", title="Test packet"):
        self.packet_id = pid
        self.title = title


class FakeVerdict:
    def __init__(self, v): self.value = v


class FakeEvidenceVerifierReport:
    def __init__(self, verdict="PASS", summary="all evidence found"):
        self.verdict = FakeVerdict(verdict)
        self.summary = summary
        self.failed_checks = []
        self.spec_conflicts = []


@pytest.mark.asyncio
async def test_full_prompt_includes_packet_id_and_evidence_verifier(mocker):
    """The final reviewer prompt must include packet id and evidence verifier summary."""
    from grace_control.core.reviewer_gate import run_reviewer_gate

    # Mock run_llm so we can capture the prompt
    mock_run_llm = mocker.patch("grace_control.core.llm_runner.run_llm", return_value='{"verdict":"PASS"}')
    mock_resolve = mocker.patch(
        "grace_control.core.executor_selector.resolve_model",
        return_value={"model": "deepseek/deepseek-v4-flash"},
    )

    packet = FakePacket()
    acc = FakeAcceptanceReport()
    evr = FakeEvidenceVerifierReport()

    with tempfile.TemporaryDirectory() as tmp:
        wt = Path(tmp) / "worktree"
        wt.mkdir()
        (wt / "agent.patch").write_text("diff --git a/file.py b/file.py\n+new")
        rd = Path(tmp) / "run"
        rd.mkdir(parents=True)
        (rd / "t0").mkdir()

        report = await run_reviewer_gate(
            packet=packet,
            acceptance_report=acc,
            evidence_verifier_report=evr,
            worktree_path=wt,
            run_dir=rd,
            changed_files=["apps/api/app/services/llm/russian.py"],
            artifacts=["path/to/evidence"],
        )

    # The prompt argument is the first positional arg to run_llm
    prompt = mock_run_llm.call_args[0][0]
    assert "pkt_test123" in prompt, "prompt must include packet ID"
    assert "Test packet" in prompt, "prompt must include packet title"
    assert "all evidence found" in prompt or "PASS" in prompt, "prompt must include evidence verifier summary"
    assert "Worktree path:" in prompt or "Run directory:" in prompt, "prompt must include evidence paths"
