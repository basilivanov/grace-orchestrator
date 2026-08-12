# ############################################################################
# AI_HEADER: admin_control_center_global — global explorer route owner
# ROLE: Owns cross-project Events, Logs and Search page orchestration while the
#       facade retains the historical decorators and template seams.
# ############################################################################

# START_MODULE_CONTRACT
# purpose: Compose cross-project explorer pages through the accepted Hub-backed
#          AdminControlCenterService without introducing project selection state.
# inputs: Explicit project filters, entity/log/search selectors and callbacks.
# returns: Full-shell or HTMX fragment HTMLResponse pages.
# side_effects: Bounded cross-project read calls only.
# emitted_logs: Hub-owned structured read logs.
# error_behavior: Unknown project filters use the canonical 404 callback;
#                 partial results remain visible.
# END_MODULE_CONTRACT

# START_MODULE_MAP
# mapping:
#   - function: admin_events_impl
#   - function: admin_logs_impl
#   - function: admin_search_impl
# END_MODULE_MAP

from __future__ import annotations

from collections.abc import Callable

from fastapi import Request
from fastapi.responses import HTMLResponse

from grace_control.core.structured_logger import GraceLogger
from grace_control.services.admin_control_center import AdminControlCenterService

_log = GraceLogger("admin_control_center_global")


# START_BLOCK_GLOBAL_EXPLORERS
# START_FUNCTION_CONTRACT
# name: admin_events_impl
# purpose: Render cross-project Events with optional explicit project/entity
#          filters and canonical full-payload event rows.
# inputs: request, project list, event filters/pagination and callbacks.
# returns: HTMLResponse.
# side_effects: Bounded Hub event reads.
# emitted_logs: Hub-owned event read logs.
# error_behavior: Unknown project filters use the canonical 404 callback.
# END_FUNCTION_CONTRACT
async def admin_events_impl(
    request: Request,
    project: list[str] | None,
    entity_id: str | None,
    entity_type: str | None,
    event_type: str | None,
    trace_id: str | None,
    since: str | None,
    until: str | None,
    text: str | None,
    limit: int,
    offset: int,
    cursor: str | None,
    *,
    service_fn: Callable[[Request], AdminControlCenterService],
    render: Callable[..., HTMLResponse],
    project_not_found: Callable[[KeyError], None],
) -> HTMLResponse:
    try:
        model = await service_fn(request).events_page(
            project,
            entity_id=entity_id,
            entity_type=entity_type,
            event_type=event_type,
            trace_id=trace_id,
            since=since,
            until=until,
            text=text,
            limit=limit,
            offset=offset,
            cursor=cursor,
        )
    except KeyError as exc:
        project_not_found(exc)
    return render(request, "events", model)


# START_FUNCTION_CONTRACT
# name: admin_logs_impl
# purpose: Render cross-project bounded Logs with explicit filters and HTMX
#          fragment behavior.
# inputs: request, project list, log filters/cursors and rendering callbacks.
# returns: Full-shell or fragment HTMLResponse.
# side_effects: Bounded Hub log reads.
# emitted_logs: Hub-owned log read logs.
# error_behavior: Unknown project filters use 404; partial results remain visible.
# END_FUNCTION_CONTRACT
async def admin_logs_impl(
    request: Request,
    project: list[str] | None,
    contains: str | None,
    level: str | None,
    source: str | None,
    worker: str | None,
    packet: str | None,
    run: str | None,
    stage: str | None,
    trace_id: str | None,
    regex: str | None,
    since: str | None,
    until: str | None,
    tail: int,
    cursor: str | None,
    follow: bool,
    wrap: bool,
    *,
    service_fn: Callable[[Request], AdminControlCenterService],
    render: Callable[..., HTMLResponse],
    render_fragment: Callable[..., HTMLResponse],
    project_not_found: Callable[[KeyError], None],
) -> HTMLResponse:
    try:
        model = await service_fn(request).logs_page(
            project,
            source=source,
            worker=worker,
            packet=packet,
            run=run,
            stage=stage,
            contains=contains,
            level=level,
            trace_id=trace_id,
            regex=regex,
            since=since,
            until=until,
            tail=tail,
            cursor=cursor,
            follow=follow,
            wrap=wrap,
        )
    except KeyError as exc:
        project_not_found(exc)
    if request.headers.get("HX-Request", "").casefold() == "true":
        return render_fragment(request, "logs", model)
    return render(request, "logs", model)


# START_FUNCTION_CONTRACT
# name: admin_search_impl
# purpose: Render cross-project canonical search results and project-aware
#          entity links.
# inputs: request, query, optional project selector and callbacks.
# returns: HTMLResponse.
# side_effects: Bounded Hub search reads.
# emitted_logs: Hub-owned search read logs.
# error_behavior: Unknown project filters use 404; isolated errors remain visible.
# END_FUNCTION_CONTRACT
async def admin_search_impl(
    request: Request,
    q: str,
    project: str | None,
    *,
    service_fn: Callable[[Request], AdminControlCenterService],
    render: Callable[..., HTMLResponse],
    project_not_found: Callable[[KeyError], None],
) -> HTMLResponse:
    try:
        model = await service_fn(request).search_page(q, project)
    except KeyError as exc:
        project_not_found(exc)
    return render(request, "search", model)


# END_BLOCK_GLOBAL_EXPLORERS
