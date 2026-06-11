"""Tests for scripts/grace_changed_files_lint.py — filtering and baseline compare."""

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest


SCRIPT = Path(__file__).resolve().parents[2] / "scripts" / "grace_changed_files_lint.py"


def _run_script(
    repo: Path,
    base_sha: str = "HEAD",
    package_manager: str = "echo",
    extra_env: dict | None = None,
) -> subprocess.CompletedProcess:
    env = os.environ.copy()
    if extra_env:
        env.update(extra_env)
    return subprocess.run(
        [sys.executable, str(SCRIPT), "--repo", str(repo), "--base-sha", base_sha, "--package-manager", package_manager],
        capture_output=True, text=True, timeout=30, env=env,
    )


def _parse_output(proc: subprocess.CompletedProcess) -> dict:
    try:
        return json.loads(proc.stdout.strip())
    except (json.JSONDecodeError, ValueError):
        return {"_parse_error": proc.stdout, "stderr": proc.stderr}


class TestIsLintable:
    """Test the _is_lintable helper via direct import."""

    @pytest.fixture(autouse=True)
    def _import(self):
        sys.path.insert(0, str(SCRIPT.parent))
        from scripts import grace_changed_files_lint as mod
        self._is_lintable = mod._is_lintable

    def test_tsx_files_are_lintable(self):
        assert self._is_lintable("src/component.tsx") is True
        assert self._is_lintable("app/page.tsx") is True

    def test_ts_files_are_lintable(self):
        assert self._is_lintable("lib/util.ts") is True
        assert self._is_lintable("types/index.ts") is True

    def test_js_jsx_files_are_lintable(self):
        assert self._is_lintable("index.js") is True
        assert self._is_lintable("Button.jsx") is True

    def test_md_files_are_not_lintable(self):
        assert self._is_lintable("README.md") is False
        assert self._is_lintable("docs/guide.md") is False

    def test_py_files_are_not_lintable(self):
        assert self._is_lintable("src/main.py") is False

    def test_node_modules_excluded(self):
        assert self._is_lintable("node_modules/react/index.js") is False

    def test_next_dir_excluded(self):
        assert self._is_lintable(".next/static/js/main.js") is False

    def test_dist_dir_excluded(self):
        assert self._is_lintable("dist/output.js") is False

    def test_build_dir_excluded(self):
        assert self._is_lintable("build/bundle.js") is False

    def test_coverage_dir_excluded(self):
        assert self._is_lintable("coverage/lcov-report/index.js") is False


class TestEslintJsonParser:
    """Test the JSON ESLint output parser via direct import."""

    @pytest.fixture(autouse=True)
    def _import(self):
        sys.path.insert(0, str(SCRIPT.parent))
        from scripts import grace_changed_files_lint as mod
        self._parse = mod._parse_eslint_json

    def test_empty_output(self):
        assert self._parse("[]") == {}

    def test_single_error(self):
        output = json.dumps([{
            "filePath": "/repo/component.tsx",
            "messages": [{"line": 5, "column": 7, "ruleId": "no-unused-vars", "message": "'x' is defined but never used", "severity": 2}],
        }])
        result = self._parse(output)
        assert "/repo/component.tsx" in result
        assert ("no-unused-vars", "'x' is defined but never used") in result["/repo/component.tsx"]

    def test_multiple_errors_same_file(self):
        output = json.dumps([{
            "filePath": "/repo/file.ts",
            "messages": [
                {"line": 1, "column": 1, "ruleId": "no-undef", "message": "'X' is not defined", "severity": 2},
                {"line": 3, "column": 1, "ruleId": "no-unused-vars", "message": "'y' is never used", "severity": 2},
            ],
        }])
        result = self._parse(output)
        assert len(result["/repo/file.ts"]) == 2

    def test_invalid_json(self):
        assert self._parse("not json") == {}

    def test_no_messages(self):
        output = json.dumps([{"filePath": "/repo/clean.ts", "messages": []}])
        result = self._parse(output)
        assert result == {}

    def test_multiple_files(self):
        output = json.dumps([
            {"filePath": "/repo/a.ts", "messages": [{"line": 1, "column": 1, "ruleId": "no-undef", "message": "err", "severity": 2}]},
            {"filePath": "/repo/b.ts", "messages": [{"line": 2, "column": 1, "ruleId": "no-unused-vars", "message": "err", "severity": 2}]},
        ])
        result = self._parse(output)
        assert "/repo/a.ts" in result
        assert "/repo/b.ts" in result

    def test_no_rule_id_uses_unknown(self):
        output = json.dumps([{
            "filePath": "/repo/x.ts",
            "messages": [{"line": 10, "column": 1, "message": "some error", "severity": 2}],
        }])
        result = self._parse(output)
        assert ("unknown", "some error") in result["/repo/x.ts"]


class TestBaselineCompare:
    """End-to-end baseline comparison tests using echo as package manager.

    The echo package manager simulates running ESLint but always succeeds with
    empty output. This tests the filtering and baseline wiring, not ESLint itself.
    """

    @pytest.fixture
    def tmp_repo(self, tmp_path: Path) -> Path:
        repo = tmp_path / "test-repo"
        repo.mkdir()
        subprocess.run(["git", "init", "-b", "main"], cwd=str(repo), capture_output=True)
        subprocess.run(["git", "config", "user.email", "t@t"], cwd=str(repo), capture_output=True)
        subprocess.run(["git", "config", "user.name", "T"], cwd=str(repo), capture_output=True)
        (repo / "README.md").write_text("# test\n")
        subprocess.run(["git", "add", "-A"], cwd=str(repo), capture_output=True)
        subprocess.run(["git", "commit", "-q", "-m", "init"], cwd=str(repo), capture_output=True)
        return repo

    def test_no_changed_lintable_files_skips(self, tmp_repo: Path):
        base = subprocess.run(["git", "rev-parse", "HEAD"], capture_output=True, text=True, cwd=str(tmp_repo)).stdout.strip()
        (tmp_repo / "README.md").write_text("# updated\n")
        subprocess.run(["git", "add", "-A"], cwd=str(tmp_repo), capture_output=True)
        subprocess.run(["git", "commit", "-q", "-m", "update readme"], cwd=str(tmp_repo), capture_output=True)
        proc = _run_script(tmp_repo, base_sha=base)
        out = _parse_output(proc)
        assert out.get("status") == "skipped"
        assert "no changed lintable frontend files" in out.get("reason", "")
        assert proc.returncode == 0

    def test_no_base_sha_skips(self, tmp_repo: Path):
        env = os.environ.copy()
        env.pop("GRACE_BASE_SHA", None)
        env.pop("BASE_SHA", None)
        proc = subprocess.run(
            [sys.executable, str(SCRIPT), "--repo", str(tmp_repo)],
            capture_output=True, text=True, timeout=30, env=env,
        )
        out = _parse_output(proc)
        assert out.get("status") == "skipped"
        assert "no base_sha provided" in out.get("reason", "")

    def test_env_var_base_sha_used(self, tmp_repo: Path):
        base = subprocess.run(["git", "rev-parse", "HEAD"], capture_output=True, text=True, cwd=str(tmp_repo)).stdout.strip()
        env = os.environ.copy()
        env["GRACE_BASE_SHA"] = base
        proc = subprocess.run(
            [sys.executable, str(SCRIPT), "--repo", str(tmp_repo)],
            capture_output=True, text=True, timeout=30, env=env,
        )
        out = _parse_output(proc)
        assert out.get("status") == "skipped"  # no changes => skips

    def test_lintable_change_with_echo_runner(self, tmp_repo: Path):
        """Lintable file change detected even with echo (no actual linting)."""
        base = subprocess.run(["git", "rev-parse", "HEAD"], capture_output=True, text=True, cwd=str(tmp_repo)).stdout.strip()
        (tmp_repo / "component.tsx").write_text("const x = 1;\n")
        subprocess.run(["git", "add", "-A"], cwd=str(tmp_repo), capture_output=True)
        subprocess.run(["git", "commit", "-q", "-m", "add tsx"], cwd=str(tmp_repo), capture_output=True)
        proc = _run_script(tmp_repo, base_sha=base)
        out = _parse_output(proc)
        assert "component.tsx" in out.get("linted_files", [])
        # With echo as package manager, eslint runs "echo exec eslint --format=json <file>"
        # which succeeds, producing empty JSON => no errors => passes
        assert out.get("status") == "passed"
        assert proc.returncode == 0

    def test_changed_node_modules_skipped(self, tmp_repo: Path):
        base = subprocess.run(["git", "rev-parse", "HEAD"], capture_output=True, text=True, cwd=str(tmp_repo)).stdout.strip()
        subdir = tmp_repo / "node_modules" / "somepkg"
        subdir.mkdir(parents=True)
        (subdir / "index.js").write_text("const x = 1;\n")
        subprocess.run(["git", "add", "-A"], cwd=str(tmp_repo), capture_output=True)
        subprocess.run(["git", "commit", "-q", "-m", "add vendor"], cwd=str(tmp_repo), capture_output=True)
        proc = _run_script(tmp_repo, base_sha=base)
        out = _parse_output(proc)
        assert out.get("status") == "skipped"
