# TZ 05 — Events, Logs, Files, Git, Raw and API Explorers

Depends on Stages 01-04.

## Objective

Finish the deep-observability side of the Admin Control Center so an operator can inspect every meaningful byte GRACE exposes through API or safe operational file/Git reads.

This stage is read-only. Control mutations are Stage 06.

## 1. Global Event Explorer

Add `/admin/events` backed by Stage 03 Hub events API.

Required table/list columns:

```text
time
project
event_type
entity_type/entity_id
component
trace_id
reason
```

Filters:

```text
project one/many/all
entity_id
entity_type
event_type
trace_id
since/until
text
page/cursor
```

Click row opens inspector/drawer with complete pretty `payload_json` plus source attribution and links to the related project/entity.

Support Copy JSON / compact-pretty toggle / download JSON where appropriate.

## 2. Global Log Explorer

Add `/admin/logs`.

Sources may include capability-dependent:

```text
API
worker
supervisor
structured GRACE JSONL
packet/run stdout
packet/run stderr
agent
stage stdout/stderr
acceptance
browser/e2e
visual
merge/recheck/recovery
```

Filters:

```text
project
source
worker
packet
run
stage
level
trace_id
contains
regex
since/until
```

UX:

```text
tail 100/500/2000
follow on/off
wrap on/off
ERROR-only / WARN+
copy selected/all visible
download bounded source where supported
```

Do not auto-load complete large logs. Use tail/cursor pagination.

When follow is off or the user has scrolled away from the bottom, polling must not force-scroll.

## 3. Packet/run Logs tab

Provide the same core viewer scoped to current packet and selected run/stage.

Make source switching explicit (`stderr`, `stdout`, `agent`, stage-specific, etc.).

Show source file/resource metadata and truncation state.

## 4. Evidence Explorer

Evidence tab should show both normalized evidence and raw evidence.

Per stage where available:

```text
status
summary
blocking issues
commands summary
failed commands
exit codes
stdout tail
stderr tail
screenshots
visual diff metadata
browser artifacts
```

Always offer `View raw JSON` when raw evidence exists.

Unknown/new evidence fields must remain reachable through Raw rather than discarded.

## 5. Artifact tree and previews

Use project-local artifact APIs.

Tree node metadata:

```text
name
relative path
size
mtime
kind
mime/category
previewable
```

Preview behavior:

- image -> inline bounded image;
- JSON -> structured viewer + raw;
- Markdown -> rendered and raw toggle;
- text/log -> bounded text viewer;
- HTML -> source text, do not execute arbitrary project HTML in privileged same-origin Admin context;
- HAR -> JSON/tree where practical;
- small binary -> optional hex preview;
- large binary -> metadata/download only.

Never inject arbitrary artifact HTML/scripts into the Admin origin.

## 6. Files Explorer

Add project-scoped `/admin/p/{project}/files` and packet Files tab.

The UI may browse only roots advertised by project-local Stage 02 filesystem capability.

Display current logical root and relative path. Never display an editable arbitrary absolute-path input.

Actions:

```text
list directory
stat
bounded preview
tail text file
copy relative path
download when allowed
```

Clearly label source as FILE.

If a project does not advertise filesystem capability, show unavailable, not error.

## 7. Git Explorer

Project and packet Git views must show:

```text
repo/target branch
HEAD/target HEAD
remote/status
worktrees
packet branch/commit
base SHA
integration base SHA
merge commit
changed files
diff stat
unified diff
```

Provide safe diff viewer with file selector and syntax-neutral text rendering.

Do not execute arbitrary Git command text supplied from the browser.

## 8. Worktree view

Show GRACE worktrees with relationships where available:

```text
path/display-safe identity
branch
packet
attempt
worker
created/mtime
registered in Git
exists on disk
packet state
lease owner
size
```

Classify display-only status:

```text
active
accepted_waiting_merge
cleanup_protected
orphan_candidate
stale
```

No delete action in this stage.

## 9. Leases explorer

Project Diagnostics/System or dedicated section should show:

### Ordinary leases

```text
packet
worker
lease fingerprint/id
claimed attempt
heartbeat/expiry
```

### Parallel leases

```text
packet
worker
scope
conflict_keys
base SHA
heartbeat/expiry
```

### Merge lease

```text
target repo
packet
worker
token fingerprint only
acquired/heartbeat/expiry
```

Never reveal full secret fencing tokens.

## 10. Stale-base view

For stale/rechecked packets display:

```text
packet base SHA
target/current HEAD
stale=true/false
integration recheck skipped/running/passed/failed
integration base SHA
failure class
evidence
```

Recognize at least current failure classes such as:

```text
stale_base_conflict
integration_verification_failed
missing_base_sha
merge_conflict
```

Unknown failure class still renders raw.

## 11. Raw inspector

Add Raw tab/inspector for major entities:

```text
project health/config/capabilities
feature/wave/packet DTO
packet trace/timeline
run + full result_json
stage
session
event payload_json
diagnostics
filesystem stat metadata
Git raw read DTO
```

Controls:

```text
Pretty/compact
Copy JSON
Download JSON
```

Raw must be source data, not a second independently recomputed model.

## 12. OpenAPI Explorer

Add `/admin/p/{project}/api`.

Load project `/openapi.json` and render every discovered endpoint:

```text
method
path
summary/description
parameters
request schema
response schema
```

GET endpoints:

- editable safe parameters;
- Execute;
- status/headers/body;
- pretty/raw response.

Mutation methods:

- visible as API documentation;
- execution disabled by default in this stage;
- Stage 06 will add safe control policy/confirmation.

Do not create an arbitrary URL fetcher. Requests are constrained to the selected project's discovered OpenAPI paths.

## 13. Source attribution

Where helpful label data source:

```text
API
EVENT
FILE
GIT
```

Example:

```text
packet state   API
merge_failed   EVENT
stderr.log     FILE
diff           GIT
```

This is operator UX metadata only.

## 14. Large data rules

Required bounded behavior:

- no complete multi-MB log read on tab open;
- no recursive artifact preview;
- directory listing can paginate/limit large directories;
- diff output has max bytes/files with explicit truncated flag;
- JSON raw payload can be truncated only if endpoint explicitly reports it; do not silently cut JSON into invalid text;
- images/downloads use streaming/response limits appropriate to current framework.

## 15. Tests

Required minimum:

- global event filters + payload drawer;
- same entity ID from two projects links correctly;
- log source switching/filter/tail;
- follow off does not jump viewport (frontend/browser test where practical);
- Markdown/JSON/text/image preview;
- HTML artifact not executed in Admin origin;
- binary/large-file bounded behavior;
- Files UI cannot request arbitrary absolute path;
- symlink/traversal backend errors render safely;
- real Git repo diff/stat/worktree rendering;
- lease full fencing token never reaches rendered DTO;
- stale-base passed/failed displays;
- Raw shows unknown extra JSON field;
- API Explorer discovers a newly-added synthetic OpenAPI endpoint without hard-coded UI change;
- API Explorer cannot execute arbitrary non-OpenAPI URL;
- mutation execution remains disabled in Stage 05.

## 16. Acceptance

Stage 05 is complete when ordinary diagnosis can be done from Admin without SSH: events, logs, evidence, artifacts, safe operational files, Git/worktrees, leases/stale-base, Raw data and every OpenAPI endpoint are inspectable.
