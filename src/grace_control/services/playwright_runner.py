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
    "desktop": {"width": 1280, "height": 720},  # TZ_FRONTEND_ACCEPTANCE P2
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
        telegram_bot_token_env: str = "",
        packet_id: str = "",
        run_id: str = "",
    ) -> None:
        self._worktree = Path(worktree_path)
        self._run_dir = Path(run_dir)
        self._viewport = viewport
        self._base_url = base_url
        self._dev_command = dev_command
        self._telegram_mode = telegram_mode
        self._telegram_bot_token_env = telegram_bot_token_env
        self._packet_id = packet_id
        self._run_id = run_id
        self._dev_proc: subprocess.Popen | None = None
        self._bridge: "TelegramBridgeService | None" = None

    @property
    def viewport_config(self) -> dict:
        return _VIEWPORT_CONFIG.get(self._viewport, _VIEWPORT_CONFIG["android"])

    def run_e2e(self, custom_cmds: list[list[str]] | None = None) -> BrowserStageResult:
        return self._run_playwright("e2e", custom_cmds=custom_cmds)

    def run_visual(self, max_diff_pct: float = 0.001,
                   custom_cmds: list[list[str]] | None = None) -> BrowserStageResult:
        return self._run_playwright("visual", extra_env={"MAX_DIFF_PCT": str(max_diff_pct)},
                                    custom_cmds=custom_cmds)

    def run_a11y(self, custom_cmds: list[list[str]] | None = None) -> BrowserStageResult:
        """Run axe-core accessibility check. TZ_FRONTEND_ACCEPTANCE P2."""
        return self._run_playwright("a11y", custom_cmds=custom_cmds)

    # ── internals ───────────────────────────────────────────────────────

    def _run_playwright(self, mode: str, extra_env: dict | None = None,
                         custom_cmds: list[list[str]] | None = None) -> BrowserStageResult:
        result = BrowserStageResult(viewport=self._viewport)

        # TZ_FRONTEND_ACCEPTANCE P1/3.4 — install Playwright if missing
        if not self._has_playwright():
            from grace_control.services.process_supervisor import playwright_install_browsers
            _log.info("playwright_installing", reason="chromium not found")
            playwright_install_browsers(self._worktree)

        # Check again after install attempt
        if not self._has_playwright():
            _log.error("playwright_missing", reason="npx playwright not available")
            result.passed = False
            result.errors = ["npx playwright not installed — cannot run frontend acceptance"]
            if custom_cmds:
                result.command = " ; ".join(" ".join(c) for c in custom_cmds)
            return result

        # Check for test files (before dev-server/bridge to fail early)
        test_pattern = (
            f"tests/e2e/**/*.a11y.spec.ts" if mode == "a11y"
            else f"tests/e2e/**/*.spec.ts" if mode == "e2e"
            else f"tests/e2e/**/*.visual.spec.ts"
        )
        test_files = list(self._worktree.glob(test_pattern))
        if not test_files:
            _log.warn("playwright_no_tests", mode=mode, reason=f"no {mode} test files found")
            result.passed = False
            result.errors = [f"No {mode} test files found — frontend gate cannot pass without tests"]
            if custom_cmds:
                result.command = " ; ".join(" ".join(c) for c in custom_cmds)
            return result

        t0 = time.time()
        ngrok_url = ""
        self._bridge = None
        try:
            # Start dev server — must be inside try so cleanup runs on failure
            if not self._start_dev_server():
                result.errors = ["Dev server failed to start"]
                return result

            # TZ_FRONTEND_ACCEPTANCE P1/3.3 — real Telegram bridge AFTER dev-server is ready.
            if self._telegram_mode == "real":
                from grace_control.services.telegram_bridge_service import TelegramBridgeService
                dev_port = int(self._base_url.rsplit(":", 1)[-1]) if ":" in self._base_url else 3000
                self._bridge = TelegramBridgeService(
                    worktree_path=self._worktree,
                    dev_port=dev_port,
                    bot_token_env=self._telegram_bot_token_env,
                )
                bridge_result = self._bridge.start()
                if bridge_result.ok:
                    ngrok_url = bridge_result.public_url
                    _log.info("telegram_bridge_active", ngrok_url=ngrok_url)
                else:
                    # STRICT+real: bridge failure is a hard fail.
                    # NORMAL+real was already downgraded to mock by routing.
                    _log.error("telegram_bridge_failed_on_strict", error=bridge_result.error)
                    result.passed = False
                    result.errors = [f"Telegram bridge failed (STRICT+real): {bridge_result.error}"]
                    return result

            # Run Playwright
            browser_dir = self._run_dir / "browser" / self._viewport
            browser_dir.mkdir(parents=True, exist_ok=True)

            env = os.environ.copy()
            env["PLAYWRIGHT_BASE_URL"] = ngrok_url or self._base_url
            if extra_env:
                env.update(extra_env)

            # Build command list: architect-provided custom commands or default.
            cmds_to_run: list[list[str]] = []
            if custom_cmds:
                cmds_to_run = [list(c) for c in custom_cmds]
            else:
                cmds_to_run = [[
                    "npx", "playwright", "test",
                    "--config", str(self._worktree / "playwright.config.ts"),
                    "--reporter", "html,json,list",
                    f"--project={self._viewport}" if not self._has_projects() else "",
                ]]

            # Execute all commands sequentially, combine results
            all_passed = True
            all_commands: list[str] = []
            all_stdout: list[str] = []
            all_stderr: list[str] = []
            worst_exit = 0

            for c in cmds_to_run:
                c = [p for p in c if p]  # filter empty
                _log.info("playwright_started", mode=mode, viewport=self._viewport,
                          test_count=len(test_files), command=" ".join(c))
                proc = subprocess.run(
                    c, cwd=str(self._worktree), env=env,
                    capture_output=True, text=True,
                    timeout=_PLAYWRIGHT_TIMEOUT,
                )
                all_commands.append(" ".join(c))
                all_stdout.append(proc.stdout[:500] if proc.stdout else "")
                all_stderr.append(proc.stderr[:500] if proc.stderr else "")
                if proc.returncode != 0:
                    all_passed = False
                    result.errors.append(proc.stderr[:500] or proc.stdout[:500])
                worst_exit = max(worst_exit, proc.returncode)

            result.duration_ms = int((time.time() - t0) * 1000)
            result.command = " ; ".join(all_commands)
            result.exit_code = worst_exit
            result.stdout_snippet = "\n---\n".join(all_stdout)
            result.stderr_snippet = "\n---\n".join(all_stderr)
            result.passed = all_passed
            if all_passed:
                _log.info("playwright_completed", mode=mode, viewport=self._viewport,
                          duration_ms=result.duration_ms, commands=len(all_commands))

            # Collect screenshots
            for png in sorted(browser_dir.rglob("*.png")):
                result.screenshots.append(str(png))

            # TZ_FRONTEND_ACCEPTANCE P2 — generate a11y-report.json for a11y mode
            if mode == "a11y":
                self._write_a11y_report(browser_dir, all_stdout, all_stderr, result)

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
            if self._bridge:
                self._bridge.stop()
                self._bridge = None

        # TZ_FRONTEND_ACCEPTANCE P3 — artifact manifest
        if self._packet_id:
            from grace_control.services.artifact_manifest import write_artifact_manifest
            write_artifact_manifest(
                self._run_dir, packet_id=self._packet_id, run_id=self._run_id or self._packet_id,
            )

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

    def _write_a11y_report(
        self,
        browser_dir: Path,
        all_stdout: list[str],
        all_stderr: list[str],
        result: BrowserStageResult,
    ) -> None:
        """Parse a11y output and write a11y-report.json for evidence. P2."""
        violations = []
        combined = "\n".join(all_stdout) + "\n" + "\n".join(all_stderr)
        # Try to extract JSON violations from the output
        import json as _json
        try:
            # Look for JSON array/object in output
            for line in combined.split("\n"):
                line = line.strip()
                if line.startswith("[") or line.startswith("{"):
                    try:
                        data = _json.loads(line)
                        if isinstance(data, list):
                            violations = data
                        elif isinstance(data, dict) and "violations" in data:
                            violations = data["violations"]
                    except _json.JSONDecodeError:
                        pass
        except Exception:
            pass
        # If stdout contains "critical" but no structured JSON, generate synthetic
        if not violations and ("critical" in combined.lower() or "violation" in combined.lower()):
            violations = [{"id": "a11y-error", "impact": "critical", "description": combined[:200]}]
        report = {
            "viewport": self._viewport,
            "violations": violations,
            "violations_count": len(violations),
            "critical_count": sum(1 for v in violations if v.get("impact") == "critical"),
            "passed": result.passed,
        }
        (browser_dir / "a11y-report.json").write_text(_json.dumps(report, indent=2))
        result.screenshots.append(str(browser_dir / "a11y-report.json"))
        _log.info("a11y_report_written", viewport=self._viewport,
                  violations=len(violations), passed=result.passed)
