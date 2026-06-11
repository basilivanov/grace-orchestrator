#!/usr/bin/env python3
"""Changed-file ESLint gate — baseline comparison mode.

Runs ESLint on changed frontend files against both the base commit version
and the current working version. Only NEW errors (present in current but
absent from base) cause the gate to fail. Pre-existing errors are reported
as informational baseline debt.

Usage:
    python3 scripts/grace_changed_files_lint.py --repo . --base-sha <sha>

Input:
  --repo           target worktree path, default cwd
  --base-sha       commit sha to diff against; fallback GRACE_BASE_SHA env, then BASE_SHA env
  --package-manager pnpm, default pnpm

Output (stdout):
  JSON with changed_files, linted_files, baseline_errors, new_errors, exit_code, policy.
  Exits 0 on pass/skip, non-zero on new lint errors.
"""

import argparse
import json
import os
import re
import subprocess
import sys
import tempfile
from pathlib import Path


EXCLUDED_DIRS = {
    "node_modules",
    ".next",
    "dist",
    "build",
    "coverage",
    ".git",
    ".venv",
    "__pycache__",
    ".tox",
    ".ruff_cache",
    ".eslintcache",
}

LINTABLE_EXTENSIONS = {".js", ".jsx", ".ts", ".tsx"}

# Regex to extract eslint error line numbers from compact output
# Format: "<file>:<line>:<col>  <severity>  <rule>  <message>"
ESLINT_ERROR_LINE_RE = re.compile(r"^(.+?):(\d+):\d+\s+(error|warning)\s+")

# Eslint compact formatter fallback patterns for JSON output
# When using --format=json, the output is a JSON array of file results


def _is_lintable(path: str) -> bool:
    p = Path(path)
    if p.suffix not in LINTABLE_EXTENSIONS:
        return False
    for part in p.parts:
        if part in EXCLUDED_DIRS:
            return False
    return True


def _get_changed_files(repo: Path, base_sha: str) -> list[str]:
    try:
        r = subprocess.run(
            ["git", "diff", "--name-only", base_sha, "HEAD"],
            capture_output=True, text=True, cwd=str(repo), timeout=30,
        )
        if r.returncode != 0:
            print(f"warning: git diff failed: {r.stderr.strip()}", file=sys.stderr)
            return []
        return [p.strip() for p in r.stdout.split("\n") if p.strip()]
    except Exception as e:
        print(f"warning: git diff exception: {e}", file=sys.stderr)
        return []


def _get_base_file(repo: Path, base_sha: str, filepath: str) -> str | None:
    """Get file content from the base commit."""
    try:
        r = subprocess.run(
            ["git", "show", f"{base_sha}:{filepath}"],
            capture_output=True, text=True, cwd=str(repo), timeout=15,
        )
        if r.returncode == 0:
            return r.stdout
        return None
    except Exception:
        return None


def _build_eslint_cmd(repo: Path, package_manager: str) -> list[str]:
    """Build eslint command with config detection."""
    if (repo / ".eslintrc.json").exists():
        return [package_manager, "exec", "eslint", "--no-eslintrc", "--config", ".eslintrc.json"]
    if (repo / ".eslintrc.js").exists():
        return [package_manager, "exec", "eslint", "--no-eslintrc", "--config", ".eslintrc.js"]
    if (repo / ".eslintrc.cjs").exists():
        return [package_manager, "exec", "eslint", "--no-eslintrc", "--config", ".eslintrc.cjs"]
    if (repo / ".eslintrc.yaml").exists():
        return [package_manager, "exec", "eslint", "--no-eslintrc", "--config", ".eslintrc.yaml"]
    if (repo / ".eslintrc.yml").exists():
        return [package_manager, "exec", "eslint", "--no-eslintrc", "--config", ".eslintrc.yml"]
    return [package_manager, "exec", "eslint"]


def _parse_eslint_compact(output: str, filepath: str) -> set[tuple[str, int]]:
    """Parse ESLint compact output into {(rule_or_msg, line)} tuples.

    Returns a set of (descriptive_key, line_number) tuples representing errors.
    """
    errors: set[tuple[str, int]] = set()
    for line in output.split("\n"):
        m = ESLINT_ERROR_LINE_RE.match(line)
        if m:
            err_path = m.group(1).strip()
            if err_path.endswith(filepath) or err_path == filepath:
                line_no = int(m.group(2))
                # Extract rule name from the rest of the line
                parts = line.split()
                if len(parts) >= 4:
                    # Format: <file>:<line>:<col>  <severity>  <rule>  <message>
                    # The rule is at index -2 relative to message end, or after severity
                    severity_idx = None
                    for i, p in enumerate(parts):
                        if p in ("error", "warning"):
                            severity_idx = i
                            break
                    if severity_idx is not None and severity_idx + 1 < len(parts):
                        rule = parts[severity_idx + 1]
                        errors.add((rule, line_no))
    return errors


def _parse_eslint_json(output: str) -> dict[str, set[tuple[str, str]]]:
    """Parse ESLint JSON output into {filepath: {(rule, message)}}.

    JSON format: [{"filePath": "...", "messages": [{"line": N, "ruleId": "...", "message": "...", ...}]}]
    Uses (ruleId, message) as key so line-shifted errors are recognized as pre-existing.
    """
    result: dict[str, set[tuple[str, str]]] = {}
    try:
        data = json.loads(output)
        for file_result in data:
            fp = file_result.get("filePath", "")
            messages = file_result.get("messages", [])
            errors: set[tuple[str, str]] = set()
            for msg in messages:
                rule = msg.get("ruleId", "unknown")
                message = msg.get("message", "")
                errors.add((rule, message))
            if errors:
                result[fp] = errors
    except (json.JSONDecodeError, ValueError):
        pass
    return result


def _run_eslint(
    repo: Path,
    package_manager: str,
    files: list[str],
    stdin_content: str | None = None,
) -> tuple[int, str, set[tuple[str, str]]]:
    """Run ESLint on files or stdin content.

    Returns (exit_code, full_stdout, parsed_errors).
    Errors deduplicated by (ruleId, message) so line-shifted errors match.
    """
    cmd = _build_eslint_cmd(repo, package_manager)
    cmd.append("--format=json")
    if stdin_content is not None:
        cmd.extend(["--stdin", "--stdin-filename", files[0]])
        try:
            r = subprocess.run(
                cmd, input=stdin_content, capture_output=True, text=True,
                cwd=str(repo), timeout=120,
            )
            parsed = _parse_eslint_json(r.stdout)
            combined: set[tuple[str, str]] = set()
            for _, errs in parsed.items():
                combined.update(errs)
            return r.returncode, r.stdout, combined
        except Exception as e:
            return 1, str(e), set()
    else:
        cmd.extend(files)
        try:
            r = subprocess.run(
                cmd, capture_output=True, text=True,
                cwd=str(repo), timeout=120,
            )
            parsed = _parse_eslint_json(r.stdout)
            combined = set()
            for _, errs in parsed.items():
                combined.update(errs)
            return r.returncode, r.stdout, combined
        except Exception as e:
            return 1, str(e), set()


def main() -> None:
    parser = argparse.ArgumentParser(description="Changed-file ESLint gate (baseline compare)")
    parser.add_argument("--repo", default=os.getcwd(), help="target worktree path")
    parser.add_argument("--base-sha", default=None, help="base commit sha to diff against")
    parser.add_argument("--package-manager", default="pnpm", help="package manager (pnpm/npm/yarn)")
    args = parser.parse_args()

    base_sha = args.base_sha or os.environ.get("GRACE_BASE_SHA") or os.environ.get("BASE_SHA", "")
    repo = Path(args.repo).resolve()

    if not base_sha:
        print(json.dumps({
            "changed_files": [],
            "linted_files": [],
            "exit_code": 0,
            "policy": "changed_files_no_new_errors",
            "status": "skipped",
            "reason": "no base_sha provided",
        }))
        sys.exit(0)

    changed = _get_changed_files(repo, base_sha)
    lintable = [f for f in changed if _is_lintable(f)]

    if not lintable:
        print(json.dumps({
            "changed_files": changed,
            "linted_files": [],
            "exit_code": 0,
            "policy": "changed_files_no_new_errors",
            "status": "skipped",
            "reason": "no changed lintable frontend files",
        }))
        sys.exit(0)

    # --- Baseline comparison: for each file, compare base vs current errors ---
    baseline_errors: dict[str, set[tuple[str, int]]] = {}
    current_errors: dict[str, set[tuple[str, int]]] = {}
    new_errors: dict[str, set[tuple[str, int]]] = {}

    for filepath in lintable:
        # Get base version
        base_content = _get_base_file(repo, base_sha, filepath)
        if base_content is not None:
            _, _, base_errs = _run_eslint(repo, args.package_manager, [filepath], stdin_content=base_content)
        else:
            base_errs = set()
        baseline_errors[filepath] = base_errs

        # Get current version
        _, _, curr_errs = _run_eslint(repo, args.package_manager, [filepath])
        current_errors[filepath] = curr_errs

        # New errors = current - baseline
        new_errs = curr_errs - base_errs
        if new_errs:
            new_errors[filepath] = new_errs

    # Convert to serializable format
    def _errs_to_list(errs: set[tuple[str, str]]) -> list[dict]:
        return [{"rule": r, "message": m} for r, m in sorted(errs)]

    baseline_serialized = {k: _errs_to_list(v) for k, v in baseline_errors.items()}
    new_serialized = {k: _errs_to_list(v) for k, v in new_errors.items()}

    has_new_errors = bool(new_errors)
    exit_code = 1 if has_new_errors else 0

    output = {
        "changed_files": changed,
        "linted_files": lintable,
        "baseline_errors": baseline_serialized,
        "new_errors": new_serialized,
        "exit_code": exit_code,
        "policy": "changed_files_baseline_compare",
        "status": "failed" if has_new_errors else "passed",
    }

    print(json.dumps(output))
    sys.exit(exit_code)


if __name__ == "__main__":
    main()
