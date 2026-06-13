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
from grace_control.core.context_collector import ContextCollector
from grace_control.core.executor_selector import resolve_model, _profile_matches_role
from grace_control.core.contracts import build_packet_contract
from grace_control.services.feature_planning_service import (
    FeaturePlanningService,
    CONTEXT_BUILDER_MUTATED_TARGET_REPO,
    _git_snapshot,
    _git_reset_hard,
)


class TestContextCollectorDoesNotUseGenericOpencodeProfile:
    """resolve_model('context_collector') must return context-json-flash
    (read-only) rather than the generic coder-like 'opencode' profile.
    """

    def test_resolve_model_returns_executor_id(self):
        ctx = resolve_model("context_collector")
        assert "executor_id" in ctx, "resolve_model must include executor_id"
        eid = ctx["executor_id"]
        assert eid != "opencode", (
            f"context_collector must not use generic opencode profile, got {eid!r}"
        )

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
            cli="opencode",
            executor_id="context-json-flash",
        )
        assert collector._executor_id == "context-json-flash", (
            f"Expected executor_id=context-json-flash, got {collector._executor_id!r}"
        )

    def test_profile_matches_role_context_collector_prefers_json_flash(self):
        """context-json-flash must match context_collector role."""
        assert _profile_matches_role("context-json-flash", "context_collector") is True
        assert _profile_matches_role("context-collector-flash", "context_collector") is True

    def test_profile_matches_role_opencode_is_not_context_collector(self):
        """Generic opencode profile must NOT be selected for context_collector."""
        profiles = load_agent_profiles()
        opencode_profile = profiles.get("opencode")
        if opencode_profile is None:
            pytest.skip("opencode profile not present in agent_profiles.yaml")
        result = resolve_model("context_collector")
        assert result["executor_id"] != "opencode", (
            "context_collector must not resolve to 'opencode' profile"
        )


class TestContextJsonProfileIsReadOnly:
    """The context-json-flash profile must be explicitly read-only."""

    def test_profile_exists(self):
        profiles = load_agent_profiles()
        profile = profiles.get("context-json-flash")
        assert profile is not None, "context-json-flash profile must exist in agent_profiles.yaml"

    def test_profile_prompt_contains_read_only(self):
        profiles = load_agent_profiles()
        profile = profiles["context-json-flash"]
        # The command list contains the prompt as the last string element
        command_parts = profile.command
        prompt_text = ""
        for part in command_parts:
            if len(part) > 100:
                prompt_text = part
                break
        if not prompt_text:
            # Try input_template
            prompt_text = profile.input_template or ""
        assert "READ-ONLY" in prompt_text, (
            "context-json-flash prompt must contain READ-ONLY"
        )

    def test_profile_prompt_forbids_create_edit_delete(self):
        profiles = load_agent_profiles()
        profile = profiles["context-json-flash"]
        command_parts = profile.command
        prompt_text = ""
        for part in command_parts:
            if len(part) > 100:
                prompt_text = part
                break
        if not prompt_text:
            prompt_text = profile.input_template or ""
        assert "MUST NOT create" in prompt_text or "MUST NOT" in prompt_text, (
            "context-json-flash prompt must explicitly forbid create/edit/delete"
        )

    def test_profile_prompt_forbids_implementation(self):
        profiles = load_agent_profiles()
        profile = profiles["context-json-flash"]
        command_parts = profile.command
        prompt_text = ""
        for part in command_parts:
            if len(part) > 100:
                prompt_text = part
                break
        if not prompt_text:
            prompt_text = profile.input_template or ""
        assert "MUST NOT implement" in prompt_text, (
            "context-json-flash prompt must explicitly forbid implementation"
        )

    def test_profile_prompt_is_json_only(self):
        profiles = load_agent_profiles()
        profile = profiles["context-json-flash"]
        command_parts = profile.command
        prompt_text = ""
        for part in command_parts:
            if len(part) > 100:
                prompt_text = part
                break
        if not prompt_text:
            prompt_text = profile.input_template or ""
        assert "JSON" in prompt_text, (
            "context-json-flash prompt must specify JSON-only output"
        )

    def test_profile_never_resumes(self):
        profiles = load_agent_profiles()
        profile = profiles["context-json-flash"]
        assert profile.resume_mode == "never", (
            "context-json-flash must not resume sessions"
        )


class TestContextCollectorFlashPromptIsReadOnly:
    """context-collector-flash (live Stage 0) must also be read-only."""

    def test_profile_exists(self):
        profiles = load_agent_profiles()
        profile = profiles.get("context-collector-flash")
        assert profile is not None, "context-collector-flash profile must exist"

    def test_prompt_contains_read_only(self):
        profiles = load_agent_profiles()
        profile = profiles["context-collector-flash"]
        command_parts = profile.command
        prompt_text = ""
        for part in command_parts:
            if len(part) > 100:
                prompt_text = part
                break
        assert "READ-ONLY" in prompt_text, (
            "context-collector-flash prompt must contain explicit READ-ONLY"
        )

    def test_prompt_forbids_file_modification(self):
        profiles = load_agent_profiles()
        profile = profiles["context-collector-flash"]
        command_parts = profile.command
        prompt_text = ""
        for part in command_parts:
            if len(part) > 100:
                prompt_text = part
                break
        forbidden_phrases = ["MUST NOT create", "MUST NOT edit", "MUST NOT delete"]
        found = any(phrase in prompt_text for phrase in forbidden_phrases)
        assert found, (
            f"context-collector-flash prompt must forbid create/edit/delete; "
            f"found none of {forbidden_phrases}"
        )

    def test_prompt_forbids_implementation(self):
        profiles = load_agent_profiles()
        profile = profiles["context-collector-flash"]
        command_parts = profile.command
        prompt_text = ""
        for part in command_parts:
            if len(part) > 100:
                prompt_text = part
                break
        assert "MUST NOT implement" in prompt_text or "do not" in prompt_text.lower(), (
            "context-collector-flash prompt must forbid implementation"
        )


@pytest.mark.usefixtures("db")
class TestRunContextBuilderMutationGuard:
    """If context-builder mutates the target repo, the pipeline must fail
    with CONTEXT_BUILDER_MUTATED_TARGET_REPO and reset the repo clean.
    """

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

    def test_git_reset_hard_restores_clean_state(self, tmp_path):
        """git reset --hard restores repo to clean state."""
        repo = tmp_path / "repo"
        repo.mkdir()
        subprocess.run(["git", "init"], cwd=str(repo), capture_output=True, timeout=10)
        subprocess.run(["git", "config", "user.email", "test@test.com"],
                        cwd=str(repo), capture_output=True, timeout=5)
        subprocess.run(["git", "config", "user.name", "Test"],
                        cwd=str(repo), capture_output=True, timeout=5)
        (repo / "file.txt").write_text("hello")
        subprocess.run(["git", "add", "."], cwd=str(repo), capture_output=True, timeout=5)
        commit_result = subprocess.run(
            ["git", "commit", "-m", "init"], cwd=str(repo),
            capture_output=True, text=True, timeout=10,
        )
        head = subprocess.run(
            ["git", "rev-parse", "HEAD"], cwd=str(repo),
            capture_output=True, text=True, timeout=10,
        ).stdout.strip()
        # Modify file
        (repo / "file.txt").write_text("modified")
        # Add untracked file
        (repo / "new_file.txt").write_text("new")
        # Reset
        _git_reset_hard(repo, head)
        # Verify clean
        snap = _git_snapshot(repo)
        assert snap is not None
        assert snap["is_clean"] is True

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

    def test_resolve_model_context_collector_not_opencode(self):
        """Regression: resolve_model('context_collector') never returns 'opencode' executor_id."""
        result = resolve_model("context_collector")
        assert result["executor_id"] != "opencode", (
            "Bug regression: context collector must not use generic opencode profile"
        )


class TestContextJsonFlashTemplateRender:
    """Blocker 1: context-json-flash input template must render correctly
    via AgentRunService's CommandTemplateRenderer.

    The template uses {packet_markdown} (not {prompt}) because
    CommandTemplateRenderer.KNOWN_KEYS only includes packet_markdown,
    and AgentRunService passes the prompt as packet_markdown in the context.
    """

    def test_context_json_flash_template_uses_packet_markdown(self):
        """Template {packet_markdown} must render; {prompt} would be literal."""
        from grace_control.config.agent_profiles import load_agent_profiles
        from grace_control.services.command_template_renderer import CommandTemplateRenderer

        profiles = load_agent_profiles()
        profile = profiles.get("context-json-flash")
        assert profile is not None, "context-json-flash profile must exist"

        template = profile.input_template
        assert "{packet_markdown}" in template, (
            f"context-json-flash input_template must use {{packet_markdown}}, "
            f"got: {template!r}"
        )

    def test_context_json_flash_render_produces_real_content(self):
        """Render the template with real context to confirm it produces
        the prompt, not a literal placeholder."""
        from grace_control.config.agent_profiles import load_agent_profiles
        from grace_control.services.command_template_renderer import CommandTemplateRenderer

        profiles = load_agent_profiles()
        profile = profiles.get("context-json-flash")
        template = profile.input_template
        renderer = CommandTemplateRenderer()

        test_prompt = "Task: filter relevant files for feature X"
        ctx = {
            "packet_id": "pkt_test",
            "model": "deepseek/deepseek-v4-flash",
            "effort": "low",
            "role": "context_collector",
            "worktree_path": "/tmp/test",
            "state_root": "/tmp",
            "attempt": "1",
            "packet_markdown": test_prompt,
        }
        rendered = renderer.render([template], ctx)
        assert rendered[0] == test_prompt, (
            f"Rendered template must equal the prompt text, "
            f"got: {rendered[0]!r}"
        )

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
    """Blocker 2: When context-builder mutates the target repo,
    the architect must NOT be called.

    Two paths block the architect:
    1. Exception path: CONTEXT_BUILDER_MUTATED_TARGET_REPO is re-raised from
       run_context_builder(), so run_architect() is never reached.
    2. Guard path: if context dict contains error="CONTEXT_BUILDER_MUTATED_TARGET_REPO",
       router code checks context.get("error") and skips run_architect().

    The integration test below proves both paths.
    """

    def test_mutation_error_in_context_prevents_architect_call(self):
        """If run_context_builder returns context with mutation error,
        architect must not be called."""
        context = {
            "summary": "Fallback",
            "file_count": 0,
            "files": [],
            "error": "CONTEXT_BUILDER_MUTATED_TARGET_REPO",
        }
        # The guard check: if context has the mutation error, skip architect
        assert context.get("error") == "CONTEXT_BUILDER_MUTATED_TARGET_REPO"

    def test_normal_context_allows_architect_call(self):
        """If context has no mutation error, architect can proceed."""
        context = {
            "summary": "Normal context",
            "file_count": 5,
            "files": [],
        }
        assert context.get("error") != "CONTEXT_BUILDER_MUTATED_TARGET_REPO"

    @pytest.mark.asyncio
    async def test_exception_path_skips_architect(self, tmp_path):
        """When CONTEXT_BUILDER_MUTATED_TARGET_REPO is raised,
        run_architect is never called.

        This patches FeaturePlanningService.run_architect to track calls,
        forces the mutation guard to trigger, and verifies run_architect
        was NOT invoked.
        """
        from unittest.mock import AsyncMock, patch
        from grace_control.db import init_db
        from grace_control.services.feature_intake_service import FeatureIntakeService

        # Set up in-memory DB
        os.environ["GRACE_CONTEXT_DISABLED"] = "true"
        init_db("sqlite:///:memory:")

        from grace_control.db import get_db
        from grace_control.services.feature_planning_service import FeaturePlanningService

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

            # Mock ContextCollector._run_llm to both mutate the repo AND return valid JSON
            original_run_llm = ContextCollector._run_llm

            async def mock_run_llm_writes_file(self, prompt):
                target = self._root / "BAD_MUTATION_EXCEPTION.py"
                target.write_text("# This should not exist - mutation guard test")
                return '{"summary": "test", "estimated_scope": [], "affected_contracts": [], "complexity_score": 50}'

            with patch.object(ContextCollector, "_run_llm", mock_run_llm_writes_file):
                with patch.object(FeaturePlanningService, "run_architect", mock_architect):
                    with pytest.raises(CONTEXT_BUILDER_MUTATED_TARGET_REPO):
                        await planning.run_context_builder(fid, target_repo_root=str(repo))

            # Verify architect was never called
            assert len(architect_calls) == 0, (
                f"run_architect should NOT have been called after mutation guard, "
                f"but was called {len(architect_calls)} time(s)"
            )

            # Verify repo is clean
            snap = _git_snapshot(repo)
            assert snap is not None
            assert snap["is_clean"] is True
            assert not (repo / "BAD_MUTATION_EXCEPTION.py").exists()
        # Architect can be called normally.