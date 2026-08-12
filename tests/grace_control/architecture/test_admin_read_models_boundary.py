# ############################################################################
# AI_HEADER: test_admin_read_models_boundary — architecture guards for Admin models
# ROLE: Protects the bounded Admin read-model module from infrastructure
#       coupling and prevents accidental contract unification across surfaces.
# ############################################################################

# START_MODULE_CONTRACT
# purpose: Enforce the typed Admin read-model boundary and its exact call sites.
# inputs: Repository source modules loaded as text or imported modules.
# returns: Pytest assertions for architecture invariants.
# side_effects: Reads source files and imports the bounded model module.
# emitted_logs: None.
# error_behavior: Fails when forbidden coupling or raw model leakage appears.
# END_MODULE_CONTRACT

# START_MODULE_MAP
# mapping:
#   - function: test_models_are_frozen_and_slotted
#   - function: test_model_module_has_no_infrastructure_imports
#   - function: test_selected_services_serialize_models_at_boundary
#   - function: test_distinct_coverage_and_worker_contracts_remain_distinct
# END_MODULE_MAP

from __future__ import annotations

import ast
from dataclasses import fields, is_dataclass
from pathlib import Path

from grace_control.services import admin_read_models

_ROOT = Path(__file__).parents[3]
_MODEL_PATH = _ROOT / "src/grace_control/services/admin_read_models.py"
_HELPERS_PATH = _ROOT / "src/grace_control/services/admin_cross_project_helpers.py"
_OVERVIEW_PATH = _ROOT / "src/grace_control/services/admin_cross_project_overview_service.py"
_ADMIN_OVERVIEW_PATH = _ROOT / "src/grace_control/services/admin_overview_read_service.py"
_LIFECYCLE_WORKER_PATH = _ROOT / "src/grace_control/services/worker_read_service.py"

_MODEL_NAMES = (
    "CrossProjectCoverage", "AttentionItem", "ProjectHealthSnapshot",
    "WorkerSnapshot", "PacketRunSummary", "PipelineStageView",
)


def _tree(path: Path) -> ast.Module:
    return ast.parse(path.read_text())


def _function(tree: ast.AST, name: str) -> ast.FunctionDef:
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name == name:
            return node
    raise AssertionError(f"function {name!r} not found")


def _calls(tree: ast.AST, name: str) -> list[ast.Call]:
    return [
        node for node in ast.walk(tree)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Name)
        and node.func.id == name
    ]


# START_FUNCTION_CONTRACT
# name: test_models_are_frozen_and_slotted
# purpose: Ensure every bounded Admin model is immutable and slotted.
# inputs: None; inspects the imported model classes.
# returns: None.
# side_effects: None.
# emitted_logs: None.
# error_behavior: Fails if a model becomes mutable or gains an instance dict.
# END_FUNCTION_CONTRACT
def test_models_are_frozen_and_slotted():
    for name in _MODEL_NAMES:
        cls = getattr(admin_read_models, name)
        assert is_dataclass(cls)
        assert cls.__dataclass_params__.frozen is True
        assert cls.__slots__
        assert fields(cls)


# START_FUNCTION_CONTRACT
# name: test_model_module_has_no_infrastructure_imports
# purpose: Keep the typed model module free of infrastructure coupling.
# inputs: None; parses the model source.
# returns: None.
# side_effects: Reads one repository source file.
# emitted_logs: None.
# error_behavior: Fails when forbidden imports or duplicate loggers appear.
# END_FUNCTION_CONTRACT
def test_model_module_has_no_infrastructure_imports():
    tree = _tree(_MODEL_PATH)
    forbidden = (
        "fastapi", "sqlalchemy", "subprocess", "pathlib", "os", "project_registry",
        "admin_aggregation", "admin_cross_project", "admin_overview", "admin_packet",
        "admin_pipeline", "router", "registry", "locator", "pydantic",
    )
    imports: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imports.extend(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            imports.append(node.module or "")
    assert all(not any(marker in module.lower() for marker in forbidden) for module in imports)
    assert "GraceLogger" in {alias.name for node in ast.walk(tree) if isinstance(node, ast.ImportFrom) for alias in node.names}
    assert sum(
        1 for node in ast.walk(tree)
        if isinstance(node, ast.Assign)
        and any(isinstance(target, ast.Name) and target.id == "_log" for target in node.targets)
    ) == 1


# START_FUNCTION_CONTRACT
# name: test_selected_services_serialize_models_at_boundary
# purpose: Verify selected services construct and serialize the bounded models.
# inputs: None; parses helper and service source.
# returns: None.
# side_effects: Reads repository source files.
# emitted_logs: None.
# error_behavior: Fails when raw duplicate dictionaries replace model usage.
# END_FUNCTION_CONTRACT
def test_selected_services_serialize_models_at_boundary():
    helpers = _tree(_HELPERS_PATH)
    assert _calls(_function(helpers, "_attention_item"), "AttentionItem")
    assert _calls(_function(helpers, "_coverage"), "CrossProjectCoverage")
    assert any(
        isinstance(node, ast.Attribute) and node.attr == "to_dict"
        for node in ast.walk(_function(helpers, "_attention_item"))
    )
    assert any(
        isinstance(node, ast.Attribute) and node.attr == "to_dict"
        for node in ast.walk(_function(helpers, "_coverage"))
    )
    disabled = _function(_tree(_OVERVIEW_PATH), "_overview_for_disabled")
    ten_key_literal = {
        "severity", "project_key", "project_name", "kind", "entity_type",
        "entity_id", "title", "reason", "timestamp", "detail_url",
    }
    assert not any(
        isinstance(node, ast.Dict)
        and {key.value for key in node.keys if isinstance(key, ast.Constant)} >= ten_key_literal
        for node in ast.walk(disabled)
    )
    overview = _tree(_ADMIN_OVERVIEW_PATH)
    assert _calls(_function(overview, "get_system_health"), "ProjectHealthSnapshot")
    assert _calls(_function(overview, "_worker_to_dict"), "WorkerSnapshot")


# START_FUNCTION_CONTRACT
# name: test_distinct_coverage_and_worker_contracts_remain_distinct
# purpose: Prevent accidental widening and lifecycle/Admin worker unification.
# inputs: None; parses the selected source files.
# returns: None.
# side_effects: Reads repository source files.
# emitted_logs: None.
# error_behavior: Fails when distinct public contracts are collapsed.
# END_FUNCTION_CONTRACT
def test_distinct_coverage_and_worker_contracts_remain_distinct():
    helpers = _tree(_HELPERS_PATH)
    full = _function(helpers, "_coverage")
    small = _function(helpers, "_coverage_from_results")
    assert _calls(full, "CrossProjectCoverage")
    assert not _calls(small, "CrossProjectCoverage")
    admin_worker = _function(_tree(_ADMIN_OVERVIEW_PATH), "_worker_to_dict")
    worker_models = [
        node for node in ast.walk(admin_worker)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Name)
        and node.func.id == "WorkerSnapshot"
    ]
    assert len(worker_models) == 1
    worker_keys = {keyword.arg for keyword in worker_models[0].keywords if keyword.arg}
    lifecycle_source = _LIFECYCLE_WORKER_PATH.read_text()
    assert "worker_id" in lifecycle_source
    assert "id" in worker_keys
    assert "worker_id" not in worker_keys
