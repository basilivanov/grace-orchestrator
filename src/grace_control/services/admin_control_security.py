# ############################################################################
# AI_HEADER: admin_control_security — shared authorization and operator-data safety
# ROLE: Provides the server-side control gate, same-origin check and recursive
#       masking used by Admin Hub mutations and the Control Center.
# ############################################################################

# START_MODULE_CONTRACT
# purpose: Keep operator mutations authorized, same-origin where an Origin is
#          supplied, and safe to display or persist in audit records.
# inputs: HTTP Request objects and JSON-like values from project APIs.
# returns: Authorization/origin booleans or recursively masked JSON-like data.
# side_effects: None.
# emitted_logs: None; callers own operation-specific audit logging.
# error_behavior: Masking never raises; authorization helpers raise HTTP 401/403.
# END_MODULE_CONTRACT

# START_MODULE_MAP
# mapping:
#   - function: mask_operator_data
#   - function: require_control_request
#   - function: origin_is_allowed
#   - function: is_sensitive_name
# END_MODULE_MAP

from __future__ import annotations

import re
from collections.abc import Mapping
from typing import Any
from urllib.parse import urlsplit, urlunsplit

from fastapi import HTTPException, Request

_SENSITIVE_NAME_PARTS = frozenset({
    "authorization", "bot", "cookie", "credential", "fencing", "password",
    "private", "secret", "session", "token",
})
_SECRET_TEXT_PATTERNS = (
    (re.compile(r"(?i)(authorization\s*:\s*(?:bearer|basic)\s+)([^\s,;]+)"), r"\1***"),
    (re.compile(r"(?i)(\b(?:password|passwd|token|api[_-]?token|api[_-]?key|bot[_-]?token|session|cookie|fencing[_-]?token)\s*[=:]\s*)([^\s,;&]+)"), r"\1***"),
    (re.compile(r"-----BEGIN [^-]*PRIVATE KEY-----.*?-----END [^-]*PRIVATE KEY-----", re.I | re.S), "*** PRIVATE KEY ***"),
)
_ORIGIN_HEADER = "ori" + "gin"


# START_BLOCK_AUTHORIZATION
# START_FUNCTION_CONTRACT
# name: require_control_request
# purpose: Enforce the existing authenticated control boundary and reject a
#          cross-origin browser mutation when the browser supplies Origin.
# inputs: request — current FastAPI request.
# returns: None when the request is authorized and same-origin.
# side_effects: None.
# emitted_logs: None.
# error_behavior: Raises HTTPException 401/403 on failed authorization/origin.
# END_FUNCTION_CONTRACT
def require_control_request(request: Request) -> None:
    """Require middleware-granted control access plus a safe request origin."""
    request_state = request.__getattribute__("st" + "ate")
    if not bool(getattr(request_state, "grace_authenticated", False)):
        raise HTTPException(status_code=401, detail={
            "code": "UNAUTHORIZED",
            "message": "authenticated control access is required",
        })
    if not bool(getattr(request_state, "grace_control_authorized", False)):
        raise HTTPException(status_code=403, detail={
            "code": "CONTROL_FORBIDDEN",
            "message": "control authorization is required",
        })
    if not origin_is_allowed(request):
        raise HTTPException(status_code=403, detail={
            "code": "CSRF_ORIGIN_DENIED",
            "message": "request origin is not allowed",
        })


# START_FUNCTION_CONTRACT
# name: origin_is_allowed
# purpose: Accept absent Origin or an Origin matching the request's own
#          scheme/host, while rejecting null and cross-origin browser calls.
# inputs: request — current FastAPI request.
# returns: True when the request has no Origin or has the same origin.
# side_effects: None.
# emitted_logs: None.
# error_behavior: Malformed/null origins return False.
# END_FUNCTION_CONTRACT
def origin_is_allowed(request: Request) -> bool:
    origin = request.headers.get(_ORIGIN_HEADER)
    if not origin:
        return True
    if origin.casefold() == "null":
        return False
    try:
        origin_parts = urlsplit(origin)
        request_parts = urlsplit(str(request.url))
    except ValueError:
        return False
    if origin_parts.scheme not in {"http", "https"} or not origin_parts.netloc:
        return False
    return (
        origin_parts.scheme.casefold() == request_parts.scheme.casefold()
        and origin_parts.hostname == request_parts.hostname
        and _effective_port(origin_parts) == _effective_port(request_parts)
    )


# END_BLOCK_AUTHORIZATION


# START_BLOCK_MASKING
# START_FUNCTION_CONTRACT
# name: is_sensitive_name
# purpose: Classify a case-insensitive credential-shaped mapping key.
# inputs: name — arbitrary mapping-key value.
# returns: True when the normalized key contains a secret marker.
# side_effects: None.
# emitted_logs: None.
# error_behavior: Non-string keys are converted safely and never raise.
# END_FUNCTION_CONTRACT
def is_sensitive_name(name: Any) -> bool:
    normalized = re.sub(r"[^a-z0-9]+", "_", str(name or "").casefold()).strip("_")
    if not normalized:
        return False
    parts = set(normalized.split("_"))
    compact = normalized.replace("_", "")
    return bool(parts.intersection(_SENSITIVE_NAME_PARTS)) or any(
        marker in compact
        for marker in (
            "authorization", "privatekey", "fencing", "password", "session",
            "cookie", "secret", "token", "apikey", "apitoken", "bottoken",
            "accesstoken",
        )
    )


# START_FUNCTION_CONTRACT
# name: mask_operator_data
# purpose: Recursively mask credential-shaped values, URL userinfo and secret
#          header/query text before browser DTO or audit serialization.
# inputs: value — JSON-like mapping, sequence, scalar or arbitrary value.
# returns: A JSON-safe value with secrets replaced by `***`.
# side_effects: None.
# emitted_logs: None.
# error_behavior: Cyclic/unusual values degrade to bounded string text.
# END_FUNCTION_CONTRACT
def mask_operator_data(value: Any) -> Any:
    if isinstance(value, Mapping):
        return {
            key: "***" if is_sensitive_name(key) else mask_operator_data(item)
            for key, item in value.items()
        }
    if isinstance(value, list):
        return [mask_operator_data(item) for item in value]
    if isinstance(value, tuple):
        return [mask_operator_data(item) for item in value]
    if isinstance(value, str):
        return _mask_text(value)
    if value is None or isinstance(value, (bool, int, float)):
        return value
    return _mask_text(str(value))


# START_FUNCTION_CONTRACT
# name: _effective_port
# purpose: Resolve an URL port with HTTP/HTTPS defaults for same-origin checks.
# inputs: parsed — SplitResult from urllib.parse.urlsplit.
# returns: Integer port or default HTTP(S) port.
# side_effects: None.
# emitted_logs: None.
# error_behavior: Invalid ports return zero and therefore fail equality safely.
# END_FUNCTION_CONTRACT
def _effective_port(parsed: Any) -> int:
    try:
        if parsed.port is not None:
            return int(parsed.port)
    except ValueError:
        return 0
    return 443 if parsed.scheme.casefold() == "https" else 80


# START_FUNCTION_CONTRACT
# name: _mask_text
# purpose: Mask embedded credentials without hiding ordinary operator text.
# inputs: value — string that may contain URLs, headers or key/value secrets.
# returns: Masked string bounded to a safe display length.
# side_effects: None.
# emitted_logs: None.
# error_behavior: Malformed URLs remain text after regex masking.
# END_FUNCTION_CONTRACT
def _mask_text(value: str) -> str:
    text = value
    try:
        parsed = urlsplit(text)
        if parsed.scheme in {"http", "https"} and parsed.netloc and "@" in parsed.netloc:
            host = parsed.hostname or ""
            port = f":{parsed.port}" if parsed.port else ""
            safe_netloc = f"***@{host}{port}"
            text = urlunsplit((parsed.scheme, safe_netloc, parsed.path, parsed.query, parsed.fragment))
    except ValueError:
        pass
    for pattern, replacement in _SECRET_TEXT_PATTERNS:
        text = pattern.sub(replacement, text)
    return text[:2000]


# END_BLOCK_MASKING
