# ############################################################################
# AI_HEADER: test_no_control_cli_surface — guard the API-only control contract
# ROLE: Architecture guard for the removed user/control CLI. It protects the
#       direct supervisor bootstrap, package metadata, active references, and
#       the public OpenAPI control surface.
# ############################################################################

# START_MODULE_CONTRACT
# purpose: Prevent the removed control CLI from returning while preserving the
#          supported supervisor bootstrap and HTTP/OpenAPI operator surface.
# inputs: Repository source, package metadata, and the FastAPI application.
# returns: Pytest assertions for the API-only control architecture.
# side_effects: Imports the deterministic application factory; no runtime
#               processes, database writes, or network calls are performed.
# emitted_logs: control_cli_guard_check.
# error_behavior: AssertionError when a removed CLI surface or bootstrap/API
#                 regression is detected.
# END_MODULE_CONTRACT

# START_MODULE_MAP
# mapping:
#   - function: test_control_cli_module_is_absent
#   - function: test_control_cli_entry_points_are_absent
#   - function: test_active_files_have_no_removed_control_cli_references
#   - function: test_api_openapi_surface_remains_constructible
#   - function: test_direct_supervisor_bootstrap_does_not_use_control_cli
# END_MODULE_MAP

from __future__ import annotations

import tomllib
from pathlib import Path

from grace_control.api.app_factory import create_app
from grace_control.core.structured_logger import GraceLogger
from grace_control.supervisor import _parse_args

_log = GraceLogger("test_no_control_cli_surface")

ROOT = Path(__file__).resolve().parents[3]
PYPROJECT = ROOT / "pyproject.toml"
ACTIVE_PATHS = (
    ROOT / "src",
    ROOT / "tests",
    ROOT / "scripts",
    ROOT / "docs" / "grace",
    ROOT / "docs" / "SUPERVISOR.md",
    ROOT / "README.md",
    ROOT / "AGENTS.md",
    PYPROJECT,
    ROOT / "docker",
)
REMOVED_CONTROL_CLI_REFERENCES = (
    "grace_control.cli",
    "grace_ctl",
    "python -m grace_control.cli",
    "command -v gracectl",
    "which gracectl",
    "gracectl --",
    "gracectl slice",
    "python -m gracectl.cli",
    "python3 -m gracectl.cli",
    "python3 -m grace_control.cli",
)
REMOVED_ENTRY_POINT_NAMES = {
    "grace",
    "grace-dev",
    "prefect-grace",
    "gracectl",
    "grace_ctl",
}


# START_BLOCK_GUARD
# START_FUNCTION_CONTRACT
# name: _active_files
# purpose: Enumerate active source, test, script, documentation, metadata, and
#          dependency files while excluding generated caches.
# inputs: None.
# returns: Iterable paths inside the active control-plane surface.
# side_effects: Reads directory metadata only.
# emitted_logs: None.
# error_behavior: Missing optional paths are skipped.
# END_FUNCTION_CONTRACT
def _active_files() -> list[Path]:
    files: list[Path] = []
    ignored_parts = {".git", ".venv", "__pycache__", ".pytest_cache"}
    for root in ACTIVE_PATHS:
        if root.is_file():
            files.append(root)
            continue
        if not root.is_dir():
            continue
        for path in root.rglob("*"):
            if path.is_file() and not ignored_parts.intersection(path.parts):
                files.append(path)
    return files


# START_FUNCTION_CONTRACT
# name: _text
# purpose: Read one active repository file for the reference guard.
# inputs: path — repository file to inspect.
# returns: UTF-8 text with undecodable bytes ignored.
# side_effects: Reads the file.
# emitted_logs: None.
# error_behavior: OSError propagates so a broken guard is visible.
# END_FUNCTION_CONTRACT
def _text(path: Path) -> str:
    return path.read_text(encoding="utf-8", errors="ignore")


# START_FUNCTION_CONTRACT
# name: test_control_cli_module_is_absent
# purpose: Prove the deleted user/control CLI has not returned as a file or
#          package directory.
# inputs: Repository filesystem.
# returns: None after the assertion passes.
# side_effects: Reads filesystem metadata.
# emitted_logs: control_cli_guard_check.
# error_behavior: AssertionError when the removed module path exists.
# END_FUNCTION_CONTRACT
def test_control_cli_module_is_absent() -> None:
    _log.info("control_cli_guard_check", check="module_absent")
    assert not (ROOT / "src" / "grace_control" / "cli.py").exists()
    assert not (ROOT / "src" / "grace_control" / "cli").exists()


# START_FUNCTION_CONTRACT
# name: test_control_cli_entry_points_are_absent
# purpose: Prove package metadata does not expose the removed operator command
#          names or targets.
# inputs: pyproject.toml.
# returns: None after the assertion passes.
# side_effects: Reads package metadata.
# emitted_logs: control_cli_guard_check.
# error_behavior: AssertionError when an old entry point is declared.
# END_FUNCTION_CONTRACT
def test_control_cli_entry_points_are_absent() -> None:
    _log.info("control_cli_guard_check", check="entry_points_absent")
    with PYPROJECT.open("rb") as stream:
        project = tomllib.load(stream)
    scripts = project.get("project", {}).get("scripts", {})
    assert not REMOVED_ENTRY_POINT_NAMES.intersection(scripts)
    assert all("grace_control.cli" not in str(target) for target in scripts.values())


# START_FUNCTION_CONTRACT
# name: test_active_files_have_no_removed_control_cli_references
# purpose: Prove active source, scripts, operator docs, metadata, and Docker
#          dependencies do not recreate the removed control CLI.
# inputs: Active repository files.
# returns: None after the assertion passes.
# side_effects: Reads active text files.
# emitted_logs: control_cli_guard_check.
# error_behavior: AssertionError listing every forbidden active reference.
# END_FUNCTION_CONTRACT
def test_active_files_have_no_removed_control_cli_references() -> None:
    _log.info("control_cli_guard_check", check="active_references_absent")
    guard_path = Path(__file__).resolve()
    offenders: list[tuple[str, str]] = []
    for path in _active_files():
        if path == guard_path:
            continue
        text = _text(path)
        for reference in REMOVED_CONTROL_CLI_REFERENCES:
            if reference in text:
                offenders.append((str(path.relative_to(ROOT)), reference))
    assert not offenders, f"Removed control CLI references remain active: {offenders}"


# START_FUNCTION_CONTRACT
# name: test_api_openapi_surface_remains_constructible
# purpose: Prove the existing FastAPI application and public lifecycle control
#          routes remain constructible after CLI removal.
# inputs: Application factory.
# returns: None after the assertion passes.
# side_effects: Builds an in-memory application object and its OpenAPI schema.
# emitted_logs: control_cli_guard_check.
# error_behavior: AssertionError when the app or canonical routes disappear.
# END_FUNCTION_CONTRACT
def test_api_openapi_surface_remains_constructible() -> None:
    _log.info("control_cli_guard_check", check="openapi_surface")
    app = create_app()
    paths = set(app.openapi().get("paths", {}))
    route_paths = {getattr(route, "path", "") for route in app.routes}
    assert "/openapi.json" in route_paths
    assert "/api/admin/lifecycle/status" in paths
    assert any(path.startswith("/api/features") for path in paths)


# START_FUNCTION_CONTRACT
# name: test_direct_supervisor_bootstrap_does_not_use_control_cli
# purpose: Prove the supported shell bootstrap invokes the real supervisor
#          module with the existing supervisor argument contract.
# inputs: live_supervisor.sh and supervisor argument parser.
# returns: None after the assertion passes.
# side_effects: Reads the bootstrap script and parses synthetic arguments.
# emitted_logs: control_cli_guard_check.
# error_behavior: AssertionError when bootstrap depends on the removed CLI or
#                 no longer accepts its established arguments.
# END_FUNCTION_CONTRACT
def test_direct_supervisor_bootstrap_does_not_use_control_cli() -> None:
    _log.info("control_cli_guard_check", check="supervisor_bootstrap")
    script = _text(ROOT / "scripts" / "live_supervisor.sh")
    assert "-m grace_control.supervisor" in script
    assert not any(reference in script for reference in REMOVED_CONTROL_CLI_REFERENCES)

    args = _parse_args([
        "--target-dir", "/tmp/target",
        "--source-dir", "/tmp/source",
        "--workers", "2",
        "--api-url", "http://127.0.0.1:8042",
        "--no-watch",
    ])
    assert str(args.target_dir) == "/tmp/target"
    assert str(args.source_dir) == "/tmp/source"
    assert args.workers == 2
    assert args.api_url == "http://127.0.0.1:8042"
    assert args.no_watch is True
# END_BLOCK_GUARD
