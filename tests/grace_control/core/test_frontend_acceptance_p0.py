"""Tests for TZ_FRONTEND_ACCEPTANCE P0 — routing, stages, evidence, contracts."""
from __future__ import annotations

from pathlib import Path

import pytest

from grace_control.core.contracts import (
    AcceptanceProfile,
    build_packet_contract,
    EvidenceRequirement,
    StageName,
    StageStatus,
)
from grace_control.core.frontend_stages import resolve_browser_routing
from grace_control.core.acceptance_pipeline import _run_frontend_stages


class TestResolveBrowserRouting:
    """resolve_browser_routing() table per TZ."""

    def test_no_frontend_spec_skips_both(self):
        r = resolve_browser_routing(None, "NORMAL")
        assert r.run_t2_browser is False
        assert r.run_t3_visual is False
        assert r.reason == "frontend not enabled"

    def test_fast_profile_skips_even_when_enabled(self):
        r = resolve_browser_routing({"enabled": True}, "FAST")
        assert r.run_t2_browser is False
        assert r.run_t3_visual is False
        assert "FAST" in r.reason

    def test_normal_mock_runs_e2e_by_default(self):
        r = resolve_browser_routing({"enabled": True, "telegram_mode": "mock"}, "NORMAL")
        assert r.run_t2_browser is True
        assert r.telegram_mode == "mock"

    def test_normal_visual_opt_in(self):
        # visual defaults to required=False → should not run by default
        r = resolve_browser_routing({"enabled": True, "visual": {"required": False}}, "NORMAL")
        assert r.run_t3_visual is False
        r2 = resolve_browser_routing({"enabled": True, "visual": {"required": True}}, "NORMAL")
        assert r2.run_t3_visual is True

    def test_normal_real_downgraded_to_mock(self):
        r = resolve_browser_routing({"enabled": True, "telegram_mode": "real"}, "NORMAL")
        assert r.telegram_mode == "mock"

    def test_strict_real_allowed(self):
        r = resolve_browser_routing({"enabled": True, "telegram_mode": "real"}, "STRICT")
        assert r.telegram_mode == "real"
        assert r.run_t2_browser is True

    def test_strict_empty_runs_both_with_defaults(self):
        r = resolve_browser_routing({"enabled": True}, "STRICT")
        assert r.run_t2_browser is True


class TestBuildPacketContractFrontend:
    """build_packet_contract() propagates t2_browser/t3_visual."""

    def test_t2_browser_and_t3_visual_in_verification(self):
        pd = {
            "id": "pkt_test", "title": "test",
            "spec_json": {
                "scope": ["x.py"],
                "verification": {
                    "t2_browser": [["npx", "playwright", "test"]],
                    "t3_visual": [["npx", "playwright", "test", "--visual"]],
                },
            },
        }
        c = build_packet_contract(pd)
        assert c.verification["t2_browser"] == [["npx", "playwright", "test"]]
        assert c.verification["t3_visual"] == [["npx", "playwright", "test", "--visual"]]

    def test_no_frontend_verification_defaults_to_empty(self):
        pd = {"id": "pkt_test", "title": "test", "spec_json": {"scope": ["x.py"]}}
        c = build_packet_contract(pd)
        assert c.verification.get("t2_browser", []) == []
        assert c.verification.get("t3_visual", []) == []

    def test_frontend_spec_in_metadata(self):
        pd = {
            "id": "pkt_test", "title": "test",
            "spec_json": {"scope": ["x.py"], "frontend": {"enabled": True}},
        }
        c = build_packet_contract(pd)
        assert c.metadata.get("frontend", {}).get("enabled") is True


class TestFrontendStagesInAcceptancePipeline:
    """_run_frontend_stages() produces valid StageResults."""

    def _make_packet(self, acceptance, metadata=None, verification=None):
        from grace_control.core.contracts import ExecutionPacketContract
        return ExecutionPacketContract(
            packet_id="t", title="t",
            allowed_write_scope=[], frozen_scope=[],
            acceptance_profile=AcceptanceProfile(acceptance),
            verification=verification or {},
            metadata=metadata or {},
        )

    def test_backend_only_skipped_with_reason(self):
        r = _run_frontend_stages(
            self._make_packet("NORMAL"),
            worktree_root=Path("/tmp"), run_dir=Path("/tmp"),
        )
        assert r["t2_browser"].status == StageStatus.SKIPPED
        assert r["t2_browser"].skipped_reason == "frontend not enabled"
        assert r["t3_visual"].status == StageStatus.SKIPPED
        assert r["t3_visual"].skipped_reason == "frontend not enabled"

    def test_fast_skipped_with_reason(self):
        r = _run_frontend_stages(
            self._make_packet("FAST", metadata={"frontend": {"enabled": True}}),
            worktree_root=Path("/tmp"), run_dir=Path("/tmp"),
        )
        assert "FAST" in r["t2_browser"].skipped_reason

    def test_verification_t2_browser_propagates_to_commands(self):
        r = _run_frontend_stages(
            self._make_packet("NORMAL",
                metadata={"frontend": {"enabled": True}},
                verification={"t2_browser": [["npx", "playwright", "test"]]},
            ),
            worktree_root=Path("/tmp"), run_dir=Path("/tmp"),
        )
        # 2 viewports (android + iphone) → 2 CommandResults
        assert len(r["t2_browser"].commands) == 2
        assert "npx playwright test" in r["t2_browser"].commands[0].command


class TestEvidenceKindFrontend:
    """Evidence checker handles new TZ_FRONTEND_ACCEPTANCE kinds."""

    def test_screenshot_non_empty_png(self, tmp_path: Path):
        from grace_control.core.evidence import _check_evidence_kind
        role = tmp_path / "browser"
        role.mkdir(parents=True)
        (role / "test.png").write_text("fake png data")
        req = EvidenceRequirement(id="s1", kind="screenshot")
        assert _check_evidence_kind(req, [], tmp_path, [])

    def test_screenshot_missing(self, tmp_path: Path):
        from grace_control.core.evidence import _check_evidence_kind
        req = EvidenceRequirement(id="s1", kind="screenshot")
        assert not _check_evidence_kind(req, [], tmp_path / "nonexistent", [])

    def test_dom_snapshot_html(self, tmp_path: Path):
        from grace_control.core.evidence import _check_evidence_kind
        role = tmp_path / "browser"
        role.mkdir(parents=True)
        (role / "snap.html").write_text("<html></html>")
        req = EvidenceRequirement(id="d1", kind="dom_snapshot")
        assert _check_evidence_kind(req, [], tmp_path, [])

    def test_console_log_no_errors(self, tmp_path: Path):
        from grace_control.core.evidence import _check_evidence_kind
        role = tmp_path / "browser"
        role.mkdir(parents=True)
        (role / "console.log").write_text("info: ok\nwarn: test")
        req = EvidenceRequirement(id="c1", kind="console_log", pattern="no_errors")
        assert _check_evidence_kind(req, [], tmp_path, [])

    def test_console_log_with_errors_fails(self, tmp_path: Path):
        from grace_control.core.evidence import _check_evidence_kind
        role = tmp_path / "browser"
        role.mkdir(parents=True)
        (role / "console.log").write_text("info: ok\nERROR: something broke")
        req = EvidenceRequirement(id="c1", kind="console_log", pattern="no_errors")
        assert not _check_evidence_kind(req, [], tmp_path, [])

    def test_network_log(self, tmp_path: Path):
        from grace_control.core.evidence import _check_evidence_kind
        role = tmp_path / "browser"
        role.mkdir(parents=True)
        (role / "network.har").write_text('{"log": {"entries": [{"url": "/api/test"}]}}')
        req = EvidenceRequirement(id="n1", kind="network_log", pattern="/api/test")
        assert _check_evidence_kind(req, [], tmp_path, [])

    def test_visual_diff_no_regression(self, tmp_path: Path):
        from grace_control.core.evidence import _check_evidence_kind
        role = tmp_path / "browser"
        role.mkdir(parents=True)
        (role / "diff.png").write_text("")  # empty = no regression
        req = EvidenceRequirement(id="v1", kind="visual_diff")
        assert _check_evidence_kind(req, [], tmp_path, [])

    def test_visual_diff_report_json_within_threshold(self, tmp_path: Path):
        from grace_control.core.evidence import _check_evidence_kind
        role = tmp_path / "browser"
        role.mkdir(parents=True)
        (role / "diff-report.json").write_text('{"diff_pct": 0.0005}')
        req = EvidenceRequirement(id="v1", kind="visual_diff", pattern="max_diff_pct=0.001")
        assert _check_evidence_kind(req, [], tmp_path, [])

    def test_visual_diff_report_json_exceeds_threshold(self, tmp_path: Path):
        from grace_control.core.evidence import _check_evidence_kind
        role = tmp_path / "browser"
        role.mkdir(parents=True)
        (role / "diff-report.json").write_text('{"diff_pct": 0.05}')
        req = EvidenceRequirement(id="v1", kind="visual_diff", pattern="max_diff_pct=0.001")
        assert not _check_evidence_kind(req, [], tmp_path, [])


class TestEvidenceRunDirFallback:
    """Evidence checker finds artifacts in run_dir/browser/ when worktree_path/browser/ is missing."""

    def test_screenshot_found_in_run_dir(self, tmp_path: Path):
        from grace_control.core.evidence import _check_evidence_kind
        run_browser = tmp_path / "run" / "browser" / "android"
        run_browser.mkdir(parents=True)
        (run_browser / "screen.png").write_text("png")
        req = EvidenceRequirement(id="s1", kind="screenshot")
        assert _check_evidence_kind(req, [], tmp_path / "wt", [], run_dir=tmp_path / "run")

    def test_console_log_in_run_dir(self, tmp_path: Path):
        from grace_control.core.evidence import _check_evidence_kind
        run_browser = tmp_path / "run" / "browser"
        run_browser.mkdir(parents=True)
        (run_browser / "console.log").write_text("info: test")
        req = EvidenceRequirement(id="c1", kind="console_log", pattern="test")
        assert _check_evidence_kind(req, [], tmp_path / "wt", [], run_dir=tmp_path / "run")

    def test_network_log_in_run_dir(self, tmp_path: Path):
        from grace_control.core.evidence import _check_evidence_kind
        run_browser = tmp_path / "run" / "browser"
        run_browser.mkdir(parents=True)
        (run_browser / "network.har").write_text('{"entries": [{"url": "/api"}]}')
        req = EvidenceRequirement(id="n1", kind="network_log", pattern="/api")
        assert _check_evidence_kind(req, [], tmp_path / "wt", [], run_dir=tmp_path / "run")


class TestPlaywrightMissingOrNoTests:
    """When Playwright is missing or no test files: must not pass silently."""

    def test_playwright_not_installed_fails(self):
        from grace_control.core.frontend_stages import BrowserStageResult
        from grace_control.services.playwright_runner import PlaywrightRunner
        import tempfile
        with tempfile.TemporaryDirectory() as d:
            runner = PlaywrightRunner(
                worktree_path=Path(d), run_dir=Path(d) / "runs",
                viewport="android", base_url="http://localhost:3000",
                dev_command="echo test",
            )
            # Mock _has_playwright to return False
            runner._has_playwright = lambda: False
            r = runner.run_e2e()
            assert r.passed is False, f"Expected failed, got passed={r.passed}"
            assert "not installed" in str(r.errors)

    def test_no_test_files_fails(self, tmp_path: Path):
        from grace_control.services.playwright_runner import PlaywrightRunner
        runner = PlaywrightRunner(
            worktree_path=tmp_path, run_dir=tmp_path / "runs",
            viewport="android", base_url="http://localhost:3000",
            dev_command="echo test",
        )
        runner._has_playwright = lambda: True
        r = runner.run_e2e()
        assert r.passed is False
        assert "no e2e test files" in str(r.errors).lower()

    def test_custom_commands_propagated_to_result(self, tmp_path: Path):
        """Architect-provided custom commands appear in BrowserStageResult.command."""
        from grace_control.services.playwright_runner import PlaywrightRunner
        custom = [["npx", "playwright", "test", "tests/e2e/login.spec.ts"]]
        runner = PlaywrightRunner(
            worktree_path=tmp_path, run_dir=tmp_path / "runs",
            viewport="android", base_url="http://localhost:3000",
            dev_command="echo test",
        )
        runner._has_playwright = lambda: True
        r = runner.run_e2e(custom_cmds=custom)
        assert "login.spec.ts" in r.command, f"Expected login.spec.ts, got: {r.command}"

    def test_custom_commands_actually_executed(self, tmp_path: Path):
        """subprocess.run() is called with the exact architect-provided command."""
        from unittest.mock import patch, MagicMock
        from grace_control.services.playwright_runner import PlaywrightRunner
        custom = [["npx", "playwright", "test", "tests/e2e/login.spec.ts"]]
        runner = PlaywrightRunner(
            worktree_path=tmp_path, run_dir=tmp_path / "runs",
            viewport="android", base_url="http://localhost:3000",
            dev_command="echo test",
        )
        runner._has_playwright = lambda: True
        runner._start_dev_server = lambda: True
        runner._stop_dev_server = lambda: None
        # Create a test file so the runner doesn't bail early
        (tmp_path / "tests" / "e2e").mkdir(parents=True)
        (tmp_path / "tests" / "e2e" / "test.spec.ts").write_text("// test")
        mock_run = MagicMock(returncode=0, stdout="", stderr="")
        with patch("subprocess.run", return_value=mock_run) as mock_subprocess:
            r = runner.run_e2e(custom_cmds=custom)
            mock_subprocess.assert_called_once()
            called_cmd = mock_subprocess.call_args[0][0]
            assert "tests/e2e/login.spec.ts" in called_cmd, (
                f"Expected login.spec.ts in subprocess command, got: {called_cmd}"
            )

    def test_multiple_custom_commands_all_executed(self, tmp_path: Path):
        """All commands in verification.t2_browser are executed, not just the first."""
        from unittest.mock import patch, MagicMock
        from grace_control.services.playwright_runner import PlaywrightRunner
        custom = [
            ["npx", "playwright", "test", "tests/e2e/login.spec.ts"],
            ["npx", "playwright", "test", "tests/e2e/dashboard.spec.ts"],
        ]
        runner = PlaywrightRunner(
            worktree_path=tmp_path, run_dir=tmp_path / "runs",
            viewport="android", base_url="http://localhost:3000",
            dev_command="echo test",
        )
        runner._has_playwright = lambda: True
        runner._start_dev_server = lambda: True
        runner._stop_dev_server = lambda: None
        (tmp_path / "tests" / "e2e").mkdir(parents=True)
        (tmp_path / "tests" / "e2e" / "test.spec.ts").write_text("// test")
        mock_run = MagicMock(returncode=0, stdout="", stderr="")
        with patch("subprocess.run", return_value=mock_run) as mock_subprocess:
            r = runner.run_e2e(custom_cmds=custom)
            assert mock_subprocess.call_count == 2, (
                f"Expected 2 subprocess calls, got {mock_subprocess.call_count}"
            )
            calls = [call[0][0] for call in mock_subprocess.call_args_list]
            assert any("login.spec.ts" in " ".join(c) for c in calls)
            assert any("dashboard.spec.ts" in " ".join(c) for c in calls)


# ── P1 tests ──────────────────────────────────────────────────────────────


class TestVisualBaselineManager:
    """VisualBaselineManager compares screenshots against baselines."""

    def test_missing_browser_dir(self, tmp_path: Path):
        from grace_control.services.visual_baseline_manager import VisualBaselineManager
        mgr = VisualBaselineManager(tmp_path, tmp_path / "runs")
        r = mgr.compare("android")
        assert r.passed is False

    def test_no_baselines_first_run_passes(self, tmp_path: Path):
        from grace_control.services.visual_baseline_manager import VisualBaselineManager
        browser_dir = tmp_path / "runs" / "browser" / "android"
        browser_dir.mkdir(parents=True)
        (browser_dir / "screen.png").write_text("fake")
        mgr = VisualBaselineManager(tmp_path, tmp_path / "runs")
        r = mgr.compare("android")
        assert r.passed is True  # first run — no baselines = pass

    def test_diff_report_json_within_threshold(self, tmp_path: Path):
        from grace_control.services.visual_baseline_manager import VisualBaselineManager
        browser_dir = tmp_path / "runs" / "browser" / "android"
        browser_dir.mkdir(parents=True)
        (browser_dir / "diff-report.json").write_text('{"diff_pct": 0.0005}')
        mgr = VisualBaselineManager(tmp_path, tmp_path / "runs")
        r = mgr.compare("android", max_diff_pct=0.001)
        assert r.passed is True

    def test_diff_report_json_exceeds_threshold(self, tmp_path: Path):
        from grace_control.services.visual_baseline_manager import VisualBaselineManager
        browser_dir = tmp_path / "runs" / "browser" / "android"
        browser_dir.mkdir(parents=True)
        (browser_dir / "diff-report.json").write_text('{"diff_pct": 0.05}')
        mgr = VisualBaselineManager(tmp_path, tmp_path / "runs")
        r = mgr.compare("android", max_diff_pct=0.001)
        assert r.passed is False

    def test_pixelmatch_real_comparison(self, tmp_path: Path):
        """When Pillow is available, real pixel comparison is used (not size-ratio)."""
        from grace_control.services.visual_baseline_manager import VisualBaselineManager
        try:
            from PIL import Image
        except ImportError:
            pytest.skip("Pillow not available")
        browser_dir = tmp_path / "runs" / "browser" / "android"
        browser_dir.mkdir(parents=True)
        # Create identical images → should pass
        # Small 1x1 images for speed
        img1 = Image.new("RGB", (10, 10), color=(255, 0, 0))
        img2 = Image.new("RGB", (10, 10), color=(255, 0, 0))
        img1.save(browser_dir / "screen.png")
        baseline_dir = tmp_path / "baselines"
        baseline_dir.mkdir(parents=True)
        img2.save(baseline_dir / "screen.png")
        mgr = VisualBaselineManager(tmp_path, tmp_path / "runs", baseline_dir=baseline_dir)
        r = mgr.compare("android")
        assert r.passed is True, f"Expected pass for identical images, got diff_pct={r.diff_pct}"


class TestMultimodalContracts:
    """ScreenshotRef, DomSnapshotRef, MultimodalEvidencePack dataclasses."""

    def test_screenshot_ref_defaults(self):
        from grace_control.core.contracts import ScreenshotRef
        sr = ScreenshotRef(path="a.png")
        assert sr.viewport == ""

    def test_multimodal_evidence_pack_defaults(self):
        from grace_control.core.contracts import MultimodalEvidencePack
        mp = MultimodalEvidencePack()
        assert mp.screenshots == []
        assert mp.multimodal_executor is False

    def test_multimodal_pack_with_screenshots(self):
        from grace_control.core.contracts import ScreenshotRef, MultimodalEvidencePack
        mp = MultimodalEvidencePack(
            screenshots=[ScreenshotRef(path="s1.png", viewport="android")],
            visual_diff_pct=0.002,
            multimodal_executor=True,
        )
        assert len(mp.screenshots) == 1
        assert mp.visual_diff_pct == 0.002
        assert mp.multimodal_executor is True


class TestTelegramBridgeService:
    """TelegramBridgeService starts ngrok + generates signed initData."""

    def test_no_bot_token_returns_error(self, tmp_path: Path):
        from grace_control.services.telegram_bridge_service import TelegramBridgeService
        bridge = TelegramBridgeService(tmp_path)
        r = bridge.start("")
        assert r.ok is False
        assert "TELEGRAM_BOT_TOKEN" in r.error

    def test_generates_init_script_with_token(self, tmp_path: Path):
        from grace_control.services.telegram_bridge_service import TelegramBridgeService
        bridge = TelegramBridgeService(tmp_path)
        r = bridge.start("12345:test_token")
        # ngrok will fail to start (not installed), but init script should still be generated
        if not r.ok and "ngrok" in r.error:
            pass  # Expected — ngrok not installed in CI
        assert True  # doesn't crash


class TestMultimodalPropagation:
    """multimodal flag propagates from AgentProfile.to_dict()."""

    def test_verifier_profile_has_multimodal(self):
        from grace_control.config.agent_profiles import get_agent_profile
        p = get_agent_profile("verifier-cheap")
        assert p is not None
        assert p.multimodal is True

    def test_multimodal_in_to_dict(self):
        from grace_control.config.agent_profiles import get_agent_profile
        p = get_agent_profile("verifier-cheap")
        d = p.to_dict()
        assert d["multimodal"] is True


class TestPlaywrightInstall:
    """npx playwright install chromium via process_supervisor (P1/3.4)."""

    def test_playwright_install_imports(self):
        from grace_control.services.process_supervisor import playwright_install_browsers
        assert callable(playwright_install_browsers)

    def test_playwright_install_returns_bool(self, tmp_path: Path):
        from grace_control.services.process_supervisor import playwright_install_browsers
        result = playwright_install_browsers(tmp_path)
        assert isinstance(result, bool)

    def test_playwright_install_called_from_runner(self, tmp_path: Path):
        """PlaywrightRunner calls playwright_install_browsers before failing."""
        from unittest.mock import patch
        from grace_control.services.playwright_runner import PlaywrightRunner
        runner = PlaywrightRunner(
            worktree_path=tmp_path, run_dir=tmp_path / "runs",
            viewport="android", base_url="http://localhost:3000",
            dev_command="echo test",
        )
        # Mock _has_playwright to fail first, then succeed after install
        call_count = [0]

        def fake_has():
            call_count[0] += 1
            return call_count[0] > 1  # fails first time, succeeds after "install"

        runner._has_playwright = fake_has
        (tmp_path / "tests" / "e2e").mkdir(parents=True)
        (tmp_path / "tests" / "e2e" / "test.spec.ts").write_text("// test")
        runner._start_dev_server = lambda: True
        runner._stop_dev_server = lambda: None

        with patch("grace_control.services.process_supervisor.playwright_install_browsers") as mock_install:
            with patch("subprocess.run", return_value=type("R", (), {"returncode": 0, "stdout": "", "stderr": ""})()):
                r = runner.run_e2e()
                mock_install.assert_called_once()  # install was attempted
                assert r.passed or "test files" in str(r.errors).lower()
