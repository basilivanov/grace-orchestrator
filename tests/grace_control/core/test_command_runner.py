"""Tests for command runner."""

import sys
import tempfile
from pathlib import Path

import pytest
from grace_control.core.command_runner import CommandRunner
from grace_control.core.contracts import CommandResult


class TestCommandRunner:
    def test_successful_command(self):
        runner = CommandRunner(Path.cwd())
        r = runner.run([sys.executable, "-c", "print('ok')"])
        assert r.exit_code == 0
        assert "ok" in r.stdout

    def test_failing_command_no_exception(self):
        runner = CommandRunner(Path.cwd())
        r = runner.run([sys.executable, "-c", "import sys; sys.exit(7)"])
        assert r.exit_code == 7
        assert r.passed is False

    def test_stdout_captured(self):
        runner = CommandRunner(Path.cwd())
        r = runner.run([sys.executable, "-c", "print('hello')"])
        assert "hello" in r.stdout

    def test_stderr_captured(self):
        runner = CommandRunner(Path.cwd())
        r = runner.run([sys.executable, "-c", "import sys; print('err', file=sys.stderr)"])
        assert "err" in r.stderr

    def test_cwd_outside_repo(self):
        runner = CommandRunner(Path("/tmp/isolated_repo_root"))
        r = runner.run([sys.executable, "-c", "pass"], cwd=Path("/another"))
        assert r.exit_code != 0
        assert "outside repo" in r.stderr.lower()

    def test_absolute_cwd_outside_repo(self):
        with tempfile.TemporaryDirectory() as td:
            runner = CommandRunner(Path(td))
            r = runner.run([sys.executable, "-c", "pass"],
                          cwd=Path("/etc"))
            assert r.exit_code != 0

    def test_empty_command(self):
        runner = CommandRunner(Path.cwd())
        r = runner.run([])
        assert r.exit_code != 0

    def test_timeout(self):
        runner = CommandRunner(Path.cwd(), default_timeout_s=1)
        r = runner.run([sys.executable, "-c", "import time; time.sleep(10)"], timeout_s=1)
        assert r.timed_out is True
        assert r.exit_code == -1

    def test_timeout_returns_minus_one(self):
        runner = CommandRunner(Path.cwd(), default_timeout_s=1)
        r = runner.run([sys.executable, "-c", "import time; time.sleep(10)"], timeout_s=1)
        assert r.exit_code == -1
        assert r.timed_out is True

    def test_cwd_outside_repo_string(self):
        runner = CommandRunner(Path("/tmp/isolated"))
        r = runner.run(["echo", "hi"], cwd=Path("/etc"))
        assert r.exit_code != 0
        assert "outside" in r.stderr
