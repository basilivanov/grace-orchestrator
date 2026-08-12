# ############################################################################
# AI_HEADER: test_admin_aggregation_dependency_graph — admin read graph guard
# ROLE: Locks the explicit, acyclic Admin Aggregation construction graph and
#       rejects deferred private collaborator wiring or resolver backreferences.
# ############################################################################

# START_MODULE_CONTRACT
# purpose: Prove that the focused admin read services receive dependencies at
#          construction time and that the aggregation root has no child wiring.
# inputs: Active admin read service source files and their ASTs.
# returns: Pytest assertions; no production values are returned.
# side_effects: Reads production source and parses Python ASTs.
# emitted_logs: None.
# error_behavior: Raises AssertionError when a forbidden dependency pattern is
#                 introduced into the touched admin read graph.
# END_MODULE_CONTRACT

# START_MODULE_MAP
# mapping:
#   - function: test_aggregation_root_has_no_post_construction_child_wiring
#   - function: test_touched_dependency_fields_are_assigned_only_in_init
#   - function: test_run_readers_use_packet_run_resolver
#   - function: test_packet_run_resolver_has_no_high_level_dependencies
# END_MODULE_MAP

from __future__ import annotations

import ast
from pathlib import Path

from grace_control.core.structured_logger import GraceLogger

_log = GraceLogger("admin_aggregation_dependency_graph")
_ROOT = Path(__file__).resolve().parents[3]
_SERVICE_ROOT = _ROOT / "src" / "grace_control" / "services"

_GRAPH_FILES = (
    "admin_aggregation_service.py",
    "admin_packet_read_service.py",
    "admin_artifact_read_service.py",
    "admin_logs_read_service.py",
    "admin_pipeline_read_service.py",
    "admin_packet_run_resolver.py",
)
_DEPENDENCY_FIELDS = {
    "AdminAggregationService": {
        "_overview", "_resolver", "_artifacts", "_logs", "_pipeline",
        "_packet", "_features",
    },
    "AdminPacketReadService": {"_size_calc", "_pipeline_service", "_session_reader"},
    "AdminArtifactReadService": {"_run_resolver"},
    "AdminLogsReadService": {"_run_resolver"},
    "AdminPipelineReadService": {"_evidence_reader"},
    "AdminFeatureReadService": {"_size_calc", "_pipeline_service"},
}
_CLASS_FILES = {
    "AdminAggregationService": "admin_aggregation_service.py",
    "AdminPacketReadService": "admin_packet_read_service.py",
    "AdminArtifactReadService": "admin_artifact_read_service.py",
    "AdminLogsReadService": "admin_logs_read_service.py",
    "AdminPipelineReadService": "admin_pipeline_read_service.py",
    "AdminFeatureReadService": "admin_feature_read_service.py",
}


def _module(filename: str) -> ast.Module:
    return ast.parse((_SERVICE_ROOT / filename).read_text(encoding="utf-8"))


def _class(module: ast.Module, name: str) -> ast.ClassDef:
    return next(
        node for node in module.body
        if isinstance(node, ast.ClassDef) and node.name == name
    )


def _method(class_node: ast.ClassDef, name: str) -> ast.FunctionDef:
    return next(
        node for node in class_node.body
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name == name
    )


def _assignment_target(node: ast.stmt) -> ast.expr | None:
    if isinstance(node, ast.Assign):
        return node.targets[0] if len(node.targets) == 1 else None
    if isinstance(node, (ast.AnnAssign, ast.AugAssign)):
        return node.target
    return None


# START_BLOCK_ARCHITECTURE_GUARD
# START_FUNCTION_CONTRACT
# name: test_aggregation_root_has_no_post_construction_child_wiring
# purpose: Reject chained private collaborator writes from the aggregation
#          root and setter-style dependency injection on focused services.
# inputs: None; parses the active admin read graph.
# returns: None after all root and setter assertions pass.
# side_effects: Reads Python source and ASTs.
# emitted_logs: None.
# error_behavior: AssertionError on deferred child wiring or setter methods.
# END_FUNCTION_CONTRACT
def test_aggregation_root_has_no_post_construction_child_wiring() -> None:
    root = _class(_module("admin_aggregation_service.py"), "AdminAggregationService")
    for node in ast.walk(root):
        target = _assignment_target(node) if isinstance(node, ast.stmt) else None
        if not isinstance(target, ast.Attribute):
            continue
        if isinstance(target.value, ast.Attribute) and target.value.attr.startswith("_"):
            raise AssertionError("aggregation root writes a child's private collaborator")

    for filename, class_name in (
        ("admin_packet_read_service.py", "AdminPacketReadService"),
        ("admin_artifact_read_service.py", "AdminArtifactReadService"),
        ("admin_logs_read_service.py", "AdminLogsReadService"),
        ("admin_pipeline_read_service.py", "AdminPipelineReadService"),
        ("admin_feature_read_service.py", "AdminFeatureReadService"),
    ):
        class_node = _class(_module(filename), class_name)
        for node in class_node.body:
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name.startswith("set_"):
                raise AssertionError(f"setter-style collaborator injection: {class_name}.{node.name}")


# START_FUNCTION_CONTRACT
# name: test_touched_dependency_fields_are_assigned_only_in_init
# purpose: Ensure every dependency field in the touched graph is assigned only
#          by its owning class constructor.
# inputs: None; parses the active admin read graph.
# returns: None after assignment-location assertions pass.
# side_effects: Reads Python source and ASTs.
# emitted_logs: None.
# error_behavior: AssertionError when a dependency field is assigned elsewhere.
# END_FUNCTION_CONTRACT
def test_touched_dependency_fields_are_assigned_only_in_init() -> None:
    for class_name, fields in _DEPENDENCY_FIELDS.items():
        filename = _CLASS_FILES[class_name]
        class_node = _class(_module(filename), class_name)
        init = _method(class_node, "__init__")
        for node in ast.walk(class_node):
            if not isinstance(node, ast.stmt):
                continue
            target = _assignment_target(node)
            if not isinstance(target, ast.Attribute) or target.attr not in fields:
                continue
            assert any(candidate is node for candidate in ast.walk(init)), (
                class_name,
                target.attr,
            )


# START_FUNCTION_CONTRACT
# name: test_run_readers_use_packet_run_resolver
# purpose: Prove artifact and log readers use the lower-level resolver and that
#          the pipeline uses an explicit evidence collaborator.
# inputs: None; parses focused service source.
# returns: None after dependency assertions pass.
# side_effects: Reads Python source and ASTs.
# emitted_logs: None.
# error_behavior: AssertionError when a high-level packet dependency returns.
# END_FUNCTION_CONTRACT
def test_run_readers_use_packet_run_resolver() -> None:
    artifact_module = _module("admin_artifact_read_service.py")
    logs_module = _module("admin_logs_read_service.py")
    pipeline_module = _module("admin_pipeline_read_service.py")
    for module in (artifact_module, logs_module, pipeline_module):
        imported_modules = {
            node.module
            for node in module.body
            if isinstance(node, ast.ImportFrom) and node.module
        }
        assert "grace_control.services.admin_packet_read_service" not in imported_modules

    def _has_call(module: ast.Module, owner: str, method: str) -> bool:
        return any(
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Attribute)
            and node.func.attr == method
            and isinstance(node.func.value, ast.Attribute)
            and node.func.value.attr == owner
            for node in ast.walk(module)
        )

    assert _has_call(artifact_module, "_run_resolver", "resolve_run")
    assert _has_call(logs_module, "_run_resolver", "resolve_run")
    assert _has_call(pipeline_module, "_evidence_reader", "get_packet_evidence")
    artifact_source = (_SERVICE_ROOT / "admin_artifact_read_service.py").read_text()
    logs_source = (_SERVICE_ROOT / "admin_logs_read_service.py").read_text()
    assert "PacketRunResolver" in artifact_source
    assert "PacketRunResolver" in logs_source
    assert "ArtifactEvidenceReader" in (_SERVICE_ROOT / "admin_pipeline_read_service.py").read_text()


# START_FUNCTION_CONTRACT
# name: test_packet_run_resolver_has_no_high_level_dependencies
# purpose: Keep PacketRunResolver independent from admin facades, focused
#          services, FastAPI and filesystem code.
# inputs: None; parses the resolver module imports.
# returns: None after forbidden-import assertions pass.
# side_effects: Reads and parses Python source.
# emitted_logs: None.
# error_behavior: AssertionError when a forbidden dependency is imported.
# END_FUNCTION_CONTRACT
def test_packet_run_resolver_has_no_high_level_dependencies() -> None:
    module = _module("admin_packet_run_resolver.py")
    imported_modules = {
        node.module
        for node in module.body
        if isinstance(node, ast.ImportFrom) and node.module
    }
    imported_names = {
        alias.name.rsplit(".", 1)[-1]
        for node in module.body
        if isinstance(node, (ast.Import, ast.ImportFrom))
        for alias in node.names
    }
    assert not any(
        name.startswith("grace_control.services.admin_")
        for name in imported_modules
    )
    assert not imported_names.intersection({"FastAPI", "Path", "SafeFilesystemService"})


# END_BLOCK_ARCHITECTURE_GUARD
