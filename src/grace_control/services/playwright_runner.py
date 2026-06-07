# ############################################################################
# AI_HEADER: playwright_runner
# ROLE: Run Playwright E2E and visual regression tests in headless browser.
#       TZ_FRONTEND_ACCEPTANCE P0 — manages dev-server lifecycle, runs
#       Playwright per viewport, collects artifacts (screenshots, traces).
# ############################################################################

# START_MODULE_CONTRACT
# purpose: Provide PlaywrightRunner that starts a dev server, runs Playwright
#          tests in headless Chromium per viewport, and collects results.
# inputs: worktree_path (Path), run_dir (Path), viewport (str),
#         base_url (str), dev_command (str), telegram_mode (str).
# returns: BrowserStageResult with passed, screenshots, errors, trace_path.
# side_effects: Spawns dev-server subprocess, runs npx playwright test,
#               writes screenshots to run_dir/browser/<viewport>/.
# emitted_logs: dev_server_started, dev_server_stopped, playwright_started,
#               playwright_completed, playwright_failed.
# error_behavior: Playwright not installed → logs and skips (passed=True).
#                 Dev-server timeout → kill + fail.
# END_MODULE_CONTRACT

# START_MODULE_MAP
# mapping:
#   - class: PlaywrightRunner
# END_MODULE_MAP

from __future__ import annotations

import os
import signal
import subprocess
import time
from pathlib import Path

from grace_control.core.structured_logger import GraceLogger
from grace_control.core.frontend_stages import BrowserStageResult

_log = GraceLogger("playwright_runner")

_DEV_SERVER_TIMEOUT = 30
_PLAYWRIGHT_TIMEOUT = 120
_VIEWPORT_CONFIG = {
    "android": {"width": 360, "height": 780},
    "iphone": {"width": 390, "height": 844},
}


class PlaywrightRunner:
    """Run Playwright tests for a packet in an isolated worktree."""

    def __init__(
        self,
        worktree_path: Path,
        run_dir: Path,
        viewport: str = "android",
        base_url: str = "http://localhost:3000",
        dev_command: str = "npm run dev",
        telegram_mode: str = "mock",
    ) -> None:
        self._worktree = Path(worktree_path)
        self._run_dir = Path(run_dir)
        self._viewport = viewport
        self._base_url = base_url
        self._dev_command = dev_command
        self._telegram_mode = telegram_mode
        self._dev_proc: subprocess.Popen | None = None

    @property
    def viewport_config(self) -> dict:
        return _VIEWPORT_CONFIG.get(self._viewport, _VIEWPORT_CONFIG["android"])

    def run_e2e(self) -> BrowserStageResult:
        return self._run_playwright("e2e")

    def run_visual(self, max_diff_pct: float = 0.001) -> BrowserStageResult:
        return self._run_playwright("visual", extra_env={"MAX_DIFF_PCT": str(max_diff_pct)})

    # ── internals ───────────────────────────────────────────────────────

    def _run_playwright(self, mode: str, extra_env: dict | None = None) -> BrowserStageResult:
        result = BrowserStageResult(viewport=self._viewport)

        # Check if Playwright is available
        if not self._has_playwright():
            _log.error("playwright_missing", reason="npx playwright not available")
            result.passed = False
            result.errors = ["npx playwright not installed — cannot run frontend acceptance"]
            return result

        # Check for test files
        test_pattern = (
            f"tests/e2e/**/*.spec.ts" if mode == "e2e"
            else f"tests/e2e/**/*.visual.spec.ts"
        )
        test_files = list(self._worktree.glob(test_pattern))
        if not test_files:
            _log.warn("playwright_no_tests", mode=mode, reason=f"no {mode} test files found")
            result.passed = False
            result.errors = [f"No {mode} test files found — frontend gate cannot pass without tests"]
            return result

        t0 = time.time()
        dev_started = False
        try:
            # Start dev server — must be inside try so cleanup runs on failure
            dev_started = self._start_dev_server()
            if not dev_started:
                result.errors = ["Dev server failed to start"]
                return result

            # Run Playwright
            browser_dir = self._run_dir / "browser" / self._viewport
            browser_dir.mkdir(parents=True, exist_ok=True)

            env = os.environ.copy()
            env["PLAYWRIGHT_BASE_URL"] = self._base_url
            if extra_env:
                env.update(extra_env)

            cmd = [
                "npx", "playwright", "test",
                "--config", str(self._worktree / "playwright.config.ts"),
                "--reporter", "html,json,list",
                f"--project={self._viewport}" if not self._has_projects() else "",
            ]
            cmd = [c for c in cmd if c]

            _log.info("playwright_started", mode=mode, viewport=self._viewport,
                      test_count=len(test_files))
            proc = subprocess.run(
                cmd, cwd=str(self._worktree), env=env,
                capture_output=True, text=True,
                timeout=_PLAYWRIGHT_TIMEOUT,
            )

            result.duration_ms = int((time.time() - t0) * 1000)
            result.command = " ".join(cmd)
            result.exit_code = proc.returncode
            result.stdout_snippet = proc.stdout[:500] if proc.stdout else ""
            result.stderr_snippet = proc.stderr[:500] if proc.stderr else ""

            if proc.returncode == 0:
                result.passed = True
                _log.info("playwright_completed", mode=mode, viewport=self._viewport,
                          duration_ms=result.duration_ms)
            else:
                result.passed = False
                result.errors.append(proc.stderr[:500] or proc.stdout[:500])
                _log.warn("playwright_failed", mode=mode, viewport=self._viewport,
                          exit_code=proc.returncode, stderr=proc.stderr[:200])

            # Collect screenshots
            for png in sorted(browser_dir.rglob("*.png")):
                result.screenshots.append(str(png))

            # Collect trace if failed
            if not result.passed:
                trace_dir = self._run_dir / "traces" / self._viewport
                trace_zip = trace_dir / "trace.zip"
                if trace_zip.exists():
                    result.trace_path = str(trace_zip)

        except subprocess.TimeoutExpired:
            result.errors = [f"Playwright timed out after {_PLAYWRIGHT_TIMEOUT}s"]
            _log.error("playwright_timeout", mode=mode, viewport=self._viewport)
        except Exception as e:
            result.errors = [str(e)[:500]]
            _log.error("playwright_error", mode=mode, viewport=self._viewport, error=str(e)[:200])
        finally:
            self._stop_dev_server()

        return result

    def _has_playwright(self) -> bool:
        try:
            r = subprocess.run(
                ["npx", "playwright", "--version"],
                capture_output=True, text=True, timeout=10,
                cwd=str(self._worktree),
            )
            return r.returncode == 0
        except Exception:
            return False

    def _has_projects(self) -> bool:
        config = self._worktree / "playwright.config.ts"
        if not config.exists():
            return False
        return "projects" in config.read_text()

    def _start_dev_server(self) -> bool:
        try:
            _log.info("dev_server_starting", command=self._dev_command)

            # Inject Telegram mock before starting dev server
            if self._telegram_mode == "mock":
                self._inject_telegram_mock()

            self._dev_proc = subprocess.Popen(
                self._dev_command.split(),
                cwd=str(self._worktree),
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                preexec_fn=os.setsid,
            )
            # Wait for server to become ready
            deadline = time.time() + _DEV_SERVER_TIMEOUT
            while time.time() < deadline:
                time.sleep(1)
                if self._dev_proc.poll() is not None:
                    _log.error("dev_server_crashed", exit_code=self._dev_proc.returncode)
                    return False
                if self._port_open():
                    _log.info("dev_server_ready", url=self._base_url)
                    return True
            _log.error("dev_server_timeout", timeout=_DEV_SERVER_TIMEOUT)
            return False
        except Exception as e:
            _log.error("dev_server_start_failed", error=str(e)[:200])
            return False

    def _stop_dev_server(self) -> None:
        if self._dev_proc and self._dev_proc.poll() is None:
            try:
                os.killpg(os.getpgid(self._dev_proc.pid), signal.SIGTERM)
                self._dev_proc.wait(timeout=5)
            except Exception:
                try:
                    os.killpg(os.getpgid(self._dev_proc.pid), signal.SIGKILL)
                except Exception:
                    pass
            _log.info("dev_server_stopped")

    def _port_open(self) -> bool:
        try:
            import socket
            from urllib.parse import urlparse
            parsed = urlparse(self._base_url)
            host = parsed.hostname or "localhost"
            port = parsed.port or 3000
            s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            s.settimeout(1)
            result = s.connect_ex((host, port))
            s.close()
            return result == 0
        except Exception:
            return False

    def _inject_telegram_mock(self) -> None:
        """Inject Telegram WebApp mock into worktree for testing."""
        try:
            from grace_control.services.telegram_webapp_mock import inject_mock_script
            inject_mock_script(self._worktree)
        except ImportError:
            pass
