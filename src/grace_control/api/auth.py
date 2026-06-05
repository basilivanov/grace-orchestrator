# AI_HEADER: api_auth — opt-in Bearer token auth middleware (W14.2)
# START_MODULE_CONTRACT
# purpose: FastAPI middleware/dependency for Bearer token authentication.
#          Disabled by default; enabled via GRACE_API_AUTH_ENABLED=true.
#          Localhost requests bypass auth when allow_unauthenticated_localhost=true.
# inputs: HTTP Request.
# returns: None or raises HTTPException(401).
# side_effects: None.
# emitted_logs: auth_failure on invalid/missing token.
# error_behavior: Returns 401 with structured error, never exposes token.
# END_MODULE_CONTRACT
# START_MODULE_MAP
# mapping:   - class: AuthMiddleware   - class: verify_token   - function: get_optional_token
# END_MODULE_MODULE

from __future__ import annotations

import os
from typing import Callable

from fastapi import HTTPException, Request
from fastapi.responses import JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.types import ASGIApp

from grace_control.core.structured_logger import GraceLogger

_log = GraceLogger("api_auth")
_PUBLIC_PATHS = {"/health", "/openapi.json"}


class AuthMiddleware(BaseHTTPMiddleware):
    def __init__(self, app: ASGIApp, token: str = "", enabled: bool = False,
                 allow_localhost: bool = True) -> None:
        super().__init__(app)
        self._token = token
        self._enabled = enabled
        self._allow_localhost = allow_localhost

    async def dispatch(self, request: Request, call_next: RequestResponseEndpoint):
        if not self._enabled:
            return await call_next(request)

        if request.url.path in _PUBLIC_PATHS:
            return await call_next(request)

        if self._allow_localhost:
            host = request.client.host if request.client else ""
            if host in ("127.0.0.1", "::1", "localhost"):
                return await call_next(request)

        auth = request.headers.get("authorization", "")
        token = ""
        if auth.startswith("Bearer "):
            token = auth[7:]

        if not token:
            token = request.headers.get("x-grace-api-token", "")

        if not token or token != self._token:
            _log.warn("auth_failure", path=request.url.path)
            return JSONResponse(
                status_code=401,
                content={"error": {"code": "UNAUTHORIZED", "message": "missing or invalid API token"}},
            )

        return await call_next(request)
