# ############################################################################
# AI_HEADER: api_app_factory
# ROLE: App factory — `create_app(settings=None)` returns the configured
#       FastAPI app. W5 of source/codex/tz-api-first-cleanup-waves-w0-w11.md.
#       `api/main.py` is wiring-only; all configuration lives here.
# ############################################################################

# START_MODULE_CONTRACT
# purpose: Build and return the FastAPI app with lifespan, CORS, the global
#          exception handler, and every router wired under the right prefix.
# inputs: settings (GraceSettings | None) — None uses the module-level singleton.
# returns: FastAPI.
# side_effects: Includes routers; no DB or process side effects.
# emitted_logs: None (the global exception handler logs the 500 path).
# error_behavior: Never raises during construction.
# END_MODULE_CONTRACT

# START_MODULE_MAP
# mapping:
#   - function: create_app
# END_MODULE_MAP

from __future__ import annotations

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from grace_control.api.lifespan import lifespan
from grace_control.api.routers import (
    agents,
    architect,
    artifacts,
    dashboard,
    diagnostics,
    events,
    features,
    health,
    lifecycle,
    packets,
    recovery,
    self_evolution,
    tools,
    trace,
    workers,
    ws,
)
from grace_control.config.settings import GraceSettings, settings as _default_settings
from grace_control.core.structured_logger import GraceLogger
from grace_control.api.auth import AuthMiddleware

_log = GraceLogger("app_factory")


# START_FUNCTION_CONTRACT
# name: create_app
# purpose: Build and return the FastAPI app with lifespan, CORS, and routers.
# inputs: settings (GraceSettings | None).
# returns: FastAPI.
# side_effects: None.
# emitted_logs: None.
# error_behavior: Never raises during construction.
# END_FUNCTION_CONTRACT
def create_app(settings: GraceSettings | None = None) -> FastAPI:
    s = settings or _default_settings
    app = FastAPI(
        title="GRACE Control Plane",
        version="0.1.0",
        lifespan=lifespan,
    )
    app.add_middleware(
        CORSMiddleware,
        allow_origin_regex=r"http://localhost:\d+",
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    app.add_middleware(
        AuthMiddleware,
        token=s.api_auth_token,
        enabled=s.api_auth_enabled,
        allow_localhost=s.api_auth_allow_unauthenticated_localhost,
        public_openapi=s.api_auth_public_openapi,
    )

    @app.exception_handler(Exception)
    async def _global_exception_handler(_request: Request, exc: Exception):
        return JSONResponse(
            status_code=500,
            content={"error": {"code": "INTERNAL_ERROR", "message": str(exc)[:200]}},
        )

    # Routers — no path prefix on dashboard / health / ws (they own / and /api/dashboard).
    app.include_router(dashboard.router, tags=["dashboard-root"])
    app.include_router(health.router, tags=["health"])
    app.include_router(ws.router, tags=["ws"])

    app.include_router(features.router, prefix="/api/features", tags=["features"])
    app.include_router(packets.router, prefix="/api/packets", tags=["packets"])
    app.include_router(artifacts.router, tags=["artifacts"])
    app.include_router(workers.router, prefix="/api/workers", tags=["workers"])
    app.include_router(architect.router, prefix="/api/architect", tags=["architect"])
    app.include_router(self_evolution.router, prefix="/api/self", tags=["self-evolution"])
    app.include_router(recovery.router, prefix="/api/recovery", tags=["recovery"])
    app.include_router(trace.router, prefix="/api/trace", tags=["trace"])
    app.include_router(events.router, prefix="/api/events", tags=["events"])
    app.include_router(diagnostics.router, prefix="/api/diagnostics", tags=["diagnostics"])
    app.include_router(agents.router, prefix="/api/agents", tags=["agents"])
    app.include_router(tools.router, prefix="/api/tools", tags=["tools"])
    app.include_router(lifecycle.router, tags=["lifecycle"])

    return app
