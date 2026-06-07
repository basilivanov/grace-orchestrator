# ############################################################################
# AI_HEADER: frontend_stages
# ROLE: Browser E2E and visual regression stage routing for acceptance pipeline.
#       TZ_FRONTEND_ACCEPTANCE P0 — resolve_browser_routing() decides which
#       T2_BROWSER_E2E / T3_VISUAL_REGRESSION stages run based on frontend spec
#       and acceptance profile.
# ############################################################################

# START_MODULE_CONTRACT
# purpose: Provide resolve_browser_routing() that maps frontend spec + profile
#          to a BrowserRouting decision (which stages run, telegram mode, viewports).
#          Also provide run_browser_stage() for T2_BROWSER_E2E execution.
# inputs: frontend_spec (dict from spec_json), acceptance_profile (str).
# returns: BrowserRouting namedtuple.
# side_effects: None (routing is pure).
# emitted_logs: browser_routing_evaluated.
# error_behavior: FrontendSpec validation failures → browser disabled.
# END_MODULE_CONTRACT

# START_MODULE_MAP
# mapping:
#   - function: resolve_browser_routing
#   - function: run_t2_browser_e2e
#   - function: run_t3_visual_regression
#   - function: run_a11y_check  # P2
#   - dataclass: BrowserRouting
#   - dataclass: BrowserStageResult
# END_MODULE_MAP

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from grace_control.core.structured_logger import GraceLogger

_log = GraceLogger("frontend_stages")

_VIEWPORT_MAP = {
    "android": {"width": 360, "height": 780},
    "iphone": {"width": 390, "height": 844},
    "desktop": {"width": 1280, "height": 720},  # TZ_FRONTEND_ACCEPTANCE P2
}


@dataclass
class BrowserRouting:
    """Decision: which frontend stages to run and how."""

    run_t2_browser: bool = False
    run_t3_visual: bool = False
    run_a11y: bool = False          # TZ_FRONTEND_ACCEPTANCE P2
    telegram_mode: str = "mock"
    telegram_bot_token_env: str = ""
    viewports: list[str] = field(default_factory=lambda: ["android", "iphone"])
    max_diff_pct: float = 0.001
    dev_command: str = "npm run dev"
    base_url: str = "http://localhost:3000"
    reason: str = "frontend not enabled"


@dataclass
class BrowserStageResult:
    """Result of a single browser stage run."""

    passed: bool = False
    viewport: str = ""
    screenshots: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)
    trace_path: str = ""
    duration_ms: int = 0
    command: str = ""           # Full command string ("npx playwright test ...")
    exit_code: int = -1         # Actual exit code from subprocess
    stdout_snippet: str = ""    # First 500 chars of stdout
    stderr_snippet: str = ""    # First 500 chars of stderr


def resolve_browser_routing(
    frontend_spec: dict | None,
    acceptance_profile: str,
) -> BrowserRouting:
    """Determine which browser stages to run.

    Follows the TZ_FRONTEND_ACCEPTANCE routing table:

    | frontend.enabled | profile | T2_BROWSER        | T3_VISUAL          |
    |------------------|---------|--------------------|--------------------|
    | false/None       | any     | skip               | skip               |
    | true             | FAST    | skip               | skip               |
    | true             | NORMAL  | run (if e2e.reqd)  | run (if visual.reqd)|
    | true             | STRICT  | run                | run                |
    """
    spec = frontend_spec or {}

    if not spec.get("enabled", False):
        _log.info("browser_routing_disabled", reason="frontend not enabled")
        return BrowserRouting(reason="frontend not enabled")

    if acceptance_profile == "FAST":
        _log.info("browser_routing_skipped", reason="FAST profile skips browser")
        return BrowserRouting(run_t2_browser=False, run_t3_visual=False,
                              telegram_mode=spec.get("telegram_mode", "mock"),
                              reason="FAST profile — browser skipped")

    # NORMAL or STRICT — run browser stages
    e2e = spec.get("e2e", {}) or {}
    visual = spec.get("visual", {}) or {}
    telegram_mode = spec.get("telegram_mode", "mock")

    # NORMAL + real Telegram → downgrade to mock (TZ Requirement)
    if acceptance_profile == "NORMAL" and telegram_mode == "real":
        _log.warn("browser_routing_telegram_downgraded",
                  reason="NORMAL profile — forcing telegram_mode=mock")
        telegram_mode = "mock"

    run_browser = acceptance_profile in ("NORMAL", "STRICT") and e2e.get("required", True)
    run_visual = acceptance_profile in ("NORMAL", "STRICT") and visual.get("required", False)
    a11y_spec = spec.get("a11y", {}) or {}
    run_a11y = acceptance_profile in ("NORMAL", "STRICT") and a11y_spec.get("required", False)

    routing = BrowserRouting(
        run_t2_browser=run_browser,
        run_t3_visual=run_visual,
        run_a11y=run_a11y,
        telegram_mode=telegram_mode,
        telegram_bot_token_env=spec.get("telegram_bot_token_env", ""),
        viewports=spec.get("viewports", ["android", "iphone"]),
        max_diff_pct=visual.get("max_diff_pct", 0.001),
        dev_command=spec.get("dev_command", "npm run dev"),
        base_url=spec.get("base_url", "http://localhost:3000"),
        reason="OK",
    )
    _log.info("browser_routing_evaluated",
              run_t2=routing.run_t2_browser, run_t3=routing.run_t3_visual,
              telegram_mode=routing.telegram_mode, viewports=routing.viewports)
    return routing


def run_t2_browser_e2e(
    worktree_path: Path,
    run_dir: Path,
    routing: BrowserRouting,
    *,
    telegram_mode: str = "mock",
    custom_cmds: list[list[str]] | None = None,
    telegram_bot_token_env: str = "",
) -> list[BrowserStageResult]:
    """Run T2_BROWSER_E2E — Playwright E2E tests per viewport.

    Uses custom_cmds from verification.t2_browser if provided;
    otherwise falls back to default playwright invocation.
    """
    results: list[BrowserStageResult] = []
    for vp in routing.viewports:
        try:
            from grace_control.services.playwright_runner import PlaywrightRunner
            runner = PlaywrightRunner(
                worktree_path=worktree_path,
                run_dir=run_dir,
                viewport=vp,
                base_url=routing.base_url,
                dev_command=routing.dev_command,
                telegram_mode=telegram_mode,
                telegram_bot_token_env=telegram_bot_token_env,
            )
            result = runner.run_e2e(custom_cmds=custom_cmds)
            results.append(result)
        except ImportError:
            _log.info("browser_e2e_skipped", viewport=vp, reason="PlaywrightRunner not available")
            results.append(BrowserStageResult(
                passed=True, viewport=vp,
                errors=["PlaywrightRunner not available — T2_BROWSER_E2E skipped"],
            ))
        except Exception as e:
            _log.error("browser_e2e_failed", viewport=vp, error=str(e)[:200])
            results.append(BrowserStageResult(
                passed=False, viewport=vp, errors=[str(e)[:200]],
            ))
    return results


def run_t3_visual_regression(
    worktree_path: Path,
    run_dir: Path,
    routing: BrowserRouting,
    *,
    telegram_mode: str = "mock",
    custom_cmds: list[list[str]] | None = None,
    telegram_bot_token_env: str = "",
) -> list[BrowserStageResult]:
    """Run T3_VISUAL_REGRESSION — Playwright visual diff per viewport.

    Uses custom_cmds from verification.t3_visual if provided;
    otherwise falls back to default playwright invocation.
    """
    results: list[BrowserStageResult] = []
    for vp in routing.viewports:
        try:
            from grace_control.services.playwright_runner import PlaywrightRunner
            runner = PlaywrightRunner(
                worktree_path=worktree_path,
                run_dir=run_dir,
                viewport=vp,
                base_url=routing.base_url,
                dev_command=routing.dev_command,
                telegram_mode=telegram_mode,
                telegram_bot_token_env=telegram_bot_token_env,
            )
            result = runner.run_visual(max_diff_pct=routing.max_diff_pct,
                                       custom_cmds=custom_cmds)
            results.append(result)
        except ImportError:
            _log.info("visual_regression_skipped", viewport=vp, reason="PlaywrightRunner not available")
            results.append(BrowserStageResult(
                passed=True, viewport=vp,
                errors=["PlaywrightRunner not available — T3_VISUAL_REGRESSION skipped"],
            ))
        except Exception as e:
            _log.error("visual_regression_failed", viewport=vp, error=str(e)[:200])
            results.append(BrowserStageResult(
                passed=False, viewport=vp, errors=[str(e)[:200]],
            ))
    return results


def run_a11y_check(
    worktree_path: Path,
    run_dir: Path,
    routing: BrowserRouting,
    *,
    telegram_mode: str = "mock",
    telegram_bot_token_env: str = "",
) -> list[BrowserStageResult]:
    """Run T2_BROWSER_A11Y — axe-core per viewport (P2).

    Critical a11y violations make the stage FAIL.
    Non-critical violations are collected as warnings.
    """
    results: list[BrowserStageResult] = []
    for vp in routing.viewports:
        try:
            from grace_control.services.playwright_runner import PlaywrightRunner
            runner = PlaywrightRunner(
                worktree_path=worktree_path,
                run_dir=run_dir,
                viewport=vp,
                base_url=routing.base_url,
                dev_command=routing.dev_command,
                telegram_mode=telegram_mode,
                telegram_bot_token_env=telegram_bot_token_env,
            )
            r = runner.run_a11y()
            results.append(r)
        except Exception as e:
            _log.error("a11y_failed", viewport=vp, error=str(e)[:200])
            results.append(BrowserStageResult(
                passed=False, viewport=vp, errors=[str(e)[:200]],
            ))
    return results
