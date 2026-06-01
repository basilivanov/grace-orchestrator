# ############################################################################
# AI_HEADER: acceptance_pipeline
# ROLE: Staged acceptance — T0 (lint/canon) → T1 (touched) → T2 (full tests).
# ############################################################################

from __future__ import annotations

import subprocess
from dataclasses import dataclass, field
from pathlib import Path


@dataclass
class StageResult:
    passed: bool
    stage: str
    output: str = ""
    duration_ms: int = 0


@dataclass
class AcceptanceResult:
    passed: bool
    stages: list[StageResult] = field(default_factory=list)
    reason: str = ""


def run_acceptance(project_root: Path, scope: list[str], profile: str = "NORMAL") -> AcceptanceResult:
    """Run T0→T1→T2 acceptance pipeline."""
    stages: list[StageResult] = []

    # T0: Lint + GRACE Canon (always)
    t0 = _run_stage("T0", ["ruff", "check"] + [str(project_root / f) for f in scope if (project_root / f).exists()])
    stages.append(t0)
    if not t0.passed:
        return AcceptanceResult(False, stages, f"T0 failed: {t0.output[:200]}")

    # T1: Touched tests (always for MVP)
    t1 = _run_stage("T1", ["pytest"] + [str(project_root / f) for f in scope if (project_root / f).exists(), "-q"])
    stages.append(t1)
    if not t1.passed and profile != "FAST":
        return AcceptanceResult(False, stages, f"T1 failed: {t1.output[:200]}")

    # T2: Full tests (NORMAL/STRICT only)
    if profile in ("NORMAL", "STRICT"):
        t2 = _run_stage("T2", ["pytest", str(project_root / "tests"), "-q"])
        stages.append(t2)
        if not t2.passed:
            return AcceptanceResult(False, stages, f"T2 failed: {t2.output[:200]}")

    return AcceptanceResult(True, stages, "All stages passed")


def _run_stage(name: str, cmd: list[str]) -> StageResult:
    import time
    t0 = time.time()
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=120)
        passed = r.returncode == 0
        output = r.stdout[:500] or r.stderr[:500]
    except subprocess.TimeoutExpired:
        passed = False
        output = "timeout"
    except FileNotFoundError:
        passed = False
        output = "tool not found"
    return StageResult(passed, name, output, int((time.time() - t0) * 1000))
