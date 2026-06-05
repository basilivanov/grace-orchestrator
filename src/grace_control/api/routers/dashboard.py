# ############################################################################
# AI_HEADER: api_routers_dashboard
# ROLE: Dashboard router — `/`, `/api/dashboard`. Extracted from api/main.py
#       in W5 of source/codex/tz-api-first-cleanup-waves-w0-w11.md. The
#       legacy `/test` debug page was removed in W5; the dashboard service
#       owns all DB aggregation now.
# ############################################################################

# START_MODULE_CONTRACT
# purpose: Render the dashboard HTML (`/`) and serve the JSON aggregation
#          (`/api/dashboard`) by delegating to DashboardService.
# inputs: HTTP requests.
# returns: HTML or JSON.
# side_effects: None.
# emitted_logs: None.
# error_behavior: 200 with an inline fallback when the template is missing.
# END_MODULE_CONTRACT

# START_MODULE_MAP
# mapping:
#   - router: APIRouter
#     routes:
#       - GET /
#       - GET /api/dashboard
# END_MODULE_MAP

from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter
from fastapi.responses import HTMLResponse

from grace_control.services.dashboard_service import DashboardService

router = APIRouter(tags=["dashboard"])
_svc = DashboardService()
_UI_DIR = Path(__file__).resolve().parents[2] / "ui"  # noqa: F841


# START_FUNCTION_CONTRACT
# name: dashboard
# purpose: Serve the static dashboard HTML template from ui/templates/.
# inputs: none.
# returns: HTMLResponse.
# side_effects: None.
# emitted_logs: None.
# error_behavior: 200 with a one-line fallback when the template is missing.
# END_FUNCTION_CONTRACT
@router.get("/", response_class=HTMLResponse)
async def dashboard():
    template = _UI_DIR / "templates" / "dashboard.html"
    if template.exists():
        return HTMLResponse(template.read_text())
    return HTMLResponse("<h1>GRACE Control Plane</h1><p>Dashboard template not found.</p>")


# START_FUNCTION_CONTRACT
# name: dashboard_data
# purpose: HTTP wrapper around DashboardService.get_dashboard.
# inputs: none.
# returns: dict (the dashboard payload).
# side_effects: None.
# emitted_logs: None.
# error_behavior: Never raises.
# END_FUNCTION_CONTRACT
@router.get("/api/dashboard")
async def dashboard_data() -> dict:
    from grace_control.db import get_db as _gdb
    with _gdb() as db:
        return _svc.get_dashboard(db)
