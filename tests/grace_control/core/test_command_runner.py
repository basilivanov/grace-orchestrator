"""Tests for command runner."""

import sys
import tempfile
from pathlib import Path

import pytest
from grace_control.core.command_runner import CommandRunner, run_command
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
        r = runner.run([sys.executable, "-c", "import time; import time; time.sleep(10)"], timeout_s=1)
        assert r.timed_out is True
        assert r.exit_code == -1

    def test_timeout_returns_minus_one(self):
        runner = CommandRunner(Path.cwd(), default_timeout_s=1)
        r = runner.run([sys.executable, "-c", "import time; import time; time.sleep(10)"], timeout_s=1)
        assert r.exit_code == -1
        assert r.timed_out is True

    def test_cwd_outside_repo_string(self):
        runner = CommandRunner(Path("/tmp/isolated"))
        r = runner.run(["echo", "hi"], cwd=Path("/etc"))
        assert r.exit_code != 0
        assert "outside" in r.stderr


class TestRunCommand:
    def test_successful_via_run_command(self):
        with tempfile.TemporaryDirectory() as td:
            out = Path(td)
            r = run_command(f"{sys.executable} -c \"print('ok')\"", cwd=Path.cwd(), output_dir=out)
            assert r.exit_code == 0
            assert "ok" in r.stdout

    def test_failing_via_run_command(self):
        with tempfile.TemporaryDirectory() as td:
            out = Path(td)
            r = run_command(f"{sys.executable} -c \"import sys; sys.exit(7)\"", cwd=Path.cwd(), output_dir=out)
            assert r.exit_code == 7
            assert r.passed is False

    def test_stdout_file_written(self):
        with tempfile.TemporaryDirectory() as td:
            out = Path(td)
            r = run_command(f"{sys.executable} -c \"print('fileout')\"", cwd=Path.cwd(), output_dir=out)
            assert r.stdout_path
            assert Path(r.stdout_path).exists()
            assert Path(r.stdout_path).read_text().strip() == "fileout"

    def test_stderr_file_written(self):
        with tempfile.TemporaryDirectory() as td:
            out = Path(td)
            r = run_command(f"{sys.executable} -c \"import sys; sys.stderr.write('errout')\"", cwd=Path.cwd(), output_dir=out)
            assert r.stderr_path
            assert Path(r.stderr_path).exists()

    def test_timeout_via_run_command(self):
        with tempfile.TemporaryDirectory() as td:
            out = Path(td)
            r = run_command(f"{sys.executable} -c \"import time; time.sleep(10)\"", cwd=Path.cwd(), output_dir=out, timeout_seconds=1)
            assert r.timed_out is True
            assert r.exit_code == -1

    def test_shell_syntax_rejected(self):
        with tempfile.TemporaryDirectory() as td:
            out = Path(td)
            r = run_command("echo ok && false", cwd=Path.cwd(), output_dir=out)
            assert r.exit_code != 0
            assert "unsupported shell syntax" in r.stderr

    def test_shell_syntax_pipe_rejected(self):
        with tempfile.TemporaryDirectory() as td:
            out = Path(td)
            r = run_command("echo ok | grep ok", cwd=Path.cwd(), output_dir=out)
            assert r.exit_code != 0
            assert "unsupported shell syntax" in r.stderr

    def test_deterministic_filenames(self):
        with tempfile.TemporaryDirectory() as td:
            out = Path(td)
            r1 = run_command(f"{sys.executable} -c \"print('a')\"", cwd=Path.cwd(), output_dir=out)
            r2 = run_command(f"{sys.executable} -c \"print('b')\"", cwd=Path.cwd(), output_dir=out)
            assert "cmd_001_stdout.log" in r1.stdout_path
            assert "cmd_002_stdout.log" in r2.stdout_path
