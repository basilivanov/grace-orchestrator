"""Tests for process_supervisor cwd handling."""
from __future__ import annotations

import os
import sys
import asyncio
from pathlib import Path

import pytest

from grace_control.services.process_supervisor import ProcessSupervisor


def test_pwd_env_matches_cwd(tmp_path: Path) -> None:
    """The subprocess must see PWD=<cwd> regardless of parent PWD."""
    sup = ProcessSupervisor()
    workdir = tmp_path / "worktree"
    workdir.mkdir()
    (workdir / "marker.txt").write_text("ok")

    result = asyncio.run(sup.run(
        [sys.executable, "-c", "import os; print(os.getcwd()); print(os.environ.get('PWD',''))"],
        cwd=workdir,
        timeout_seconds=10,
    ))
    lines = result.stdout.strip().splitlines()
    assert len(lines) >= 1
    assert Path(lines[0]).resolve() == workdir.resolve()
    # PWD must be set to the requested cwd, not the inherited parent PWD.
    assert Path(lines[1]).resolve() == workdir.resolve(), (
        f"PWD env was {lines[1]!r}, expected {str(workdir)!r}"
    )


def test_pwd_overrides_parent_inherited_pwd(tmp_path: Path) -> None:
    """If parent PWD differs from cwd, child must still use cwd."""
    sup = ProcessSupervisor()
    fake_parent_pwd = str(tmp_path / "somewhere_else")
    (tmp_path / "somewhere_else").mkdir(exist_ok=True)

    workdir = tmp_path / "actual_work"
    workdir.mkdir()

    saved_pwd = os.environ.get("PWD", "")
    os.environ["PWD"] = fake_parent_pwd
    try:
        result = asyncio.run(sup.run(
            [sys.executable, "-c", "import os; print(os.environ.get('PWD',''))"],
            cwd=workdir,
            timeout_seconds=10,
        ))
    finally:
        os.environ["PWD"] = saved_pwd

    assert result.exit_code == 0
    # Child must see PWD=workdir, not the inherited fake PWD.
    assert Path(result.stdout.strip()).resolve() == workdir.resolve()


def test_cwd_does_not_exist_returns_error(tmp_path: Path) -> None:
    """If cwd doesn't exist, subprocess should fail cleanly."""
    sup = ProcessSupervisor()
    missing = tmp_path / "does_not_exist"
    result = asyncio.run(sup.run(
        [sys.executable, "-c", "print('ok')"],
        cwd=missing,
        timeout_seconds=10,
    ))
    assert result.exit_code != 0
