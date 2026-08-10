# Review 010 — Admin Control Center Stage 04

Status: CHANGES REQUIRED

Implementation commit reviewed: `3f3645aef49f3f58cea9c229f8edc0e93ea24343`.

The Stage 04 direction is broadly correct: the Jinja2/HTMX shell is project-aware, project selection remains URL-scoped, the same packet ID is isolated by project, packet Blocking/WAIT/pipeline/sessions/system views are present, disabled/offline cards are isolated, and no Stage 05 explorer implementation was started. However four Stage 04 acceptance gaps remain.

## Required fixes

### 1. `run_id` is preserved in URLs but does not propagate into run-dependent views

Task 010 acceptance explicitly requires that selecting a run changes run-dependent context while retaining project/packet identity.

Current `_packet_page()` only loads `runs` / resolves `selected_run` inside:

```python
if tab == "runs":
    ...
```

For `timeline`, `pipeline`, `stages`, `spec`, `diagnostics`, etc., an incoming `run_id` is merely carried through the template URL. It does not change the data read, stage set, timeline, selected run metadata, or any run-dependent view.

The tab navigation therefore gives the appearance of preserved run context without actually applying it.

Required:

- resolve the selected run independently of the current tab when `run_id` is present;
- apply that run context to the run-dependent Stage 04 views that can be scoped with existing project-local data (at minimum Stages/Pipeline and any Timeline rows that can be associated with the selected run);
- preserve explicit `project_key` + `packet_id` + `run_id` in links/polling;
- do not cross-wire a run from another packet/project;
- add an acceptance test with two distinguishable runs proving that selecting run B changes a dependent tab/view, not only the Runs table highlight.

Stage 02 raw data already exposes `run_id` on StageRun rows, so run scoping does not require direct DB access from the Hub/UI.

### 2. Packet Timeline is missing the required Stage 04 filters

TZ04 requires Timeline filters for event/component, run/stage, trace ID and text. The current packet route only accepts `tab`, `run_id` and `stage_id`, while `_packet_page()` always reads:

```text
/api/admin/packet/{packet_id}/timeline?limit=200&offset=0
```

and `_packet.html` renders the returned rows with no timeline filter controls or filtering semantics.

Required:

- add explicit packet-timeline filter inputs/query parameters for event/component, run/stage, trace ID and text (names may differ if clear and documented);
- preserve those filters across HTMX polling and relevant packet URLs;
- keep unknown event types visible when they match the filters;
- retain original timestamps, trace IDs and full payload drill-down;
- add deterministic acceptance coverage showing filters narrow the timeline without losing project/packet identity.

A bounded UI/service-side filter over the canonical timeline response is acceptable if the project-local endpoint does not natively support every filter; do not introduce direct DB reads in the Hub UI.

### 3. Dashboard `Blocked` semantics are wrong for canonical blocked variants

`DiagnosticsService` returns `packets_by_state` for **every** `PacketState`, including zero-valued `blocked`, `blocked_recoverable` and `blocked_final` keys.

`_matches_dashboard_filter()` calls:

```python
_count_state(states, "blocked", "BLOCKED", "blocked_recoverable", ...)
```

but `_count_state()` returns immediately on the first present candidate. Because the canonical diagnostics mapping always contains `blocked`, a project with:

```text
blocked = 0
blocked_final = 1
```

is treated as not blocked. The project-card state grid likewise displays only the generic `BLOCKED` count, so terminal/recoverable blocked work can be visually hidden.

Required:

- make the dashboard `Blocked` filter treat `blocked`, `blocked_recoverable` and `blocked_final` as the blocked family (sum/any-positive semantics, not first-key semantics);
- make the card's Blocked count/summary reflect the blocked family rather than only deprecated generic `blocked`;
- keep FAILED separate;
- add a test where generic `blocked` is zero but `blocked_final` or `blocked_recoverable` is positive and verify the card appears under `filter=blocked` with a visible non-zero blocked count.

### 4. Mobile acceptance is not actually proven at a mobile viewport

Task 010 requires a mobile smoke at the repository's existing frontend acceptance viewport(s), around 390 px. The added `test_control_center_mobile_css_is_single_column()` only reads the CSS file as text and asserts that a media-query string exists.

That proves a rule was written, not that the rendered Control Center is usable at a mobile viewport (no overflow, selector/navigation/tree/detail collapse, etc.). The repository already defines mobile frontend acceptance viewports including `390x844` (and `360x780`).

Required:

- add a real browser/layout smoke using the repository's existing frontend/browser acceptance approach where available, at least at ~390x844;
- verify the Control Center page renders without forced desktop multi-column overflow and that key navigation/project selector/content remain usable/visible;
- if the local CI/browser dependency is intentionally unavailable in one environment, keep a deterministic browser test in the suite and report the environment skip explicitly rather than replacing it with a CSS-string assertion.

## Scope

Do not start Task 011 / Stage 05. Fix only these Stage 04 UI/read-model/acceptance issues and directly exposed regressions.

Re-run the focused Stage 04 acceptance tests plus Task 007–009 isolation/read/aggregation regressions and relevant Admin UI tests, then Ruff, `py_compile`, GRACE lint and `git diff --check`.

Then create/update:

`docs/work/agent_exchange/outbox/010_RESUBMISSION.md`

Include the fix commit SHA, run-context behavior, timeline filtering, blocked-family semantics, mobile browser-smoke result and concise checks.
