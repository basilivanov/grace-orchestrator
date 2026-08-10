# Review 011 — Admin Control Center Stage 05

Status: CHANGES REQUIRED

Original implementation reviewed: `a6063d858ee402865b3f2cdb7908f94830e04728`.
Latest resubmission reviewed: `9bb11eca1b9dd32fa0a24c77c420af77444e8684`.

The latest resubmission correctly closes most of the previous review:

- Events and Logs now expose filter-preserving opaque continuation links and do not mix the rendered cursor with an `offset` query parameter.
- `source=all` is now treated as a no-filter sentinel and source aliases map to project-local stream/source names.
- Project and packet Git views now expose changed-file selectors and pass the exact selected path to bounded Stage 02 diff/stat reads.
- OpenAPI execution now supports declared scalar path/query parameters, safely quotes path values, rejects missing/undeclared selectors, and keeps mutations/non-discovered browser paths disabled.

Two Stage 05 blockers remain.

## Required fixes

### 1. Follow polling swaps the wrong HTMX fragment and duplicates the Logs UI

The Logs viewer now has real polling markup:

```html
hx-get="..."
hx-trigger="every 5s"
hx-target="#bounded-log-viewer"
hx-swap="outerHTML"
```

However, an HX request to `/admin/logs` or `/admin/p/{project}/logs` is handled with:

```python
return _render_fragment(request, "logs", model)
```

and `_render_fragment(..., "logs", ...)` renders the entire `control/_logs.html` template. That response contains the page heading, filter form, continuation UI **and** `#bounded-log-viewer`.

HTMX therefore replaces only `#bounded-log-viewer` with the entire Logs fragment. After the first poll the page gains another heading/form/continuation block before the new viewer; repeated polls keep adding duplicate Logs UI.

The browser acceptance test does not exercise the actual HTMX response. It manually performs:

```javascript
viewer.outerHTML = viewer.outerHTML;
```

so it proves the scroll-restoration helper only, not that real Follow polling swaps a correct fragment.

Required:

- make the follow request return/select exactly the viewer fragment being swapped, for example with a dedicated `_logs_viewer.html` partial or an equivalent `hx-select`/target arrangement;
- preserve project/filter/tail/follow/wrap state;
- keep one and only one Logs heading/filter form/viewer after repeated polls;
- preserve away-from-bottom scroll position and only follow the bottom when the operator was already at the bottom;
- extend the browser test to exercise at least one real HTMX poll/response (or the exact production fragment endpoint), and assert there is still exactly one log filter form and one bounded viewer after the swap.

### 2. OpenAPI discovered-path validation still permits cross-origin network-path references

`_openapi_operations()` currently accepts any path string for which:

```python
raw_path.startswith("/")
```

That includes a network-path reference such as:

```text
//example.invalid/collect
```

The selected path is later passed unchanged to the project client. `ProjectClient.request_json()` also only checks `path.startswith("/")` and sends the value through an `httpx.AsyncClient` configured with the selected project's `base_url` and project API credential headers.

For HTTP-backed projects, a `//host/path` reference can resolve with a different authority instead of remaining on the selected project's origin. That breaks the Stage 05 requirement that the API explorer is not an arbitrary URL fetcher and can also risk forwarding `x-grace-api-token` / `x-grace-api-password` to another host.

Required:

- reject OpenAPI executable path templates that are not strict same-origin path components; at minimum reject `//...`, schemes/authorities, fragments and query-bearing path templates before they enter the executable allowlist;
- preferably harden the common project-client boundary as well so a project-local request can never change authority through a network-path reference;
- keep ordinary single-leading-slash paths and safely substituted path parameters working;
- add a deterministic transport-level regression test with a synthetic discovered `//other-host/...` GET (or equivalent) proving no request is issued to a different authority and no project credential header can be forwarded there;
- retain the existing non-discovered-path and mutation-disabled tests.

## Scope

Do not start Task 012 / Stage 06. No further changes are requested to the already-fixed Events/Logs continuation, source-all semantics, Git selector or ordinary parameterized OpenAPI GET behavior unless required by the two fixes above.

Re-run the focused Stage 05 acceptance tests plus Task 007–010 isolation/read/aggregation/UI regressions and relevant Admin tests. Also run targeted Ruff, `py_compile`, changed/new-file GRACE lint and `git diff --check`.

Update the existing:

`docs/work/agent_exchange/outbox/011_RESUBMISSION.md`

with the latest fix commit SHA, real Follow fragment/browser proof, same-origin OpenAPI transport proof and concise check results.

Do not start Task 012 until reviewer returns `ACCEPT 011`.
