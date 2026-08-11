# ############################################################################
# AI_HEADER: plan_validation — coherent PlanCompiler validation owners
# ROLE: Package marker for command, scope, evidence, dependency, and source-split
#       validators used by the bounded compiler facade.
# ############################################################################

# START_MODULE_CONTRACT
# purpose: Group PlanCompiler validation domains under one internal package.
# inputs: Imported validator modules.
# returns: No runtime API; consumers import the explicit domain owners.
# side_effects: Imports no validators eagerly.
# emitted_logs: None.
# error_behavior: Import errors surface from the selected validator module.
# END_MODULE_CONTRACT

# START_MODULE_MAP
# mapping:
#   - package: command
#   - package: scope
#   - package: evidence
#   - package: dependencies
#   - package: source_split
# END_MODULE_MAP

from grace_control.core.structured_logger import GraceLogger

_log = GraceLogger("plan_validation")


# START_BLOCK_PACKAGE
__all__: list[str] = []
# END_BLOCK_PACKAGE
