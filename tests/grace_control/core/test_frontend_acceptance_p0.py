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
        assert r.passed is False, f"Expected failed, got passed={r.passed}"
        assert "no e2e test files" in str(r.errors).lower()
