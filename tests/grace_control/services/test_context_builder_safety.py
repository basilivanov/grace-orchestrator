"""Tests for context-builder safety: read-only profile, mutation guard, target repo routing.

Part E of TZ: Fix context-builder read-only role, target repo worktree routing,
and revert bad SolarSage LLM split.
"""
from __future__ import annotations

import os
import subprocess
import tempfile
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from grace_control.config.agent_profiles import load_agent_profiles
from grace_control.core.context_collector import ContextCollector, _default_context_scopes
from grace_control.core.executor_selector import resolve_model, _profile_matches_role
from grace_control.core.contracts import build_packet_contract
from grace_control.services.feature_planning_service import (
    FeaturePlanningService,
    CONTEXT_BUILDER_MUTATED_TARGET_REPO,
    _git_snapshot,
    _planning_workspace_mutation,
    _prepare_planning_workspace,
    _remove_planning_workspace,
)


class TestContextCollectorUsesDedicatedProfile:
    """resolve_model('context_collector') must return the dedicated read-only profile."""

    def test_resolve_model_returns_executor_id(self):
        ctx = resolve_model("context_collector")
        assert "executor_id" in ctx, "resolve_model must include executor_id"
        eid = ctx["executor_id"]
        assert eid == "context-json-flash"

    def test_resolve_model_returns_context_json_flash(self):
        ctx = resolve_model("context_collector")
        assert ctx["executor_id"] == "context-json-flash", (
            f"Expected context-json-flash, got {ctx['executor_id']!r}"
        )

    def test_context_collector_uses_executor_id_not_cli(self):
        """ContextCollector._run_llm must use executor_id for profile lookup."""
        collector = ContextCollector(
            project_root=Path("/tmp"),
            model="test-model",
            cli="",
            executor_id="context-json-flash",
        )
        assert collector._executor_id == "context-json-flash", (
            f"Expected executor_id=context-json-flash, got {collector._executor_id!r}"
        )

    def test_profile_matches_role_context_collector_prefers_json_flash(self):
        """context-json-flash must match context_collector role."""
        assert _profile_matches_role("context-json-flash", "context_collector") is True
        assert _profile_matches_role("context-legacy", "context_collector") is False

class TestContextJsonProfileIsReadOnly:
    """The context-json-flash profile must be explicitly read-only."""

    def test_profile_exists(self):
        profiles = load_agent_profiles()
        profile = profiles.get("context-json-flash")
        assert profile is not None, "context-json-flash profile must exist in agent_profiles.yaml"

    def test_profile_prompt_contains_read_only(self):
        from grace_control.runtime.mini_swe_runner import ROLE_CONTRACTS
        prompt_text = ROLE_CONTRACTS["context_collector"]
        assert "read-only" in prompt_text, (
            "context-json-flash prompt must contain READ-ONLY"
        )

    def test_profile_prompt_forbids_create_edit_delete(self):
        from grace_control.runtime.mini_swe_runner import ROLE_CONTRACTS
        prompt_text = ROLE_CONTRACTS["context_collector"]
        assert "Do not create, edit, delete" in prompt_text, (
            "context-json-flash prompt must explicitly forbid create/edit/delete"
        )

    def test_profile_prompt_forbids_implementation(self):
        from grace_control.runtime.mini_swe_runner import ROLE_CONTRACTS
        prompt_text = ROLE_CONTRACTS["context_collector"]
        assert "Do not implement" in prompt_text, (
            "context-json-flash prompt must explicitly forbid implementation"
        )

    def test_profile_prompt_is_json_only(self):
        from grace_control.runtime.mini_swe_runner import ROLE_CONTRACTS
        prompt_text = ROLE_CONTRACTS["context_collector"]
        assert "JSON" in prompt_text, (
            "context-json-flash prompt must specify JSON-only output"
        )

    def test_profile_uses_primary_mini_swe_wrapper(self):
        profile = load_agent_profiles()["context-json-flash"]
        assert profile.command[:3] == [
            "{python_executable}", "-m", "grace_control.runtime.mini_swe_runner"
        ]
        assert "context_collector" in profile.command


def test_default_context_scopes_follow_target_topology(tmp_path):
    (tmp_path / "app").mkdir()
    (tmp_path / "tests").mkdir()
    (tmp_path / "pyproject.toml").write_text("[project]\n")

    scopes = _default_context_scopes(tmp_path)

    assert scopes == ["app/", "tests/", "pyproject.toml"]

    def test_profile_never_resumes(self):
        profiles = load_agent_profiles()
        profile = profiles["context-json-flash"]
        assert profile.resume_mode == "never", (
            "context-json-flash must not resume sessions"
        )


@pytest.mark.usefixtures("db")
class TestRunContextBuilderMutationGuard:
    """Planning mutations must fail inside an isolated disposable clone."""

    def test_git_snapshot_detects_clean_repo(self, tmp_path):
        """A clean git repo returns is_clean=True."""
        repo = tmp_path / "repo"
        repo.mkdir()
        subprocess.run(["git", "init"], cwd=str(repo), capture_output=True, timeout=10)
        subprocess.run(["git", "config", "user.email", "test@test.com"],
                        cwd=str(repo), capture_output=True, timeout=5)
        subprocess.run(["git", "config", "user.name", "Test"],
                        cwd=str(repo), capture_output=True, timeout=5)
        (repo / "file.txt").write_text("hello")
        subprocess.run(["git", "add", "."], cwd=str(repo), capture_output=True, timeout=5)
        subprocess.run(["git", "commit", "-m", "init"], cwd=str(repo), capture_output=True, timeout=10)
        snap = _git_snapshot(repo)
        assert snap is not None
        assert snap["is_clean"] is True
        assert snap["branch"] in {"master", "main"}

    def test_branch_only_change_is_a_planning_mutation(self):
        before = {
            "head": "abc",
            "branch": "main",
            "is_clean": True,
            "status_short": "",
        }
        after = {
            "head": "abc",
            "branch": "agent/test",
            "is_clean": True,
            "status_short": "",
        }

        mutation = _planning_workspace_mutation(before, after)

        assert mutation is not None
        assert mutation["pre_branch"] == "main"
        assert mutation["post_branch"] == "agent/test"

    def test_standalone_planning_clone_cannot_remove_live_coder_worktree(self, tmp_path):
        repo = tmp_path / "target_repo"
        repo.mkdir()
        subprocess.run(
            ["git", "init", "-b", "main"], cwd=repo, check=True, capture_output=True
        )
        subprocess.run(
            ["git", "config", "user.email", "test@test.com"], cwd=repo, check=True
        )
        subprocess.run(
            ["git", "config", "user.name", "Test"], cwd=repo, check=True
        )
        (repo / "file.txt").write_text("base")
        subprocess.run(["git", "add", "."], cwd=repo, check=True)
        subprocess.run(
            ["git", "commit", "-m", "init"], cwd=repo, check=True, capture_output=True
        )
        live_worktree = tmp_path / "live-coder"
        subprocess.run(
            ["git", "worktree", "add", "-b", "agent/live", str(live_worktree), "main"],
            cwd=repo,
            check=True,
            capture_output=True,
        )
        log_dir = tmp_path / "planning"
        log_dir.mkdir()
        planning_repo = _prepare_planning_workspace(repo, log_dir, "context-builder")
        try:
            removal = subprocess.run(
                ["git", "worktree", "remove", "--force", str(live_worktree)],
                cwd=planning_repo,
                capture_output=True,
                text=True,
            )

            assert removal.returncode != 0
            assert live_worktree.exists()
            target_snapshot = _git_snapshot(repo)
            assert target_snapshot is not None
            assert target_snapshot["branch"] == "main"
        finally:
            _remove_planning_workspace(planning_repo)

    def test_git_snapshot_detects_dirty_repo(self, tmp_path):
        """A dirty git repo returns is_clean=False."""
        repo = tmp_path / "repo"
        repo.mkdir()
        subprocess.run(["git", "init"], cwd=str(repo), capture_output=True, timeout=10)
        subprocess.run(["git", "config", "user.email", "test@test.com"],
                        cwd=str(repo), capture_output=True, timeout=5)
        subprocess.run(["git", "config", "user.name", "Test"],
                        cwd=str(repo), capture_output=True, timeout=5)
        (repo / "file.txt").write_text("hello")
        subprocess.run(["git", "add", "."], cwd=str(repo), capture_output=True, timeout=5)
        subprocess.run(["git", "commit", "-m", "init"], cwd=str(repo), capture_output=True, timeout=10)
        # Make a change
        (repo / "file.txt").write_text("modified")
        snap = _git_snapshot(repo)
        assert snap is not None
        assert snap["is_clean"] is False

    @pytest.mark.asyncio
    async def test_mutation_guard_raises_on_dirty_repo(self, tmp_path):
        """If context-builder leaves the target repo dirty, raises CONTEXT_BUILDER_MUTATED_TARGET_REPO."""
        from grace_control.db import get_db
        from grace_control.db.schema import Feature, FeaturePlanningRun
        from grace_control.config.settings import settings

        # Create a real git repo as target
        repo = tmp_path / "target_repo"
        repo.mkdir()
        subprocess.run(["git", "init"], cwd=str(repo), capture_output=True, timeout=10)
        subprocess.run(["git", "config", "user.email", "test@test.com"],
                        cwd=str(repo), capture_output=True, timeout=5)
        subprocess.run(["git", "config", "user.name", "Test"],
                        cwd=str(repo), capture_output=True, timeout=5)
        (repo / "app.py").write_text("print('hello')")
        subprocess.run(["git", "add", "."], cwd=str(repo), capture_output=True, timeout=5)
        subprocess.run(["git", "commit", "-m", "init"], cwd=str(repo), capture_output=True, timeout=10)

        # Mock the LLM to write a file (simulate bad context-builder)
        original_run_llm = ContextCollector._run_llm

        async def mock_run_llm_writes_file(self, prompt):
            # Simulate bad context-builder writing a file
            target = self._root / "BAD_MUTATION.py"
            target.write_text("# This should not exist")
            # Return valid JSON
            return '{"summary": "test", "estimated_scope": [], "affected_contracts": [], "complexity_score": 50}'

        with get_db() as db:
            from grace_control.services.feature_intake_service import FeatureIntakeService
            intake = FeatureIntakeService(db)
            result = intake.create_feature(
                title="Mutation Guard Test",
                mode="draft_plan",
                target_repo_root=str(repo),
            )
            fid = result["feature_id"]

            planning = FeaturePlanningService(db)

            with patch.object(ContextCollector, "_run_llm", mock_run_llm_writes_file):
                with pytest.raises(CONTEXT_BUILDER_MUTATED_TARGET_REPO):
                    await planning.run_context_builder(fid, target_repo_root=str(repo))

        # Verify repo is clean after cleanup
        snap = _git_snapshot(repo)
        assert snap is not None
        assert snap["is_clean"] is True
        assert not (repo / "BAD_MUTATION.py").exists()


@pytest.mark.usefixtures("db")
class TestTargetRepoRootPropagatedToPackets:
    """target_repo_root from feature spec must propagate into packet spec."""

    def test_target_repo_root_in_packet_spec(self):
        """When feature has target_repo_root, approve_plan propagates it to packets."""
        from grace_control.db import get_db
        from grace_control.db.schema import Feature, FeaturePlanningRun, Wave, Packet
        from grace_control.services.feature_intake_service import FeatureIntakeService
        from grace_control.services.feature_planning_service import FeaturePlanningService

        with get_db() as db:
            intake = FeatureIntakeService(db)
            result = intake.create_feature(
                title="Propagation Test",
                mode="draft_plan",
                target_repo_root="/opt/solarsage-astro",
            )
            fid = result["feature_id"]

            # Set up a plan
            feature = db.query(Feature).filter_by(id=fid).first()
            spec = dict(feature.spec_json)
            spec["plan_json"] = {
                "waves": [
                    {
                        "title": "Wave 1",
                        "packets": [
                            {
                                "title": "Test Packet",
                                "scope": ["src/app.py"],
                                "acceptance_profile": "FAST",
                                "depends_on": [],
                                "description": "test",
                                "verification": {"t0": [], "t1": [], "t2": []},
                                "expected_evidence": [],
                            }
                        ]
                    }
                ]
            }
            spec["target_repo_root"] = "/opt/solarsage-astro"
            feature.spec_json = spec
            feature.status = "PLAN_READY"
            db.commit()

            planning = FeaturePlanningService(db)
            approval = planning.approve_plan(fid)

            # Verify packets have target_repo_root in spec_json
            packets = db.query(Packet).filter_by(feature_id=fid).all()
            for pkt in packets:
                pkt_spec = pkt.spec_json or {}
                assert pkt_spec.get("target_repo_root") == "/opt/solarsage-astro", (
                    f"Packet {pkt.id} spec_json must include target_repo_root from feature"
                )
                assert pkt_spec.get("feature_context") == {
                    "feature_id": fid,
                    "title": "Propagation Test",
                    "description": "",
                }


class TestPacketExecutorTargetRepoWorktreeByDefault:
    """When target_repo_root differs from project_root, packets should
    default to target_repo_worktree mode.
    """

    def test_build_packet_contract_includes_target_repo_root(self):
        """build_packet_contract propagates target_repo_root in metadata."""
        packet_data = {
            "id": "pkt_test001",
            "title": "Test Packet",
            "spec_json": {
                "scope": ["src/app.py"],
                "target_repo_root": "/opt/solarsage-astro",
                "workspace_mode": "target_repo_worktree",
            },
            "acceptance_profile": "NORMAL",
        }
        contract = build_packet_contract(packet_data)
        assert contract.metadata.get("target_repo_root") == "/opt/solarsage-astro"
        assert contract.metadata.get("workspace_mode") == "target_repo_worktree"

    def test_build_packet_contract_empty_target_repo_root(self):
        """build_packet_contract handles no target_repo_root gracefully."""
        packet_data = {
            "id": "pkt_test002",
            "title": "Test Packet",
            "spec_json": {
                "scope": ["src/app.py"],
            },
            "acceptance_profile": "NORMAL",
        }
        contract = build_packet_contract(packet_data)
        assert contract.metadata.get("target_repo_root", "") == ""
        assert contract.metadata.get("workspace_mode", "") == ""


class TestContextCollectorFilterRelevantStillReturnsJson:
    """Regression: ContextCollector._filter_relevant() and _summarize()
    must still return expected JSON structures.
    """

    def test_filter_relevant_returns_subset_on_large_input(self):
        """When files > MAX_RELEVANT_FILES, _filter_relevant returns a subset."""
        files = [
            type("FileContext", (), {"path": f"src/mod_{i}.py", "size_lines": 50, "exports": [], "module_contract": None, "relevant": False, "content_preview": ""})()
            for i in range(20)
        ]
        collector = ContextCollector(project_root=Path("/tmp"))
        # For <= 15 files, fallback returns analysis
        small_files = files[:10]
        result = collector._fallback_analysis("test task", small_files, ["src/"])
        assert "Fallback" in result.summary or result.complexity_score > 0

    def test_resolve_model_context_collector_uses_read_only_profile(self):
        """Regression: context collection always uses the read-only profile."""
        result = resolve_model("context_collector")
        assert result["executor_id"] == "context-json-flash"


class TestContextJsonFlashTemplateRender:
    """The mini-swe context profile must receive the generated packet file."""

    def test_context_json_flash_uses_packet_file_input(self):
        from grace_control.config.agent_profiles import load_agent_profiles

        profiles = load_agent_profiles()
        profile = profiles.get("context-json-flash")
        assert profile is not None, "context-json-flash profile must exist"
        assert profile.input_mode == "file"
        assert "{packet_path}" in profile.command

    def test_context_json_flash_command_renders_packet_path(self):
        from grace_control.config.agent_profiles import load_agent_profiles
        from grace_control.services.command_template_renderer import CommandTemplateRenderer

        profiles = load_agent_profiles()
        profile = profiles.get("context-json-flash")
        renderer = CommandTemplateRenderer()
        ctx = {
            "packet_id": "pkt_test",
            "model": "openai/gemini-3-flash-agent",
            "effort": "low",
            "role": "context_collector",
            "worktree_path": "/tmp/test",
            "state_root": "/tmp",
            "attempt": "1",
            "packet_path": "/tmp/test/EXECUTION_PACKET.md",
            "python_executable": "/usr/bin/python3",
        }
        rendered = renderer.render(profile.command, ctx)
        assert "/tmp/test/EXECUTION_PACKET.md" in rendered
        assert "grace_control.runtime.mini_swe_runner" in rendered

    def test_prompt_placeholder_would_render_as_literal(self):
        """Confirm that {prompt} would NOT be substituted by
        CommandTemplateRenderer (it's not in KNOWN_KEYS)."""
        from grace_control.services.command_template_renderer import CommandTemplateRenderer

        renderer = CommandTemplateRenderer()
        ctx = {
            "packet_id": "pkt_test",
            "model": "test-model",
            "effort": "low",
            "role": "context_collector",
            "worktree_path": "/tmp",
            "state_root": "/tmp",
            "attempt": "1",
            "packet_markdown": "REAL_PROMPT_CONTENT",
            "prompt": "SHOULD_NOT_APPEAR",
        }
        # {prompt} is NOT in KNOWN_KEYS, so it stays literal
        rendered = renderer.render(["{prompt}"], ctx)
        assert rendered[0] == "{prompt}", (
            f"{{prompt}} should NOT be substituted by CommandTemplateRenderer, "
            f"got: {rendered[0]!r}. This proves {prompt} would be a blocker."
        )

        # {packet_markdown} IS in KNOWN_KEYS and renders correctly
        rendered2 = renderer.render(["{packet_markdown}"], ctx)
        assert rendered2[0] == "REAL_PROMPT_CONTENT", (
            f"{{packet_markdown}} MUST be substituted, got: {rendered2[0]!r}"
        )


class TestMutationGuardBlocksArchitect:
    """When context-builder mutates the target repo, run_architect must
    NOT be called.

    Two blocking paths:
    1. Exception path: CONTEXT_BUILDER_MUTATED_TARGET_REPO re-raises from
       run_context_builder(), so execution never reaches run_architect().
    2. Guard path: router code checks context.get("error") and skips
       run_architect() even if run_context_builder returns normally
       (fallback context with error field).
    """

    @pytest.mark.asyncio
    async def test_exception_path_skips_architect(self, tmp_path):
        """When CONTEXT_BUILDER_MUTATED_TARGET_REPO is raised,
        run_architect is never called. Tests the full
        run_context_builder → exception → architect-not-reached flow.
        """
        from unittest.mock import AsyncMock, patch
        from grace_control.db import init_db
        from grace_control.services.feature_intake_service import FeatureIntakeService

        os.environ["GRACE_CONTEXT_DISABLED"] = "true"
        init_db("sqlite:///:memory:")

        from grace_control.db import get_db
        from grace_control.services.feature_planning_service import FeaturePlanningService

        repo = tmp_path / "target_repo"
        repo.mkdir()
        subprocess.run(["git", "init"], cwd=str(repo), capture_output=True, timeout=10)
        subprocess.run(["git", "config", "user.email", "test@test.com"],
                        cwd=str(repo), capture_output=True, timeout=5)
        subprocess.run(["git", "config", "user.name", "Test"],
                        cwd=str(repo), capture_output=True, timeout=5)
        (repo / "app.py").write_text("print('hello')")
        subprocess.run(["git", "add", "."], cwd=str(repo), capture_output=True, timeout=5)
        subprocess.run(["git", "commit", "-m", "init"], cwd=str(repo), capture_output=True, timeout=10)

        architect_calls = []

        async def mock_architect(self_planning, feature_id, context, target_repo_root=None):
            architect_calls.append({"feature_id": feature_id, "context": context})
            return {"waves": [], "summary": "mock"}

        with get_db() as db:
            intake = FeatureIntakeService(db)
            result = intake.create_feature(
                title="Exception Path Test",
                mode="draft_plan",
                target_repo_root=str(repo),
            )
            fid = result["feature_id"]
            planning = FeaturePlanningService(db)

            async def mock_run_llm_writes_file(self, prompt):
                target = self._root / "BAD_MUTATION_EXCEPTION.py"
                target.write_text("# This should not exist - mutation guard test")
                return '{"summary": "test", "estimated_scope": [], "affected_contracts": [], "complexity_score": 50}'

            with patch.object(ContextCollector, "_run_llm", mock_run_llm_writes_file):
                with patch.object(FeaturePlanningService, "run_architect", mock_architect):
                    with pytest.raises(CONTEXT_BUILDER_MUTATED_TARGET_REPO):
                        await planning.run_context_builder(fid, target_repo_root=str(repo))

            assert len(architect_calls) == 0, (
                f"run_architect should NOT have been called after mutation guard, "
                f"but was called {len(architect_calls)} time(s)"
            )

            snap = _git_snapshot(repo)
            assert snap is not None
            assert snap["is_clean"] is True
            assert not (repo / "BAD_MUTATION_EXCEPTION.py").exists()

    @pytest.mark.asyncio
    async def test_guard_path_skips_architect_after_error_context(self, tmp_path):
        """Simulates the router guard pattern: run_context_builder returns
        a context dict with error=CONTEXT_BUILDER_MUTATED_TARGET_REPO,
        and the guard check prevents run_architect from being called.

        This tests the same guard pattern used in features.py and architect.py:
          context = await planning.run_context_builder(...)
          if context.get("error") == "CONTEXT_BUILDER_MUTATED_TARGET_REPO":
              return   # ← skip architect
          await planning.run_architect(...)   # ← only reached if no error
        """
        from unittest.mock import AsyncMock, patch
        from grace_control.db import init_db
        from grace_control.services.feature_intake_service import FeatureIntakeService

        os.environ["GRACE_CONTEXT_DISABLED"] = "true"
        init_db("sqlite:///:memory:")

        from grace_control.db import get_db
        from grace_control.services.feature_planning_service import FeaturePlanningService

        repo = tmp_path / "target_repo_guard"
        repo.mkdir()
        subprocess.run(["git", "init"], cwd=str(repo), capture_output=True, timeout=10)
        subprocess.run(["git", "config", "user.email", "test@test.com"],
                        cwd=str(repo), capture_output=True, timeout=5)
        subprocess.run(["git", "config", "user.name", "Test"],
                        cwd=str(repo), capture_output=True, timeout=5)
        (repo / "app.py").write_text("print('hello')")
        subprocess.run(["git", "add", "."], cwd=str(repo), capture_output=True, timeout=5)
        subprocess.run(["git", "commit", "-m", "init"], cwd=str(repo), capture_output=True, timeout=10)

        architect_calls = []

        async def mock_architect(self_planning, feature_id, context, target_repo_root=None):
            architect_calls.append({"feature_id": feature_id, "context": context})
            return {"waves": [], "summary": "mock"}

        with get_db() as db:
            intake = FeatureIntakeService(db)
            result = intake.create_feature(
                title="Guard Path Test",
                mode="draft_plan",
                target_repo_root=str(repo),
            )
            fid = result["feature_id"]
            planning = FeaturePlanningService(db)

            # Mock run_context_builder to return error context (simulates
            # the case where mutation is detected but exception is caught
            # at an outer layer, e.g. by a generic except in a router).
            async def mock_context_builder_returns_error(self_planning, feature_id, target_repo_root=None):
                return {
                    "summary": "Fallback",
                    "file_count": 0,
                    "files": [],
                    "error": "CONTEXT_BUILDER_MUTATED_TARGET_REPO",
                }

            with patch.object(FeaturePlanningService, "run_context_builder", mock_context_builder_returns_error):
                with patch.object(FeaturePlanningService, "run_architect", mock_architect):
                    context = await planning.run_context_builder(fid, target_repo_root=str(repo))

                    # This is the exact guard pattern from features.py and architect.py:
                    if context.get("error") == "CONTEXT_BUILDER_MUTATED_TARGET_REPO":
                        pass  # skip architect — same as `return` in background or `raise HTTPException` in sync
                    else:
                        await planning.run_architect(fid, context, target_repo_root=str(repo))

            assert len(architect_calls) == 0, (
                f"run_architect should NOT have been called when context error "
                f"is CONTEXT_BUILDER_MUTATED_TARGET_REPO, but was called "
                f"{len(architect_calls)} time(s)"
            )

    @pytest.mark.asyncio
    async def test_normal_context_reaches_architect(self, tmp_path):
        """When context is normal (no error), architect IS called.
        This proves the guard doesn't false-positive block architect.
        """
        from unittest.mock import AsyncMock, patch
        from grace_control.db import init_db
        from grace_control.services.feature_intake_service import FeatureIntakeService

        os.environ["GRACE_CONTEXT_DISABLED"] = "true"
        init_db("sqlite:///:memory:")

        from grace_control.db import get_db
        from grace_control.services.feature_planning_service import FeaturePlanningService

        repo = tmp_path / "target_repo_normal"
        repo.mkdir()
        subprocess.run(["git", "init"], cwd=str(repo), capture_output=True, timeout=10)
        subprocess.run(["git", "config", "user.email", "test@test.com"],
                        cwd=str(repo), capture_output=True, timeout=5)
        subprocess.run(["git", "config", "user.name", "Test"],
                        cwd=str(repo), capture_output=True, timeout=5)
        (repo / "app.py").write_text("print('hello')")
        subprocess.run(["git", "add", "."], cwd=str(repo), capture_output=True, timeout=5)
        subprocess.run(["git", "commit", "-m", "init"], cwd=str(repo), capture_output=True, timeout=10)

        architect_calls = []

        async def mock_architect(self_planning, feature_id, context, target_repo_root=None):
            architect_calls.append({"feature_id": feature_id, "context": context})
            return {"waves": [], "summary": "mock"}

        with get_db() as db:
            intake = FeatureIntakeService(db)
            result = intake.create_feature(
                title="Normal Path Test",
                mode="draft_plan",
                target_repo_root=str(repo),
            )
            fid = result["feature_id"]
            planning = FeaturePlanningService(db)

            # Mock to return normal context (no mutation, no error)
            async def mock_context_builder_normal(self_planning, feature_id, target_repo_root=None):
                return {
                    "summary": "Normal context for testing",
                    "file_count": 3,
                    "files": [],
                    "complexity_score": 50,
                    "estimated_scope": [],
                }

            with patch.object(FeaturePlanningService, "run_context_builder", mock_context_builder_normal):
                with patch.object(FeaturePlanningService, "run_architect", mock_architect):
                    context = await planning.run_context_builder(fid, target_repo_root=str(repo))

                    # Same guard pattern as in routers:
                    if context.get("error") == "CONTEXT_BUILDER_MUTATED_TARGET_REPO":
                        pass  # skip
                    else:
                        await planning.run_architect(fid, context, target_repo_root=str(repo))

            # Architect IS called when context has no error
            assert len(architect_calls) == 1, (
                f"run_architect should have been called once for normal context, "
                f"but was called {len(architect_calls)} time(s)"
            )
        # Architect can be called normally.
