#!/usr/bin/env python3
# ############################################################################
# AI_HEADER: ci_repo_hygiene — deterministic tracked-repository hygiene gate
# ROLE: Rejects tracked runtime/generated artifacts and preserves the existing
#       legacy-entrypoint/package checks used by CI. It never scans untracked
#       developer state or accesses the network.
# ############################################################################

# START_MODULE_CONTRACT
# purpose: Check tracked repository paths and packaging metadata for obsolete
#          runtime artifacts and legacy package surfaces.
# inputs: Git tracked paths and the repository pyproject.toml.
# returns: Exit status zero for a clean repository, one with exact violations.
# side_effects: Reads Git index metadata and local pyproject.toml only.
# emitted_logs: repo_hygiene_failed, repo_hygiene_passed.
# error_behavior: Git or metadata read failures are reported as hygiene errors.
# END_MODULE_CONTRACT

# START_MODULE_MAP
# mapping:
#   - function: tracked_files
#   - function: tracked_runtime_artifacts
#   - function: check_repo_hygiene
#   - function: main
# END_MODULE_MAP

from __future__ import annotations

import re
import subprocess
import sys
import tomllib
from collections.abc import Sequence
from pathlib import Path

_SRC_ROOT = Path(__file__).resolve().parents[1] / "src"
if str(_SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(_SRC_ROOT))

from grace_control.core.structured_logger import GraceLogger  # noqa: E402

_log = GraceLogger("ci_repo_hygiene")

# START_BLOCK_CONSTANTS
_REPO_ROOT = Path(__file__).resolve().parents[1]
_LEGACY_ENTRYPOINTS = ("grace", "grace-dev", "prefect-grace", "gracectl")
_TRACKED_RUNTIME_PATTERNS = (
    re.compile(r"^%2Ftmp%2F"),
    re.compile(r"^\.goldw/"),
    re.compile(r"^\.lw3/"),
    re.compile(r"^\.grace-live-wt/"),
    re.compile(r"^src/gold-test/"),
)
# END_BLOCK_CONSTANTS


# START_BLOCK_HELPERS
# START_FUNCTION_CONTRACT
# name: _tracked_files_for_root
# purpose: Read the repository's tracked paths from its Git index.
# inputs: repo_root — repository root containing the Git checkout.
# returns: Sorted tracked relative paths.
# side_effects: Executes local `git ls-files`; no network access.
# emitted_logs: None.
# error_behavior: Raises RuntimeError when Git cannot return the index.
# END_FUNCTION_CONTRACT
def _tracked_files_for_root(repo_root: Path) -> tuple[str, ...]:
    result = subprocess.run(
        ["git", "ls-files", "-z"],
        cwd=repo_root,
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode != 0:
        raise RuntimeError(result.stderr.strip() or "git ls-files failed")
    return tuple(sorted(path for path in result.stdout.split("\0") if path))


# START_FUNCTION_CONTRACT
# name: tracked_files
# purpose: Return all paths currently tracked by this repository.
# inputs: None; repository root is resolved from this script location.
# returns: Sorted tuple of tracked relative paths.
# side_effects: Executes local `git ls-files`; no network access.
# emitted_logs: None.
# error_behavior: Propagates a local Git index failure.
# END_FUNCTION_CONTRACT
def tracked_files() -> tuple[str, ...]:
    return _tracked_files_for_root(_REPO_ROOT)


# START_FUNCTION_CONTRACT
# name: tracked_runtime_artifacts
# purpose: Select only confirmed generated/runtime paths from tracked paths.
# inputs: paths — tracked repository-relative paths.
# returns: Tuple containing every offending path in deterministic order.
# side_effects: None.
# emitted_logs: None.
# error_behavior: Never raises for an iterable of path strings.
# END_FUNCTION_CONTRACT
def tracked_runtime_artifacts(paths: Sequence[str]) -> tuple[str, ...]:
    return tuple(
        path for path in paths
        if any(pattern.match(path) for pattern in _TRACKED_RUNTIME_PATTERNS)
    )


# END_BLOCK_HELPERS


# START_BLOCK_CHECK
# START_FUNCTION_CONTRACT
# name: check_repo_hygiene
# purpose: Combine tracked-artifact, legacy-entrypoint and package checks.
# inputs: repo_root — optional root for tests; paths — optional tracked paths.
# returns: Exact human-readable hygiene errors, empty when clean.
# side_effects: Reads Git index and pyproject.toml when arguments are omitted.
# emitted_logs: None.
# error_behavior: Converts local inspection failures into one hygiene error.
# END_FUNCTION_CONTRACT
def check_repo_hygiene(
    repo_root: Path | None = None,
    paths: Sequence[str] | None = None,
) -> list[str]:
    root = repo_root or _REPO_ROOT
    errors: list[str] = []
    try:
        if paths is not None:
            tracked = tuple(paths)
        elif repo_root is None:
            tracked = tracked_files()
        else:
            tracked = _tracked_files_for_root(root)
        errors.extend(
            f"tracked runtime/generated artifact: {path}"
            for path in tracked_runtime_artifacts(tracked)
        )
        agents = tuple(path for path in tracked if path.startswith("agents/"))
        if agents:
            errors.append(f"tracked artifacts in agents/:\n{chr(10).join(agents)[:200]}")
        with (root / "pyproject.toml").open("rb") as config_file:
            project = tomllib.load(config_file)
    except (OSError, RuntimeError, tomllib.TOMLDecodeError) as exc:
        return [f"repository inspection failed: {exc}"]

    scripts = project.get("project", {}).get("scripts", {})
    for name in _LEGACY_ENTRYPOINTS:
        if name in scripts:
            errors.append(f"legacy entrypoint '{name}' found in pyproject.toml")

    packages = project.get("tool", {}).get("hatch", {}).get("build", {}).get("packages", [])
    if "src/prefect_grace" in packages:
        errors.append("src/prefect_grace in hatch packages")
    return errors


# END_BLOCK_CHECK


# START_BLOCK_MAIN
# START_FUNCTION_CONTRACT
# name: main
# purpose: Run the repository hygiene gate and render deterministic CLI output.
# inputs: None; reads the current repository checkout.
# returns: Process exit code, zero for clean and one for violations.
# side_effects: Writes status and exact offending paths to stdout.
# emitted_logs: None.
# error_behavior: Returns one when any hygiene check fails.
# END_FUNCTION_CONTRACT
def main() -> int:
    errors = check_repo_hygiene()
    if errors:
        _log.error("repo_hygiene_failed", error_count=len(errors))
        sys.stdout.write("FAIL: repo-hygiene\n")
        for error in errors:
            sys.stdout.write(f"  - {error}\n")
        return 1
    _log.info("repo_hygiene_passed")
    sys.stdout.write("OK: repo-hygiene passed\n")
    return 0


# END_BLOCK_MAIN


if __name__ == "__main__":
    sys.exit(main())
