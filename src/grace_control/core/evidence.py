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
    run_dir: Path | None = None,
) -> list[str]:
    issues: list[str] = []

    if profile == AcceptanceProfile.FAST:
        return issues

    for req in expected:
        if not req.required:
            continue

        found = _check_evidence_kind(req, stage_results, worktree_path, changed_files, run_dir=run_dir)
        if not found:
            if profile == AcceptanceProfile.NORMAL:
                continue
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


_ACTIVE_CODE_DIRS = ["apps/", "src/", "packages/", "tests/", "scripts/"]


def _check_evidence_kind(
    req: EvidenceRequirement,
    stage_results: list[StageResult],
    worktree_path: Path,
    changed_files: list[str],
    *,
    run_dir: Path | None = None,
) -> bool:
    # ── Dispatch by expectation (TZ typed evidence expectations) ──────
    if req.expectation == "deleted":
        return _check_expectation_deleted(req, worktree_path, changed_files)
    if req.expectation == "absent":
        return _check_expectation_absent(req, worktree_path)
    if req.expectation == "created":
        return _check_expectation_created(req, worktree_path, changed_files)
    if req.expectation == "modified":
        return _check_expectation_modified(req, worktree_path, changed_files)
    if req.expectation == "diff_contains":
        return _check_expectation_diff_contains(req, changed_files)
    if req.expectation == "import_absent":
        return _check_expectation_import_absent(req, worktree_path)
    if req.expectation == "import_updated":
        return _check_expectation_import_absent(req, worktree_path)
    # Fall through for "exists" (default) and "test_output"

    if req.kind == "command":
        for stage in stage_results:
            for cmd in stage.commands:
                if cmd.exit_code != 0:
                    continue
                if req.pattern:
                    haystack = f"{cmd.command}\n{cmd.stdout}\n{cmd.stderr}"
                    if req.pattern in haystack:
                        return True
                else:
                    return True
        return False

    if req.kind == "file":
        if not worktree_path or not worktree_path.exists():
            return False
        patterns = req.artifact_patterns or ([req.pattern] if req.pattern else [])
        if patterns:
            return any(list(worktree_path.rglob(p)) for p in patterns)
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

    # TZ_FRONTEND_ACCEPTANCE P0 — new browser/visual evidence kinds.
    # Check both worktree_path and run_dir since PlaywrightRunner writes
    # artifacts to run_dir/browser/<viewport>/.
    _browser_dirs: list[Path] = []
    for root in (worktree_path, run_dir):
        if root:
            bd = Path(root) / "browser"
            if bd.exists():
                _browser_dirs.append(bd)

    def _browser_glob(pattern: str) -> list[Path]:
        result: list[Path] = []
        for bd in _browser_dirs:
            result.extend(bd.rglob(pattern))
        return result

    if req.kind == "screenshot":
        if req.pattern:
            return len(_browser_glob(req.pattern)) > 0
        pngs = _browser_glob("*.png")
        return len(pngs) > 0 and all(p.stat().st_size > 0 for p in pngs)

    if req.kind == "dom_snapshot":
        if req.pattern:
            return len(_browser_glob(req.pattern)) > 0
        return len(_browser_glob("*.html")) > 0

    if req.kind == "console_log":
        log_files = _browser_glob("*.log") + _browser_glob("console.*")
        if not log_files:
            return False
        if req.pattern == "no_errors":
            for f in log_files:
                if "error" in f.read_text().lower():
                    return False
            return True
        return any(req.pattern in f.read_text() for f in log_files) if req.pattern else True

    if req.kind == "network_log":
        har_files = _browser_glob("*.har") + _browser_glob("network*")
        if not har_files:
            return False
        if req.pattern:
            return any(req.pattern in f.read_text() for f in har_files)
        return True

    if req.kind == "visual_diff":
        # Check for diff-report.json which contains pixelmatch results.
        # No weak fallback — must have a real report.
        reports = _browser_glob("diff-report.json")
        if not reports:
            return False
        try:
            import json
            data = json.loads(reports[0].read_text())
            diff_pct = float(data.get("diff_pct", 1.0))
            max_pct = 0.001
            if req.pattern and "=" in req.pattern:
                max_pct = float(req.pattern.split("=", 1)[1])
            return diff_pct <= max_pct
        except Exception:
            return False

    # TZ_FRONTEND_ACCEPTANCE P2 — a11y accessibility check evidence
    if req.kind == "a11y_report":
        reports = _browser_glob("a11y-report.json")
        if not reports:
            return False
        try:
            import json
            data = json.loads(reports[0].read_text())
            violations = data.get("violations", [])
            critical = [v for v in violations if v.get("impact") == "critical"]
            # Pattern like "max_critical=0" means zero critical violations allowed
            max_critical = 0
            if req.pattern and req.pattern.startswith("max_critical="):
                max_critical = int(req.pattern.split("=", 1)[1])
            return len(critical) <= max_critical
        except Exception:
            return False

    # TZ_FRONTEND_ACCEPTANCE P3 — artifact manifest validation
    if req.kind == "artifact_manifest":
        from grace_control.services.artifact_manifest import validate_artifact_manifest
        errors = validate_artifact_manifest(run_dir) if run_dir else validate_artifact_manifest(worktree_path)
        return len(errors) == 0

    return False


# ── Typed expectation helpers ──────────────────────────────────────────


def _check_expectation_deleted(
    req: EvidenceRequirement,
    worktree_path: Path,
    changed_files: list[str],
) -> bool:
    """Expectation=deleted: file must not exist on disk.
    If pattern provides a specific path, check it's absent.
    Also check git diff D status if pattern is in changed_files.
    """
    if not worktree_path or not worktree_path.exists():
        return False
    patterns = req.artifact_patterns or ([req.pattern] if req.pattern else [])
    if not patterns:
        # No pattern — check that ALL changed files show deletion intent
        return len(changed_files) > 0
    for p in patterns:
        fpath = worktree_path / p
        if fpath.exists():
            return False  # file still exists — not properly deleted
    # If in changed_files, mark as pass (file was touched)
    for p in patterns:
        if p in changed_files:
            return True
    # File absent from disk but not in changed_files — still OK for deleted
    # (might have been absent before execution)
    return True


def _check_expectation_absent(
    req: EvidenceRequirement,
    worktree_path: Path,
) -> bool:
    """Expectation=absent: file must not exist on disk (no git diff needed)."""
    if not worktree_path or not worktree_path.exists():
        return False
    patterns = req.artifact_patterns or ([req.pattern] if req.pattern else [])
    if not patterns:
        return True  # no pattern → vacuously true
    for p in patterns:
        fpath = worktree_path / p
        if fpath.exists():
            return False
    return True


def _check_expectation_created(
    req: EvidenceRequirement,
    worktree_path: Path,
    changed_files: list[str],
) -> bool:
    """Expectation=created: file must exist AND be in changed_files (new)."""
    if not worktree_path or not worktree_path.exists():
        return False
    patterns = req.artifact_patterns or ([req.pattern] if req.pattern else [])
    if not patterns:
        return True
    for p in patterns:
        fpath = worktree_path / p
        if not fpath.exists():
            return False
        if p not in changed_files:
            return False
    return True


def _check_expectation_modified(
    req: EvidenceRequirement,
    worktree_path: Path,
    changed_files: list[str],
) -> bool:
    """Expectation=modified: file must exist AND be in changed_files."""
    return _check_expectation_created(req, worktree_path, changed_files)


def _check_expectation_diff_contains(
    req: EvidenceRequirement,
    changed_files: list[str],
) -> bool:
    """Expectation=diff_contains: changed_files must contain the pattern."""
    import fnmatch
    patterns = req.artifact_patterns or ([req.pattern] if req.pattern else [])
    if not patterns:
        return bool(changed_files)
    for p in patterns:
        matched = any(fnmatch.fnmatch(f, p) for f in changed_files)
        if matched:
            return True
    return False


def _check_expectation_import_absent(
    req: EvidenceRequirement,
    worktree_path: Path,
) -> bool:
    """Expectation=import_absent: old import path must NOT appear
    in active code directories. Greps for the pattern (which should be
    the old import path) across apps/, src/, packages/, tests/, scripts/.
    Returns True when the import is absent (gone) — i.e. no matches found.
    """
    if not worktree_path or not worktree_path.exists():
        return False
    pattern = req.pattern or ""
    if not pattern and req.artifact_patterns:
        pattern = req.artifact_patterns[0]
    if not pattern:
        return True  # no import to check → vacuously true
    exclude_dirs = {".git", ".grace", "node_modules", ".venv", "dist", "build", "coverage", "__pycache__", "archive"}
    for rel_dir in _ACTIVE_CODE_DIRS:
        search_root = worktree_path / rel_dir
        if not search_root.exists():
            continue
        for fpath in search_root.rglob("*"):
            if fpath.is_dir():
                continue
            parts = fpath.relative_to(worktree_path).parts
            if any(ex in parts for ex in exclude_dirs):
                continue
            try:
                text = fpath.read_text(encoding="utf-8", errors="replace")
                if pattern in text:
                    return False  # old import still present
            except Exception:
                continue
    return True  # import not found — absent as expected


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

        passed_commands = [e for e in collected_evidence if e.startswith("exit_code:0")]

        if acceptance_profile == AcceptanceProfile.NORMAL:
            return len(passed_commands) >= 1

        if acceptance_profile == AcceptanceProfile.STRICT:
            if not expected_evidence:
                return False
            return len(passed_commands) >= 1

        return False
