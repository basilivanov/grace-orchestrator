# ############################################################################
# AI_HEADER: tests — make repository test helpers importable as a local package
# ROLE: Pytest imports this package before modules that reference tests.conftest.
#       It prevents unrelated site-packages named tests from shadowing helpers.
# ############################################################################

# START_MODULE_CONTRACT
# purpose: Mark the repository tests directory as an importable local package.
# inputs: Python package import machinery.
# returns: The local tests package namespace.
# side_effects: Initializes a module-level GraceLogger without emitting logs.
# emitted_logs: None.
# error_behavior: Propagates import errors from GraceLogger.
# END_MODULE_CONTRACT

# START_MODULE_MAP
# mapping: []
# END_MODULE_MAP

from __future__ import annotations

from grace_control.core.structured_logger import GraceLogger

_log = GraceLogger("tests_package")
