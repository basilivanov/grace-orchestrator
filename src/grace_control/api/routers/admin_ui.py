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
#       - GET  /admin/_partial/maintenance
#       - POST /admin/maintenance/cleanup
# END_MODULE_MAP

from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter, HTTPException, Query, Request
from fastapi.responses import HTMLResponse, Response
from fastapi.templating import Jinja2Templates

from grace_control.db import get_db
from grace_control.services.admin_aggregation_service import AdminAggregationService
from grace_control.services.maintenance_service import MaintenanceService, CleanupResult
from grace_control.ui.admin_template_filters import register as _register_filters
from grace_control.ui.admin_template_filters import shell_url as _shell_url
from grace_control.config.settings import settings as _settings

router = APIRouter()
_svc = AdminAggregationService()
_project = Path(_settings.target_repo_root or ".").resolve()
_maint_svc = MaintenanceService(
    state_root=_project / _settings.state_root,
    worktree_root=_project / _settings.worktree_root,
    project_root=_project,
)

_TEMPLATES_DIR = Path(__file__).parent.parent.parent / "ui" / "templates"
_templates = Jinja2Templates(directory=str(_TEMPLATES_DIR / "admin"))
_register_filters(_templates.env)
_templates.env.globals["dev_tools_enabled"] = _settings.dev_tools_enabled
_templates.env.globals["dev_keep_failed_worktrees"] = _settings.dev_keep_failed_worktrees

# Tabs that can be swapped via HTMX (each one is a single hx-get endpoint)
_TABS = ("timeline", "spec", "runs", "sessions", "evidence", "logs", "artifacts", "diagnostics")


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


def _wave_detail(feature_id: str, wave_id: str) -> dict | None:
    with get_db() as db:
        return _svc.get_wave_detail(db, feature_id, wave_id)


def _split_sets(*vals: str) -> list[list[str]]:
    """Parse comma-separated query strings into sorted lists."""
    out = []
    for v in vals:
        s = sorted(x for x in (v or "").split(",") if x)
        out.append(s)
    return out


def _ctx(
    *,
    search: str = "",
    filter: str = "all",
    selected_feature_id: str | None = None,
    selected_wave_id: str | None = None,
    selected_packet_id: str | None = None,
    tab: str = "timeline",
    expanded_features: list[str] | None = None,
    expanded_waves: list[str] | None = None,
) -> dict:
    """Build the common shell_url() context for templates."""
    return {
        "search": search,
        "filter": filter,
        "selected_feature_id": selected_feature_id,
        "selected_wave_id": selected_wave_id,
        "selected_packet_id": selected_packet_id,
        "active_tab": tab,
        "expanded_features": expanded_features or [],
        "expanded_waves": expanded_waves or [],
        "shell_url": _shell_url,
    }


# ── Top-level pages (full reload allowed) ───────────────────────────────────


@router.get("/admin", response_class=HTMLResponse)
def admin_console(
    request: Request,
    feature_id: str | None = None,
    wave_id: str | None = None,
    packet_id: str | None = None,
    tab: str = "timeline",
    search: str = "",
    filter: str = "all",
    expanded_features: str = "",
    expanded_waves: str = "",
    view: str = "overview",
) -> HTMLResponse:
    """The main operator console — server-rendered with HTMX.

    Top-level navigation. Within the page, HTMX handles all interactions
    (feature click → partial timeline update, packet click → partial detail
    update, tab click → partial tab update, search → partial master update).

    `view` switches between "overview" (default) and "maintenance".
    """
    features_data = _features_data()
    overview = _overview_data()
    features = features_data.get("features", [])

    # Expand feature/wave sets from query string (comma-separated)
    ef, ew = _split_sets(expanded_features, expanded_waves)
    ef_set = set(ef)
    ew_set = set(ew)
    # If a packet is selected, auto-expand its feature/wave so it's visible
    if packet_id and not ef_set and not ew_set:
        for f in features:
            for w in (f.get("waves") or []):
                for p in (w.get("packets") or []):
                    if p["id"] == packet_id:
                        ef_set.add(f["id"])
                        ew_set.add(w["id"])
                        break
    elif wave_id and not ef_set and not ew_set:
        # If a wave is selected, auto-expand its feature so it's visible
        for f in features:
            for w in (f.get("waves") or []):
                if w["id"] == wave_id:
                    ef_set.add(f["id"])
                    ew_set.add(w["id"])
                    break
    ef = sorted(ef_set)
    ew = sorted(ew_set)

    # Load packet detail if selected; else wave detail if selected
    packet = _packet_detail(packet_id) if packet_id else None
    wave = (
        _wave_detail(feature_id, wave_id)
        if (wave_id and feature_id and not packet_id) else None
    )

    # Pre-compute click URLs for each feature / wave / packet.
    for f in features:
        new_ef = sorted(set(ef) | {f["id"]})
        f["click_url"] = _shell_url(
            feature_id=f["id"], expanded_features=new_ef, expanded_waves=ew,
            search=search, filter=filter,
        )
        for w in (f.get("waves") or []):
            new_ew = sorted(set(ew) | {w["id"]}) if w["id"] != wave_id else sorted(set(ew))
            # Wave click URL: expand the wave so its packets are visible
            w["click_url"] = _shell_url(
                feature_id=f["id"], wave_id=w["id"],
                expanded_features=new_ef, expanded_waves=new_ew,
                search=search, filter=filter,
            )
            for p in (w.get("packets") or []):
                p["click_url"] = _shell_url(
                    feature_id=f["id"], packet_id=p["id"], tab="timeline",
                    expanded_features=new_ef, expanded_waves=new_ew,
                    search=search, filter=filter,
                )

    # Pre-compute filter chip URLs.
    chips: list[dict] = []
    for chip_filter in ("all", "failed", "running", "blocked", "attention"):
        chips.append({
            "filter": chip_filter,
            "url": _shell_url(
                feature_id=feature_id, wave_id=wave_id,
                filter=chip_filter,
                expanded_features=ef, expanded_waves=ew, search=search,
            ),
        })

    # Pre-compute packet click URLs in the rendered feature timeline.
    if feature_id:
        for f in features:
            if f["id"] != feature_id:
                continue
            for w in (f.get("waves") or []):
                for p in (w.get("packets") or []):
                    p["click_url"] = _shell_url(
                        feature_id=f["id"], packet_id=p["id"], tab="timeline",
                        filter=filter, expanded_features=ef, expanded_waves=ew,
                        search=search,
                    )

    # Pre-compute tab URLs for packet detail.
    tab_urls: dict[str, str] = {}
    if packet:
        for t in _TABS:
            tab_urls[t] = _shell_url(
                feature_id=feature_id, packet_id=packet_id, tab=t,
                expanded_features=ef, expanded_waves=ew,
                search=search, filter=filter,
            )

    # Pre-compute wave click URLs in the detail-pane packet list
    if wave:
        for p in (wave.get("packets") or []):
            p["click_url"] = _shell_url(
                feature_id=feature_id, packet_id=p["id"], tab="timeline",
                filter=filter, expanded_features=ef, expanded_waves=ew,
                search=search,
            )

    # Find selected feature data for detail pane
    selected_feature = None
    if feature_id:
        for f in features:
            if f["id"] == feature_id:
                selected_feature = f
                break

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
        "selected_wave_id": wave_id,
        "selected_packet_id": packet_id,
        "packet": packet,
        "wave": wave,
        "feature": selected_feature,
        "expanded_features": ef,
        "expanded_waves": ew,
        "chips": chips,
        "view": view,
        "tab_urls": tab_urls,
        "shell_url": _shell_url,
        "total_packets": sum(
            len(p) for f in features for w in (f.get("waves") or [])
            for p in [w.get("packets") or []] for p in p
        ),
    }
    # Maintenance view: pass snapshot for the inlined _maintenance.html
    if view == "maintenance":
        with get_db() as db:
            states = _packet_states_map(db)
        ctx["snapshot"] = _maint_svc.snapshot(packet_states=states)
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
    wave_id: str | None = None,
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
    ef, ew = _split_sets(expanded_features, expanded_waves)

    # Pre-compute click URLs for each feature, wave, packet.
    for f in features:
        new_ef = sorted(set(ef) | {f["id"]})
        f["click_url"] = _shell_url(
            feature_id=f["id"],
            expanded_features=new_ef,
            expanded_waves=ew,
            search=search,
            filter=filter,
        )
        for w in (f.get("waves") or []):
            new_ew = sorted(set(ew) | {w["id"]}) if w["id"] != wave_id else sorted(set(ew))
            w["click_url"] = _shell_url(
                feature_id=f["id"], wave_id=w["id"],
                expanded_features=new_ef, expanded_waves=new_ew,
                search=search, filter=filter,
            )
            for p in (w.get("packets") or []):
                p["click_url"] = _shell_url(
                    feature_id=f["id"],
                    packet_id=p["id"],
                    tab="timeline",
                    expanded_features=new_ef,
                    expanded_waves=new_ew,
                    search=search,
                    filter=filter,
                )

    return _templates.TemplateResponse(request, "_master.html", {
        "request": request,
        "features": features,
        "search": search,
        "filter": filter,
        "selected_feature_id": feature_id,
        "selected_wave_id": wave_id,
        "selected_packet_id": packet_id,
        "expanded_features": ef,
        "expanded_waves": ew,
        "shell_url": _shell_url,
    })


@router.get("/admin/_partial/timeline", response_class=HTMLResponse)
def partial_timeline(
    request: Request,
    feature_id: str | None = None,
    wave_id: str | None = None,
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
    ef, ew = _split_sets(expanded_features, expanded_waves)
    ew_set = set(ew)
    # If toggle_wave is in the query, flip it in the URL we push.
    if toggle_wave:
        if toggle_wave in ew_set:
            ew_set.discard(toggle_wave)
        else:
            ew_set.add(toggle_wave)
    ew = sorted(ew_set)

    # Pre-compute chip URLs and packet click URLs.
    chips: list[dict] = []
    for chip_filter in ("all", "failed", "running", "blocked", "attention"):
        chips.append({
            "filter": chip_filter,
            "url": _shell_url(
                feature_id=feature_id, wave_id=wave_id,
                filter=chip_filter,
                expanded_features=ef,
                expanded_waves=ew,
                search="",
            ),
        })

    # Pre-compute wave click URLs (select wave → detail pane)
    # and packet click URLs in the rendered feature.
    if feature_id:
        for f in features:
            if f["id"] != feature_id:
                continue
            for w in (f.get("waves") or []):
                new_ew_wave = sorted(set(ew) | {w["id"]}) if w["id"] != wave_id else sorted(set(ew))
                w["click_url"] = _shell_url(
                    feature_id=f["id"], wave_id=w["id"],
                    expanded_features=ef, expanded_waves=new_ew_wave,
                    filter=filter, search="",
                )
                for p in (w.get("packets") or []):
                    p["click_url"] = _shell_url(
                        feature_id=f["id"],
                        packet_id=p["id"],
                        tab="timeline",
                        filter=filter,
                        expanded_features=ef,
                        expanded_waves=ew,
                        search="",
                    )

    return _templates.TemplateResponse(request, "_timeline.html", {
        "request": request,
        "features": features,
        "filter": filter,
        "selected_feature_id": feature_id,
        "selected_wave_id": wave_id,
        "selected_packet_id": packet_id,
        "expanded_features": ef,
        "expanded_waves": ew,
        "chips": chips,
        "shell_url": _shell_url,
    })


@router.get("/admin/_partial/detail", response_class=HTMLResponse)
def partial_detail(
    request: Request,
    packet_id: str | None = None,
    wave_id: str | None = None,
    feature_id: str | None = None,
    tab: str = "timeline",
    search: str = "",
    filter: str = "all",
    expanded_features: str = "",
    expanded_waves: str = "",
) -> HTMLResponse:
    """Detail fragment — renders Wave details or Packet details.

    - If `packet_id` is provided → packet details.
    - Else if `wave_id` (and `feature_id`) is provided → wave details.
    - Else → empty detail pane.

    Swaps only #detail-pane (outerHTML). Pushes URL with hx-push-url=true.
    Preserves master tree state (search, filter, expanded) via query params.
    """
    ef, ew = _split_sets(expanded_features, expanded_waves)
    active_tab = tab if tab in _TABS else "timeline"

    # Wave detail mode (no packet)
    if not packet_id and wave_id and feature_id:
        wave = _wave_detail(feature_id, wave_id)
        # Pre-compute packet click URLs in the wave
        if wave:
            for p in (wave.get("packets") or []):
                p["click_url"] = _shell_url(
                    feature_id=feature_id, packet_id=p["id"], tab="timeline",
                    filter=filter, expanded_features=ef, expanded_waves=ew,
                    search=search,
                )
        return _templates.TemplateResponse(request, "_detail.html", {
            "request": request,
            "packet": None,
            "wave": wave,
            "selected_feature_id": feature_id,
            "selected_wave_id": wave_id,
            "selected_packet_id": None,
            "tabs": _TABS,
            "active_tab": active_tab,
            "tab_urls": {},
            "search": search,
            "filter": filter,
            "expanded_features": ef,
            "expanded_waves": ew,
            "shell_url": _shell_url,
        })

    if not packet_id:
        # Feature detail mode: look up feature data if feature_id is set
        feature = None
        if feature_id:
            features_data = _features_data()
            for f in features_data.get("features", []):
                if f["id"] == feature_id:
                    # Pre-compute wave click URLs in the feature
                    for w in (f.get("waves") or []):
                        w["click_url"] = _shell_url(
                            feature_id=f["id"], wave_id=w["id"],
                            expanded_features=ef, expanded_waves=ew,
                            filter=filter, search=search,
                        )
                    feature = f
                    break
        return _templates.TemplateResponse(request, "_detail.html", {
            "request": request,
            "packet": None,
            "wave": None,
            "feature": feature,
            "selected_feature_id": feature_id,
            "selected_wave_id": wave_id,
            "selected_packet_id": None,
            "tabs": _TABS,
            "active_tab": active_tab,
            "tab_urls": {},
            "search": search,
            "filter": filter,
            "expanded_features": ef,
            "expanded_waves": ew,
            "shell_url": _shell_url,
        })

    packet = _packet_detail(packet_id)
    tab_urls: dict[str, str] = {}
    for t in _TABS:
        tab_urls[t] = _shell_url(
            feature_id=feature_id, packet_id=packet_id, tab=t,
            expanded_features=ef, expanded_waves=ew,
            search=search, filter=filter,
        )
    if packet is None:
        return _templates.TemplateResponse(request, "_detail.html", {
            "request": request,
            "selected_packet_id": packet_id,
            "selected_feature_id": feature_id,
            "selected_wave_id": wave_id,
            "packet": None,
            "wave": None,
            "tabs": _TABS,
            "active_tab": active_tab,
            "tab_urls": tab_urls,
            "search": search,
            "filter": filter,
            "expanded_features": ef,
            "expanded_waves": ew,
            "shell_url": _shell_url,
        })

    return _templates.TemplateResponse(request, "_detail.html", {
        "request": request,
        "packet": packet,
        "wave": None,
        "selected_packet_id": packet_id,
        "selected_feature_id": feature_id,
        "selected_wave_id": wave_id,
        "tabs": _TABS,
        "active_tab": active_tab,
        "tab_urls": tab_urls,
        "search": search,
        "filter": filter,
        "expanded_features": ef,
        "expanded_waves": ew,
        "shell_url": _shell_url,
    })


@router.get("/admin/_partial/tab", response_class=HTMLResponse)
def partial_tab(
    request: Request,
    packet_id: str = Query(...),
    tab: str = "timeline",
    feature_id: str | None = None,
    wave_id: str | None = None,
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
            "shell_url": _shell_url,
        })

    # Pre-fetch data for the requested tab
    timeline_events: list[dict] = []
    timeline_total = 0
    runs: list[dict] = []
    sessions: dict | None = None
    evidence: dict | None = None
    logs_text = ""
    artifacts: dict | None = None
    diagnostic_data: dict | None = None

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
        elif tab == "diagnostics":
            if last_run_number:
                run = _svc.get_packet_run(db, packet_id, last_run_number)
            else:
                run = None
            if run:
                rj = run.get("result_json") or {}
                diag_evidence = (rj.get("diagnostics") or {}).get("evidence", {}) or rj.get("evidence", {})
                scope = diag_evidence.get("scope_enforcement", {})
                details = ""
                if isinstance(scope, dict):
                    if scope.get("out_of_scope_files"):
                        details = f"Files outside scope: {scope['out_of_scope_files']}"
                    elif scope.get("frozen_touched_files"):
                        details = f"Frozen scope changes: {scope['frozen_touched_files']}"
                    if scope.get("summary"):
                        details = details or scope["summary"]
                diagnostic_data = {
                    "failure_code": diag_evidence.get("failure_code"),
                    "details": details,
                    "changed_files": diag_evidence.get("changed_files", []),
                    "artifact_refs": diag_evidence.get("artifact_refs", []),
                    "scope_enforcement": scope,
                    "diff_inspection": diag_evidence.get("diff_inspection", {}),
                }
            else:
                diagnostic_data = {"failure_code": None, "details": "No runs for this packet",
                                   "changed_files": [], "artifact_refs": []}

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
        "diagnostic_data": diagnostic_data,
        "shell_url": _shell_url,
    })


# ── Maintenance tab (TZ_RETENTION_POLICY.md Phase 3) ───────────────────────


def _packet_states_map(db) -> dict[str, str]:
    """Return {packet_id: state} for all packets (used to flag stale worktrees)."""
    from grace_control.db.schema import Packet
    return {p.id: (p.state or "draft") for p in db.query(Packet).all()}


@router.get("/admin/_partial/maintenance", response_class=HTMLResponse)
def partial_maintenance(request: Request) -> HTMLResponse:
    """Maintenance tab fragment — disk usage, branches, worktrees, actions.

    Swaps into #detail-pane (outerHTML). Pushes URL via hx-push-url.
    Refreshes on every 5s polling tick (same as other panes).
    """
    with get_db() as db:
        states = _packet_states_map(db)
    snap = _maint_svc.snapshot(packet_states=states)
    return _templates.TemplateResponse(request, "_maintenance.html", {
        "request": request,
        "snapshot": snap,
        "shell_url": _shell_url,
    })


@router.post("/admin/maintenance/cleanup", response_class=HTMLResponse)
def cleanup_action(
    request: Request,
    action: str = Query(..., description="worktree|branch|stale"),
    slug: str | None = Query(None),
    branch: str | None = Query(None),
    dry_run: bool = Query(False),
) -> HTMLResponse:
    """Run a manual cleanup action and re-render the maintenance pane.

    Actions:
      - worktree: delete a specific worktree (slug required)
      - branch:   delete a specific agent/* branch (branch required)
      - stale:    delete all worktrees for terminal-state packets
    """
    with get_db() as db:
        states = _packet_states_map(db)

    if action == "worktree" and slug:
        result = _maint_svc.cleanup_worktree(slug, dry_run=dry_run)
    elif action == "branch" and branch:
        result = _maint_svc.cleanup_branch(branch, dry_run=dry_run)
    elif action == "stale":
        result = _maint_svc.cleanup_stale_worktrees(
            packet_states=states, dry_run=dry_run,
        )
    else:
        result = CleanupResult()  # unknown action
        result.errors.append(f"unknown action: {action}")

    snap = _maint_svc.snapshot(packet_states=states)
    return _templates.TemplateResponse(request, "_maintenance.html", {
        "request": request,
        "snapshot": snap,
        "last_result": result,
        "shell_url": _shell_url,
    })
