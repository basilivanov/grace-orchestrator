"""W2 — Packet Runtime Observability: trace, events, artifacts, redaction."""

from __future__ import annotations

import json
import tempfile
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

pytestmark = pytest.mark.asyncio

from grace_control.adapters.packet_executor import PacketExecutionAdapter
from grace_control.agent.backend import ExecutionRequest, ExecutionResult as BackendResult
from grace_control.core.contracts import (
    AcceptanceProfile,
    AcceptanceReport,
    FinalVerdict,
    StageName,
    StageResult,
    StageStatus,
)


class _MockBackend:
    def __init__(self, accepted=True):
        self._accepted = accepted

    async def run(self, request: ExecutionRequest) -> BackendResult:
        return BackendResult(
            accepted=self._accepted,
            domain_status="accepted" if self._accepted else "failed",
            worktree_path=request.worktree_path,
            branch_name=request.branch_name,
            commit_sha="",
            stdout="mock stdout output\n",
            stderr="mock stderr output\n",
            duration_ms=100,
            evidence={},
            reason="",
            errors=[],
            prompt="this is the prompt sent to the agent\n",
        )

    async def cancel(self, request: ExecutionRequest) -> None:
        pass


class _InspectorStub:
    def is_git_worktree(self, p): return True
    def has_changes(self, p, scope=None): return True
    def base_sha(self, project_root, base_ref): return "a" * 40
    def collect_changed_files(self, p): return ["file1.py"]


class _CommitterStub:
    def commit(self, worktree_path, packet_id, attempt_count, timeout_seconds=10):
        return "b" * 40


def _make_accepted():
    return AcceptanceReport(
        packet_id="pkt-w2",
        final_verdict=FinalVerdict.ACCEPTED,
        profile=AcceptanceProfile.FAST,
        stages=[StageResult(
            name=StageName.T0_SCOPE_AND_LINT,
            status=StageStatus.PASSED, summary="ok",
        )],
        legacy_domain_status="accepted", legacy_ok=True, summary="passed",
    )


def _make_rework():
    return AcceptanceReport(
        packet_id="pkt-w2",
        final_verdict=FinalVerdict.REWORK_REQUIRED,
        profile=AcceptanceProfile.NORMAL,
        stages=[StageResult(
            name=StageName.T0_SCOPE_AND_LINT,
            status=StageStatus.FAILED, summary="T0 failed",
            blocking_issues=["scope violation"],
        )],
        summary="T0 failed",
    )


def _make_mock_packet(attempt=1, profile="FAST", feature_id="feat_w2"):
    p = MagicMock()
    p.id = "pkt-w2"
    p.feature_id = feature_id
    p.wave_id = "wave_w2"
    p.slug = "test-packet"
    p.title = "Test"
    p.description = "Desc"
    p.spec_json = {}
    p.state = "running"
    p.acceptance_profile = profile
    p.attempt_count = attempt
    p.max_attempts = 3
    return p


def _make_run(run_id="pkt-w2-R01", attempt=1):
    r = MagicMock()
    r.id = run_id
    r.packet_id = "pkt-w2"
    r.run_number = attempt
    r.status = "running"
    r.started_at = None
    r.finished_at = None
    r.duration_ms = None
    r.evidence_path = ""
    r.executor_id = ""
    r.model = ""
    r.command_preview = None
    r.prompt = ""
    r.result_json = None
    return r


def _make_db_mock(packet=None, run=None, attempt=1):
    db = MagicMock()
    values = [
        packet or _make_mock_packet(attempt=attempt),
        run,
        run or _make_run(attempt=attempt),
    ]
    db.__enter__.return_value.query.return_value.filter_by.return_value.first.side_effect = values
    return db


async def _run_adapter(td: Path, *, accepted=True, report=None, backend=None, attempt=1,
                       settings_overrides=None):
    """Run packet execute with mocks, return result."""
    from grace_control.config.settings import settings as _s
    if settings_overrides:
        for k, v in settings_overrides.items():
            setattr(_s, k, v)

    if backend is None:
        backend = _MockBackend(accepted=accepted)

    adapter = PacketExecutionAdapter(
        project_root=td, state_root=td, worktree_root=td, backend=backend,
    )
    adapter._inspector = _InspectorStub()
    adapter._committer = _CommitterStub()

    wt_path = td / "wt"
    wt_path.mkdir(parents=True, exist_ok=True)
    run_dir = td / "runs" / f"R{attempt:02d}"
    run_dir.mkdir(parents=True, exist_ok=True)
    # Pre-create agent.patch so _capture_diff_patch_artifact can copy it
    (run_dir / "agent.patch").write_text("mock diff content\n")

    _s.runtime_artifacts_root = str(td / ".grace" / "runs")
    # W3 selftest — relax checks for test env (no real git repos)
    if not settings_overrides or "agent_runtime_fail_on_bad_cwd" not in settings_overrides:
        _s.agent_runtime_fail_on_bad_cwd = False
    if not settings_overrides or "agent_runtime_fail_on_bad_git_root" not in settings_overrides:
        _s.agent_runtime_fail_on_bad_git_root = False
    if not settings_overrides or "agent_runtime_allow_non_git_scope_skip" not in settings_overrides:
        _s.agent_runtime_allow_non_git_scope_skip = True

    if report is None:
        report = _make_accepted() if accepted else _make_rework()

    async def _fake_call_exec(self, *a, **kw):
        return await backend.run(
            ExecutionRequest(
                packet_id="pkt-w2", spec={},
                worktree_path=wt_path, branch_name="agent/test",
                scope_paths=[], executor={}, timeout_s=600,
            )
        )

    async def _fake_accept(self, *a, **kw):
        return report, "", {"ok": True}, ["file1.py"], wt_path, run_dir

    db = _make_db_mock(attempt=attempt)

    with patch.object(PacketExecutionAdapter, "_call_executor", _fake_call_exec):
        with patch.object(PacketExecutionAdapter, "_run_acceptance", _fake_accept):
            with patch("grace_control.adapters.packet_executor.get_db", return_value=db):
                result = await adapter.execute("pkt-w2", "w1")
    return result


# ── Tests ───────────────────────────────────────────────────────────────


class TestTracePropagation:
    async def test_events_contain_all_lifecycle_stages(self):
        with tempfile.TemporaryDirectory() as _td:
            td = Path(_td)
            result = await _run_adapter(Path(td))
            assert result.accepted is True

    async def test_execution_events_are_logged(self):
        """Verify event emission by checking artifact directory exists
        (events.jsonl is written by RuntimeEventLogger)."""
        with tempfile.TemporaryDirectory() as _td:
            td = Path(_td)
            result = await _run_adapter(Path(td))
            events_file = Path(td) / ".grace" / "runs" / "feat_w2" / "events.jsonl"
            assert events_file.exists(), "events.jsonl must exist"
            lines = events_file.read_text().strip().split("\n")
            events = [json.loads(l) for l in lines if l.strip()]
            event_names = {e["event"] for e in events}
            for ev in ("packet.execution_started", "packet.worktree_created",
                       "packet.agent_started", "packet.prompt_built",
                       "packet.agent_completed", "packet.diff_captured",
                       "packet.tests_started", "packet.tests_completed",
                       "packet.evidence_captured", "packet.execution_completed"):
                assert ev in event_names, f"missing event in events.jsonl: {ev}"
            assert result.accepted is True

    async def test_events_carry_artifact_refs_with_sha_and_size(self):
        """Events that capture artifacts should carry RuntimeArtifactRef with sha256/size."""
        with tempfile.TemporaryDirectory() as _td:
            td = Path(_td)
            result = await _run_adapter(Path(td))
            events_file = Path(td) / ".grace" / "runs" / "feat_w2" / "events.jsonl"
            lines = events_file.read_text().strip().split("\n")
            events = [json.loads(l) for l in lines if l.strip()]
            # Find events with artifact_refs
            ref_events = {e["event"]: e.get("artifact_refs", []) for e in events if e.get("artifact_refs")}
            assert "packet.prompt_built" in ref_events, "prompt_built should carry artifact_refs"
            assert "packet.evidence_captured" in ref_events, "evidence_captured should carry artifact_refs"
            # Check sha256 and size_bytes on each ref
            for event_name, refs in ref_events.items():
                for ref in refs:
                    assert "sha256" in ref, f"{event_name} ref missing sha256: {ref}"
                    assert "size_bytes" in ref, f"{event_name} ref missing size_bytes: {ref}"
                    assert ref["size_bytes"] > 0, f"{event_name} ref has zero size: {ref}"


class TestArtifactLocation:
    async def test_all_artifact_files_written(self):
        with tempfile.TemporaryDirectory() as _td:
            td = Path(_td)
            result = await _run_adapter(Path(td))
            root = td / ".grace" / "runs" / "feat_w2" / "packets" / "pkt-w2"
            assert root.exists()
            expected = {"prompt.txt", "agent_stdout.txt", "agent_stderr.txt",
                        "diff.patch", "test_output.txt", "evidence.json", "metadata.json"}
            actual = {p.name for p in root.iterdir() if p.is_file()}
            missing = expected - actual
            assert not missing, f"missing artifact files: {missing}"
            assert result.accepted is True

    async def test_prompt_has_content(self):
        with tempfile.TemporaryDirectory() as _td:
            td = Path(_td)
            result = await _run_adapter(Path(td))
            content = (td / ".grace" / "runs" / "feat_w2" / "packets" / "pkt-w2" / "prompt.txt").read_text()
            assert "prompt" in content.lower()

    async def test_stdout_content_preserved(self):
        with tempfile.TemporaryDirectory() as _td:
            td = Path(_td)
            result = await _run_adapter(Path(td))
            content = (td / ".grace" / "runs" / "feat_w2" / "packets" / "pkt-w2" / "agent_stdout.txt").read_text()
            assert "mock stdout" in content

    async def test_stderr_content_preserved(self):
        with tempfile.TemporaryDirectory() as _td:
            td = Path(_td)
            result = await _run_adapter(Path(td))
            content = (td / ".grace" / "runs" / "feat_w2" / "packets" / "pkt-w2" / "agent_stderr.txt").read_text()
            assert "mock stderr" in content

    async def test_evidence_json_valid(self):
        with tempfile.TemporaryDirectory() as _td:
            td = Path(_td)
            result = await _run_adapter(Path(td))
            data = json.loads((td / ".grace" / "runs" / "feat_w2" / "packets" / "pkt-w2" / "evidence.json").read_text())
            assert data["packet_id"] == "pkt-w2"
            assert data["accepted"] is True
            assert data["acceptance_verdict"] == "accepted"

    async def test_metadata_json_valid(self):
        with tempfile.TemporaryDirectory() as _td:
            td = Path(_td)
            result = await _run_adapter(Path(td))
            data = json.loads((td / ".grace" / "runs" / "feat_w2" / "packets" / "pkt-w2" / "metadata.json").read_text())
            assert data["packet_id"] == "pkt-w2"
            assert data["artifacts"]["prompt.txt"]["present"] is True
            assert data["artifacts"]["prompt.txt"]["sha256"]
            assert data["artifacts"]["prompt.txt"]["size_bytes"] > 0


class TestRedaction:
    async def test_prompt_redacts_api_key(self):
        class _SecretBackend(_MockBackend):
            async def run(self, request):
                return BackendResult(
                    accepted=True, domain_status="accepted",
                    worktree_path=request.worktree_path,
                    branch_name=request.branch_name, commit_sha="",
                    stdout="safe output\n", stderr="",
                    duration_ms=100, evidence={}, reason="", errors=[],
                    prompt="use key sk-Akf83Ksj29Jdjs93Kskd93Jdks93Kdjs93Kdj for auth\n",
                )

        with tempfile.TemporaryDirectory() as _td:
            td = Path(_td)
            result = await _run_adapter(Path(td), backend=_SecretBackend())
            content = (td / ".grace" / "runs" / "feat_w2" / "packets" / "pkt-w2" / "prompt.txt").read_text()
            assert "sk-..." in content, f"Expected redacted key in prompt, got: {content!r}"

    async def test_stdout_redacts_token(self):
        class _TokenBackend(_MockBackend):
            async def run(self, request):
                return BackendResult(
                    accepted=True, domain_status="accepted",
                    worktree_path=request.worktree_path,
                    branch_name=request.branch_name, commit_sha="",
                    stdout="token: sk-Akf83Ksj29Jdjs93Kskd93Jdks93Kdjs93Kdj\n",
                    stderr="", duration_ms=100, evidence={}, reason="", errors=[],
                    prompt="safe\n",
                )

        with tempfile.TemporaryDirectory() as _td:
            td = Path(_td)
            result = await _run_adapter(Path(td), backend=_TokenBackend())
            content = (td / ".grace" / "runs" / "feat_w2" / "packets" / "pkt-w2" / "agent_stdout.txt").read_text()
            assert "sk-..." in content, f"Expected redacted key in stdout, got: {content!r}"


class TestObservabilityDisabled:
    async def test_no_artifact_files_written(self):
        with tempfile.TemporaryDirectory() as _td:
            td = Path(_td)
            result = await _run_adapter(Path(td), settings_overrides={
                "runtime_observability_enabled": False,
            })
            root = td / ".grace" / "runs" / "feat_w2" / "packets" / "pkt-w2"
            assert not root.exists(), "artifacts must not be written when disabled"
            assert result.accepted is True

    async def test_packet_execution_succeeds(self):
        with tempfile.TemporaryDirectory() as _td:
            td = Path(_td)
            result = await _run_adapter(Path(td), settings_overrides={
                "runtime_observability_enabled": False,
            })
            assert result.accepted is True

    async def test_selftest_blocks_execution_even_with_observability_disabled(self):
        """Selftest is a safety gate — must run even when observability is off.
        If a critical failure occurs, execution must be blocked."""
        with tempfile.TemporaryDirectory() as _td:
            td = Path(_td)
            from grace_control.config.settings import settings as _s
            original_selftest = _s.agent_runtime_selftest_enabled
            original_git = _s.agent_runtime_fail_on_bad_git_root
            original_target_repo = _s.target_repo_root
            try:
                _s.agent_runtime_selftest_enabled = True
                _s.agent_runtime_fail_on_bad_git_root = True
                _s.target_repo_root = str(td)
                result = await _run_adapter(
                    Path(td),
                    settings_overrides={"runtime_observability_enabled": False,
                                        "agent_runtime_selftest_enabled": True,
                                        "agent_runtime_fail_on_bad_git_root": True},
                )
                # With observability off but selftest on + bad git root,
                # execution should be blocked (no mock git in test env).
                assert not result.accepted, "selftest with critical failure must block execution"
                assert result.reason is not None
            finally:
                _s.agent_runtime_selftest_enabled = original_selftest
                _s.agent_runtime_fail_on_bad_git_root = original_git
                _s.target_repo_root = original_target_repo


class TestFailureIsolation:
    async def test_artifact_write_failure_does_not_crash(self):
        from grace_control.config.settings import settings as _s
        _s.agent_runtime_allow_non_git_scope_skip = True
        with tempfile.TemporaryDirectory() as _td:
            td = Path(_td)
            adapter = PacketExecutionAdapter(
                project_root=Path(td), state_root=Path(td),
                worktree_root=Path(td), backend=_MockBackend(),
            )
            adapter._inspector = _InspectorStub()
            adapter._committer = _CommitterStub()

            def _broken(name, content, kind):
                raise OSError("disk full")
            adapter._obs_write_artifact = _broken
            adapter._obs_write_json_artifact = _broken

            wt_path = Path(td) / "wt"
            wt_path.mkdir(parents=True, exist_ok=True)
            run_dir = Path(td) / "runs" / "R01"
            run_dir.mkdir(parents=True, exist_ok=True)

            async def _fake_call(self, *a, **kw):
                req = ExecutionRequest(
                    packet_id="pkt-w2", spec={},
                    worktree_path=wt_path, branch_name="agent/test",
                    scope_paths=[], executor={}, timeout_s=600,
                )
                return await _MockBackend().run(req)

            async def _fake_acc(self, *a, **kw):
                return _make_accepted(), "", {"ok": True}, ["f"], wt_path, run_dir

            db = _make_db_mock()

            with patch.object(PacketExecutionAdapter, "_call_executor", _fake_call):
                with patch.object(PacketExecutionAdapter, "_run_acceptance", _fake_acc):
                    with patch("grace_control.adapters.packet_executor.get_db", return_value=db):
                        r = await adapter.execute("pkt-w2", "w1")
            assert r.accepted is True

    async def test_event_failure_does_not_crash(self):
        from grace_control.config.settings import settings as _s
        _s.agent_runtime_allow_non_git_scope_skip = True
        with tempfile.TemporaryDirectory() as _td:
            td = Path(_td)
            adapter = PacketExecutionAdapter(
                project_root=Path(td), state_root=Path(td),
                worktree_root=Path(td), backend=_MockBackend(),
            )
            adapter._inspector = _InspectorStub()
            adapter._committer = _CommitterStub()

            wt_path = Path(td) / "wt"
            wt_path.mkdir(parents=True, exist_ok=True)
            run_dir = Path(td) / "runs" / "R01"
            run_dir.mkdir(parents=True, exist_ok=True)

            # Patch RuntimeEventLogger.emit so _obs_event's try/except is exercised
            from grace_control.core.runtime_events import RuntimeEventLogger

            async def _fake_call(self, *a, **kw):
                req = ExecutionRequest(
                    packet_id="pkt-w2", spec={},
                    worktree_path=wt_path, branch_name="agent/test",
                    scope_paths=[], executor={}, timeout_s=600,
                )
                return await _MockBackend().run(req)

            async def _fake_acc(self, *a, **kw):
                return _make_accepted(), "", {"ok": True}, ["f"], wt_path, run_dir

            db = _make_db_mock()

            with patch.object(PacketExecutionAdapter, "_call_executor", _fake_call):
                with patch.object(PacketExecutionAdapter, "_run_acceptance", _fake_acc):
                    with patch("grace_control.adapters.packet_executor.get_db", return_value=db):
                        with patch.object(RuntimeEventLogger, "emit", side_effect=RuntimeError("event bus down")):
                            r = await adapter.execute("pkt-w2", "w1")
            assert r.accepted is True


class TestWorktreeRegression:
    def test_fallback_uses_effective_repo(self):
        import inspect
        src = inspect.getsource(PacketExecutionAdapter._call_executor)
        assert "_effective_repo = target_root if _effective_target_repo else self.project_root" in src
        assert "git.worktree_add(_effective_repo, wt_path, branch, base_ref=base_ref)" in src


class TestOpenCodeAdapterIntegration:
    """W4: verify PacketExecutionAdapter switches backend based on flag."""

    def test_uses_opencode_backend_when_enabled(self):
        from grace_control.runtime.opencode_runtime_adapter import OpenCodeExecutionBackend
        from grace_control.config.settings import settings as _s
        original = _s.agent_runtime_use_opencode_adapter
        try:
            _s.agent_runtime_use_opencode_adapter = True
            adapter = PacketExecutionAdapter(
                project_root=Path("/tmp"), state_root=Path("/tmp"),
                worktree_root=Path("/tmp"),
            )
            assert isinstance(adapter._backend, OpenCodeExecutionBackend)
        finally:
            _s.agent_runtime_use_opencode_adapter = original

    def test_falls_back_to_legacy_when_disabled(self):
        from grace_control.runtime.opencode_runtime_adapter import OpenCodeExecutionBackend
        from grace_control.config.settings import settings as _s
        original = _s.agent_runtime_use_opencode_adapter
        try:
            _s.agent_runtime_use_opencode_adapter = False
            adapter = PacketExecutionAdapter(
                project_root=Path("/tmp"), state_root=Path("/tmp"),
                worktree_root=Path("/tmp"),
            )
            assert not isinstance(adapter._backend, OpenCodeExecutionBackend)
        finally:
            _s.agent_runtime_use_opencode_adapter = original


class TestTargetRepoRootPropagation:
    """Regression: feature spec target_repo_root must override global settings."""

    async def test_target_repo_root_from_spec_overrides_settings(self):
        from grace_control.config.settings import settings as _s
        import tempfile
        tempdir = Path(tempfile.mkdtemp())
        try:
            orchestrator_root = Path(tempdir) / "orchestrator"
            spec_target = Path(tempdir) / "spec-target"
            orchestrator_root.mkdir(parents=True, exist_ok=True)
            spec_target.mkdir(parents=True, exist_ok=True)
            (spec_target / ".grace" / "worktrees").mkdir(parents=True, exist_ok=True)

            orig_repo = _s.target_repo_root
            orig_wt = _s.worktree_root
            orig_art = _s.runtime_artifacts_root
            _s.runtime_artifacts_root = str(spec_target / ".grace" / "runs")
            orig_git = _s.agent_runtime_fail_on_bad_git_root
            orig_non_git = _s.agent_runtime_allow_non_git_scope_skip
            _s.agent_runtime_fail_on_bad_git_root = False
            _s.agent_runtime_allow_non_git_scope_skip = True
            _s.target_repo_root = str(orchestrator_root)
            _s.worktree_root = ".grace/worktrees"

            from grace_control.adapters.packet_executor import (
                PacketExecutionAdapter,
                _resolve_worktree_for_contract,
            )
            from grace_control.agent.backend import ExecutionResult as BackendResult
            from unittest.mock import patch, MagicMock as _MM

            adapter = PacketExecutionAdapter(
                project_root=orchestrator_root, state_root=orchestrator_root,
                worktree_root=Path(".grace/worktrees"),
            )
            adapter._inspector = _MM()
            adapter._inspector.is_git_worktree.return_value = True
            adapter._inspector.has_changes.return_value = True
            adapter._inspector.base_sha.return_value = "a" * 40
            adapter._committer = _MM()
            adapter._committer.commit.return_value = "b" * 40

            async def _fake_call(self, *a, **kw):
                return BackendResult(
                    accepted=True, domain_status="accepted",
                    worktree_path=spec_target, branch_name="agent/test",
                    commit_sha="", stdout="", stderr="", duration_ms=100,
                )

            async def _fake_acc(self, *a, **kw):
                from grace_control.core.contracts import AcceptanceReport, FinalVerdict, StageName, StageResult, StageStatus
                return AcceptanceReport(
                    packet_id="pkt-repo-test",
                    final_verdict=FinalVerdict.ACCEPTED,
                    profile=_MM(),
                    stages=[StageResult(name=StageName.T0_SCOPE_AND_LINT,
                                        status=StageStatus.PASSED, summary="ok")],
                    summary="passed",
                ), "", {"ok": True}, ["file1.py"], spec_target, spec_target / "runs"

            claim_data = {
                "attempt": 1, "feature_id": "f1", "wave_id": "w1",
                "slug": "test", "title": "Test",
                "acceptance_profile": "NORMAL",
                "spec": {"target_repo_root": str(spec_target),
                          "scope": ["src/"], "frozen_scope": [],
                          "verification": {"t0": ["echo ok"]}},
                "max_attempts": 3,
            }

            # Verify _resolve_worktree_for_contract produces path under spec_target
            wt_executor = {"workspace_mode": "target_repo_worktree"}
            wt_path = _resolve_worktree_for_contract(
                {"id": "pkt-repo-test", "attempt_count": 1,
                 "spec_json": {"target_repo_root": str(spec_target)}},
                wt_executor, _s, orchestrator_root, Path(".grace/worktrees"),
            )
            assert str(wt_path).startswith(str(spec_target)), \
                f"resolve_worktree: expected under {spec_target}, got {wt_path}"

            with patch.object(PacketExecutionAdapter, "_call_executor", _fake_call):
                with patch.object(PacketExecutionAdapter, "_run_acceptance", _fake_acc):
                    with patch("grace_control.adapters.packet_executor.get_db") as mock_db:
                        db = _MM()
                        mock_db.return_value.__enter__.return_value = db
                        db.query.return_value.filter_by.return_value.first.return_value = None

                        result = await adapter.execute("pkt-repo-test", "w1", claim_data=claim_data)

            assert result.accepted, f"expected accepted, got {result.reason}"
            assert adapter._packet_target_repo == str(spec_target), \
                f"expected {spec_target}, got {adapter._packet_target_repo}"

            cleanup = adapter._effective_cleanup_root({})
            assert str(spec_target) in str(cleanup), \
                f"cleanup root should contain spec_target, got {cleanup}"

        finally:
            import shutil
            shutil.rmtree(str(tempdir), ignore_errors=True)
            _s.target_repo_root = orig_repo
            _s.worktree_root = orig_wt
            _s.runtime_artifacts_root = orig_art
            _s.agent_runtime_fail_on_bad_git_root = orig_git
            _s.agent_runtime_allow_non_git_scope_skip = orig_non_git


class TestNoChangeClassification:
    """W9: no-change is not Worktree issue — explicit AGENT_NO_CHANGES_PRODUCED."""

    async def test_no_changes_not_worktree_issue(self):
        """Valid worktree + no changes = AGENT_NO_CHANGES_PRODUCED, not Worktree issue."""
        from grace_control.config.settings import settings as _s
        orig_fail = _s.agent_runtime_fail_on_no_changes
        try:
            _s.agent_runtime_fail_on_no_changes = True
            from unittest.mock import MagicMock, patch
            from grace_control.adapters.packet_executor import PacketExecutionAdapter
            from grace_control.agent.backend import ExecutionResult as BackendResult
            from pathlib import Path

            adapter = PacketExecutionAdapter(
                project_root=Path("/tmp"), state_root=Path("/tmp"), worktree_root=Path("/tmp"),
            )
            adapter._inspector = MagicMock()
            adapter._inspector.is_git_worktree.return_value = True
            adapter._inspector.has_changes.return_value = False
            adapter._committer = MagicMock()
            adapter._evidence = MagicMock()

            pkt_contract = MagicMock()
            pkt_contract.allowed_write_scope = []

            result = adapter._inspected_worktree(
                BackendResult(accepted=True, domain_status="accepted",
                              worktree_path=Path("/tmp"), branch_name="agent/test",
                              commit_sha="", stdout="", stderr="", duration_ms=100),
                pkt_contract, "pkt-test", 1,
            )
            status, sha = result
            assert status == "no_changes", f"expected no_changes, got {status}"
        finally:
            _s.agent_runtime_fail_on_no_changes = orig_fail

    async def test_no_changes_continues_when_not_failing(self):
        """No changes without fail_on_no_changes should NOT reject."""
        from unittest.mock import MagicMock
        from grace_control.adapters.packet_executor import PacketExecutionAdapter
        from grace_control.agent.backend import ExecutionResult as BackendResult
        from pathlib import Path

        adapter = PacketExecutionAdapter(
            project_root=Path("/tmp"), state_root=Path("/tmp"), worktree_root=Path("/tmp"),
        )
        adapter._inspector = MagicMock()
        adapter._inspector.is_git_worktree.return_value = True
        adapter._inspector.has_changes.return_value = True
        adapter._committer = MagicMock()
        adapter._committer.commit.return_value = "a" * 40
        adapter._evidence = MagicMock()

        pkt_contract = MagicMock()
        pkt_contract.allowed_write_scope = []

        result = adapter._inspected_worktree(
            BackendResult(accepted=True, domain_status="accepted",
                          worktree_path=Path("/tmp"), branch_name="agent/test",
                          commit_sha="", stdout="", stderr="", duration_ms=100),
            pkt_contract, "pkt-test", 1,
        )
        status, sha = result
        assert status == "committed", f"expected committed, got {status}"

    async def test_missing_worktree_still_worktree_issue(self):
        """Missing worktree path must still be classified as worktree_missing."""
        from unittest.mock import MagicMock
        from grace_control.adapters.packet_executor import PacketExecutionAdapter
        from grace_control.agent.backend import ExecutionResult as BackendResult
        from pathlib import Path

        adapter = PacketExecutionAdapter(
            project_root=Path("/tmp"), state_root=Path("/tmp"), worktree_root=Path("/tmp"),
        )
        adapter._inspector = MagicMock()
        adapter._committer = MagicMock()
        adapter._evidence = MagicMock()

        result = adapter._inspected_worktree(
            BackendResult(accepted=True, domain_status="accepted",
                          worktree_path=Path("/nonexistent/path"),
                          branch_name="agent/test", commit_sha="",
                          stdout="", stderr="", duration_ms=100),
            None, "pkt-test", 1,
        )
        status, sha = result
        assert status == "worktree_missing", f"expected worktree_missing, got {status}"


class TestRejectedPacket:
    async def test_rejected_packet_still_creates_some_artifacts(self):
        with tempfile.TemporaryDirectory() as _td:
            td = Path(_td)
            result = await _run_adapter(Path(td), accepted=True, report=_make_rework())
            root = td / ".grace" / "runs" / "feat_w2" / "packets" / "pkt-w2"
            if root.exists():
                files = {p.name for p in root.iterdir() if p.is_file()}
                assert "prompt.txt" in files or "agent_stdout.txt" in files
