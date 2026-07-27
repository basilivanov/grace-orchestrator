"""Tests for evidence verifier parser and helpers."""

from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest
from grace_control.core.contracts import (
    AcceptanceProfile,
    AcceptanceReport,
    CommandResult,
    EvidenceRequirement,
    ExecutionPacketContract,
    FinalVerdict,
    StageName,
    StageResult,
    StageStatus,
)
from grace_control.core.evidence_verifier import (
    EvidenceVerifierReport,
    EvidenceVerifierVerdict,
    parse_evidence_verifier_json,
    run_evidence_verifier,
    skipped_evidence_report,
)


class TestParseEvidenceVerifier:
    def test_valid_pass_json(self):
        raw = '{"verdict": "PASS", "summary": "all good", "missing_evidence": [], "failed_checks": []}'
        r = parse_evidence_verifier_json(raw)
        assert r.verdict == EvidenceVerifierVerdict.PASS
        assert r.summary == "all good"
        assert r.skipped is False

    def test_valid_rework_json(self):
        raw = '{"verdict": "REWORK_TO_CODER", "summary": "bad impl", "coder_instructions": ["fix tests"]}'
        r = parse_evidence_verifier_json(raw)
        assert r.verdict == EvidenceVerifierVerdict.REWORK_TO_CODER
        assert "fix tests" in r.coder_instructions

    def test_valid_return_to_architect_json(self):
        raw = '{"verdict": "RETURN_TO_ARCHITECT", "summary": "bad spec", "spec_conflicts": ["scope too narrow"]}'
        r = parse_evidence_verifier_json(raw)
        assert r.verdict == EvidenceVerifierVerdict.RETURN_TO_ARCHITECT
        assert "scope too narrow" in r.spec_conflicts

    def test_invalid_json(self):
        raw = "not json at all"
        r = parse_evidence_verifier_json(raw)
        assert r.verdict == EvidenceVerifierVerdict.REWORK_TO_CODER
        assert r.failed_checks

    def test_unknown_verdict(self):
        raw = '{"verdict": "INVALID", "summary": "test"}'
        r = parse_evidence_verifier_json(raw)
        assert r.verdict == EvidenceVerifierVerdict.REWORK_TO_CODER
        assert "unrecognized" in str(r).lower() or "unknown" in r.summary

    def test_skipped_report(self):
        r = skipped_evidence_report("deterministic acceptance failed")
        assert r.skipped is True
        assert r.verdict == EvidenceVerifierVerdict.REWORK_TO_CODER
        assert "deterministic" in r.reason


class TestEvidenceArtifactInventory:
    @pytest.mark.asyncio
    async def test_legacy_diff_stdout_alias_uses_controller_changed_files(
        self,
        tmp_path: Path,
    ):
        worktree = tmp_path / "worktree"
        run_dir = tmp_path / "run"
        worktree.mkdir()
        run_dir.mkdir()
        packet = ExecutionPacketContract(
            packet_id="pkt-legacy-diff-alias",
            title="Legacy diff alias",
            allowed_write_scope=["src/router.js"],
            frozen_scope=[],
            acceptance_profile=AcceptanceProfile.STRICT,
            verification={"t0": ["git diff -- src/router.js"], "t1": [], "t2": []},
            expected_evidence=[
                EvidenceRequirement(
                    id="EV-DIFF",
                    kind="diff",
                    producer="agent",
                    artifact_patterns=["t0_stdout"],
                )
            ],
        )
        acceptance_report = AcceptanceReport(
            packet_id=packet.packet_id,
            final_verdict=FinalVerdict.ACCEPTED,
            profile=AcceptanceProfile.STRICT,
            stages=[],
            summary="all deterministic gates passed",
        )

        with patch(
            "grace_control.core.llm_runner.run_llm",
            new=AsyncMock(return_value='{"verdict":"PASS","summary":"diff captured"}'),
        ) as run_llm:
            verifier = getattr(run_evidence_verifier, "__wrapped__")
            report = await verifier(
                packet=packet,
                acceptance_report=acceptance_report,
                worktree_path=worktree,
                run_dir=run_dir,
                changed_files=["src/router.js"],
                artifacts=[],
            )

        assert report.verdict == EvidenceVerifierVerdict.PASS
        run_llm.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_unsupported_evidence_kind_returns_to_architect_without_llm(
        self,
        tmp_path: Path,
    ):
        worktree = tmp_path / "worktree"
        run_dir = tmp_path / "run"
        worktree.mkdir()
        run_dir.mkdir()
        packet = ExecutionPacketContract(
            packet_id="pkt-invalid-evidence",
            title="Invalid evidence contract",
            allowed_write_scope=["src/ui/app.js"],
            frozen_scope=[],
            acceptance_profile=AcceptanceProfile.STRICT,
            expected_evidence=[
                EvidenceRequirement(
                    id="EV-VISUAL",
                    kind="visual",
                    producer="manual",
                    artifact_patterns=["dashboard visual description"],
                )
            ],
        )
        acceptance_report = AcceptanceReport(
            packet_id=packet.packet_id,
            final_verdict=FinalVerdict.BLOCKED,
            profile=AcceptanceProfile.STRICT,
            stages=[],
            evidence_issues=["missing required evidence 'EV-VISUAL' (kind=visual)"],
            summary="missing evidence",
        )

        with patch(
            "grace_control.core.llm_runner.run_llm",
            new=AsyncMock(return_value='{"verdict":"REWORK_TO_CODER"}'),
        ) as run_llm:
            verifier = getattr(run_evidence_verifier, "__wrapped__")
            report = await verifier(
                packet=packet,
                acceptance_report=acceptance_report,
                worktree_path=worktree,
                run_dir=run_dir,
                changed_files=["src/ui/app.js"],
                artifacts=[],
            )

        assert report.verdict == EvidenceVerifierVerdict.RETURN_TO_ARCHITECT
        assert report.suggested_next_owner == "architect"
        run_llm.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_passed_command_stdout_satisfies_legacy_output_label(
        self,
        tmp_path: Path,
    ):
        worktree = tmp_path / "worktree"
        run_dir = tmp_path / "run"
        stdout_path = run_dir / "t1" / "cmd_001_stdout.log"
        worktree.mkdir()
        stdout_path.parent.mkdir(parents=True)
        stdout_path.write_text("17 tests passed")
        packet = ExecutionPacketContract(
            packet_id="pkt-command-output",
            title="Command output evidence",
            allowed_write_scope=["src"],
            frozen_scope=[],
            acceptance_profile=AcceptanceProfile.STRICT,
            verification={"t0": [], "t1": ["npm test"], "t2": []},
            expected_evidence=[
                EvidenceRequirement(
                    id="EV-TEST",
                    kind="test",
                    stage="packet_local",
                    owner="coder",
                    producer="cli",
                    artifact_patterns=["npm test output"],
                )
            ],
        )
        acceptance_report = AcceptanceReport(
            packet_id=packet.packet_id,
            final_verdict=FinalVerdict.ACCEPTED,
            profile=AcceptanceProfile.STRICT,
            stages=[
                StageResult(
                    name=StageName.T1_TARGETED_TESTS,
                    status=StageStatus.PASSED,
                    summary="passed",
                    commands=[
                        CommandResult(
                            command="npm test",
                            cwd=str(worktree),
                            exit_code=0,
                            stdout_path=str(stdout_path),
                        )
                    ],
                )
            ],
            summary="all deterministic gates passed",
        )

        with patch(
            "grace_control.core.llm_runner.run_llm",
            new=AsyncMock(return_value='{"verdict":"PASS","summary":"evidence complete"}'),
        ) as run_llm:
            verifier = getattr(run_evidence_verifier, "__wrapped__")
            report = await verifier(
                packet=packet,
                acceptance_report=acceptance_report,
                worktree_path=worktree,
                run_dir=run_dir,
                changed_files=[],
                artifacts=[],
            )

        assert report.verdict == EvidenceVerifierVerdict.PASS
        run_llm.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_passed_command_stdout_satisfies_legacy_run_label(
        self,
        tmp_path: Path,
    ):
        worktree = tmp_path / "worktree"
        run_dir = tmp_path / "run"
        stdout_path = run_dir / "t1" / "cmd_001_stdout.log"
        worktree.mkdir()
        stdout_path.parent.mkdir(parents=True)
        stdout_path.write_text("tests passed")
        packet = ExecutionPacketContract(
            packet_id="pkt-run-label",
            title="Run-label evidence",
            allowed_write_scope=["src"],
            frozen_scope=[],
            acceptance_profile=AcceptanceProfile.STRICT,
            verification={"t0": [], "t1": ["npm test"], "t2": []},
            expected_evidence=[
                EvidenceRequirement(
                    id="EV-TEST",
                    kind="test",
                    producer="cli",
                    artifact_patterns=["run: npm test"],
                )
            ],
        )
        acceptance_report = AcceptanceReport(
            packet_id=packet.packet_id,
            final_verdict=FinalVerdict.ACCEPTED,
            profile=AcceptanceProfile.STRICT,
            stages=[
                StageResult(
                    name=StageName.T1_TARGETED_TESTS,
                    status=StageStatus.PASSED,
                    summary="passed",
                    commands=[
                        CommandResult(
                            command="npm test",
                            cwd=str(worktree),
                            exit_code=0,
                            stdout_path=str(stdout_path),
                        )
                    ],
                )
            ],
            summary="all deterministic gates passed",
        )

        with patch(
            "grace_control.core.llm_runner.run_llm",
            new=AsyncMock(return_value='{"verdict":"PASS","summary":"evidence complete"}'),
        ) as run_llm:
            verifier = getattr(run_evidence_verifier, "__wrapped__")
            report = await verifier(
                packet=packet,
                acceptance_report=acceptance_report,
                worktree_path=worktree,
                run_dir=run_dir,
                changed_files=[],
                artifacts=[],
            )

        assert report.verdict == EvidenceVerifierVerdict.PASS
        run_llm.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_passed_command_stdout_satisfies_legacy_bare_command_label(
        self,
        tmp_path: Path,
    ):
        worktree = tmp_path / "worktree"
        run_dir = tmp_path / "run"
        stdout_path = run_dir / "t1" / "cmd_001_stdout.log"
        worktree.mkdir()
        stdout_path.parent.mkdir(parents=True)
        stdout_path.write_text("check passed")
        packet = ExecutionPacketContract(
            packet_id="pkt-bare-command-label",
            title="Bare-command evidence",
            allowed_write_scope=["src"],
            frozen_scope=[],
            acceptance_profile=AcceptanceProfile.STRICT,
            verification={"t0": [], "t1": ["npm run check"], "t2": []},
            expected_evidence=[
                EvidenceRequirement(
                    id="EV-CHECK",
                    kind="test",
                    producer="cli",
                    artifact_patterns=["npm run check"],
                )
            ],
        )
        acceptance_report = AcceptanceReport(
            packet_id=packet.packet_id,
            final_verdict=FinalVerdict.ACCEPTED,
            profile=AcceptanceProfile.STRICT,
            stages=[
                StageResult(
                    name=StageName.T1_TARGETED_TESTS,
                    status=StageStatus.PASSED,
                    summary="passed",
                    commands=[
                        CommandResult(
                            command="npm run check",
                            cwd=str(worktree),
                            exit_code=0,
                            stdout_path=str(stdout_path),
                        )
                    ],
                )
            ],
            summary="all deterministic gates passed",
        )

        with patch(
            "grace_control.core.llm_runner.run_llm",
            new=AsyncMock(return_value='{"verdict":"PASS","summary":"evidence complete"}'),
        ) as run_llm:
            verifier = getattr(run_evidence_verifier, "__wrapped__")
            report = await verifier(
                packet=packet,
                acceptance_report=acceptance_report,
                worktree_path=worktree,
                run_dir=run_dir,
                changed_files=[],
                artifacts=[],
            )

        assert report.verdict == EvidenceVerifierVerdict.PASS
        run_llm.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_worktree_evidence_satisfies_patterns_without_controller_artifacts(
        self,
        tmp_path: Path,
    ):
        worktree = tmp_path / "worktree"
        run_dir = tmp_path / "run"
        (worktree / "docs" / "controller-packets").mkdir(parents=True)
        (worktree / "verification-output").mkdir()
        run_dir.mkdir()
        (worktree / "AGENTS.md").write_text("rules")
        (worktree / "docs" / "requirements.xml").write_text("<requirements/>")
        (worktree / "docs" / "controller-packets" / ".gitkeep").write_text("")
        (worktree / "verification-output" / "W00-P01-verification.log").write_text("ok")

        packet = ExecutionPacketContract(
            packet_id="pkt-evidence",
            title="Worktree evidence",
            allowed_write_scope=["AGENTS.md", "docs", "verification-output"],
            frozen_scope=[],
            acceptance_profile=AcceptanceProfile.STRICT,
            verification={"t0": [], "t1": ["true"], "t2": []},
            expected_evidence=[
                EvidenceRequirement(
                    id="EV-CONTRACT",
                    kind="contract",
                    stage="packet_local",
                    owner="coder",
                    producer="agent",
                    artifact_patterns=[
                        "AGENTS.md",
                        "docs/*.xml",
                        "docs/controller-packets/.gitkeep",
                    ],
                ),
                EvidenceRequirement(
                    id="EV-LOG",
                    kind="test",
                    stage="packet_local",
                    owner="coder",
                    producer="cli",
                    artifact_patterns=["verification-output/W00-P01*.log"],
                ),
            ],
        )
        acceptance_report = AcceptanceReport(
            packet_id=packet.packet_id,
            final_verdict=FinalVerdict.ACCEPTED,
            profile=AcceptanceProfile.STRICT,
            stages=[
                StageResult(
                    name=StageName.T0_SCOPE_AND_LINT,
                    status=StageStatus.PASSED,
                    summary="passed",
                )
            ],
            summary="all deterministic gates passed",
        )

        with patch(
            "grace_control.core.llm_runner.run_llm",
            new=AsyncMock(return_value='{"verdict":"PASS","summary":"evidence complete"}'),
        ) as run_llm:
            verifier = getattr(run_evidence_verifier, "__wrapped__")
            report = await verifier(
                packet=packet,
                acceptance_report=acceptance_report,
                worktree_path=worktree,
                run_dir=run_dir,
                changed_files=[],
                artifacts=[],
            )

        assert report.verdict == EvidenceVerifierVerdict.PASS
        run_llm.assert_awaited_once()
