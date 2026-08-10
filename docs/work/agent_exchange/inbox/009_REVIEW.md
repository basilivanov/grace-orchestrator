# Review 009 — Admin Control Center Stage 03

Status: CHANGES REQUIRED

Implementation commit reviewed: `635da6421a6aff71ef577bfe99996aa24fd706a8`.

The Stage 03 architecture is broadly aligned with the task: fan-out/merge logic lives in `AdminCrossProjectService`, project-local APIs are used through explicit project contexts, per-project errors are isolated, rows preserve project attribution and source timestamps, and the required Hub JSON routes are present. However several Stage 03 contract errors remain.

## Required fixes

### 1. Event/log continuation incorrectly treats a per-project cap as a global cap

The service documents and implements bounded prefixes per project:

- events: `_MAX_EVENTS_PER_PROJECT = 1000`;
- logs: `_MAX_LOG_LINES_PER_PROJECT = 5000`.

But continuation stops using those constants as if they were global merged limits.

For events, `bounded_total = min(known_total, _MAX_EVENTS_PER_PROJECT)` and the error-path `has_more` check also requires `page_offset + page_limit < _MAX_EVENTS_PER_PROJECT`.

For logs, `next_offset` is only produced while `page_offset + page_limit < _MAX_LOG_LINES_PER_PROJECT`.

With two healthy projects, each contributing its allowed prefix, the merged bounded domain can contain up to `2 * per_project_cap` rows (and generally `N * per_project_cap`). The current cursor can therefore terminate early and make valid rows from another project unreachable.

Required:

- make continuation math consistent with the documented **per-project** prefix strategy;
- for events, compute the accessible bounded total from per-project totals/prefixes (for example `sum(min(project_total, cap))` when totals are known), not `min(sum(totals), cap)`;
- for logs, do not impose one global 5000-row continuation ceiling when several projects each contribute a bounded tail;
- retain deterministic merged ordering and filter/project-bound cursors;
- add tests with at least two projects where the merged accessible domain exceeds one per-project cap, proving continuation does not stop early.

Do not replace this with an unbounded fetch.

### 2. Partial diagnostics can be counted as zero-valued data in aggregates

In `get_diagnostics()`, a project is appended to `snapshots` when diagnostics fails but health succeeds, because `system_health` makes the snapshot non-empty. `_aggregate_snapshots()` then treats missing packet/worker/run/lease fields as zero and includes that project in `projects_in_aggregate`.

That violates the Task 009/TZ03 requirement that aggregate counts are computed only when mathematically valid and that unavailable project data is not represented as healthy zeroes.

Required:

- keep the per-project health-only partial response visible if useful;
- exclude a project from count aggregates when its diagnostics payload is unavailable/malformed, or introduce field-specific validity/coverage that makes the aggregate mathematically correct;
- `projects_in_aggregate` must represent projects whose diagnostic counters actually contributed;
- add a test where project A diagnostics succeeds, project B diagnostics fails, but project B health succeeds. The aggregate must contain only A's diagnostic counts while coverage marks B partial rather than silently contributing zeros.

### 3. Project metadata search disappears when the project-local search endpoint fails

`search()` currently skips the whole project as soon as the remote `/api/admin/search` result is not `ok`, and only afterwards evaluates `_matches_project(q, context)`.

Project metadata is Hub/registry data and TZ03 explicitly requires search over **project-local canonical search plus project metadata**. A remote search failure should be reported in `errors`, but it should not prevent a matching project registry entry from being returned.

Required:

- evaluate/add matching project metadata independently of the project-local search success;
- keep the remote project search failure in `errors`;
- preserve the global result limit and canonical project-aware URL;
- add a test where the query matches a project's key/name/tag while that project's `/api/admin/search` is unavailable/malformed, and the project result is still returned.

### 4. Default overview omits disabled configured projects entirely

TZ03's project-card contract explicitly includes status `online/degraded/offline/disabled`. Stage 01 also established that disabled projects remain listable but are skipped by default remote fan-out.

`get_projects_overview()` calls `_select_contexts(None)`, which returns only `enabled_projects()`. Therefore the existing `_overview_for_disabled()` branch is never used for the normal all-project overview, and configured disabled projects disappear instead of being shown as disabled cards.

Required:

- default `/api/admin-hub/overview` should include configured disabled projects as local registry-backed cards;
- disabled projects must not receive remote requests;
- coverage/aggregate semantics must distinguish disabled from failed/offline rather than counting disabled as a remote failure;
- add an acceptance test with one enabled and one disabled project proving the disabled card is present and its client is never called.

## Scope

Do not start Task 010 / Stage 04. Fix only these Stage 03 aggregation/continuation/search/overview issues and any directly exposed regressions.

Re-run the focused Task 009 acceptance tests plus Task 007–008 regressions and the relevant Admin/Trace/Events/Diagnostics checks, then Ruff, `py_compile`, GRACE lint and `git diff --check`.

Then create/update:

`docs/work/agent_exchange/outbox/009_RESUBMISSION.md`

Include the fix commit SHA, the corrected continuation semantics, coverage/aggregate behavior and concise check results.