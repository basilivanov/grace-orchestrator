# ############################################################################
# AI_HEADER: mod
# ROLE: Feature processing module — entry point for executing feature tasks.
# ############################################################################

# START_MODULE_CONTRACT
# purpose: Provide feature processing — reads task descriptions, validates scope,
#          registers feature-type handlers, dispatches to appropriate handler,
#          and produces execution results with logging.
# inputs: task_description (str), target_scope (list[str]), metadata (dict | None).
# returns: dict with status, summary, processed_paths.
# side_effects: Logs processing events; registers feature handlers.
# emitted_logs: 'mod_process_start', 'mod_process_done', 'mod_handler_registered', 'mod_validation_failed'
# error_behavior: Returns error dict with reason on failure.
# END_MODULE_CONTRACT

# START_MODULE_MAP
# mapping:
#   - function: process
#   - function: register_handler
#   - function: validate_feature
#   - function: list_handlers
# END_MODULE_MAP

from __future__ import annotations

from collections.abc import Callable
from typing import Protocol

from grace_control.core.structured_logger import GraceLogger

_log = GraceLogger("mod")

_handler_registry: dict[str, Callable[..., dict]] = {}


class FeatureHandler(Protocol):
    """Protocol for feature-type handlers registered via register_handler."""

    def __call__(self, task_description: str,
                 target_scope: list[str] | None = None,
                 metadata: dict | None = None) -> dict: ...


def register_handler(feature_type: str, handler: FeatureHandler) -> None:
    """Register a handler for a specific feature type."""
    _handler_registry[feature_type] = handler
    _log.info("mod_handler_registered", feature_type=feature_type)


def list_handlers() -> list[str]:
    """Return list of registered feature type keys."""
    return list(_handler_registry)


def validate_feature(task_description: str,
                     target_scope: list[str] | None = None) -> list[str]:
    """Validate a feature task. Returns list of validation error messages."""
    errors: list[str] = []
    if not task_description or not task_description.strip():
        errors.append("task_description must be a non-empty string")
    scope = target_scope or []
    for path in scope:
        if not isinstance(path, str) or not path.strip():
            errors.append(f"Invalid scope path: {path!r}")
    if errors:
        _log.warn("mod_validation_failed", errors=errors)
    return errors


def process(task_description: str,
            target_scope: list[str] | None = None,
            metadata: dict | None = None) -> dict:
    _log.info("mod_process_start", task=task_description[:120],
              scope_count=len(target_scope or []))
    errors = validate_feature(task_description, target_scope)
    if errors:
        return {
            "status": "error",
            "summary": "Validation failed",
            "errors": errors,
        }
    scope = target_scope or ["src/grace_control/"]
    meta = metadata or {}
    feature_type = meta.get("feature_type", "")
    if feature_type and feature_type in _handler_registry:
        handler = _handler_registry[feature_type]
        return handler(task_description, scope, meta)
    result = {
        "status": "ok",
        "summary": f"Processed: {task_description[:200]}",
        "processed_paths": scope,
        "metadata": meta,
    }
    _log.info("mod_process_done", paths=len(scope))
    return result
