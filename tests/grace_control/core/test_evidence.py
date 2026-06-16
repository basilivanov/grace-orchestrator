"""Tests for evidence collector."""
from pathlib import Path

from grace_control.core.contracts import (
    AcceptanceProfile,
    CommandResult,
    EvidenceRequirement,
    StageName,
    StageResult,
    StageStatus,
)
from grace_control.core.evidence import EvidenceCollector


class TestEvidenceCollector:
    def _collector(self):
        return EvidenceCollector()

    def test_collect_from_passed_stage(self):
        ec = self._collector()
        stage = StageResult(name=StageName.T1_TARGETED_TESTS, status=StageStatus.PASSED,
                           summary="ok",
                           commands=[CommandResult(command="pytest", cwd="/", exit_code=0)])
        evidence = ec.collect_from_stage(stage)
        assert "command:pytest" in evidence
        assert "exit_code:0" in evidence

    def test_collect_from_failed_stage(self):
        ec = self._collector()
        stage = StageResult(name=StageName.T1_TARGETED_TESTS, status=StageStatus.FAILED,
                           summary="fail",
                           commands=[CommandResult(command="pytest", cwd="/", exit_code=1)],
                           blocking_issues=["reason"])
        evidence = ec.collect_from_stage(stage)
        assert "exit_code:1" in evidence

    def test_normal_requires_passed_evidence(self):
        ec = self._collector()
        assert ec.has_required_evidence(
            expected_evidence=[EvidenceRequirement(id="tests", kind="command")],
            collected_evidence=["exit_code:0"],
            acceptance_profile=AcceptanceProfile.NORMAL,
        ) is True

    def test_normal_no_passed_fails(self):
        ec = self._collector()
        assert ec.has_required_evidence(
            expected_evidence=[EvidenceRequirement(id="tests", kind="command")],
            collected_evidence=["exit_code:1"],
            acceptance_profile=AcceptanceProfile.NORMAL,
        ) is False

    def test_fast_always_true(self):
        ec = self._collector()
        assert ec.has_required_evidence(
            expected_evidence=[],
            collected_evidence=[],
            acceptance_profile=AcceptanceProfile.FAST,
        ) is True

    def test_no_expected_evidence_passes_normal_with_passed_commands(self):
        ec = self._collector()
        assert ec.has_required_evidence(
            expected_evidence=[],
            collected_evidence=["exit_code:0"],
            acceptance_profile=AcceptanceProfile.NORMAL,
        ) is True

    def test_failed_command_evidence_does_not_satisfy(self):
        ec = self._collector()
        assert ec.has_required_evidence(
            expected_evidence=[EvidenceRequirement(id="tests", kind="command")],
            collected_evidence=["exit_code:1"],
            acceptance_profile=AcceptanceProfile.NORMAL,
        ) is False


# ══════════════════════════════════════════════════════════════════════
# Typed evidence expectations (check_expected_evidence with expectation)
# ══════════════════════════════════════════════════════════════════════


class TestTypedEvidenceExpectations:
    """TZ: Evidence verifier dispatches by expectation kind."""

    def _make_check(
        self,
        expectation: str,
        file_path: str,
        worktree: Path,
        changed_files: list[str] | None = None,
    ) -> list[str]:
        from grace_control.core.evidence import check_expected_evidence
        req = EvidenceRequirement(
            id="test-ev",
            kind="file",
            artifact_patterns=[file_path],
            expectation=expectation,
        )
        return check_expected_evidence(
            expected=[req],
            stage_results=[],
            worktree_path=worktree,
            changed_files=changed_files or [],
            profile=AcceptanceProfile.STRICT,
        )

    def test_deleted_file_accepted_when_absent(self, tmp_path):
        """expectation=deleted: file absent from disk → passes (no issues)."""
        f = tmp_path / "old.py"
        issues = self._make_check("deleted", "old.py", tmp_path)
        assert issues == []

    def test_deleted_file_rejected_when_still_exists(self, tmp_path):
        """expectation=deleted: file still exists → fails."""
        f = tmp_path / "old.py"
        f.write_text("still here")
        issues = self._make_check("deleted", "old.py", tmp_path)
        assert len(issues) > 0
        assert "old.py" in issues[0] or "test-ev" in issues[0]

    def test_absent_file_accepted_when_missing(self, tmp_path):
        """expectation=absent: file not on disk → passes."""
        issues = self._make_check("absent", "never_existed.py", tmp_path)
        assert issues == []

    def test_absent_file_rejected_when_present(self, tmp_path):
        """expectation=absent: file exists → fails."""
        f = tmp_path / "should_not_exist.py"
        f.write_text("unexpected")
        issues = self._make_check("absent", "should_not_exist.py", tmp_path)
        assert len(issues) > 0

    def test_created_file_accepted_when_exists_and_changed(self, tmp_path):
        """expectation=created: file exists AND in changed_files → passes."""
        f = tmp_path / "new.py"
        f.write_text("new file")
        issues = self._make_check("created", "new.py", tmp_path, changed_files=["new.py"])
        assert issues == []

    def test_created_file_rejected_when_not_in_changed(self, tmp_path):
        """expectation=created: file exists but not in changed_files → fails."""
        f = tmp_path / "existing.py"
        f.write_text("existing")
        issues = self._make_check("created", "existing.py", tmp_path, changed_files=[])
        assert len(issues) > 0

    def test_created_file_rejected_when_missing(self, tmp_path):
        """expectation=created: file does not exist → fails."""
        issues = self._make_check("created", "missing.py", tmp_path, changed_files=["missing.py"])
        assert len(issues) > 0

    def test_diff_contains_passes_when_pattern_in_changed(self, tmp_path):
        """expectation=diff_contains: pattern in changed_files → passes."""
        issues = self._make_check("diff_contains", "src/*.py", tmp_path,
                                  changed_files=["src/new.py"])
        assert issues == []

    def test_diff_contains_fails_when_no_match(self, tmp_path):
        """expectation=diff_contains: pattern not in changed_files → fails."""
        issues = self._make_check("diff_contains", "*.md", tmp_path,
                                  changed_files=["src/new.py"])
        assert len(issues) > 0

    def test_import_absent_passes_when_import_gone(self, tmp_path):
        """expectation=import_absent: old import not found in code → passes."""
        # Create a code dir with no reference to the old import
        (tmp_path / "src").mkdir()
        (tmp_path / "src" / "main.py").write_text("from new_module import foo\n")
        req = EvidenceRequirement(
            id="import-ev",
            kind="file",
            pattern="old_module",
            artifact_patterns=["src/main.py"],
            expectation="import_absent",
        )
        from grace_control.core.evidence import check_expected_evidence
        issues = check_expected_evidence(
            expected=[req],
            stage_results=[],
            worktree_path=tmp_path,
            changed_files=[],
            profile=AcceptanceProfile.STRICT,
        )
        assert issues == []

    def test_import_absent_fails_when_import_still_present(self, tmp_path):
        """expectation=import_absent: old import still in code → fails."""
        (tmp_path / "src").mkdir()
        (tmp_path / "src" / "main.py").write_text("from old_module import bar\n")
        req = EvidenceRequirement(
            id="import-ev",
            kind="file",
            pattern="old_module",
            artifact_patterns=["src/main.py"],
            expectation="import_absent",
        )
        from grace_control.core.evidence import check_expected_evidence
        issues = check_expected_evidence(
            expected=[req],
            stage_results=[],
            worktree_path=tmp_path,
            changed_files=[],
            profile=AcceptanceProfile.STRICT,
        )
        assert len(issues) > 0

    def test_modified_file_accepted_when_exists_and_changed(self, tmp_path):
        """expectation=modified: file exists AND in changed_files → passes."""
        f = tmp_path / "mod.py"
        f.write_text("modified content")
        issues = self._make_check("modified", "mod.py", tmp_path, changed_files=["mod.py"])
        assert issues == []

    def test_exists_default_behavior_unchanged(self, tmp_path):
        """expectation=exists (default): file exists → passes (same as before TZ)."""
        f = tmp_path / "file.py"
        f.write_text("content")
        issues = self._make_check("exists", "file.py", tmp_path)
        assert issues == []

    def test_exists_rejected_when_missing(self, tmp_path):
        """expectation=exists (default): file missing → fails."""
        issues = self._make_check("exists", "missing.py", tmp_path)
        assert len(issues) > 0
