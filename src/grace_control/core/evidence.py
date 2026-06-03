# ############################################################################
# AI_HEADER: evidence
# ROLE: Collect machine-readable evidence from acceptance pipeline stages.
# ############################################################################

# START_MODULE_CONTRACT
# purpose: Collect evidence strings from stage results; check if required evidence is present.
#          check_expected_evidence() is the spec-facing function.
# inputs: expected (list[EvidenceRequirement]), stage_results (list[StageResult]),
#         worktree_path (Path), changed_files (list[str]), profile (AcceptanceProfile).
# returns: list[str] (evidence issue strings).
# side_effects: None.
# emitted_logs: None.
# error_behavior: None.
# END_MODULE_CONTRACT

# START_MODULE_MAP
# mapping:
#   - function: check_expected_evidence
#   - class: EvidenceCollector
# END_MODULE_MAP

from __future__ import annotations

import fnmatch
from pathlib import Path

from grace_control.core.contracts import AcceptanceProfile, StageResult, EvidenceRequirement


def check_expected_evidence(
    expected: list[EvidenceRequirement],
    stage_results: list[StageResult],
    worktree_path: Path,
    changed_files: list[str],
    profile: AcceptanceProfile,
) -> list[str]:
    issues: list[str] = []

    if profile == AcceptanceProfile.FAST:
        return issues

    for req in expected:
        if not req.required:
            continue

        found = _check_evidence_kind(req, stage_results, worktree_path, changed_files)
        if not found:
            issues.append(f"missing required evidence '{req.id}' (kind={req.kind})")

    if profile == AcceptanceProfile.NORMAL and not issues:
        passed_commands_found = any(
            cmd.exit_code == 0
            for stage in stage_results
            for cmd in stage.commands
        )
        if not passed_commands_found and expected:
            issues.append("NORMAL profile requires at least one successful command")

    return issues


def _check_evidence_kind(
    req: EvidenceRequirement,
    stage_results: list[StageResult],
    worktree_path: Path,
    changed_files: list[str],
) -> bool:
    if req.kind == "command":
        for stage in stage_results:
            for cmd in stage.commands:
                if cmd.exit_code != 0:
                    continue
                if req.pattern:
                    if req.pattern in cmd.command:
                        return True
                else:
                    return True
        return False

    if req.kind == "file":
        if not worktree_path or not worktree_path.exists():
            return False
        if req.pattern:
            matches = list(worktree_path.rglob(req.pattern))
            return len(matches) > 0
        return True

    if req.kind == "diff":
        if not changed_files:
            return False
        if req.pattern:
            return any(fnmatch.fnmatch(f, req.pattern) for f in changed_files)
        return True

    if req.kind == "log":
        log_dir = worktree_path / "logs" if worktree_path else Path()
        if not log_dir.exists():
            return False
        if req.pattern:
            return any(req.pattern in f.read_text() for f in log_dir.rglob("*") if f.is_file())
        return any(log_dir.rglob("*"))

    return False


class EvidenceCollector:

    def collect_from_stage(self, stage: StageResult) -> list[str]:
        evidence: list[str] = []
        for cmd in stage.commands:
            evidence.append(f"command:{cmd.command}")
            evidence.append(f"exit_code:{cmd.exit_code}")
        return evidence

    def has_required_evidence(
        self,
        *,
        expected_evidence: list[EvidenceRequirement],
        collected_evidence: list[str],
        acceptance_profile: AcceptanceProfile,
    ) -> bool:
        if acceptance_profile == AcceptanceProfile.FAST:
            return True  # FAST only needs T0

        if not expected_evidence:
            return False

        passed_commands = [e for e in collected_evidence if e.startswith("exit_code:0")]
        return len(passed_commands) >= 1
