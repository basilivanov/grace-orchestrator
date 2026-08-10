# TZ: GRACE Admin Control Center v3 — Multi-Project + Full Observability

Status: SOURCE OF TRUTH FOR NEW ADMIN CONTROL CENTER WORK

## 1. Goal

Build one operator-facing GRACE Admin Control Center for all configured projects on one server.

The operator must be able to drill down without using SQLite, SSH, `tail`, `cat`, direct `.grace/state` browsing, or manual Git commands for normal diagnostics:

```text
Server
  -> Project
    -> Feature
      -> Wave
        -> Packet
          -> Run
            -> Stage
              -> Session
              -> Events
              -> Logs
              -> Evidence
              -> Artifacts
              -> Files
```

Core product rule:

> If GRACE can expose data through its API, or the project-local GRACE runtime can safely read that operational data from disk/Git, the Admin Control Center must make it inspectable.

This is an extension of the existing Admin v2 / HTMX console and existing Trace / Events / Diagnostics APIs. Do not rewrite working observability from scratch.

## 2. Existing surfaces to reuse

Keep and compose the existing architecture where possible:

- `src/grace_control/api/routers/admin_ui.py` — server-rendered Jinja2 + HTMX operator console;
- `src/grace_control/api/routers/admin.py` — `/api/admin/*` read/control surface;
- `src/grace_control/services/admin_aggregation_service.py` — admin DTO composition;
- Trace API — packet/feature/run/search read models;
- `/api/events` — filtered/paginated event log;
- `/api/diagnostics/state` — runtime diagnostics, including parallel execution state;
- existing artifacts/log readers and maintenance services;
- `.grace/config.yaml` / `ProjectConfig` for project-local configuration.

Historical `TZ_ADMIN_*` specifications remain valid for already-shipped behavior unless this master explicitly supersedes them for multi-project behavior, isolation, filesystem safety, cross-project aggregation, or new Control Center UI.

## 3. Non-negotiable architecture

### 3.1 One Hub, project-local runtimes

Recommended topology:

```text
Browser
   |
   v
GRACE Admin Hub
   |
   +---- Project A GRACE API ---- Project A DB/state/worktrees, Unix user A
   +---- Project B GRACE API ---- Project B DB/state/worktrees, Unix user B
   +---- Project C GRACE API ---- Project C DB/state/worktrees, Unix user C
```

The Hub is an aggregator/proxy/operator UI. It must not directly open another project's SQLite database and must not bypass Unix-user isolation to read another project's private runtime tree.

Project-local APIs are responsible for project-local DB, filesystem, Git and control operations.

### 3.2 Never switch projects through process-global state

Forbidden implementation patterns:

```python
os.environ["GRACE_PROJECT_ROOT"] = selected_project
settings.target_repo_root = selected_project
```

inside a request or any equivalent mutation of process-global settings.

Two requests for two different projects must be safe concurrently.

Use immutable/request-scoped `ProjectContext` and explicit `project_key` routing.

### 3.3 Fail isolated

One offline, malformed, slow or broken project must not break the whole Admin Hub.

Cross-project operations must return per-project errors and continue producing results from healthy projects.

### 3.4 Read model first, UI second

Do not make Jinja templates or browser JavaScript read SQLite/files/Git directly. Add/extend services and API contracts first, then consume them from the UI.

## 4. Required information model

The final Control Center must expose, where available:

### Projects

- project key/name/description/tags;
- enabled/disabled;
- Unix user metadata (never credentials);
- project root identity;
- API/socket endpoint health;
- target branch and target HEAD;
- GRACE version/code SHA;
- supervisor/API/DB/worker health;
- effective runtime configuration;
- packet state counts;
- active leases and merge owner;
- latest event/error;
- state/worktree/evidence disk usage.

### Features / waves / packets

Preserve existing feature -> wave -> packet navigation and add:

- worker/model/executor;
- attempt/max_attempt;
- scope/conflict_keys/depends_on;
- elapsed time;
- wait reason;
- base SHA / integration base SHA;
- stale-base / integration recheck state;
- latest meaningful failure/recovery reason;
- aggregate duration/tokens/cost where available.

### Runs / stages / sessions

Expose:

- run metadata and complete `result_json`;
- prompt and command preview where persisted;
- evidence path metadata;
- StageRun lifecycle, model, worker, executor, tokens, cost, stdout/stderr/result/artifact paths;
- recovery parent/child chain and loop rounds;
- session tree where session support exists; graceful empty capability result when it does not.

### Events

Expose full event history, not only recent overview rows:

- timestamp;
- project;
- event_type;
- entity_type/entity_id;
- trace_id;
- component/reason;
- complete payload JSON in drill-down;
- filters/pagination/time range.

### Logs

Expose project-local operational logs where they exist:

- API;
- worker;
- supervisor;
- structured GRACE JSONL;
- packet/run agent/stdout/stderr;
- stage stdout/stderr;
- acceptance/browser/visual logs;
- merge/recheck/recovery logs.

Long logs require tail/cursor pagination. Do not load unbounded logs into memory or HTML.

### Evidence / artifacts / files

Expose parsed evidence and raw evidence, artifact trees and safe file previews. Project-local filesystem reading must be constrained to explicit operational roots and must defend against traversal/symlink escape/secrets/oversized reads.

### Git / worktrees

Expose target branch/HEAD/status/remote, packet/base/integration/merge commits, changed files, diff/stat, GRACE worktrees and their ownership/state/lease relationships.

### Parallel execution / leases

Expose ordinary packet leases, parallel leases, merge lease metadata, effective concurrency, conflict scope/keys, wait reasons and stale-base recheck state. Never expose full secret fencing tokens; use masked identity/fingerprint only.

### Raw/API Explorer

Every important entity needs a Raw view. In addition, each project must expose `/openapi.json` through the Hub and an API Explorer must make every discoverable API endpoint inspectable even before a dedicated pretty UI exists.

## 5. Navigation target

Project-scoped URLs:

```text
/admin/p/{project_key}
/admin/p/{project_key}/feature/{feature_id}
/admin/p/{project_key}/wave/{wave_id}
/admin/p/{project_key}/packet/{packet_id}
/admin/p/{project_key}/system
/admin/p/{project_key}/events
/admin/p/{project_key}/logs
/admin/p/{project_key}/files
/admin/p/{project_key}/api
```

Cross-project:

```text
/admin
/admin/projects
/admin/events
/admin/logs
/admin/search
```

Keep project selector visible globally.

## 6. Packet operator view

Packet detail is the primary debugging screen. Required tabs:

```text
Overview
Timeline
Pipeline
Spec
Runs
Stages
Sessions
Evidence
Logs
Artifacts
Files
Git
Diagnostics
Raw
```

For blocked/failed packets, the header must answer immediately:

- who/which component blocked it;
- why;
- failure class/stage;
- blocking issues;
- failed command/exit code;
- stderr tail;
- recommended next action.

READY/ACCEPTED packets with a typed wait reason must not look mysteriously stuck.

## 7. API Explorer completeness rule

The project API's `/openapi.json` is the fallback completeness mechanism.

The Hub must be able to show method/path/summary/parameters/request/response schema for every API path and execute allowed GET operations. Mutation execution is disabled by default and must pass through the control-action safety policy.

A newly added API path therefore becomes visible in Admin automatically even if no dedicated UI card has been implemented yet.

## 8. Filesystem safety rule

Never expose an arbitrary absolute-path reader.

Allowed read roots are project-local operational roots resolved by the project runtime, for example:

- configured state root;
- configured worktree root;
- PacketRun evidence directory;
- StageRun artifact/stdout/stderr/result paths;
- explicitly configured log roots;
- Git-tracked project files through Git (`ls-files`, `show`) rather than arbitrary raw root browsing.

Required defenses:

- canonical `realpath` containment;
- traversal rejection;
- symlink escape rejection;
- secret deny rules (`.env*`, private keys, credentials/secrets patterns, etc.);
- maximum read/tail/preview sizes;
- binary detection;
- timeouts;
- no `/etc`, arbitrary `/home`, or arbitrary absolute path access.

## 9. Controls

UI mutations must call domain/API operations, never edit DB rows or `rm -rf` directly.

Surface all actually implemented actions and clearly mark stubs/unavailable capabilities. Examples include retry/resume/stop/cancel/archive/unarchive/merge/cleanup and supervisor restart/reload actions where supported.

Destructive actions require explicit confirmation. Operator mutations must produce an audit Event with project/action/entity/actor/request/result metadata.

## 10. Performance rules

Overview pages must use summaries only. Do not recursively scan evidence/log/worktree trees for every card.

Heavy data loads lazily when its tab/explorer opens.

Events/logs/search/runs/large directories require pagination/tailing.

Cross-project fan-out must be concurrent with bounded per-project timeouts.

## 11. Security rules

- preserve existing authentication/authorization;
- project isolation is enforced by project-local runtime boundaries;
- validate project keys;
- mask secrets/config credentials;
- no arbitrary shell execution from API Explorer or Files UI;
- mutation CSRF/authorization rules must match existing auth model;
- output/read limits and content-type validation;
- admin Hub must not use arbitrary `sudo -u` to impersonate projects.

## 12. Delivery model

Implementation is split into numbered stages in `docs/work/TZ_GRACE_ADMIN_CONTROL_CENTER_00_INDEX.md`.

Each stage must:

1. preserve all accepted previous stages;
2. have focused tests;
3. leave the repository in a usable state;
4. be committed independently;
5. not implement later stages speculatively unless a small shared primitive is required.

## 13. Final Definition of Done

The feature is not done merely because a project selector exists.

Final acceptance requires that an operator can, from one Admin Control Center:

1. see all configured projects and their health;
2. inspect any feature/wave/packet/run/stage/session;
3. read complete event timelines and raw payloads;
4. inspect/tail relevant logs;
5. inspect evidence/artifacts and permitted operational files;
6. inspect Git diffs/worktrees/commits;
7. understand leases, wait reasons and stale-base integration state;
8. inspect raw API responses and discover every API path through OpenAPI;
9. search across projects;
10. execute supported controls with audit trail;
11. keep working when one project is offline;
12. prove no cross-project DB/filesystem/context leakage in tests.

Forbidden final states include:

- project selector backed by one global DB;
- process-global environment/settings switching per request;
- logs still requiring SSH for ordinary diagnosis;
- event explorer limited to recent 20 rows;
- hidden payload_json/result_json;
- listed artifacts that cannot be opened safely;
- API data invisible both in dedicated UI and API Explorer;
- arbitrary filesystem read endpoint;
- one failed project breaking the Hub.
