# Review 011 — Admin Control Center Stage 05

Status: CHANGES REQUIRED

Implementation commit reviewed: `a6063d858ee402865b3f2cdb7908f94830e04728`.

The Stage 05 implementation has a solid safety direction: project scoping remains explicit, Files uses advertised roots plus Stage 02 typed errors, artifact HTML is escaped instead of executed, lease secrets are masked/fingerprinted, Git reads stay behind the project-local API, and OpenAPI execution is limited to discovered GET path templates. However four functional acceptance gaps remain before Stage 05 can be accepted.

## Required fixes

### 1. Events/Logs continuation exists in the service but is not navigable from the UI

The Hub correctly returns bounded continuation metadata and `next_cursor` for both events and logs. The Stage 05 UI does not actually expose that continuation.

`_events.html` only renders:

```jinja2
{% if next_cursor %}<p class="small muted">More bounded results are available below this page.</p>{% endif %}
```

There is no Next/cursor link or form control, so an operator cannot move beyond the first bounded page.

`_logs.html` similarly receives `next_cursor` but exposes no continuation action at all.

This violates the TZ05 page/cursor requirement and the bounded-data design: bounded reads are only useful if the remainder is reachable without SSH/manual cursor editing.

Required:

- expose deterministic Next/continuation controls for global Events and Logs;
- preserve project selection and every active filter when advancing the cursor;
- do not mix `offset` and cursor in a way that can duplicate/skip rows;
- keep cursor values opaque in the UI;
- add acceptance coverage with enough synthetic rows to force a second page and prove a row beyond page 1 is reachable through the rendered continuation link while project/filter context is preserved.

### 2. Log source/follow semantics are incomplete

There are two separate issues here.

#### `source=all` currently filters out real rows

The Logs form submits `source=all`. `query_logs()` passes that value into `_log_matches()`, which performs exact source equality for every non-empty `source` value. A normal row whose source is `stderr`, `api`, `worker`, etc. therefore does **not** match `all`.

So submitting the default/All source option can turn a populated log view into an empty one.

Required:

- treat `None`, empty and `all` as the no-source-filter sentinel;
- map the UI source taxonomy to actual project-local source/stream semantics instead of relying on accidental exact-string matches;
- add a regression test proving `source=all` retains heterogeneous rows and a concrete source selection narrows them.

#### `follow=on` is only a checkbox/state label; it does not follow

`_logs.html` has no HTMX polling/follow request. The shell JS only preserves `scrollTop` during an HTMX swap if one happens; it does not create a log refresh loop. Therefore `follow=true` does not cause new log data to be fetched.

Required:

- implement real bounded HTMX log polling when Follow is on, preserving all filters/tail/project state;
- when Follow is off, do not auto-poll/force-scroll;
- when Follow is on but the operator has scrolled away from the bottom, polling must not force-scroll them back down;
- add the browser behavior test defined by TZ05. It may explicitly skip when Playwright/server is unavailable in the execution environment, but the deterministic browser test itself must exist; an HTML `data-follow="off"` assertion is not sufficient proof.

### 3. Git explorer has no usable file selector for bounded per-file diff

The service/router accept `path` and send it to Stage 02 `diff-stat`/`diff`, but `_git.html` renders `changed_files` as JSON and has no form/link that lets an operator select one changed file. The packet Git tab has the same issue.

TZ05 explicitly requires a safe diff viewer with a file selector.

Required:

- render changed files as selectable project-aware links/controls;
- selecting a file must preserve project/packet/ref context and request the bounded diff/stat for that exact path through Stage 02;
- show which file is selected and explicit truncation state;
- do not add arbitrary Git command input;
- add acceptance coverage proving a selected changed file is passed as the `path` selector and only its bounded diff is rendered.

### 4. OpenAPI GET execution does not support discovered path parameters

`_openapi_operations()` discovers and displays OpenAPI parameters, but `api_page()` only accepts the exact raw OpenAPI path string and a JSON object that is sent as **query parameters**:

```python
selected_path = str(path or "")
if selected_path not in get_paths:
    ...
params, params_error = _json_query_params(params_json)
...
result = await self._read(project_key, selected_path, params=params, ...)
```

For a normal discovered endpoint such as:

```text
/api/admin/packet/{packet_id}/detail
```

there is no way to supply `packet_id` as an OpenAPI path parameter. The client would request the literal `{packet_id}` template. The current synthetic acceptance endpoint has no parameters, so it does not prove the required editable-parameter behavior.

Required:

- derive executable parameter definitions from the selected discovered GET operation;
- support at least declared OpenAPI `path` and `query` parameters with bounded scalar values;
- safely URL-encode/substitute required path parameters into the already-discovered path template;
- reject missing required path parameters and undeclared/arbitrary execution selectors before any project request;
- continue to reject non-discovered paths and keep POST/PUT/PATCH/DELETE execution disabled;
- add a synthetic discovered GET such as `/api/items/{item_id}` with path + query parameters and prove execution reaches only the correctly substituted discovered route.

## Scope

Do not start Task 012 / Stage 06. Fix only these Stage 05 explorer/acceptance gaps and directly exposed regressions.

Re-run the focused Stage 05 acceptance tests plus Task 007–010 isolation/read/aggregation/UI regressions and relevant Admin tests. Also run Ruff, `py_compile`, GRACE lint for changed/new files and `git diff --check`.

Then create/update:

`docs/work/agent_exchange/outbox/011_RESUBMISSION.md`

Include the fix commit SHA, Events/Logs continuation proof, working source/follow semantics, Git file-selection proof, parameterized OpenAPI GET proof, browser test result/explicit environment skip, and concise regression/check results.

Do not start Task 012 until reviewer returns `ACCEPT 011`.
