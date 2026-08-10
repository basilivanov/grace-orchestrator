# ############################################################################
# AI_HEADER: api_app_factory
# ROLE: App factory — `create_app(settings=None)` returns the configured
#       FastAPI app. W5 of source/codex/tz-api-first-cleanup-waves-w0-w11.md.
#       `api/main.py` is wiring-only; all configuration lives here.
# ############################################################################

# START_MODULE_CONTRACT
# purpose: Build and return the FastAPI app with lifespan, CORS, the global
#          exception handler, and every router wired under the right prefix.
# inputs: settings (GraceSettings | None) — None uses the module-level singleton;
#          project_registry — optional immutable Admin Hub registry;
#          project_client_factory — optional test/integration client factory.
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

from grace_control.api.auth import AuthMiddleware
from grace_control.api.lifespan import lifespan
from grace_control.api.routers import (
    admin,
    admin_control_center,
    admin_filesystem,
    admin_git,
    admin_hub,
    admin_pipeline,
    admin_raw,
    admin_ui,
    agents,
    architect,
    artifacts,
    capabilities,
    dev_replay,
    diagnostics,
    events,
    features,
    health,
    lifecycle,
    packets,
    project_identity,
    recovery,
    self_evolution,
    tools,
    trace,
    workers,
    ws,
)
from grace_control.config.project_registry import ProjectRegistry, load_project_registry
from grace_control.config.runtime_identity import get_runtime_identity
from grace_control.config.settings import GraceSettings
from grace_control.config.settings import settings as _default_settings
from grace_control.core.structured_logger import GraceLogger
from grace_control.services.admin_cross_project_service import AdminCrossProjectService
from grace_control.services.admin_git_read_service import AdminGitReadService
from grace_control.services.admin_project_service import AdminProjectService
from grace_control.services.safe_filesystem_service import SafeFilesystemService

_log = GraceLogger("app_factory")


# START_FUNCTION_CONTRACT
# name: create_app
# purpose: Build and return the FastAPI app with lifespan, CORS, and routers.
# inputs: settings (GraceSettings | None); project_registry — optional Hub
#         registry; project_client_factory — optional project client factory.
# returns: FastAPI.
# side_effects: None.
# emitted_logs: None.
# error_behavior: Never raises during construction.
# END_FUNCTION_CONTRACT
def create_app(
    settings: GraceSettings | None = None,
    project_registry: ProjectRegistry | None = None,
    project_client_factory=None,
) -> FastAPI:
    s = settings or _default_settings
    registry = project_registry or load_project_registry()
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

    # Admin v2 — replaces the deleted dashboard router.
    # Mounts:
    #   - JSON API at /api/admin/* (read-only, for other consumers)
    #   - HTMX UI at /admin and /admin/_partial/* (server-rendered HTML)
    app.include_router(admin.router, tags=["admin"])
    app.include_router(admin_raw.router, tags=["admin-raw"])
    app.include_router(admin_filesystem.router, tags=["admin-filesystem"])
    app.include_router(admin_git.router, tags=["admin-git"])
    app.include_router(capabilities.router, tags=["capabilities"])
    app.include_router(admin_hub.router, tags=["admin-hub"])
    app.include_router(admin_pipeline.router, tags=["admin-pipeline"])
    app.include_router(admin_control_center.router, tags=["admin-control-center"])
    app.include_router(admin_ui.router, tags=["admin-ui"])
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
    app.include_router(dev_replay.router, tags=["dev_replay"])
    app.include_router(lifecycle.router, tags=["lifecycle"])
    app.include_router(project_identity.router, tags=["project-identity"])

    app_state = app.__dict__["state"]
    app_state.admin_project_service = AdminProjectService(registry, client_factory=project_client_factory)
    app_state.admin_cross_project_service = AdminCrossProjectService(
        registry,
        client_factory=project_client_factory,
    )
    identity = get_runtime_identity()
    app_state.project_filesystem_service = SafeFilesystemService.from_runtime(
        settings_obj=s,
        project_root=identity["project_root"],
    )
    app_state.project_git_read_service = AdminGitReadService(
        identity["target_repo_root"],
        target_branch=str(identity["target_branch"]),
        base_branch=str(identity["base_branch"]),
        remote=str(identity["git_remote"]),
    )

    # Admin UI — static assets for /static/* (HTMX is loaded from CDN in the template).
    from pathlib import Path as _P

    from fastapi.responses import HTMLResponse, RedirectResponse
    from fastapi.staticfiles import StaticFiles as _SF

    _ui_dir = _P(__file__).resolve().parents[1] / "ui"
    _admin_static = _ui_dir / "static"
    if _admin_static.exists():
        app.mount("/static", _SF(directory=str(_admin_static)), name="static")

    @app.get("/", include_in_schema=False)
    async def _root_redirect():
        """Root URL → /admin.html (new flat dashboard)."""
        return RedirectResponse(url="/admin.html", status_code=307)

    # Build ID from git HEAD
    _build_id = ""
    try:
        _proc = __import__("subprocess").run(
            ["git", "rev-parse", "--short", "HEAD"],
            capture_output=True, text=True, timeout=3,
        )
        if _proc.returncode == 0:
            _build_id = _proc.stdout.strip()
    except Exception:
        pass

    @app.get("/api/debug/version")
    async def _version_endpoint():
        return {"build_id": _build_id, "app": "GRACE Control Plane"}

    # Serve the new flat admin dashboard as a standalone HTML page
    _new_admin_html = _admin_static / "admin.html"

    @app.get("/admin.html", include_in_schema=False, response_class=HTMLResponse)
    async def _new_admin_dashboard():
        """New flat at-a-glance GRACE Control Plane dashboard."""
        if not _new_admin_html.exists():
            return HTMLResponse(content="<h1>admin.html not found</h1>", status_code=404)
        html = _new_admin_html.read_text()
        # Inject build ID
        build_script = f'<script>window.BUILD_ID="{_build_id}";</script>'
        html = html.replace("<head>", "<head>" + build_script)
        return HTMLResponse(content=html)

    # Keep old HTMX console at /admin/old
    @app.get("/admin/old", include_in_schema=False, response_class=HTMLResponse)
    async def _old_admin_redirect(request: Request):
        """Old HTMX console — still accessible for reference."""
        from grace_control.api.routers.admin_ui import admin_console
        return await admin_console(request=request)

    return app
