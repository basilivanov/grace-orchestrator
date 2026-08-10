# Task 011 — Admin Control Center Stage 05: Explorers

## Source of truth

Implement:

`docs/work/TZ_GRACE_ADMIN_CONTROL_CENTER_05_EXPLORERS.md`

Read for context/invariants:

- `docs/work/TZ_GRACE_ADMIN_CONTROL_CENTER_MASTER.md`
- `docs/work/TZ_GRACE_ADMIN_CONTROL_CENTER_00_INDEX.md`

Depends on accepted Tasks 007–010 / Control Center Stages 01–04. Current code on `main` is authoritative where older docs differ.

## Objective

Implement only Control Center **Stage 05**: finish the read-only deep-observability explorers so ordinary diagnosis can be done from Admin without SSH.

This stage remains **read-only**. Do not start Stage 06 control mutations.

## Reviewer constraints

1. Preserve the accepted project-aware Jinja2 + HTMX architecture and explicit URL/request-scoped `project_key`. No process-global project switching and no Hub-side direct cross-project DB/filesystem/Git access.
2. Global Events explorer must support project one/many/all, entity ID/type, event type, trace ID, since/until, text and deterministic cursor/page semantics. Rows must preserve full payload/source attribution and canonical project/entity links.
3. Global Logs explorer must support bounded source switching/filtering/tail across capability-dependent API/worker/supervisor/structured/packet/run/stage/acceptance/browser/merge sources. Never auto-load full large logs.
4. Packet/run Logs must scope to the selected project + packet + run/stage and expose source metadata/truncation state.
5. Evidence explorer must expose normalized evidence plus raw JSON, including stage status/summary/issues/commands/exit/stdout/stderr/browser/visual data where available. Unknown evidence fields remain reachable through Raw.
6. Artifact tree/previews must use project-local APIs and remain bounded. Support safe image/JSON/Markdown/text previews; render arbitrary HTML only as source text, never execute project HTML/scripts in privileged Admin origin. Large/binary files must degrade to bounded metadata/download behavior.
7. Add project-scoped Files explorer and packet Files tab using only Stage 02 advertised logical roots. No editable arbitrary absolute path input. Traversal/symlink/secret/backend typed errors must render safely.
8. Add project/packet Git explorer from Stage 02 Git APIs: repo/branch/HEAD/worktrees/packet branch+commit/base/integration/merge metadata, changed files, bounded diff stat/unified diff. Never accept arbitrary browser-supplied Git commands.
9. Worktree explorer is display-only and must show safe identity/branch/packet/attempt/worker/registered/existence/state/lease/size plus active/accepted_waiting_merge/cleanup_protected/orphan_candidate/stale classification. No delete action.
10. Leases UI must expose ordinary/parallel/merge lease metadata and never render full fencing/secret tokens; fingerprints only where applicable.
11. Stale-base view must surface base/current HEAD, stale state, recheck lifecycle, integration base, failure class and evidence for current known classes while preserving unknown classes through Raw.
12. Raw inspector must expose source DTOs rather than recomputing an independent model. Support pretty/compact/copy/download semantics without silently truncating JSON into invalid text.
13. Add project OpenAPI explorer at `/admin/p/{project}/api`. Discover endpoints dynamically from selected project's `/openapi.json`; render method/path/description/params/request/response schemas. GET execution is constrained to discovered selected-project paths. Mutation methods remain visible but execution disabled in Stage 05. No arbitrary URL fetcher.
14. Label source attribution (`API`, `EVENT`, `FILE`, `GIT`) where useful.
15. Enforce bounded large-data behavior: log tails/cursors, bounded directory listings/previews, bounded Git diffs/files with explicit truncation, no recursive artifact preview, safe image/download limits.
16. Preserve Stage 04 project/entity/run/tab/polling state and Stage 01–03 isolation/coverage semantics. Do not weaken filesystem/Git safety established in Task 008.
17. Do not start Task 012 / Stage 06 controls.

## Required tests / acceptance proof

At minimum prove:

1. global event filters plus full payload inspector;
2. same entity ID from two projects produces correct project-aware links;
3. log source switching/filter/tail and bounded behavior;
4. follow-off does not jump viewport in browser acceptance where practical;
5. Markdown/JSON/text/image artifact preview;
6. arbitrary HTML artifact is not executed in Admin origin;
7. binary/large-file bounded behavior;
8. Files UI cannot request arbitrary absolute paths and renders traversal/symlink typed errors safely;
9. real Git repo diff/stat/worktree rendering with explicit truncation where applicable;
10. full lease fencing/secret token never reaches rendered DTO/HTML;
11. stale-base passed and failed/recheck states render;
12. Raw preserves an unknown extra JSON field;
13. OpenAPI explorer discovers a synthetic newly-added endpoint without hard-coded UI changes;
14. OpenAPI explorer cannot execute arbitrary non-discovered URL;
15. mutation execution remains disabled;
16. Task 007–010 isolation/read/aggregation/UI regressions and relevant existing Admin tests remain green.

Use deterministic ASGI/service tests and the repository's browser acceptance harness for UI behavior that cannot be proven from template strings alone. Environment-dependent browser skips must remain explicit and must not replace the deterministic test definition.

Also run relevant Ruff / `py_compile` / GRACE lint checks and `git diff --check`.

## Required result

Commit and push the implementation.

Then create:

`docs/work/agent_exchange/outbox/011_SUBMISSION.md`

Keep it short and include:

- implementation commit SHA;
- Events/Logs/Evidence/Artifacts/Files/Git/Worktrees/Leases/Stale-base/Raw/OpenAPI work completed;
- bounded/safety behavior proof summary;
- browser/UI checks and any explicit environment skips;
- Task 007–010 regression results;
- any limitation or deviation from TZ05.

Do not start Task 012 until reviewer returns `ACCEPT 011`.