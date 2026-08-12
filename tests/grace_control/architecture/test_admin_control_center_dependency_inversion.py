# ############################################################################
# AI_HEADER: test_admin_control_center_dependency_inversion — Control Center graph guard
# ROLE: Locks the explicit Admin Control Center dependency graph and prevents
#       facade backreferences, private Hub reach-through and dynamic cache state.
# ############################################################################

# START_MODULE_CONTRACT
# purpose: Prove that focused Control Center services use explicit constructor
#          collaborators and that the composition root remains acyclic.
# inputs: Active Control Center source modules and their ASTs.
# returns: Pytest assertions; no production values are returned.
# side_effects: Reads source files and parses Python ASTs.
# emitted_logs: None.
# error_behavior: Raises AssertionError when a forbidden dependency pattern is found.
# END_MODULE_CONTRACT

# START_MODULE_MAP
# mapping:
#   - function: test_admin_control_center_has_no_facade_backreferences
#   - function: test_admin_control_center_constructors_are_explicit
#   - function: test_admin_control_center_has_no_post_construction_wiring
#   - function: test_admin_project_access_is_narrow
# END_MODULE_MAP

from __future__ import annotations

import ast
from pathlib import Path

from grace_control.core.structured_logger import GraceLogger

_log = GraceLogger("admin_control_center_dependency_inversion")

_ROOT = Path(__file__).resolve().parents[3]
_SERVICE_ROOT = _ROOT / "src" / "grace_control" / "services"
_CHILD_NAMES = (
    "admin_control_center_project_service.py",
    "admin_control_center_packet_service.py",
    "admin_control_center_explorer_service.py",
    "admin_control_center_page_service.py",
)
_CONTROL_FILES = (
    "admin_control_center.py",
    "admin_control_center_project_shell.py",
    *_CHILD_NAMES,
    "admin_project_access.py",
)


# START_BLOCK_ARCHITECTURE_GUARD
# START_FUNCTION_CONTRACT
# name: test_admin_control_center_has_no_facade_backreferences
# purpose: Reject facade storage, private Hub reach-through and dynamic cache
#          injection in the active Control Center graph.
# inputs: None; reads the active service modules.
# returns: None after all forbidden-reference assertions pass.
# side_effects: Reads source files and ASTs.
# emitted_logs: None.
# error_behavior: Raises AssertionError on any forbidden architecture pattern.
# END_FUNCTION_CONTRACT
def test_admin_control_center_has_no_facade_backreferences() -> None:
    source = "\n".join((_SERVICE_ROOT / name).read_text() for name in _CONTROL_FILES)
    forbidden = (
        "self._facade",
        "_facade._hub",
        "_hub._registry",
        "_hub._request",
        "_hub._client_factory",
        "_admin_openapi_cache",
    )
    assert not any(token in source for token in forbidden)
    child_source = "\n".join((_SERVICE_ROOT / name).read_text() for name in _CHILD_NAMES)
    assert "AdminControlCenterService" not in child_source


# START_FUNCTION_CONTRACT
# name: test_admin_control_center_constructors_are_explicit
# purpose: Verify the four focused child constructors accept no facade and the
#          composition root wires each collaborator during construction.
# inputs: None; parses focused service and composition-root ASTs.
# returns: None after constructor assertions pass.
# side_effects: Reads Python source.
# emitted_logs: None.
# error_behavior: Raises AssertionError when constructor wiring regresses.
# END_FUNCTION_CONTRACT
def test_admin_control_center_constructors_are_explicit() -> None:
    expected = {
        "AdminControlCenterProjectService": ("admin_control_center_project_service.py", {"access", "shell", "packet"}),
        "AdminControlCenterPacketService": ("admin_control_center_packet_service.py", {"access", "explorer", "mutation", "packet_tabs"}),
        "AdminControlCenterExplorerService": ("admin_control_center_explorer_service.py", {"access", "shell", "mutation"}),
        "AdminControlCenterPageService": ("admin_control_center_page_service.py", {"hub", "shell"}),
    }
    for class_name, (filename, names) in expected.items():
        path = _SERVICE_ROOT / filename
        module = ast.parse(path.read_text())
        class_node = next(node for node in module.body if isinstance(node, ast.ClassDef) and node.name == class_name)
        init = next(node for node in class_node.body if isinstance(node, ast.FunctionDef) and node.name == "__init__")
        parameters = {arg.arg for arg in (*init.args.posonlyargs, *init.args.args, *init.args.kwonlyargs)} - {"self"}
        assert parameters == names, (class_name, parameters)
        assert not any(isinstance(node, ast.Assign) and any(
            isinstance(target, ast.Attribute) and target.attr.startswith("_")
            and isinstance(target.value, ast.Name) and target.value.id == "facade"
            for target in node.targets
        ) for node in ast.walk(init))

    root = ast.parse((_SERVICE_ROOT / "admin_control_center.py").read_text())
    root_class = next(node for node in root.body if isinstance(node, ast.ClassDef) and node.name == "AdminControlCenterService")
    init = next(node for node in root_class.body if isinstance(node, ast.FunctionDef) and node.name == "__init__")
    calls = [node for node in ast.walk(init) if isinstance(node, ast.Call) and isinstance(node.func, ast.Name)]
    called = {node.func.id for node in calls}
    assert {
        "AdminProjectAccess",
        "AdminMutationService",
        "AdminControlCenterProjectShell",
        "AdminControlCenterExplorerService",
        "AdminControlCenterPacketService",
        "AdminControlCenterProjectService",
        "AdminControlCenterPageService",
    } <= called


# START_FUNCTION_CONTRACT
# name: test_admin_control_center_has_no_post_construction_wiring
# purpose: Reject collaborator assignment outside the owning constructor.
# inputs: None; parses focused service ASTs.
# returns: None after assignment-location assertions pass.
# side_effects: Reads Python source.
# emitted_logs: None.
# error_behavior: Raises AssertionError when dependency wiring is deferred.
# END_FUNCTION_CONTRACT
def test_admin_control_center_has_no_post_construction_wiring() -> None:
    collaborator_names = {
        "_access",
        "_shell",
        "_packet",
        "_explorer",
        "_mutation",
        "_hub",
        "_packet_tabs",
    }
    for filename in (*_CHILD_NAMES, "admin_control_center.py"):
        module = ast.parse((_SERVICE_ROOT / filename).read_text())
        for class_node in (node for node in module.body if isinstance(node, ast.ClassDef)):
            init = next(
                (node for node in class_node.body if isinstance(node, ast.FunctionDef) and node.name == "__init__"),
                None,
            )
            for node in ast.walk(class_node):
                if not isinstance(node, (ast.Assign, ast.AnnAssign, ast.AugAssign)):
                    continue
                targets = node.targets if isinstance(node, ast.Assign) else [node.target]
                for target in targets:
                    if not isinstance(target, ast.Attribute) or target.attr not in collaborator_names:
                        continue
                    assert init is not None and any(
                        candidate is node for candidate in ast.walk(init)
                    ), (filename, class_node.name, target.attr)


# START_FUNCTION_CONTRACT
# name: test_admin_project_access_is_narrow
# purpose: Ensure AdminProjectAccess references only transport/context types and
#          does not become a focused-service locator.
# inputs: None; parses the access module AST.
# returns: None after import/reference assertions pass.
# side_effects: Reads Python source.
# emitted_logs: None.
# error_behavior: Raises AssertionError on focused-service references.
# END_FUNCTION_CONTRACT
def test_admin_project_access_is_narrow() -> None:
    path = _SERVICE_ROOT / "admin_project_access.py"
    module = ast.parse(path.read_text())
    imported = {
        alias.name.rsplit(".", 1)[-1]
        for node in module.body
        if isinstance(node, (ast.Import, ast.ImportFrom))
        for alias in node.names
    }
    assert not imported.intersection({
        "AdminControlCenterProjectService",
        "AdminControlCenterPacketService",
        "AdminControlCenterExplorerService",
        "AdminControlCenterPageService",
    })
    assert "AdminControlCenter" not in path.read_text()


# END_BLOCK_ARCHITECTURE_GUARD
