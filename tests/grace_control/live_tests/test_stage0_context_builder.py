"""Tests for Stage 0 context-builder flow in WaveResumeRunner.

Covers:
1. Scenario validation with context_builder field
2. _submit_feature filters out context-builder packets
3. _run_stage0_context_builder scenario parsing and mutation detection
4. Agent profile alias (role: context-builder -> context-collector-flash)
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))


# ── Fixtures ────────────────────────────────────────────────────────────────


@pytest.fixture
def scenario_with_cb() -> dict:
    """A scenario with context_builder enabled and W0/C1 role: context-builder."""
    return {
        "id": "test-cb-scenario",
        "target_repo_worktree": True,
        "context_builder": {
            "enabled": True,
            "mode": "bounded_bundle",
            "required": True,
            "min_context_runs": 1,
        },
        "waves": [
            {
                "id": "W0",
                "title": "Bounded context bundle",
                "packets": [
                    {
                        "id": "C1",
                        "role": "context-builder",
                        "acceptance_profile": "NORMAL",
                        "prompt": "Build a bounded context bundle.",
                        "scope": ["src/main.py"],
                    },
                ],
            },
            {
                "id": "W1",
                "title": "Implementation",
                "packets": [
                    {
                        "id": "P1",
                        "role": "coder",
                        "acceptance_profile": "NORMAL",
                        "prompt": "Implement the feature.",
                        "scope": ["src/feature.py"],
                    },
                ],
            },
        ],
    }


@pytest.fixture
def scenario_without_cb() -> dict:
    """A scenario with context_builder disabled."""
    return {
        "id": "test-no-cb",
        "fixture_app": "simple-app",
        "context_builder": {"enabled": False},
        "waves": [
            {
                "id": "W1",
                "title": "Phase 1",
                "packets": [
                    {
                        "id": "P1",
                        "role": "coder",
                        "acceptance_profile": "NORMAL",
                        "prompt": "Do work.",
                        "scope": ["src/work.py"],
                    },
                ],
            },
        ],
    }


@pytest.fixture
def scenario_no_cb_field() -> dict:
    """A scenario with no context_builder field at all."""
    return {
        "id": "test-no-cb-field",
        "fixture_app": "simple-app",
        "waves": [
            {
                "id": "W1",
                "title": "Phase 1",
                "packets": [
                    {
                        "id": "P1",
                        "role": "coder",
                        "acceptance_profile": "NORMAL",
                        "prompt": "Do work.",
                    },
                ],
            },
        ],
    }


@pytest.fixture
def clean_git_repo(tmp_path: Path) -> Path:
    """Create a clean temporary git repo for mutation tests."""
    repo = tmp_path / "target_repo"
    repo.mkdir()
    subprocess.run(["git", "init", "-b", "main"], cwd=str(repo),
                   capture_output=True, check=True)
    subprocess.run(["git", "config", "user.email", "test@test"],
                   cwd=str(repo), capture_output=True, check=True)
    subprocess.run(["git", "config", "user.name", "Test"],
                   cwd=str(repo), capture_output=True, check=True)
    (repo / "README.md").write_text("# Test Repo")
    subprocess.run(["git", "add", "-A"], cwd=str(repo), capture_output=True, check=True)
    subprocess.run(["git", "commit", "-m", "initial"], cwd=str(repo),
                   capture_output=True, check=True)
    result = subprocess.run(["git", "status", "--short"], cwd=str(repo),
                            capture_output=True, text=True, timeout=10)
    assert result.stdout.strip() == "", f"Repo is not clean: {result.stdout}"
    return repo


def test_load_scenario_with_context_builder():
    """Scenario loader should accept context_builder field (not validated explicitly)."""
    from tests_live.runner.scenario_loader import load_scenario
    scenario = load_scenario("solarsage-pilot-003-context-builder-full-smoke")
    assert scenario.get("context_builder", {}).get("enabled") is True
    assert any(
        p.get("role") == "context-builder"
        for w in scenario.get("waves", [])
        for p in w.get("packets", [])
    )


# ── Agent profile alias ─────────────────────────────────────────────────────


def test_context_builder_role_alias():
    """context-builder role maps to context-collector-flash executor."""
    from grace_control.config.agent_profiles import load_agent_profiles
    profiles = load_agent_profiles()
    assert "context-collector-flash" in profiles
    prof = profiles["context-collector-flash"]
    assert "context_bundle_path" in "\n".join(prof.command)
    assert "bounded GRACE Context Builder" in "\n".join(prof.command)


def test_context_builder_role_in_codex():
    """context-collector-flash has both context_collector and context-builder roles."""
    from grace_control.config.agent_profiles import load_agent_profiles
    profiles = load_agent_profiles()

    # Verify the codex section references context-builder
    import yaml
    from pathlib import Path
    yaml_path = Path(__file__).resolve().parents[3] / "src" / "grace_control" / "config" / "agent_profiles.yaml"
    raw = yaml.safe_load(yaml_path.read_text()) or {}
    codex = raw.get("codex", {})
    executors = codex.get("executors", [])
    cb_entry = next((e for e in executors if e.get("executor_id") == "context-collector-flash"), None)
    assert cb_entry is not None, "context-collector-flash not in codex executors"
    roles = cb_entry.get("roles", [])
    assert "context-builder" in roles, "context-builder role not in context-collector-flash roles"
    assert "context_collector" in roles, "context_collector role not in context-collector-flash roles"


# ── _submit_feature filtering ───────────────────────────────────────────────


def _build_runner_with_scenario(scenario_data: dict) -> any:
    """Helper: create WaveResumeRunner with load_scenario patched to return test data."""
    from tests_live.runner.wave_resume_runner import WaveResumeRunner
    import argparse

    args = argparse.Namespace(
        scenario=scenario_data.get("id", "test"),
        api_url="http://127.0.0.1:8042",
        target_dir="/tmp/grace-live-test",
        source_dir=".",
        agent_profile="coder-deepseek-flash",
        architect_profile="architect-premium",
        workspace_mode=None,
        target_repo_root=None,
        max_waves=0,
        timeout=600,
        keep_artifacts=False,
    )

    with (
        patch("tests_live.runner.wave_resume_runner.load_scenario",
              return_value=scenario_data),
    ):
        return WaveResumeRunner(args)


def test_submit_feature_filters_context_builder_packets(scenario_with_cb):
    """_submit_feature should drop context-builder packets and only submit remaining."""
    runner = _build_runner_with_scenario(scenario_with_cb)
    runner._save_artifact = MagicMock()
    runner._check_api = MagicMock(return_value=False)
    runner._start_api = MagicMock()

    with patch("tests_live.runner.wave_resume_runner._api_call") as mock_api:
        mock_api.return_value = {
            "data": {
                "feature_id": "feat_test_001",
                "packet_ids": ["pkt_P1_001"],
                "packets_count": 1,
            }
        }
        feat_id = runner._submit_feature()

    assert feat_id == "feat_test_001"
    assert runner.report["waves_requested"] == 1  # W0 filtered out, only W1
    submitted_body = mock_api.call_args.kwargs["body"]
    assert submitted_body is not None
    feature_spec = submitted_body.get("feature_spec", {})
    waves = feature_spec.get("waves", [])
    assert len(waves) == 1
    assert len(waves[0]["packets"]) == 1
    assert waves[0]["packets"][0]["title"] == "P1"


def test_submit_feature_context_bundle_injected(scenario_with_cb):
    """When context_bundle provided, it should be injected into first packet prompt."""
    runner = _build_runner_with_scenario(scenario_with_cb)
    runner._save_artifact = MagicMock()
    runner._check_api = MagicMock(return_value=False)
    runner._start_api = MagicMock()

    context_bundle = [
        {
            "context_bundle_path": "/tmp/grace-context/test/C1/context-bundle.md",
            "context_bundle_summary": "Found 2 relevant files",
            "selected_files": ["src/main.py"],
        }
    ]

    with patch("tests_live.runner.wave_resume_runner._api_call") as mock_api:
        mock_api.return_value = {
            "data": {
                "feature_id": "feat_test_002",
                "packet_ids": ["pkt_P1_002"],
                "packets_count": 1,
            }
        }
        feat_id = runner._submit_feature(context_bundle=context_bundle)

    assert feat_id == "feat_test_002"
    submitted_body = mock_api.call_args.kwargs["body"]
    feature_spec = submitted_body.get("feature_spec", {})
    waves = feature_spec.get("waves", [])
    assert len(waves) == 1
    first_packet = waves[0]["packets"][0]
    assert "## Context Bundle" in first_packet["prompt"]
    assert feature_spec.get("context_bundle") == context_bundle


def test_submit_feature_no_context_bundle(scenario_without_cb):
    """Without context_bundle, prompt should not be modified."""
    runner = _build_runner_with_scenario(scenario_without_cb)
    runner._save_artifact = MagicMock()
    runner._check_api = MagicMock(return_value=False)
    runner._start_api = MagicMock()

    with patch("tests_live.runner.wave_resume_runner._api_call") as mock_api:
        mock_api.return_value = {
            "data": {
                "feature_id": "feat_test_003",
                "packet_ids": ["pkt_P1_003"],
                "packets_count": 1,
            }
        }
        feat_id = runner._submit_feature()

    assert feat_id == "feat_test_003"
    submitted_body = mock_api.call_args.kwargs["body"]
    feature_spec = submitted_body.get("feature_spec", {})
    waves = feature_spec.get("waves", [])
    assert len(waves) == 1
    assert "## Context Bundle" not in waves[0]["packets"][0]["prompt"]
    assert "context_bundle" not in feature_spec


def test_submit_feature_all_context_builder():
    """When all packets are context-builder, should return None (nothing to submit)."""
    runner = _build_runner_with_scenario({
        "id": "test-all-cb",
        "target_repo_worktree": True,
        "context_builder": {"enabled": True},
        "waves": [
            {
                "id": "W0",
                "title": "Context only",
                "packets": [
                    {
                        "id": "C1",
                        "role": "context-builder",
                        "prompt": "Build context.",
                    },
                ],
            },
        ],
    })
    runner._save_artifact = MagicMock()
    runner._check_api = MagicMock(return_value=False)
    runner._start_api = MagicMock()

    with patch("tests_live.runner.wave_resume_runner._api_call") as mock_api:
        mock_api.return_value = {"data": {}}
        feat_id = runner._submit_feature()

    assert feat_id is None
    assert runner.report["waves_requested"] == 0
    mock_api.assert_not_called()


# ── _run_stage0_context_builder scenario parsing ────────────────────────────


def test_stage0_disabled(scenario_no_cb_field):
    """When context_builder not enabled, _run_stage0_context_builder returns []."""
    runner = _build_runner_with_scenario(scenario_no_cb_field)
    result = runner._run_stage0_context_builder()
    assert result == []
    assert runner.report["failures"] == []


def test_stage0_disabled_explicit(scenario_without_cb):
    """When context_builder.enabled is False, _run_stage0_context_builder returns []."""
    runner = _build_runner_with_scenario(scenario_without_cb)
    result = runner._run_stage0_context_builder()
    assert result == []


def test_stage0_no_target_repo(scenario_with_cb):
    """Stage 0 fails gracefully when target repo doesn't exist."""
    from tests_live.runner.wave_resume_runner import WaveResumeRunner
    from unittest.mock import patch
    import argparse

    args = argparse.Namespace(
        scenario=scenario_with_cb["id"],
        api_url="http://127.0.0.1:8042",
        target_dir="/nonexistent/path",
        source_dir=".",
        agent_profile="coder-deepseek-flash",
        architect_profile="architect-premium",
        workspace_mode=None,
        target_repo_root="/nonexistent/path",
        max_waves=0,
        timeout=600,
        keep_artifacts=False,
    )

    with patch("tests_live.runner.wave_resume_runner.load_scenario",
               return_value=scenario_with_cb):
        runner = WaveResumeRunner(args)

    result = runner._run_stage0_context_builder()
    assert result == []
    assert any("target repo not found" in f for f in runner.report["failures"])


# ── Mutation detection (uses real git repo) ─────────────────────────────────


def _build_runner_for_mutation(clean_git_repo: Path, scenario_data: dict) -> any:
    """Helper: create WaveResumeRunner with clean_git_repo target and patched scenario."""
    from tests_live.runner.wave_resume_runner import WaveResumeRunner
    import argparse

    args = argparse.Namespace(
        scenario=scenario_data.get("id", "test-mutation"),
        api_url="http://127.0.0.1:8042",
        target_dir=str(clean_git_repo),
        source_dir=".",
        agent_profile="coder-deepseek-flash",
        architect_profile="architect-premium",
        workspace_mode=None,
        target_repo_root=str(clean_git_repo),
        max_waves=0,
        timeout=600,
        keep_artifacts=False,
    )

    with patch("tests_live.runner.wave_resume_runner.load_scenario",
               return_value=scenario_data):
        return WaveResumeRunner(args)


def test_mutation_detection_clean_agent(clean_git_repo: Path):
    """When agent does NOT modify files and creates bundle, mutation detection passes."""
    bundle_path = Path(f"/tmp/grace-context/test-mutation-clean/C1/context-bundle.md")

    with patch(
        "grace_control.config.agent_profiles.get_agent_profile"
    ) as mock_get_profile:
        mock_prof = MagicMock()
        # Also write the bundle file so the new MISSING_BUNDLE check passes
        mock_prof.command = [
            "sh", "-c",
            f"mkdir -p {bundle_path.parent} && "
            f"echo '# Bundle' > {bundle_path} && "
            'echo \'{"context_bundle_summary": "Clean run", '
            '"selected_files": ["README.md"]}\'',
        ]
        mock_prof.model = ""
        mock_prof.effort = ""
        mock_prof.timeout_seconds = 30
        mock_get_profile.return_value = mock_prof

        scenario = {
            "id": "test-mutation-clean",
            "target_repo_worktree": True,
            "context_builder": {"enabled": True},
            "waves": [
                {
                    "id": "W0",
                    "title": "Context",
                    "packets": [
                        {
                            "id": "C1",
                            "role": "context-builder",
                            "prompt": "Read files, do not modify.",
                            "scope": ["README.md"],
                        },
                    ],
                },
            ],
        }
        runner = _build_runner_for_mutation(clean_git_repo, scenario)
        result = runner._run_stage0_context_builder()

    assert len(result) == 1
    assert result[0]["context_bundle_summary"] == "Clean run"
    assert runner.report["context_runs"] == 1
    assert runner.report["real_agent_runs"] == 1
    assert runner.report["failures"] == []
    assert bundle_path.exists()
    assert bundle_path.stat().st_size > 0


def test_mutation_detection_dirty_agent(clean_git_repo: Path):
    """When agent modifies files, CONTEXT_BUILDER_MUTATED_WORKTREE is raised."""
    with patch(
        "grace_control.config.agent_profiles.get_agent_profile"
    ) as mock_get_profile:
        mock_prof = MagicMock()
        # Use sh to run a command that creates a file — simulating mutation
        mock_prof.command = [
            "sh", "-c",
            f"echo agent-did-this > {clean_git_repo / 'modified.txt'} "
            f"&& echo '{{\"context_bundle_path\": \"/tmp/x\"}}'",
        ]
        mock_prof.model = ""
        mock_prof.effort = ""
        mock_prof.timeout_seconds = 30
        mock_get_profile.return_value = mock_prof

        scenario = {
            "id": "test-mutation-dirty",
            "target_repo_worktree": True,
            "context_builder": {"enabled": True},
            "waves": [
                {
                    "id": "W0",
                    "title": "Context",
                    "packets": [
                        {
                            "id": "C1",
                            "role": "context-builder",
                            "prompt": "Do not modify files.",
                            "scope": ["README.md"],
                        },
                    ],
                },
            ],
        }
        runner = _build_runner_for_mutation(clean_git_repo, scenario)
        result = runner._run_stage0_context_builder()

    assert result == []
    assert any("CONTEXT_BUILDER_MUTATED_WORKTREE" in f
               for f in runner.report["failures"])
    assert not (clean_git_repo / "modified.txt").exists()


def test_mutation_detection_agent_failure(clean_git_repo: Path):
    """When agent exits with non-zero code, Stage 0 fails early."""
    with patch(
        "grace_control.config.agent_profiles.get_agent_profile"
    ) as mock_get_profile:
        mock_prof = MagicMock()
        # Use sh to exit with code 1 — simulating agent failure
        mock_prof.command = ["sh", "-c", "exit 1"]
        mock_prof.model = ""
        mock_prof.effort = ""
        mock_prof.timeout_seconds = 30
        mock_get_profile.return_value = mock_prof

        scenario = {
            "id": "test-mutation-fail",
            "target_repo_worktree": True,
            "context_builder": {"enabled": True},
            "waves": [
                {
                    "id": "W0",
                    "title": "Context",
                    "packets": [
                        {
                            "id": "C1",
                            "role": "context-builder",
                            "prompt": "Do work.",
                            "scope": ["README.md"],
                        },
                    ],
                },
            ],
        }
        runner = _build_runner_for_mutation(clean_git_repo, scenario)
        result = runner._run_stage0_context_builder()

    assert result == []
    assert any("agent failed" in f for f in runner.report["failures"])


def test_stage0_missing_bundle_file(clean_git_repo: Path):
    """Agent exits 0 with JSON stdout, but does not create bundle file → fail."""
    with patch(
        "grace_control.config.agent_profiles.get_agent_profile"
    ) as mock_get_profile:
        mock_prof = MagicMock()
        # Command echoes valid JSON but does NOT write the bundle file
        mock_prof.command = [
            "sh", "-c",
            "echo '{\"context_bundle_summary\": \"Pretend success\"}'",
        ]
        mock_prof.model = ""
        mock_prof.effort = ""
        mock_prof.timeout_seconds = 30
        mock_get_profile.return_value = mock_prof

        scenario = {
            "id": "test-missing-bundle",
            "target_repo_worktree": True,
            "context_builder": {"enabled": True},
            "waves": [
                {
                    "id": "W0",
                    "title": "Context",
                    "packets": [
                        {
                            "id": "C1",
                            "role": "context-builder",
                            "prompt": "Collect context.",
                            "scope": ["README.md"],
                        },
                    ],
                },
            ],
        }
        runner = _build_runner_for_mutation(clean_git_repo, scenario)
        result = runner._run_stage0_context_builder()

    assert result == []
    assert any("CONTEXT_BUILDER_MISSING_BUNDLE" in f
               for f in runner.report["failures"])
    assert runner.report["context_runs"] == 1
    assert runner.report["real_agent_runs"] == 1


# ── Report counters ─────────────────────────────────────────────────────────


def test_report_has_stage0_counters(scenario_with_cb):
    """Report includes context_runs and watchdog_restarts fields."""
    runner = _build_runner_with_scenario(scenario_with_cb)
    report = runner.report
    assert "context_runs" in report
    assert "watchdog_restarts" in report
    assert "live_log_path" in report
    assert "runner_pid" in report
    assert report["context_runs"] == 0
    assert report["watchdog_restarts"] == 0
