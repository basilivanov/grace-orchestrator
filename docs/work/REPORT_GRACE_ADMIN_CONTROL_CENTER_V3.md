# GRACE Admin Control Center v3 — Stage 07 Final Integration Report

## Implementation SHAs

- Stage 07 final integration and acceptance: `2518202c909d217d6c7bf93dc563e43b3c23a1c7`
- Stage 06 control foundation: `af2e5a6146a8ff46fa9e45368c0607905890a11d`, review closure `1d68960ce78982cd5c30df6e04a9df0bbd8ca7d8`
- Stage 05 explorer foundation/review closure: `a6063d858ee402865b3f2cdb7908f94830e04728`, `9bb11eca1b9dd32fa0a24c77c420af77444e8684`, `3ef3f04058b884d504c4ad9814796d520e174bc5`

## Architecture and topology

The Hub owns an immutable `ProjectRegistry` and routes every read/control by
explicit project key through the production `ProjectClient` boundary. It does
not switch process-global settings, open another project's SQLite database, or
read another project's filesystem directly.

The Stage 07 fixture starts two independent project APIs (`alpha` and `beta`),
each with its own project root, SQLite database, state/worktree/run/log roots,
real Git repository and loopback API process. Both deliberately contain
`pkt-shared-stage07`; concurrent reads prove that the same ID resolves to the
correct project data. Controls, filesystem reads, Git reads and caches remain
project-local. The browser fixture adds an intentionally unreachable `offline`
project to prove partial health behavior.

The supported registry shape is:

```yaml
projects:
  - key: alpha
    name: Alpha
    enabled: true
    unix_user: grace-alpha
    project_root: /srv/grace/alpha
    api_url: http://127.0.0.1:8101
  - key: beta
    name: Beta
    enabled: true
    unix_user: grace-beta
    project_root: /srv/grace/beta
    api_socket: /run/grace/beta.sock
```

Each entry uses one transport (`api_url` or `api_socket`), a unique key and an
absolute project root. Operator deployment and troubleshooting guidance is in
[`docs/grace/RUNBOOK_SERVER_DEPLOY.md`](../grace/RUNBOOK_SERVER_DEPLOY.md).

## Read surface, journeys and dynamic API

The rich fixture covers Feature → Wave → Packet → PacketRun → StageRun,
sessions, full event payloads, result JSON, stdout/stderr/agent logs, parsed
and raw evidence, Markdown/text/image/binary artifacts, leases, waits,
stale-base metadata, worktrees and Git diff/stat/SHAs. The acceptance suite
checks these through project API and Hub/UI surfaces only.

Journeys A–E are covered by the Stage 07 tests:

- healthy parallel work and merged result;
- blocked failure diagnosis with failed stage, stderr, raw event and evidence;
- stale-base diagnosis and integration recheck/Git view;
- cross-project Events/Logs/Search filtering and deep links;
- confirmed project-local retry with refreshed state and canonical audit event.

The project API's synthetic `/api/debug/version` GET is discovered from
`/openapi.json` and executed through the bounded API Explorer without a
hard-coded frontend route. OpenAPI responses use a five-second,
project-keyed cache; failures are not cached.

## Security and boundedness

Stage 07 proves traversal, absolute-path, symlink-escape, cross-project-root,
`.env`, private-key and credential-pattern denial. Filesystem and artifact
previews, log tails, binary reads and large Git output are bounded. Git refs,
paths and options remain validated by the project-local Git reader. Controls
use capability/state checks, authorization, confirmation, fencing and audit;
unknown mutation outcomes are never automatically retried. The system log
reader now uses the named project `logs` root rather than a global `/tmp` glob.

## Review 013 fix-up

The final review fix-up inventories every live mutating `/api/admin/*` route,
including the legacy packet, feature and lifecycle aliases. Read-only tokens
are rejected by the same project-local Stage 06 control gate before any state
or audit mutation. Confirmed retry, cancel, archive and unarchive aliases
delegate to the canonical dispatcher; destructive or unsupported legacy
aliases remain explicitly unavailable with requested/failed audit records.

Global Logs now reports a bounded row count separately from the filesystem byte
count. The Hub keeps a stable internal line index while merging bounded tails,
so opaque continuation cursors terminate at the reachable row domain without
duplicates, skips or phantom empty pages.

The Chromium acceptance path performs a real production HTMX poll, confirms
the selected project, deep link and single viewer after the swap, checks
follow-off/follow-on scroll behavior, and executes a typed confirmation against
a fixture packet before asserting its state and canonical audit timeline.

## Checks and results

- Stage 07 integration/browser acceptance: **6 passed**, 92 SQLAlchemy deprecation warnings.
- Admin/Hub/API/UI regression group: **120 passed, 2 skipped**.
- Diagnostics, migrations/schema, supervisor/maintenance and related runtime regressions: **106 passed, 14 skipped**.
- Packet/worker API and W07 fencing/retry regressions: **42 passed**.
- Parallel/merge/worker/supervisor and self-starting frontend regression group: **105 passed, 14 skipped**.
- Ruff on all changed Python files: **PASS**.
- `python3 -m py_compile` on all changed Python files: **PASS**.
- `git diff --check`: **PASS**.
- Applicable GRACE lint: new Stage 07 modules and changed router pass. The existing `admin_control_center.py` still reports baseline `GRC005` because it is 1653 lines; it was not split as part of Stage 07.
- Review 013 security/log/browser regressions: **3 passed**, 99 SQLAlchemy deprecation warnings.

The older deployment-oriented UI tests that assume an independently launched
server at `GRACE_BASE_URL` (default `127.0.0.1:8042`) were not counted in the
pass totals when that server was absent; they stopped at connection refusal.
The deterministic Stage 07 browser harness starts its own real Hub and
project APIs and passed desktop/mobile/deeplink/polling checks.
