# ############################################################################
# AI_HEADER: ci_lint_baseline — full-scope baseline-aware Ruff and GraceLint gate
# ROLE: Runs both canonical Python linters across the supported source, test,
#      and script tree, then rejects diagnostic drift against the reviewed
#      baseline. Make owns invocation; this module owns comparison semantics.
# ############################################################################

# START_MODULE_CONTRACT
# purpose: Execute Ruff and GraceLint over the complete supported Python scope
#          and fail when the reviewed diagnostic baseline changes.
# inputs: Baseline JSON path and one or more repository-relative Python roots.
# returns: Process exit code; zero only when both full-scope diagnostics match.
# side_effects: Spawns local linter subprocesses and reads the baseline file.
# emitted_logs: ci_lint_baseline_loaded, ci_lint_baseline_passed,
#               ci_lint_baseline_changed.
# error_behavior: Returns one for missing/malformed baseline, linter failure,
#                 or any diagnostic/exit-code drift.
# END_MODULE_CONTRACT

# START_MODULE_MAP
# mapping:
#   - function: main
# END_MODULE_MAP

from __future__ import annotations

import argparse
import hashlib
import json
import re
import subprocess
import sys
from pathlib import Path

from grace_control.core.structured_logger import GraceLogger

_log = GraceLogger("ci_lint_baseline")
_ROOT = Path(__file__).resolve().parents[1]
_BASELINE_VERSION = 1


# START_BLOCK_HELPERS
def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run full-scope baseline-aware Ruff and GraceLint.")
    parser.add_argument("--baseline", required=True, help="reviewed JSON diagnostic baseline")
    parser.add_argument("--scope", nargs="+", required=True, help="repository-relative Python roots")
    return parser.parse_args()


def _run(command: list[str]) -> tuple[int, str]:
    result = subprocess.run(
        command,
        cwd=_ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    output = "\n".join(sorted(line.rstrip() for line in (result.stdout + result.stderr).splitlines() if line.strip()))
    return result.returncode, output


def _digest(output: str) -> str:
    return hashlib.sha256(output.encode("utf-8")).hexdigest()


def _diagnostic_count(tool: str, output: str) -> int:
    if tool == "ruff":
        match = re.search(r"Found (\d+) errors?\.", output)
        return int(match.group(1)) if match else 0
    return sum(1 for line in output.splitlines() if re.search(r"^.+:\d+: GRC\d{3} ", line))


def _baseline_record(tool: str, exit_code: int, output: str) -> dict[str, int | str]:
    return {
        "exit_code": exit_code,
        "diagnostic_count": _diagnostic_count(tool, output),
        "sha256": _digest(output),
    }


def _load_baseline(path: Path) -> dict:
    try:
        baseline = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError(f"cannot read lint baseline {path}: {exc}") from exc
    if baseline.get("version") != _BASELINE_VERSION:
        raise ValueError(f"unsupported lint baseline version in {path}")
    if baseline.get("scope") != ["src/grace_control", "tests", "scripts"]:
        raise ValueError(f"lint baseline scope is not the supported full scope: {path}")
    return baseline


def _compare(tool: str, actual: dict[str, int | str], expected: dict[str, int | str]) -> bool:
    if actual["exit_code"] not in (0, 1):
        sys.stdout.write(f"FAIL: {tool} command failed with exit code {actual['exit_code']}\n")
        return False
    if (
        actual["exit_code"] == expected["exit_code"]
        and actual["diagnostic_count"] == expected["diagnostic_count"]
        and actual["sha256"] == expected["sha256"]
    ):
        return True
    sys.stdout.write(
        f"FAIL: {tool} diagnostic baseline changed; expected "
        f"exit={expected['exit_code']} count={expected['diagnostic_count']} "
        f"sha={expected['sha256']}, got exit={actual['exit_code']} "
        f"count={actual['diagnostic_count']} sha={actual['sha256']}\n"
    )
    return False


# END_BLOCK_HELPERS


# START_BLOCK_MAIN
# START_FUNCTION_CONTRACT
# name: main
# purpose: Run both full-scope linters and compare their diagnostics with the reviewed baseline.
# inputs: --baseline JSON path and --scope repository-relative Python roots.
# returns: Zero when both tools match the baseline; one when they drift or fail.
# side_effects: Spawns Ruff and GraceLint subprocesses and writes gate status.
# emitted_logs: ci_lint_baseline_loaded, ci_lint_baseline_passed, ci_lint_baseline_changed.
# error_behavior: Reports invalid baseline or diagnostic drift and returns one.
# END_FUNCTION_CONTRACT
def main() -> int:
    args = _parse_args()
    baseline_path = _ROOT / args.baseline
    try:
        baseline = _load_baseline(baseline_path)
    except ValueError as exc:
        _log.error("ci_lint_baseline_changed", reason=str(exc))
        sys.stdout.write(f"FAIL: {exc}\n")
        return 1

    _log.info("ci_lint_baseline_loaded", baseline=str(baseline_path), scope=args.scope)
    ruff_exit, ruff_output = _run(
        [sys.executable, "-m", "ruff", "check", "--output-format", "concise", *args.scope]
    )
    grace_exit, grace_output = _run([sys.executable, "scripts/grace_lint.py", *args.scope])
    actual = {
        "ruff": _baseline_record("ruff", ruff_exit, ruff_output),
        "gracelint": _baseline_record("gracelint", grace_exit, grace_output),
    }
    matches = all(_compare(tool, actual[tool], baseline[tool]) for tool in ("ruff", "gracelint"))
    if not matches:
        _log.error("ci_lint_baseline_changed", scope=args.scope)
        return 1

    _log.info(
        "ci_lint_baseline_passed",
        ruff_diagnostics=actual["ruff"]["diagnostic_count"],
        gracelint_diagnostics=actual["gracelint"]["diagnostic_count"],
    )
    sys.stdout.write(
        "OK: full-scope Ruff and GraceLint match reviewed baseline; "
        f"ruff={actual['ruff']['diagnostic_count']} "
        f"gracelint={actual['gracelint']['diagnostic_count']}\n"
    )
    return 0


# END_BLOCK_MAIN


if __name__ == "__main__":
    sys.exit(main())
