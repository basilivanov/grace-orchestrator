# ############################################################################
# AI_HEADER: test_repo_hygiene_boundary — guard for dead-code cleanup policy
# ROLE: Ensures the tracked runtime gate remains present and deleted legacy
#       modules do not quietly return through active source references.
# ############################################################################

# START_MODULE_CONTRACT
# purpose: Guard the narrow repository-hygiene policy and deletion boundary.
# inputs: Repository source, tests, scripts and hygiene module.
# returns: Pytest assertions for tracked artifact and dead-reference invariants.
# side_effects: Reads repository files only.
# emitted_logs: None.
# error_behavior: Fails when proven generated paths or deleted imports recur.
# END_MODULE_CONTRACT

# START_MODULE_MAP
# mapping:
#   - function: test_hygiene_script_and_policy_exist
#   - function: test_deleted_legacy_paths_have_no_active_imports
# END_MODULE_MAP

from __future__ import annotations

import ast
import importlib.util
from pathlib import Path

from grace_control.core.structured_logger import GraceLogger

_log = GraceLogger("test_repo_hygiene_boundary")

_ROOT = Path(__file__).parents[3]
_SCRIPT = _ROOT / "scripts/ci_repo_hygiene.py"
_SPEC = importlib.util.spec_from_file_location("ci_repo_hygiene_boundary", _SCRIPT)
assert _SPEC is not None and _SPEC.loader is not None
_MODULE = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(_MODULE)
_DELETED_PATHS = (
    _ROOT / "src/hello_grace.py",
    _ROOT / "tests/test_hello_grace.py",
    _ROOT / "src/grace_control/core/hello.py",
    _ROOT / "src/grace_control/mod.py",
    _ROOT / "tests/grace_control/core/test_mod.py",
    _ROOT / "demo_resources.py",
    _ROOT / "scripts/test_api_integration.py",
    _ROOT / "src/gold-test/result.txt",
)
_ACTIVE_ROOTS = (_ROOT / "src", _ROOT / "tests", _ROOT / "scripts")


# START_FUNCTION_CONTRACT
# name: test_hygiene_script_and_policy_exist
# purpose: Ensure the executable hygiene gate and all confirmed path families
#          remain present in policy rather than comments only.
# inputs: None; uses the repository hygiene module.
# returns: None.
# side_effects: Reads local policy state.
# emitted_logs: None.
# error_behavior: Fails when the gate or any confirmed matcher disappears.
# END_FUNCTION_CONTRACT
def test_hygiene_script_and_policy_exist():
    assert (_ROOT / "scripts/ci_repo_hygiene.py").exists()
    samples = (
        "%2Ftmp%2Fsomething.db",
        ".goldw/x",
        ".lw3/x",
        ".grace-live-wt/x",
        "src/gold-test/result.txt",
        "runtime.db",
        "state/runtime.db-shm",
        "state/runtime.db-wal",
    )
    assert _MODULE.tracked_runtime_artifacts(samples) == samples


# START_FUNCTION_CONTRACT
# name: test_deleted_legacy_paths_have_no_active_imports
# purpose: Ensure deleted demo/module paths do not reappear as active imports.
# inputs: None; scans active source/test/script Python files.
# returns: None.
# side_effects: Reads Python source files.
# emitted_logs: None.
# error_behavior: Fails if a surviving file imports a deleted module path.
# END_FUNCTION_CONTRACT
def test_deleted_legacy_paths_have_no_active_imports():
    for path in _DELETED_PATHS:
        assert not path.exists(), path
    forbidden_modules = {
        "hello_grace", "grace_control.mod", "grace_control.core.hello",
        "demo_resources", "test_api_integration",
    }
    for root in _ACTIVE_ROOTS:
        for path in root.rglob("*.py"):
            if path == Path(__file__) or path.name == "test_ci_repo_hygiene.py":
                continue
            tree = ast.parse(path.read_text())
            for node in ast.walk(tree):
                if isinstance(node, ast.Import):
                    names = {alias.name for alias in node.names}
                elif isinstance(node, ast.ImportFrom):
                    names = {node.module or ""}
                else:
                    continue
                assert names.isdisjoint(forbidden_modules), f"{path}: {names & forbidden_modules}"
