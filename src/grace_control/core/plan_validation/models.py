# ############################################################################
# AI_HEADER: plan_validation_models — compiler result models and diagnostics
# ROLE: Shared data owner for plan compiler validation results. Validators append
#       stable errors and warnings through these helpers without owning orchestration.
# ############################################################################

# START_MODULE_CONTRACT
# purpose: Define compiler result models and append structured diagnostics.
# inputs: Validation result, diagnostic code, field path, message, and optional context.
# returns: CompileError instances appended to CompileResult.
# side_effects: Mutates the supplied CompileResult only.
# emitted_logs: None.
# error_behavior: Pydantic validates model fields; diagnostic helpers do not raise.
# END_MODULE_CONTRACT

# START_MODULE_MAP
# mapping:
#   - class: CompileError
#   - class: CompileResult
#   - function: _add_error
#   - function: _add_warning
# END_MODULE_MAP

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel

from grace_control.core.structured_logger import GraceLogger

_log = GraceLogger("plan_validation.models")


# START_BLOCK_MODELS
class CompileError(BaseModel):
    code: str
    severity: Literal["error", "warning"]
    packet_title: str | None = None
    field_path: str
    message: str
    suggestion: str | None = None
    details: dict | None = None

    model_config = {"frozen": False}


class CompileResult(BaseModel):
    ok: bool
    errors: list[CompileError] = []
    warnings: list[CompileError] = []
    normalized_plan: dict | None = None

    model_config = {"frozen": False}
# END_BLOCK_MODELS


# START_BLOCK_DIAGNOSTICS
def _add_error(
    result: CompileResult,
    code: str,
    field_path: str,
    message: str,
    packet_title: str | None = None,
    suggestion: str | None = None,
    details: dict | None = None,
) -> None:
    result.errors.append(
        CompileError(
            code=code,
            severity="error",
            packet_title=packet_title,
            field_path=field_path,
            message=message,
            suggestion=suggestion,
            details=details,
        )
    )
    result.ok = False


def _add_warning(
    result: CompileResult,
    code: str,
    field_path: str,
    message: str,
    packet_title: str | None = None,
    suggestion: str | None = None,
) -> None:
    result.warnings.append(
        CompileError(
            code=code,
            severity="warning",
            packet_title=packet_title,
            field_path=field_path,
            message=message,
            suggestion=suggestion,
        )
    )
# END_BLOCK_DIAGNOSTICS
