# ############################################################################
# AI_HEADER: admin_mutation_result — canonical mutation outcome normalization
# ROLE: Converts selected-project mutation responses and transport ambiguity into
#       the stable audit-safe DTO consumed by Admin Hub APIs and the UI.
# ############################################################################

# START_MODULE_CONTRACT
# purpose: Normalize mutation success, failure, wait, unavailable, identity and
#          unknown-after-timeout outcomes without changing retry safety.
# inputs: Raw ProjectApiResult/fake response and immutable base result mapping.
# returns: Masked canonical mutation DTO.
# side_effects: None.
# emitted_logs: admin_mutation_failed for ambiguous outcomes.
# error_behavior: Unsupported responses fail closed; ambiguous no-response is
#                 unknown_after_timeout with retry disabled.
# END_MODULE_CONTRACT

# START_MODULE_MAP
# mapping:
#   - function: normalize_mutation_result
#   - function: _unknown_result
#   - function: _is_ambiguous
# END_MODULE_MAP

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from grace_control.core.structured_logger import GraceLogger
from grace_control.services.admin_control_security import mask_operator_data
from grace_control.services.admin_mutation_validation import _int_or_none
from grace_control.services.project_client import ProjectApiResult

_log = GraceLogger("admin_mutation_result")

UNKNOWN_OUTCOME_MESSAGE = "UNKNOWN OUTCOME — verify project state before retrying"


# START_BLOCK_NORMALIZATION
# START_FUNCTION_CONTRACT
# name: normalize_mutation_result
# purpose: Convert ProjectApiResult or compatible test/fake responses to the
#          canonical success/failure/unknown outcome DTO.
# inputs: raw — remote result; base — request identity DTO.
# returns: Masked mutation result with status, response and retry safety.
# side_effects: None.
# emitted_logs: None.
# error_behavior: Timeout/connection/no-response errors become unknown outcome.
# END_FUNCTION_CONTRACT
def normalize_mutation_result(raw: Any, base: Mapping[str, Any]) -> dict[str, Any]:
    if isinstance(raw, ProjectApiResult):
        ok = bool(raw.ok)
        status = raw.http_status
        payload = raw.payload or {}
        error = raw.error or raw.error_class
        error_class = raw.error_class or ""
    elif isinstance(raw, Mapping):
        ok = bool(raw.get("ok", True))
        status = _int_or_none(raw.get("http_status", raw.get("status_code", raw.get("status"))))
        payload = raw.get("payload", raw.get("response", raw))
        error = raw.get("error") or raw.get("message")
        error_class = str(raw.get("error_class") or raw.get("code") or "")
    else:
        ok = False
        status = None
        payload = {}
        error = "project mutation returned an unsupported response"
        error_class = "malformed_response"
    if not isinstance(payload, Mapping):
        payload = {"value": payload}
    payload = dict(payload)
    if isinstance(error, Mapping):
        error = error.get("message") or error.get("detail") or str(error)
    identity_code = str(payload.get("error_code") or error_class).upper()
    if identity_code == "IDENTITY_MISMATCH":
        identity_code = "PROJECT_IDENTITY_MISMATCH"
    elif identity_code == "IDENTITY_UNAVAILABLE":
        identity_code = "PROJECT_IDENTITY_UNAVAILABLE"
    if identity_code in {"PROJECT_IDENTITY_MISMATCH", "PROJECT_IDENTITY_UNAVAILABLE"}:
        status = status or (409 if identity_code.endswith("MISMATCH") else 503)
        return {
            **dict(base),
            "ok": False,
            "result": "failed",
            "status": status,
            "error_code": identity_code,
            "error": "selected runtime identity could not be verified",
            "reason": "selected project runtime identity verification failed",
            "response": mask_operator_data(payload),
            "retry_allowed": False,
            "attention": True,
        }
    ambiguous = not ok and status is None and _is_ambiguous(error_class, error)
    if ambiguous:
        return {
            **dict(base),
            "ok": False,
            "result": "unknown_after_timeout",
            "unknown_outcome": True,
            "status": 504,
            "display_message": UNKNOWN_OUTCOME_MESSAGE,
            "error": UNKNOWN_OUTCOME_MESSAGE,
            "error_class": error_class or "ambiguous_disconnect",
            "response": mask_operator_data(payload),
            "retry_allowed": False,
            "attention": True,
        }
    planned_text = f"{error_class} {error or ''} {payload.get('detail', '')}".casefold()
    if status == 501 or "not implemented" in planned_text or "planned" in planned_text:
        return {
            **dict(base),
            "ok": False,
            "result": "failed",
            "unknown_outcome": False,
            "status": 501,
            "available": False,
            "error_code": "CONTROL_UNAVAILABLE",
            "error": "Not implemented / unavailable for this runtime",
            "reason": "Not implemented / unavailable for this runtime",
            "response": mask_operator_data(payload),
            "retry_allowed": False,
            "attention": True,
        }
    remote_ok = ok and not ("ok" in payload and payload.get("ok") is False)
    wait_state = bool(payload.get("wait")) or str(
        payload.get("state") or payload.get("status") or payload.get("result") or ""
    ).casefold() in {"waiting", "wait"}
    wait_reason = str(payload.get("wait_reason") or payload.get("reason") or "").strip()
    if wait_state:
        remote_ok = False
    result_name = "success" if remote_ok else "failed"
    return {
        **dict(base),
        "ok": remote_ok,
        "result": result_name,
        "unknown_outcome": False,
        "status": status or (200 if remote_ok else 502),
        "response": mask_operator_data(payload),
        "display_message": f"WAIT — {wait_reason}" if wait_state and wait_reason else None,
        "error": None if remote_ok else mask_operator_data(
            wait_reason or error or "project mutation failed"
        ),
        "error_class": error_class or ("merge_slot_wait" if wait_state else None),
        "retry_allowed": False if wait_state else remote_ok,
        "attention": bool(wait_state or not remote_ok),
        "wait": wait_state,
    }


# END_BLOCK_NORMALIZATION


# START_BLOCK_HELPERS
# START_FUNCTION_CONTRACT
# name: _unknown_result
# purpose: Convert timeout/connection ambiguity into the exact operator state.
# inputs: base result and exception.
# returns: Unknown-outcome mutation DTO with blind retry disabled.
# side_effects: None.
# emitted_logs: admin_mutation_failed.
# error_behavior: Never raises.
# END_FUNCTION_CONTRACT
def _unknown_result(base: Mapping[str, Any], error: Exception) -> dict[str, Any]:
    _log.warn("admin_mutation_failed", project_key=str(base.get("project_key")),
              action=str(base.get("action")), reason="unknown_after_timeout")
    return {
        **dict(base),
        "ok": False,
        "result": "unknown_after_timeout",
        "unknown_outcome": True,
        "status": 504,
        "display_message": UNKNOWN_OUTCOME_MESSAGE,
        "error": UNKNOWN_OUTCOME_MESSAGE,
        "error_class": error.__class__.__name__,
        "error_detail": mask_operator_data(str(error)[:240]),
        "retry_allowed": False,
        "attention": True,
    }


# START_FUNCTION_CONTRACT
# name: _is_ambiguous
# purpose: Classify no-response timeout/disconnect errors.
# inputs: error class and message.
# returns: True for transport ambiguity.
# side_effects: None.
# error_behavior: Never raises.
# END_FUNCTION_CONTRACT
def _is_ambiguous(error_class: str, error: Any) -> bool:
    text = f"{error_class} {error or ''}".casefold()
    return any(marker in text for marker in ("timeout", "disconnect", "offline", "network", "connect"))


# END_BLOCK_HELPERS
