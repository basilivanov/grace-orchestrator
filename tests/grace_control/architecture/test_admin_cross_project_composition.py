# ############################################################################
# AI_HEADER: test_admin_cross_project_composition — cross-project composition guard
# ROLE: Protects the explicit Admin Hub transport/projection architecture from
#       a regression to hidden mixin inheritance or duplicated transport logic.
# ############################################################################

# START_MODULE_CONTRACT
# purpose: Verify the Wave 2 cross-project service graph is explicit and that
#          transport responsibilities have one owner.
# inputs: Active cross-project production modules and imported service classes.
# returns: Passing architecture assertions for composition and ownership.
# side_effects: Reads source files and imports production classes only.
# emitted_logs: None directly; the test module uses no runtime logging.
# error_behavior: Raises assertion failures when hidden inheritance, stale
#                 mixin files or transport duplication returns.
# END_MODULE_CONTRACT

# START_MODULE_MAP
# mapping:
#   - function: test_cross_project_facade_uses_explicit_composition
#   - function: test_cross_project_projection_services_use_transport_only
#   - function: test_cross_project_transport_owns_transport_responsibilities
# END_MODULE_MAP

from __future__ import annotations

import ast
import inspect
from pathlib import Path

from grace_control.core.structured_logger import GraceLogger
from grace_control.services.admin_cross_project_overview_service import (
    AdminCrossProjectOverviewService,
)
from grace_control.services.admin_cross_project_query_service import (
    AdminCrossProjectQueryService,
)
from grace_control.services.admin_cross_project_service import AdminCrossProjectService
from grace_control.services.admin_cross_project_transport import CrossProjectTransport

_log = GraceLogger("test_admin_cross_project_composition")

_SERVICES_DIR = Path(__file__).resolve().parents[3] / "src" / "grace_control" / "services"
_FORBIDDEN_HIDDEN_MEMBERS = {"_registry", "_request", "_fanout", "_select_contexts"}


# START_BLOCK_GUARDS
# START_FUNCTION_CONTRACT
# name: test_cross_project_facade_uses_explicit_composition
# purpose: Ensure the stable facade no longer inherits cross-project mixins and
#          owns the required explicit collaborators.
# inputs: Imported service classes.
# returns: None after architecture assertions pass.
# side_effects: None.
# emitted_logs: None.
# error_behavior: AssertionError when facade inheritance or collaborators drift.
# END_FUNCTION_CONTRACT
def test_cross_project_facade_uses_explicit_composition() -> None:
    assert not any(base.__name__.endswith("Mixin") for base in AdminCrossProjectService.__bases__)
    assert AdminCrossProjectService.__init__.__annotations__["registry"] is not None
    facade_source = inspect.getsource(AdminCrossProjectService.__init__)
    assert "CrossProjectTransport" in facade_source
    assert "AdminCrossProjectOverviewService" in facade_source
    assert "AdminCrossProjectQueryService" in facade_source


# START_FUNCTION_CONTRACT
# name: test_cross_project_projection_services_use_transport_only
# purpose: Reject projection services that access hidden facade/transport
#          members instead of calling the explicit transport object.
# inputs: Active projection module source trees.
# returns: None after architecture assertions pass.
# side_effects: Reads source files.
# emitted_logs: None.
# error_behavior: AssertionError when hidden member access or mixin classes exist.
# END_FUNCTION_CONTRACT
def test_cross_project_projection_services_use_transport_only() -> None:
    for class_type in (AdminCrossProjectOverviewService, AdminCrossProjectQueryService):
        assert not class_type.__name__.endswith("Mixin")
        tree = ast.parse(inspect.getsource(class_type))
        for node in ast.walk(tree):
            if isinstance(node, ast.Attribute) and node.attr in _FORBIDDEN_HIDDEN_MEMBERS:
                raise AssertionError(f"{class_type.__name__} owns hidden member {node.attr}")
    for path in _SERVICES_DIR.glob("admin_cross_project_*.py"):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, ast.ClassDef) and node.name.endswith("Mixin"):
                raise AssertionError(f"legacy cross-project mixin remains: {path.name}:{node.name}")
    assert not (_SERVICES_DIR / "admin_cross_project_overview_mixin.py").exists()
    assert not (_SERVICES_DIR / "admin_cross_project_query_mixin.py").exists()


# START_FUNCTION_CONTRACT
# name: test_cross_project_transport_owns_transport_responsibilities
# purpose: Ensure CrossProjectTransport exposes selection, bounded fan-out and
#          request normalization as one explicit boundary.
# inputs: CrossProjectTransport class.
# returns: None after architecture assertions pass.
# side_effects: None.
# emitted_logs: None.
# error_behavior: AssertionError when a required transport method is absent.
# END_FUNCTION_CONTRACT
def test_cross_project_transport_owns_transport_responsibilities() -> None:
    required = {"list_contexts", "select_contexts", "fanout", "request"}
    assert required.issubset(vars(CrossProjectTransport))
    source = inspect.getsource(CrossProjectTransport)
    assert "ProjectRegistry" in source
    assert "asyncio.Semaphore" in source
    assert "_coerce_remote" in source


# END_BLOCK_GUARDS
