# ############################################################################
# AI_HEADER: admin_control_center_rendering — Control Center rendering helpers
# ROLE: Owns pure URL construction and template rendering primitives for the
#       Control Center facade. Route owners provide current facade callbacks.
# ############################################################################

# START_MODULE_CONTRACT
# purpose: Render Control Center shells/fragments and build explicit quoted
#          project/entity URLs without selecting or mutating project state.
# inputs: Requests, page models, templates and scalar URL selectors.
# returns: HTMLResponse or bounded URL/status strings.
# side_effects: None beyond Jinja template rendering.
# emitted_logs: None.
# error_behavior: Ordinary scalar inputs render deterministically; templates
#                 receive the same context keys as the historical router.
# END_MODULE_CONTRACT

# START_MODULE_MAP
# mapping:
#   - function: render
#   - function: render_fragment
#   - function: render_project_partial
#   - function: cc_url
#   - function: cc_query_url
#   - function: partial_url
#   - function: status_icon
# END_MODULE_MAP

from __future__ import annotations

from collections.abc import Callable
from typing import Any
from urllib.parse import quote, urlencode

from fastapi import Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates

from grace_control.core.structured_logger import GraceLogger

_log = GraceLogger("admin_control_center_rendering")


# START_BLOCK_RENDERING
# START_FUNCTION_CONTRACT
# name: render
# purpose: Render the common persistent Control Center shell around one page.
# inputs: request, page name, model, current URL helper and status helper.
# returns: HTMLResponse.
# side_effects: None.
# emitted_logs: None.
# error_behavior: Never raises for valid template models.
# END_FUNCTION_CONTRACT
def render(
    request: Request,
    page: str,
    model: dict[str, Any],
    *,
    templates: Jinja2Templates,
    cc_url: Callable[..., str],
    status_icon: Callable[[Any], str],
) -> HTMLResponse:
    context = {
        "request": request,
        "page": page,
        "current_project": model.get("current_project") or model.get("project"),
        "projects": model.get("projects", []),
        "cc_url": cc_url,
        "cc_status_icon": status_icon,
    }
    context.update(model)
    return templates.TemplateResponse(request, "control_center.html", context)


# START_FUNCTION_CONTRACT
# name: render_fragment
# purpose: Render one explorer fragment for bounded HTMX polling.
# inputs: request, fragment template name, model and current URL helpers.
# returns: HTMLResponse containing the requested explorer fragment.
# side_effects: None.
# emitted_logs: None.
# error_behavior: Never raises for valid template models.
# END_FUNCTION_CONTRACT
def render_fragment(
    request: Request,
    template_name: str,
    model: dict[str, Any],
    *,
    templates: Jinja2Templates,
    cc_url: Callable[..., str],
    cc_query_url: Callable[..., str],
    status_icon: Callable[[Any], str],
) -> HTMLResponse:
    context = {
        "request": request,
        "cc_url": cc_url,
        "cc_query_url": cc_query_url,
        "cc_status_icon": status_icon,
    }
    context.update(model)
    return templates.TemplateResponse(request, f"control/_{template_name}.html", context)


# START_FUNCTION_CONTRACT
# name: render_project_partial
# purpose: Render only the selected project content for HTMX polling.
# inputs: request, project model and current URL/status helpers.
# returns: HTMLResponse containing one project-content section.
# side_effects: None.
# emitted_logs: None.
# error_behavior: Never raises for valid template models.
# END_FUNCTION_CONTRACT
def render_project_partial(
    request: Request,
    model: dict[str, Any],
    *,
    templates: Jinja2Templates,
    cc_url: Callable[..., str],
    status_icon: Callable[[Any], str],
) -> HTMLResponse:
    context = {
        "request": request,
        "cc_url": cc_url,
        "cc_status_icon": status_icon,
    }
    context.update(model)
    return templates.TemplateResponse(request, "control/_project_content.html", context)


# START_FUNCTION_CONTRACT
# name: cc_url
# purpose: Build canonical project-aware URLs with safely quoted selectors.
# inputs: project key, optional entity kind/id and query parameters.
# returns: URL string.
# side_effects: None.
# emitted_logs: None.
# error_behavior: Never raises for ordinary string values.
# END_FUNCTION_CONTRACT
def cc_url(
    project_key: str | None = None,
    kind: str = "",
    entity_id: str = "",
    **params: Any,
) -> str:
    if project_key:
        path = f"/admin/p/{quote(str(project_key), safe='-_.~')}"
        if kind:
            path += f"/{quote(str(kind), safe='-_.~')}"
            if entity_id:
                path += f"/{quote(str(entity_id), safe='-_.~')}"
    else:
        path = "/admin"
    query = [(key, str(value)) for key, value in params.items() if value not in (None, "", False)]
    return f"{path}?{urlencode(query)}" if query else path


# START_FUNCTION_CONTRACT
# name: cc_query_url
# purpose: Build a bounded continuation/polling URL from an internal path.
# inputs: router-owned relative path and scalar query values.
# returns: URL with encoded non-empty query parameters.
# side_effects: None.
# emitted_logs: None.
# error_behavior: Never raises for ordinary string/scalar values.
# END_FUNCTION_CONTRACT
def cc_query_url(path: str, **params: Any) -> str:
    query = [(key, str(value)) for key, value in params.items() if value not in (None, "", False)]
    return f"{path}?{urlencode(query)}" if query else path


# START_FUNCTION_CONTRACT
# name: partial_url
# purpose: Build an explicit project/entity/tab URL for HTMX polling.
# inputs: project/entity selectors and optional tab/run/stage/explorer values.
# returns: Absolute project partial URL.
# side_effects: None.
# emitted_logs: None.
# error_behavior: Never raises for ordinary string values.
# END_FUNCTION_CONTRACT
def partial_url(
    project_key: str,
    entity_type: str | None = None,
    entity_id: str | None = None,
    tab: str | None = None,
    run_id: str | None = None,
    stage_id: str | None = None,
    event: str | None = None,
    component: str | None = None,
    run_stage: str | None = None,
    trace_id: str | None = None,
    text: str | None = None,
    source: str | None = None,
    tail: int | None = None,
    artifact_path: str | None = None,
    root: str | None = None,
    file_path: str | None = None,
    ref: str | None = None,
    file: str | None = None,
    git_path: str | None = None,
) -> str:
    path = f"/admin/p/{quote(str(project_key), safe='-_.~')}/_partial/content"
    params = {
        "entity_type": entity_type,
        "entity_id": entity_id,
        "tab": tab or "overview",
        "run_id": run_id,
        "stage_id": stage_id,
        "event": event,
        "component": component,
        "run_stage": run_stage,
        "trace_id": trace_id,
        "text": text,
        "source": source,
        "tail": tail,
        "artifact_path": artifact_path,
        "root": root,
        "path": file_path,
        "ref": ref,
        "file": file,
        "git_path": git_path,
    }
    query = [(key, str(value)) for key, value in params.items() if value not in (None, "")]
    return f"{path}?{urlencode(query)}"


# START_FUNCTION_CONTRACT
# name: status_icon
# purpose: Return a textual/icon status semantic independent of color.
# inputs: status string.
# returns: Human-readable status marker.
# side_effects: None.
# emitted_logs: None.
# error_behavior: Unknown values return an explicit uppercase marker.
# END_FUNCTION_CONTRACT
def status_icon(status: Any) -> str:
    value = str(status or "unknown").casefold()
    return {
        "online": "● ONLINE",
        "running": "▶ RUNNING",
        "degraded": "▲ DEGRADED",
        "offline": "■ OFFLINE",
        "disabled": "○ DISABLED",
        "idle": "○ IDLE",
    }.get(value, f"? {value.upper()}")


# END_BLOCK_RENDERING
