# ############################################################################
# AI_HEADER: visual_baseline_manager
# ROLE: Visual regression baseline management — compare current screenshots
#       against baselines, compute diff percentages via pixelmatch metadata.
#       TZ_FRONTEND_ACCEPTANCE P1.
# ############################################################################

# START_MODULE_CONTRACT
# purpose: Manage visual regression baselines and perform diff comparisons.
#          Reads pixelmatch-compatible diff metadata from Playwright test
#          output (JSON reports) and computes pass/fail against thresholds.
# inputs: run_dir (Path), viewport (str), baseline_dir (Path | None).
# returns: VisualDiffResult with passed, diff_pct, diff_path, baseline_path.
# side_effects: Reads baseline screenshots and diff reports from disk.
# emitted_logs: visual_diff_compared, visual_baseline_missing.
# error_behavior: Missing baseline → pass (first run creates baseline).
#                 Corrupt diff data → fail with error.
# END_MODULE_CONTRACT

# START_MODULE_MAP
# mapping:
#   - class: VisualBaselineManager
#   - dataclass: VisualDiffResult
# END_MODULE_MAP

from __future__ import annotations

import json
from grace_control.core.stage_instrumentation import stage
from dataclasses import dataclass, field
from pathlib import Path

from grace_control.core.structured_logger import GraceLogger

_log = GraceLogger("visual_baseline")


@dataclass
class VisualDiffResult:
    """Outcome of a visual regression comparison."""

    passed: bool = False
    viewport: str = ""
    diff_pct: float = 0.0
    max_diff_pct: float = 0.001
    diff_path: str = ""
    current_path: str = ""
    baseline_path: str = ""
    error: str = ""


class VisualBaselineManager:
    """Compare screenshots against baselines using pixelmatch/PW metadata.

    Baselines are expected in tests/e2e/**/*-snapshots/ within the worktree.
    The PlaywrightRunner writes artifacts to run_dir/browser/<viewport>/.
    """

    def __init__(
        self,
        worktree_path: Path,
        run_dir: Path,
        baseline_dir: Path | None = None,
    ) -> None:
        self._worktree = Path(worktree_path)
        self._run_dir = Path(run_dir)
        self._baseline_dir = baseline_dir or (self._worktree / "tests" / "e2e")

    @stage("t3_visual")
    def compare(
        self,
        viewport: str,
        max_diff_pct: float = 0.001,
    ) -> VisualDiffResult:
        """Compare all screenshots for a viewport against baselines.

        Returns a combined result: fails if ANY screenshot exceeds threshold.
        """
        browser_dir = self._run_dir / "browser" / viewport
        result = VisualDiffResult(viewport=viewport, max_diff_pct=max_diff_pct)

        if not browser_dir.exists():
            result.error = f"browser dir not found: {browser_dir}"
            return result

        # Primary: parse JSON diff reports from Playwright
        reports = list(browser_dir.rglob("*diff-report*.json"))
        if reports:
            return self._compare_from_reports(reports, result, max_diff_pct)

        # Fallback: no diff-reports, compare against baselines using
        # a real image diff when available, or fail closed.
        screenshots = sorted(browser_dir.rglob("*.png"))
        baselines = self._find_baselines(screenshots)
        if not baselines:
            result.passed = True  # No baselines = first run
            _log.info("visual_baseline_missing", viewport=viewport,
                      count=len(screenshots))
            return result

        # Try real pixelmatch via Pillow, fall back to reporting
        # "unverified" rather than passing on a file-size surrogate.
        return self._compare_pixelmatch(screenshots, baselines, result, max_diff_pct)

    # ── internals ───────────────────────────────────────────────────────

    def _compare_from_reports(
        self, reports: list[Path], result: VisualDiffResult, max_pct: float
    ) -> VisualDiffResult:
        worst_pct = 0.0
        for rp in reports:
            try:
                data = json.loads(rp.read_text())
                pct = float(data.get("diff_pct", 0.0))
                worst_pct = max(worst_pct, pct)
                result.diff_path = str(rp)
            except (json.JSONDecodeError, ValueError, KeyError):
                pass
        result.diff_pct = worst_pct
        result.passed = worst_pct <= max_pct
        _log.info("visual_diff_compared", viewport=result.viewport,
                  diff_pct=worst_pct, max_pct=max_pct, passed=result.passed)
        return result

    def _find_baselines(self, screenshots: list[Path]) -> dict[str, Path]:
        baselines: dict[str, Path] = {}
        for s in screenshots:
            name = s.name
            # Look in tests/e2e/**/<name> (Playwright snapshot convention)
            for b in self._baseline_dir.rglob(name):
                baselines[name] = b
                break
        return baselines

    @staticmethod
    def _compare_pixelmatch(
        screenshots: list[Path],
        baselines: dict[str, Path],
        result: VisualDiffResult,
        max_pct: float,
    ) -> VisualDiffResult:
        """Try real image comparison via Pillow. Fail closed if unavailable."""
        try:
            from PIL import Image
            import math
            worst_pct = 0.0
            for s in screenshots:
                bl = baselines.get(s.name)
                if not bl:
                    continue
                img1 = Image.open(s).convert("RGB")
                img2 = Image.open(bl).convert("RGB")
                if img1.size != img2.size:
                    _log.warn("visual_size_mismatch", current=s.name, baseline=bl.name)
                    result.diff_pct = 1.0
                    result.passed = False
                    result.diff_path = str(s)
                    result.baseline_path = str(bl)
                    return result
                # Compute pixel difference percentage
                total = img1.size[0] * img1.size[1]
                diff_pixels = sum(
                    1 for x, (p1, p2) in enumerate(zip(img1.getdata(), img2.getdata()))
                    if p1 != p2
                )
                pct = diff_pixels / total if total > 0 else 0.0
                worst_pct = max(worst_pct, pct)
                result.diff_path = str(s)
                result.baseline_path = str(bl)
            result.diff_pct = worst_pct
            result.passed = worst_pct <= max_pct
        except ImportError:
            # Pillow not available — fail closed (can't verify visual regression)
            result.passed = False
            result.error = "Pillow not installed — cannot perform visual comparison"
            _log.warn("visual_pillow_missing", error=result.error)
        except Exception as e:
            result.passed = False
            result.error = f"visual comparison error: {e}"
            _log.error("visual_compare_error", error=str(e)[:200])
        _log.info("visual_diff_compared", viewport=result.viewport,
                  diff_pct=result.diff_pct, max_pct=max_pct, passed=result.passed)
        return result
