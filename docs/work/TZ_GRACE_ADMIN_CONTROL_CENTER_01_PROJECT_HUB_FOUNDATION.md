# TZ 01 — Project Hub foundation and isolation

Depends on:

- `TZ_GRACE_ADMIN_CONTROL_CENTER_MASTER.md`
- current single-project Admin/ProjectConfig behavior on `main`

## Objective

Introduce the multi-project backend foundation without rebuilding the existing Admin UI yet.

At the end of this stage the process can discover multiple projects, build immutable project contexts, communicate with each project GRACE API concurrently, expose a Hub project/health JSON API and remain correct when one project is unavailable.

No cross-project event/log UI in this stage.

## 1. Project Registry

Implement a central registry configuration owned by the Admin Hub.

Recommended default location/configurable equivalent:

```text
/etc/grace/projects.yaml
```

A repo/dev-local override may be supported for tests/development.

Schema:

```yaml
projects:
  - key: astro
    name: SolarSage Astro
    enabled: true
    unix_user: solarsage
    project_root: /srv/solarsage
    api_url: http://127.0.0.1:8142
    description: optional
    tags: [production]
```

Support either `api_url` or a Unix-socket transport if the existing HTTP client stack can support it cleanly.

Required validation:

- unique non-empty project key;
- safe key pattern suitable for URL path usage;
- non-empty project root identity;
- exactly one usable API transport;
- duplicate key is configuration error, never last-one-wins;
- disabled projects remain listable but are not queried by default fan-out;
- do not store API passwords/tokens in DTOs returned to the browser.

## 2. Immutable ProjectContext

Add an immutable dataclass/model such as:

```python
@dataclass(frozen=True)
class ProjectContext:
    key: str
    name: str
    enabled: bool
    unix_user: str | None
    project_root: Path
    api_url: str | None
    api_socket: Path | None
    description: str
    tags: tuple[str, ...]
```

Request handling and services must explicitly receive a context/key.

Forbidden:

- changing `GRACE_PROJECT_ROOT` per request;
- rebinding global SQLAlchemy DB to selected project;
- changing module-global `_project`, `_svc`, `settings.target_repo_root`, etc. as project selector state;
- a global mutable `current_project`.

## 3. ProjectClient

Implement a reusable client for one project runtime.

Responsibilities:

- GET/POST project-local GRACE API paths;
- bounded connect/read timeout;
- optional Unix-socket support if configured;
- JSON decoding and typed error normalization;
- propagate project key in returned Hub DTOs;
- never silently retry mutations;
- allow bounded retry only for idempotent GET if useful;
- expose health/openapi helpers for later stages.

Normalized project error example:

```json
{
  "project_key": "astro",
  "ok": false,
  "error_class": "connect_error",
  "error": "...",
  "last_attempt_at": "..."
}
```

Never throw one project connection exception through an ALL PROJECTS response.

## 4. AdminProjectService / Hub service

Add a Hub composition service. It may be named differently but must own project fan-out, not routers/templates.

Required methods conceptually:

```text
list_projects()
get_project(key)
get_project_health(key)
get_projects_health()
```

Fan-out must run concurrently with bounded concurrency/timeouts. Do not query projects sequentially when building `/admin`.

## 5. Project-local identity check

The Hub registry and project-local runtime can disagree. Add an identity/readiness response or consume existing config/health data so the Hub can show:

```text
registry key/name/root
runtime project key/name
runtime target repo root
runtime code SHA/version
```

Do not automatically mutate registry values from remote responses.

If a registry project points to a runtime whose identity obviously mismatches, mark it degraded/misconfigured.

## 6. Hub API

Add a separate central namespace; do not overload project-local `/api/admin/*` contracts.

Minimum:

```text
GET /api/admin-hub/projects
GET /api/admin-hub/projects/{project_key}
GET /api/admin-hub/projects/{project_key}/health
GET /api/admin-hub/health
```

Suggested project list DTO:

```json
{
  "projects": [
    {
      "key": "astro",
      "name": "SolarSage Astro",
      "enabled": true,
      "status": "online|degraded|offline|disabled",
      "unix_user": "solarsage",
      "project_root": "/srv/solarsage",
      "api_endpoint": "masked/display-safe",
      "health": {},
      "error": null
    }
  ],
  "fetched_at": "..."
}
```

## 7. Backward compatibility

Existing `/admin` and `/api/admin/*` single-project functionality must continue to work during this stage.

Do not force all current AdminAggregationService callers to become multi-project by swapping the global DB. The Hub is a new aggregation layer above project-local APIs.

## 8. Timeouts and resilience

Use explicitly configured or sensible bounded defaults. Cross-project overview must not wait tens of seconds for one dead project.

Tests should make timing deterministic rather than asserting fragile wall-clock values.

Health DTO should distinguish at least:

```text
online
api_offline
timeout
malformed_response
identity_mismatch
disabled
```

## 9. Tests

Required minimum:

1. registry parses two valid projects;
2. duplicate project key fails configuration;
3. invalid key/path/transport configuration fails clearly;
4. disabled project is listed without remote request by default;
5. two concurrent requests resolve different immutable contexts with no leakage;
6. one project timeout/offline does not break another project response;
7. cross-project fan-out is concurrent, not serial;
8. project identity mismatch is degraded, not silently accepted;
9. no secret transport credentials appear in browser DTO;
10. existing single-project Admin API tests still pass.

Use at least two fake/test project APIs with different identity values. Do not satisfy the isolation test by mocking both to one global settings object.

## 10. Acceptance

Stage 01 is complete when:

- the Hub lists at least two independent projects;
- requests carry explicit project context;
- there is no process-global project switching;
- one project can be offline without breaking Hub health/list;
- existing single-project Admin remains functional.

Do not implement global events/logs/files or major UI redesign in this stage.
