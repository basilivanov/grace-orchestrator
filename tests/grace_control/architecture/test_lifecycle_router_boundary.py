# ############################################################################
# AI_HEADER: test_lifecycle_router_boundary — lifecycle dependency graph guard
# ROLE: Locks the thin lifecycle HTTP boundary and explicit service graph.
#      AST checks prevent filesystem, DB, subprocess, and router-private control
#      coupling from returning to the API adapter.
# ############################################################################

# START_MODULE_CONTRACT
# purpose: Verify lifecycle router and extracted services retain the required
#          dependency direction and explicit composition contracts.
# inputs: Active lifecycle router, service, composition, and Admin source files.
# returns: Pytest assertions; no production values are returned.
# side_effects: Reads and parses Python source files.
# emitted_logs: None.
# error_behavior: Raises AssertionError when a forbidden boundary dependency or
#                 hidden constructor dependency is detected.
# END_MODULE_CONTRACT

# START_MODULE_MAP
# mapping:
#   - function: test_lifecycle_router_has_no_infrastructure_imports
#   - function: test_lifecycle_router_has_no_infrastructure_calls
#   - function: test_admin_local_has_no_router_private_controls
#   - function: test_lifecycle_services_have_no_fastapi_imports
#   - function: test_lifecycle_service_constructor_is_explicit
#   - function: test_lifecycle_composition_is_narrow
# END_MODULE_MAP

from __future__ import annotations

import ast
from pathlib import Path

from grace_control.core.structured_logger import GraceLogger

_log = GraceLogger("lifecycle_router_boundary")
_ROOT = Path(__file__).resolve().parents[3]
_SRC = _ROOT / "src" / "grace_control"
_ROUTER = _SRC / "api" / "routers" / "lifecycle.py"
_ADMIN_LOCAL = _SRC / "api" / "routers" / "admin_controls_local.py"
_SERVICE_FILES = (
    "runtime_state_store.py",
    "supervisor_control_service.py",
    "worker_read_service.py",
    "version_provider.py",
    "lifecycle_service.py",
)


# START_BLOCK_LIFECYCLE_BOUNDARY
# START_FUNCTION_CONTRACT
# name: _tree
# purpose: Parse one active source file for AST assertions.
# inputs: path — source file path.
# returns: Parsed Python AST.
# side_effects: Reads path.
# emitted_logs: None.
# error_behavior: Syntax errors propagate to make the guard fail closed.
# END_FUNCTION_CONTRACT
def _tree(path: Path) -> ast.Module:
    return ast.parse(path.read_text(encoding="utf-8"))


# START_FUNCTION_CONTRACT
# name: test_lifecycle_router_has_no_infrastructure_imports
# purpose: Reject direct infrastructure imports from the lifecycle adapter.
# inputs: None; parses lifecycle.py.
# returns: None after import assertions pass.
# side_effects: Reads and parses lifecycle.py.
# emitted_logs: None.
# error_behavior: AssertionError for forbidden imports.
# END_FUNCTION_CONTRACT
def test_lifecycle_router_has_no_infrastructure_imports() -> None:
    tree = _tree(_ROUTER)
    forbidden = {"os", "subprocess", "httpx", "get_db", "Worker"}
    imported: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported.update(alias.name.split(".")[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            imported.update(alias.name for alias in node.names)
    assert not imported.intersection(forbidden), imported.intersection(forbidden)


# START_FUNCTION_CONTRACT
# name: test_lifecycle_router_has_no_infrastructure_calls
# purpose: Reject direct environment, subprocess, ORM, state-file, and UDS
#          transport operations in the lifecycle adapter.
# inputs: None; parses lifecycle.py.
# returns: None after call/string assertions pass.
# side_effects: Reads and parses lifecycle.py.
# emitted_logs: None.
# error_behavior: AssertionError for forbidden calls or helper definitions.
# END_FUNCTION_CONTRACT
def test_lifecycle_router_has_no_infrastructure_calls() -> None:
    tree = _tree(_ROUTER)
    source = _ROUTER.read_text(encoding="utf-8")
    forbidden_calls = {"environ", "run", "query", "AsyncHTTPTransport", "read_text", "read_bytes"}
    assert not any(
        isinstance(node, ast.Attribute) and node.attr in forbidden_calls
        for node in ast.walk(tree)
    )
    assert "supervisor.json" not in source
    assert not {
        node.name for node in tree.body if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
    }.intersection({"read_state_file", "get_git_sha", "get_db_workers", "_proxy_supervisor"})


# START_FUNCTION_CONTRACT
# name: test_admin_local_has_no_router_private_controls
# purpose: Reject the former lifecycle-router private restart/reload seam from
#          local Admin dispatch.
# inputs: None; reads admin_controls_local.py.
# returns: None after source assertions pass.
# side_effects: Reads admin_controls_local.py.
# emitted_logs: None.
# error_behavior: AssertionError for forbidden imports or helper names.
# END_FUNCTION_CONTRACT
def test_admin_local_has_no_router_private_controls() -> None:
    source = _ADMIN_LOCAL.read_text(encoding="utf-8")
    assert "grace_control.api.routers.lifecycle" not in source
    assert "_restart_local" not in source
    assert "_reload_local" not in source


# START_FUNCTION_CONTRACT
# name: test_lifecycle_services_have_no_fastapi_imports
# purpose: Keep extracted lifecycle services independent from the HTTP layer.
# inputs: None; parses all five lifecycle service modules.
# returns: None after import assertions pass.
# side_effects: Reads and parses service files.
# emitted_logs: None.
# error_behavior: AssertionError for FastAPI imports.
# END_FUNCTION_CONTRACT
def test_lifecycle_services_have_no_fastapi_imports() -> None:
    for filename in _SERVICE_FILES:
        tree = _tree(_SRC / "services" / filename)
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                assert all(alias.name != "fastapi" for alias in node.names), filename
            if isinstance(node, ast.ImportFrom):
                assert node.module != "fastapi", filename


# START_FUNCTION_CONTRACT
# name: test_lifecycle_service_constructor_is_explicit
# purpose: Verify LifecycleService receives exactly its four lower-level
#          collaborators rather than constructing hidden dependencies.
# inputs: None; parses lifecycle_service.py.
# returns: None after constructor assertions pass.
# side_effects: Reads and parses lifecycle_service.py.
# emitted_logs: None.
# error_behavior: AssertionError when the explicit collaborator contract drifts.
# END_FUNCTION_CONTRACT
def test_lifecycle_service_constructor_is_explicit() -> None:
    tree = _tree(_SRC / "services" / "lifecycle_service.py")
    service = next(node for node in tree.body if isinstance(node, ast.ClassDef) and node.name == "LifecycleService")
    init = next(node for node in service.body if isinstance(node, ast.FunctionDef) and node.name == "__init__")
    names = {arg.arg for arg in (*init.args.posonlyargs, *init.args.args, *init.args.kwonlyargs)} - {"self"}
    assert names == {"state_store", "supervisor", "workers", "version"}


# START_FUNCTION_CONTRACT
# name: test_lifecycle_composition_is_narrow
# purpose: Reject generic lookup and process-global settings mutation in the
#          lifecycle composition root.
# inputs: None; reads lifecycle_composition.py.
# returns: None after composition assertions pass.
# side_effects: Reads source.
# emitted_logs: None.
# error_behavior: AssertionError for generic locator or settings mutation.
# END_FUNCTION_CONTRACT
def test_lifecycle_composition_is_narrow() -> None:
    path = _SRC / "lifecycle_composition.py"
    source = path.read_text(encoding="utf-8")
    assert "ServiceLocator" not in source
    assert "ManagerFactory" not in source
    assert "settings.target_dir =" not in source
    tree = _tree(path)
    assert any(
        isinstance(node, ast.FunctionDef) and node.name == "build_lifecycle_service"
        for node in tree.body
    )


# END_BLOCK_LIFECYCLE_BOUNDARY
