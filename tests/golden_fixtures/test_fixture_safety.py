"""Safety guard tests for golden fixtures."""

import os
import tempfile
from pathlib import Path
from unittest.mock import patch

import pytest

from grace_control.core.golden_fixtures import (
    FixtureSafetyError,
    FixtureSpec,
    assert_golden_fixture_allowed,
    init_target_repo,
    create_fixture_git_state,
)


class TestSafetyGuards:
    def test_requires_env_flag(self):
        with patch.dict(os.environ, {}, clear=True):
            with pytest.raises(FixtureSafetyError, match="GRACE_GOLDEN_FIXTURE"):
                assert_golden_fixture_allowed(
                    Path("/tmp/grace-fixtures/test"),
                    Path("fixtures/golden/test.yaml"),
                )

    def test_requires_tmp_base_dir(self):
        with patch.dict(os.environ, {"GRACE_GOLDEN_FIXTURE": "1"}):
            with pytest.raises(FixtureSafetyError, match="/tmp/grace-fixtures/"):
                assert_golden_fixture_allowed(
                    Path("/home/user/repo"),
                    Path("fixtures/golden/test.yaml"),
                )

    def test_rejects_non_fixture_path(self):
        with patch.dict(os.environ, {"GRACE_GOLDEN_FIXTURE": "1"}):
            with pytest.raises(FixtureSafetyError, match="not in allowed directory"):
                assert_golden_fixture_allowed(
                    Path("/tmp/grace-fixtures/test"),
                    Path("/etc/passwd"),
                )

    def test_accepts_valid_paths(self):
        with patch.dict(os.environ, {"GRACE_GOLDEN_FIXTURE": "1"}):
            with tempfile.TemporaryDirectory() as td:
                base = Path(td) / "grace-fixtures" / "test"
                fp = Path("/tmp/test/golden-fixtures/test.yaml")
                assert_golden_fixture_allowed(Path("/tmp/grace-fixtures/test"), fp)


class TestGitState:
    def test_init_target_repo_creates_base_branch(self):
        with tempfile.TemporaryDirectory() as td:
            repo = Path(td) / "target"
            sha = init_target_repo(repo)
            assert sha
            assert (repo / "README.md").exists()
            assert (repo / ".git").exists()

    def test_create_fixture_git_state(self):
        with tempfile.TemporaryDirectory() as td:
            from grace_control.core.golden_fixtures import FixtureGit, FixtureChangedFile

            target = Path(td) / "target"
            wt_root = Path(td) / "worktrees"
            git_cfg = FixtureGit(
                init_target_repo=True,
                create_worktree=True,
                create_branch=True,
                branch_name="agent/default/test/attempt-0001",
                changed_files=[
                    FixtureChangedFile(path="sandbox/test/file.py", content="x=1"),
                ],
            )
            state = create_fixture_git_state(target, wt_root, "pkt_test", git_cfg)
            assert state["branch_name"] == "agent/default/test/attempt-0001"
            assert state["worktree_path"]
            assert state["agent_commit_sha"]
            wt = Path(state["worktree_path"])
            assert (wt / "sandbox/test/file.py").exists()
            assert (wt / "sandbox/test/file.py").read_text() == "x=1"

    def test_dirty_uncommitted_file(self):
        with tempfile.TemporaryDirectory() as td:
            from grace_control.core.golden_fixtures import FixtureGit, FixtureChangedFile

            target = Path(td) / "target"
            wt_root = Path(td) / "worktrees"
            git_cfg = FixtureGit(
                init_target_repo=True,
                create_worktree=True,
                create_branch=True,
                branch_name="agent/default/dirty/attempt-0001",
                dirty_uncommitted_file="DIRTY.txt",
                changed_files=[FixtureChangedFile(path="clean.py", content="clean")],
            )
            state = create_fixture_git_state(target, wt_root, "pkt_dirty", git_cfg)
            assert (target / "DIRTY.txt").exists()
