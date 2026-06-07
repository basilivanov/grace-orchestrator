# ############################################################################
# AI_HEADER: admin_ui_router
# ROLE: Server-rendered HTML endpoints for the operator console.
#       Powers HTMX partial updates at /admin/_partial/*. The /admin SPA shell
#       is server-rendered (Jinja2 + HTMX), with HTMX handling all in-page
#       navigation. JSON API at /api/admin/* remains for other consumers.
# ############################################################################

# START_MODULE_CONTRACT
# purpose: Render the operator console as a server-rendered HTMX page.
#          - GET /admin               (full page — top-level nav)
#          - GET /admin/system        (full page — top-level nav)
#          - GET /admin/_partial/*    (HTML fragments, swapped by HTMX)
# inputs:  URL query params: feature_id, packet_id, tab, search, filter.
# returns: HTML (Jinja2 templates).
# side_effects: None.
# emitted_logs: None.
# error_behavior: 404 on missing entities; empty fragments otherwise.
# END_MODULE_CONTRACT

# START_MODULE_MAP
# mapping:
#   - router: APIRouter
#     routes:
#       - GET  /admin
#       - GET  /admin/system
#       - GET  /admin/_partial/stats
#       - GET  /admin/_partial/master
#       - GET  /admin/_partial/timeline
#       - GET  /admin/_partial/detail
#       - GET  /admin/_partial/tab
# END_MODULE_MAP

from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter, HTTPException, Query, Request
from fastapi.responses import HTMLResponse, Response
from fastapi.templating import Jinja2Templates

from grace_control.db import get_db
from grace_control.services.admin_aggregation_service import AdminAggregationService
from grace_control.ui.admin_template_filters import register as _register_filters

router = APIRouter()
_svc = AdminAggregationService()

_TEMPLATES_DIR = Path(__file__).parent.parent.parent / "ui" / "templates"
_templates = Jinja2Templates(directory=str(_TEMPLATES_DIR / "admin"))
_register_filters(_templates.env)

# Tabs that can be swapped via HTMX (each one is a single hx-get endpoint)
_TABS = ("timeline", "spec", "runs", "sessions", "evidence", "logs", "artifacts")


def _features_data() -> dict:
    """Return the features tree (cached per request)."""
    with get_db() as db:
        return _svc.get_features_tree(db)


def _overview_data() -> dict:
    with get_db() as db:
        return _svc.get_overview(db)


def _packet_detail(packet_id: str) -> dict | None:
    with get_db() as db:
        return _svc.get_packet_detail(db, packet_id)


# ── Top-level pages (full reload allowed) ───────────────────────────────────


@router.get("/admin", response_class=HTMLResponse)
def admin_console(
    request: Request,
    feature_id: str | None = None,
    packet_id: str | None = None,
    tab: str = "timeline",
    search: str = "",
    filter: str = "all",
    expanded_features: str = "",
    expanded_waves: str = "",
) -> HTMLResponse:
    """The main operator console — server-rendered with HTMX.

    Top-level navigation. Within the page, HTMX handles all interactions
    (feature click → partial timeline update, packet click → partial detail
    update, tab click → partial tab update, search → partial master update).
    """
    features_data = _features_data()
    overview = _overview_data()
    features = features_data.get("features", [])

    # Expand feature/wave sets from query string (comma-separated)
    ef = set(s for s in expanded_features.split(",") if s)
    ew = set(s for s in expanded_waves.split(",") if s)
    # If a packet is selected, auto-expand its feature/wave so it's visible
    if packet_id and not ef and not ew:
        for f in features:
            for w in (f.get("waves") or []):
                for p in (w.get("packets") or []):
                    if p["id"] == packet_id:
                        ef.add(f["id"])
                        ew.add(w["id"])
                        break

    # Load packet detail if selected
    packet = _packet_detail(packet_id) if packet_id else None

    ctx = {
        "request": request,
        "active_nav": "overview",
        "active_tab": tab if tab in _TABS else "timeline",
        "tabs": _TABS,
        "overview": overview,
        "features": features,
        "search": search,
        "filter": filter,
        "selected_feature_id": feature_id,
        "selected_packet_id": packet_id,
        "packet": packet,
        "expanded_features": ef,
        "expanded_waves": ew,
        "total_packets": sum(
            len(p) for f in features for w in (f.get("waves") or [])
            for p in [w.get("packets") or []] for p in p
        ),
    }
    return _templates.TemplateResponse(request, "console.html", ctx)


@router.get("/admin/system", response_class=HTMLResponse)
def admin_system(request: Request) -> HTMLResponse:
    with get_db() as db:
        health = _svc.get_system_health()
        workers = _svc.get_workers(db)
    return _templates.TemplateResponse(request, "system.html", {
        "request": request,
        "active_nav": "system",
        "health": health,
        "workers": workers.get("workers", []),
    })


# ── HTMX partials ───────────────────────────────────────────────────────────


@router.get("/admin/_partial/stats", response_class=HTMLResponse)
def partial_stats(request: Request) -> HTMLResponse:
    """Stats bar fragment — polls every 5s, swaps only #stats-bar-container."""
    return _templates.TemplateResponse(request, "_stats.html", {
        "request": request,
        "overview": _overview_data(),
    })


@router.get("/admin/_partial/master", response_class=HTMLResponse)
def partial_master(
    request: Request,
    search: str = "",
    filter: str = "all",
    feature_id: str | None = None,
    packet_id: str | None = None,
    expanded_features: str = "",
    expanded_waves: str = "",
) -> HTMLResponse:
    """Master tree fragment — swaps on search input or filter change.

    Swaps only the master tree (outerHTML of #master-tree).
    Does NOT push URL by itself — caller controls URL via hx-push-url.
    """
    features_data = _features_data()
    features = features_data.get("features", [])

    ef = set(s for s in expanded_features.split(",") if s)
    ew = set(s for s in expanded_waves.split(",") if s)

    return _templates.TemplateResponse(request, "_master.html", {
        "request": request,
        "features": features,
        "search": search,
        "filter": filter,
        "selected_feature_id": feature_id,
        "selected_packet_id": packet_id,
        "expanded_features": ef,
        "expanded_waves": ew,
    })


@router.get("/admin/_partial/timeline", response_class=HTMLResponse)
def partial_timeline(
    request: Request,
    feature_id: str | None = None,
    packet_id: str | None = None,
    filter: str = "all",
    expanded_features: str = "",
    expanded_waves: str = "",
    toggle_wave: str | None = None,
) -> HTMLResponse:
    """Feature timeline fragment — swaps on feature click or filter change.

    Swaps only #timeline-pane (outerHTML). Pushes URL with hx-push-url=true.
    """
    features_data = _features_data()
    features = features_data.get("features", [])

    ef = set(s for s in expanded_features.split(",") if s)
    ew = set(s for s in expanded_waves.split(",") if s)

    # If toggle_wave is in the query, flip it in the URL we push.
    if toggle_wave:
        if toggle_wave in ew:
            ew.discard(toggle_wave)
        else:
            ew.add(toggle_wave)

    return _templates.TemplateResponse(request, "_timeline.html", {
        "request": request,
        "features": features,
        "filter": filter,
        "selected_feature_id": feature_id,
        "selected_packet_id": packet_id,
        "expanded_features": ef,
        "expanded_waves": ew,
    })


@router.get("/admin/_partial/detail", response_class=HTMLResponse)
def partial_detail(
    request: Request,
    packet_id: str = Query(...),
    feature_id: str | None = None,
    tab: str = "timeline",
    expanded_features: str = "",
    expanded_waves: str = "",
) -> HTMLResponse:
    """Packet detail fragment — swaps on packet click.

    Swaps only #detail-pane (outerHTML). Pushes URL with hx-push-url=true.
    Preserves master tree state (search, filter, expanded) via query params.
    """
    packet = _packet_detail(packet_id)
    if packet is None:
        return _templates.TemplateResponse(request, "_detail.html", {
            "request": request,
            "selected_packet_id": packet_id,
            "selected_feature_id": feature_id,
            "packet": None,
            "tabs": _TABS,
            "active_tab": tab,
        })

    return _templates.TemplateResponse(request, "_detail.html", {
        "request": request,
        "packet": packet,
        "selected_packet_id": packet_id,
        "selected_feature_id": feature_id,
        "tabs": _TABS,
        "active_tab": tab if tab in _TABS else "timeline",
    })


@router.get("/admin/_partial/tab", response_class=HTMLResponse)
def partial_tab(
    request: Request,
    packet_id: str = Query(...),
    tab: str = "timeline",
    feature_id: str | None = None,
) -> HTMLResponse:
    """Tab body fragment — swaps on tab click.

    Swaps only #packet-tab-content (outerHTML). Does NOT re-render the header,
    state machine, why-failed, or tabs themselves. Pushes URL with hx-push-url.
    """
    if tab not in _TABS:
        tab = "timeline"
    packet = _packet_detail(packet_id)
    if packet is None:
        return _templates.TemplateResponse(request, "_tab.html", {
            "request": request, "packet": None, "active_tab": tab,
        })

    # Pre-fetch data for the requested tab
    timeline_events: list[dict] = []
    timeline_total = 0
    runs: list[dict] = []
    sessions: dict | None = None
    evidence: dict | None = None
    logs_text = ""
    artifacts: dict | None = None

    # The aggregation service expects run_id to be the suffix (run_number),
    # not the full id "pkt_xxx-N". Extract run_number from runs_summary.
    last_run_number = None
    last_summary = (packet.get("runs_summary") or [])
    if last_summary:
        last_run_number = str(last_summary[-1].get("run_number") or "")

    with get_db() as db:
        if tab == "timeline":
            tdata = _svc.get_packet_timeline(db, packet_id, limit=200, offset=0)
            timeline_events = tdata.get("events", [])
            timeline_total = tdata.get("total", 0)
        elif tab == "runs":
            rdata = _svc.get_packet_runs(db, packet_id)
            runs = rdata.get("runs", [])
        elif tab == "sessions":
            sessions = _svc.get_packet_sessions(db, packet_id)
        elif tab == "evidence":
            if last_run_number:
                evidence = _svc.get_packet_evidence(db, packet_id, run_id=last_run_number)
        elif tab == "logs":
            if last_run_number:
                ldata = _svc.get_packet_logs(db, packet_id, last_run_number,
                                              stream="stderr", tail=200, filter_regex="")
                logs_text = ldata.get("text", "")
        elif tab == "artifacts":
            if last_run_number:
                artifacts = _svc.get_packet_artifacts(db, packet_id, last_run_number)

    return _templates.TemplateResponse(request, "_tab.html", {
        "request": request,
        "packet": packet,
        "active_tab": tab,
        "timeline_events": timeline_events,
        "timeline_total": timeline_total,
        "runs": runs,
        "sessions": sessions,
        "evidence": evidence,
        "logs_text": logs_text,
        "artifacts": artifacts,
    })
