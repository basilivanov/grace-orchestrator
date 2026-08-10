# TZ 02 — Complete project-local Admin read surface

Depends on Stage 01.

## Objective

Make each project-local GRACE runtime a complete, safe source of truth for the Admin Hub.

At the end of this stage the Hub does not need direct SQLite/filesystem/Git access to inspect a project. Existing Admin/Trace/Event/Diagnostics services should be reused and extended instead of duplicated.

This stage is primarily backend/API. Do not build the final global explorers yet.

## 1. Inventory current read capabilities

Before coding, enumerate current OpenAPI paths and current implementation for:

- `/api/admin/*`;
- `/api/trace/*`;
- `/api/events`;
- `/api/diagnostics/state`;
- supervisor/admin lifecycle endpoints;
- existing artifact/log readers.

Add missing read capabilities; do not create a duplicate endpoint when an existing canonical endpoint already provides the data safely.

## 2. Project metadata endpoint

Ensure project-local API can return a display-safe runtime identity/config snapshot.

Required fields where available:

```text
project key/name
project root identity
target repo root
target/base branch
workspace mode
execution backend
state/worktree roots as display metadata
GRACE code SHA/version
API/supervisor status
effective max concurrency
parallel scope guard
merge serialization
stale-base recheck enabled
```

Mask credentials, tokens, passwords and secret env values.

## 3. Complete packet/run/stage raw read model

Dedicated pretty Admin DTOs may stay aggregated, but the project API must allow the Hub/operator to reach the underlying diagnostic information.

Packet detail/raw must make inspectable:

- canonical packet spec including `scope`, `conflict_keys`, `depends_on`;
- current state and attempts;
- runs;
- state machine/pipeline/stages/recovery chain;
- worker/executor/model;
- tokens/cost where persisted;
- base_sha/integration_base_sha;
- stale-base/integration recheck metadata;
- wait/failure/recovery reason;
- full relevant `result_json` in Raw/drill-down form.

Run detail must include persisted prompt/command preview/evidence metadata where available.

Stage detail/read model must expose StageRun paths as logical resources but never allow arbitrary absolute path access from the browser.

## 4. Events

Preserve `/api/events` as canonical filtered event query surface.

Ensure it supports the data needed by the Hub:

```text
entity_id
entity_type
event_type
trace_id
since
until
limit
offset
```

Drill-down result must include complete `payload_json`.

Overview APIs may intentionally return summaries only.

## 5. Diagnostics and leases

Extend canonical diagnostics read model as necessary so the project API can expose:

- packet counts by state;
- feature counts/status;
- workers;
- runs;
- ordinary leases;
- parallel leases with packet/worker/scope/conflict_keys/base_sha/expiry metadata;
- merge lease holder/target repo/packet/worker/acquired/heartbeat/expiry metadata;
- effective max concurrency;
- typed wait reasons or recent waits;
- packet base/integration SHA and recheck state where practical.

Do not return the complete secret merge fencing token. Return a safe fingerprint/masked identifier only if operator correlation needs it.

## 6. Safe operational filesystem API

Create a project-local filesystem read service, not generic router `Path.read_text()` calls.

Conceptual API:

```text
GET /api/admin/fs/roots
GET /api/admin/fs/list?root=...&path=...
GET /api/admin/fs/stat?root=...&path=...
GET /api/admin/fs/file?root=...&path=...&max_bytes=...
GET /api/admin/fs/tail?root=...&path=...&lines=...
```

Exact path names may differ if they fit existing Admin API conventions.

### Allowed roots

Resolve roots server-side from known GRACE metadata, for example:

- configured state root;
- configured worktree root;
- explicitly configured logs root(s);
- a specific PacketRun evidence directory addressed by packet/run ID;
- StageRun stdout/stderr/result/artifacts addressed by stage ID;
- other explicit GRACE-owned operational directories approved in code.

Do not accept arbitrary filesystem root from the client.

### Path safety

Required:

1. `realpath` containment after symlink resolution;
2. reject `..` traversal;
3. reject symlink escapes;
4. deny secrets by normalized relative path/pattern;
5. no arbitrary absolute paths;
6. bounded max file preview bytes;
7. bounded tail lines/bytes;
8. binary detection;
9. read timeout where appropriate;
10. permission/read errors returned as typed non-500 results when expected.

Default deny patterns include at least:

```text
.env
.env.*
*.pem
*.key
id_rsa*
.git/credentials
credentials*
secrets*
```

Do not accidentally deny legitimate evidence merely because content contains the word `secret`; deny by path policy, not text scanning.

## 7. Artifact/evidence integration

Reuse the existing per-run evidence/artifact APIs. Extend metadata so file nodes can include where safely available:

```text
name
relative path
size
mtime
kind
mime/content category
preview capability
```

For preview:

- image -> bounded inline response;
- JSON/text/Markdown/log -> bounded text;
- small binary -> optional bounded hex preview;
- large binary -> metadata/download endpoint rather than memory load.

Existing artifact path-traversal protections must remain.

## 8. Git read service

Add or formalize a project-local Admin Git read service.

Required project/packet information:

```text
repo root identity
current branch
target branch
HEAD
target branch HEAD
remote
clean/dirty status
worktree list
packet branch/commit
base SHA
integration base SHA
merge commit if known
changed files
diff stat
unified diff
```

For project source file inspection prefer Git-tracked operations:

```text
git ls-files
git show <safe-ref>:<safe-path>
```

rather than exposing an unrestricted project-root filesystem browser.

All refs/paths supplied by clients must be validated to avoid option injection/path escape.

Git read operations must have output and time limits.

## 9. OpenAPI passthrough/discovery

The project-local `/openapi.json` is the completeness contract for the future API Explorer.

Ensure Hub's `ProjectClient` can retrieve it and cache it briefly if useful.

Do not build a hand-maintained endpoint registry that can drift from FastAPI OpenAPI.

## 10. Capability document

Add a project-local capability endpoint or equivalent Hub normalization result that identifies optional features, for example:

```json
{
  "sessions": true,
  "stage_runs": true,
  "filesystem": true,
  "git_read": true,
  "controls": ["archive", "cleanup"],
  "api_explorer": true
}
```

A missing optional table/feature must be represented as unavailable capability, not a broken project.

## 11. Tests

Required minimum:

- packet raw/result_json visibility;
- event full payload and pagination/filter regression;
- diagnostics includes parallel/merge lease metadata without full fencing token;
- filesystem allowed root list;
- traversal reject;
- symlink escape reject;
- secret path reject;
- large text preview bounded;
- tail bounded;
- binary handling;
- unreadable/missing file typed response;
- evidence/artifact normal reads still pass;
- Git diff/stat/changed files on isolated real repo;
- unsafe Git path/ref input rejected;
- OpenAPI retrieval;
- optional capability absent is graceful;
- existing Admin/Trace/Events/Diagnostics tests remain green.

Use real temp directories and a real temp Git repository for the safety tests; do not prove filesystem containment only with mocked Path objects.

## 12. Acceptance

Stage 02 is complete when the Admin Hub can obtain all ordinary project diagnostic data through project APIs and no longer has a reason to directly open another project's DB or arbitrary filesystem tree.
