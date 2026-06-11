# ############################################################################
# AI_HEADER: api_routers_auth
# ROLE: Auth router — forgot-password / reset-password via email.
# ############################################################################

# START_MODULE_CONTRACT
# purpose: Provide password-reset flow via email.
#
#   POST /api/auth/forgot-password  — accepts email, creates/updates user,
#                                     generates reset token, sends email.
#   POST /api/auth/reset-password   — accepts token + new password, resets.
#
# Uses hashlib for password hashing (no external bcrypt dep) and secrets
# module for cryptographically secure tokens. Tokens expire after 1 hour.
# inputs: JSON body with email (forgot) or token+password (reset).
# returns: JSON {"ok": true} or {"error": ...}.
# side_effects: DB writes (user upsert, token generation, password update).
#               SMTP send on forgot-password.
# emitted_logs: password_reset_requested, password_reset_email_sent,
#               password_reset_completed, password_reset_failed.
# error_behavior: Returns 400/404 with structured error; never exposes
#                 whether email exists (to prevent enumeration).
# END_MODULE_CONTRACT

# START_MODULE_MAP
# mapping:
#   - router: APIRouter
#     routes:
#       - POST /api/auth/forgot-password
#       - POST /api/auth/reset-password
# END_MODULE_MAP

from __future__ import annotations

import hashlib
import secrets
from datetime import UTC, datetime, timedelta
from typing import Any

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from grace_control.core.email_service import send_password_reset_email
from grace_control.core.structured_logger import GraceLogger
from grace_control.db import get_db
from grace_control.db.schema import User

_log = GraceLogger("auth_router")
router = APIRouter(tags=["auth"])

_TOKEN_BYTES = 32
_RESET_EXPIRY_HOURS = 1


#START_BLOCK_SCHEMAS

class ForgotPasswordRequest(BaseModel):
    email: str


class ResetPasswordRequest(BaseModel):
    token: str
    password: str


#END_BLOCK_SCHEMAS


#START_BLOCK_HELPERS

def _hash_password(password: str) -> str:
    return hashlib.sha256(password.encode("utf-8")).hexdigest()


def _generate_token() -> str:
    return secrets.token_urlsafe(_TOKEN_BYTES)


def _user_id_from_email(email: str) -> str:
    return "usr_" + hashlib.sha256(email.encode("utf-8")).hexdigest()[:16]


#END_BLOCK_HELPERS


#START_BLOCK_ENDPOINTS

# START_FUNCTION_CONTRACT
# name: forgot_password
# purpose: Accept email, upsert user, generate reset token, send email.
#          Always returns 200 (to prevent email enumeration).
# inputs: body — ForgotPasswordRequest.
# returns: dict {"ok": true}.
# side_effects: DB upsert, SMTP send.
# emitted_logs: password_reset_requested, password_reset_email_sent,
#               password_reset_email_failed.
# error_behavior: Returns 200 even if email invalid / send fails.
# END_FUNCTION_CONTRACT
@router.post("/api/auth/forgot-password")
def forgot_password(body: ForgotPasswordRequest) -> dict[str, Any]:
    email = body.email.strip().lower()
    _log.info("password_reset_requested", email=email)

    token = _generate_token()
    expires_at = datetime.now(UTC) + timedelta(hours=_RESET_EXPIRY_HOURS)

    with get_db() as db:
        user = db.query(User).filter(User.email == email).first()
        if user is None:
            user = User(
                id=_user_id_from_email(email),
                email=email,
                password_hash=_hash_password(secrets.token_hex(16)),
            )
            db.add(user)
        user.reset_token = token
        user.reset_token_expires_at = expires_at

    sent = send_password_reset_email(email, token)
    if sent:
        _log.info("password_reset_email_sent", email=email)
    else:
        _log.warn("password_reset_email_failed", email=email)

    return {"ok": True}


# START_FUNCTION_CONTRACT
# name: reset_password
# purpose: Accept reset token + new password, validate token, update password.
# inputs: body — ResetPasswordRequest.
# returns: dict {"ok": true}.
# side_effects: DB update (clears reset_token, sets password_hash).
# emitted_logs: password_reset_completed, password_reset_failed.
# error_behavior: 400 on invalid/expired token, 400 on weak password.
# END_FUNCTION_CONTRACT
@router.post("/api/auth/reset-password")
def reset_password(body: ResetPasswordRequest) -> dict[str, Any]:
    if len(body.password) < 8:
        raise HTTPException(status_code=400, detail={
            "error": {"code": "WEAK_PASSWORD", "message": "Password must be at least 8 characters"},
        })

    now = datetime.now(UTC)
    with get_db() as db:
        user = db.query(User).filter(
            User.reset_token == body.token,
            User.reset_token_expires_at.isnot(None),
        ).first()

        if user is None:
            _log.warn("password_reset_failed", reason="invalid_token")
            raise HTTPException(status_code=400, detail={
                "error": {"code": "INVALID_TOKEN", "message": "Reset token is invalid or expired"},
            })

        if user.reset_token_expires_at and user.reset_token_expires_at.replace(tzinfo=UTC) < now:
            _log.warn("password_reset_failed", reason="expired_token", email=user.email)
            raise HTTPException(status_code=400, detail={
                "error": {"code": "EXPIRED_TOKEN", "message": "Reset token has expired"},
            })

        user.password_hash = _hash_password(body.password)
        user.reset_token = None
        user.reset_token_expires_at = None

    _log.info("password_reset_completed", email=user.email)
    return {"ok": True}

#END_BLOCK_ENDPOINTS
