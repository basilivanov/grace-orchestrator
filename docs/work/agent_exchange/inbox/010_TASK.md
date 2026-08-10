# Task 010 — Admin Control Center Stage 04: Multi-Project UI and Entity Drill-Down

## Source of truth

Implement:

`docs/work/TZ_GRACE_ADMIN_CONTROL_CENTER_04_MULTI_PROJECT_UI.md`

Read for context/invariants:

- `docs/work/TZ_GRACE_ADMIN_CONTROL_CENTER_MASTER.md`
- `docs/work/TZ_GRACE_ADMIN_CONTROL_CENTER_00_INDEX.md`

Depends on accepted Tasks 007–009 / Control Center Stages 01–03. Current code on `main` is authoritative where older docs differ.

## Objective

Implement only Control Center **Stage 04**: extend the existing Jinja2 + HTMX Admin console into a project-aware multi-project UI using the accepted Hub/project-local APIs.

At the end of this stage an operator must be able to navigate Projects -> selected project -> Feature/Wave/Packet -> Run/Stage and understand runtime/failure state from pretty server-rendered views. Heavy global explorers remain Stage 05.

Do **not** replace the current frontend stack with React/Vue/npm and do not introduce process-global project selection.

## Reviewer constraints

1. Preserve the existing server-rendered Jinja2 + HTMX architecture. Reuse current Admin templates/routes/components where practical rather than creating a parallel frontend.
2. Add a persistent project selector and top-level navigation for Projects, Current Project, Events, Logs, Search and System/Diagnostics. Project status must be visible as text/icon semantics, not color only.
3. Project selection must be encoded explicitly in URLs/request context. Never mutate process-global settings/current project/DB based on browser selection.
4. Support canonical project-aware deep links at minimum:
   - `/admin` or `/admin/projects`
   - `/admin/p/{project_key}`
   - `/admin/p/{project_key}/feature/{feature_id}`
   - `/admin/p/{project_key}/wave/{wave_id}`
   - `/admin/p/{project_key}/packet/{packet_id}`
   - `/admin/p/{project_key}/system`
   Back/forward and copied URLs must reconstruct selection without hidden global state.
5. Build the Projects dashboard from Stage 03 Hub overview/attention data. One offline/degraded/disabled project must render its own card and must not fail the whole page.
6. Project cards should expose the TZ04 operational fields where available: name/key/status, Unix user metadata, root identity, target branch/HEAD, GRACE version/SHA, API/supervisor/DB health, workers, packet-state counts, leases, latest event/error/attention and disk summaries.
7. Implement dashboard filters for All/Running/Attention/Blocked/Offline/Idle with deterministic server-side/read-model semantics. Attention cards should sort ahead of healthy idle cards.
8. Reuse the current Feature/Wave/Packet master tree for the selected project. Same entity IDs in different projects must never cross-wire; every data load must retain explicit `project_key`.
9. Packet compact rows must show useful execution/safety state where available: packet state, attempts, worker/model, elapsed, scope/conflict/dependency summaries, base/integration SHAs, integration recheck and typed wait reason.
10. Typed waits are first-class UI. READY/ACCEPTED packets with a wait must display `WAIT: <reason>` rather than appearing frozen.
11. Make Packet Detail the primary debugging page. For blocked/failed packets, render an immediately visible Blocking panel with primary reason/failure class/stage/issues/failed command/exit code/stderr tail where available.
12. Provide packet tabs for Overview, Timeline, Pipeline, Spec, Runs, Stages, Sessions, Evidence, Logs, Artifacts, Files, Git, Diagnostics and Raw. Stage 04 must fully wire at least Overview/Timeline/Pipeline/Spec/Runs/Stages/Sessions/Diagnostics. Heavy Logs/Artifacts/Files/Git/Raw may be capability-aware placeholders for Stage 05.
13. Timeline must use canonical events and preserve all events, source timestamps, trace IDs and full-payload drill-down. Do not silently discard unknown event types.
14. Pipeline/StageRun UI must render runtime stage order and unknown/new `stage_key` values generically. Show status/timing/loop/attempt/parent/worker/executor/model/tokens/cost/error/trace/recovery and logical output links where available. Recovery loops must remain visible.
15. Runs tab must allow selecting a run and propagate that run context to run-dependent views without losing project/packet identity.
16. Sessions tab must degrade gracefully when the project capability is unavailable; show a clear capability banner rather than exception/empty broken UI.
17. Project System view must surface API/supervisor/DB/Git health, workers, runtime version/SHA, effective config, packet/feature counts, ordinary/parallel/merge leases and wait summaries. Secrets remain masked.
18. Mobile layout must remain usable around the existing ~390px acceptance viewport: single-column flow, no forced desktop multi-column control center.
19. Use HTMX partial polling rather than full-page reloads. Polling must preserve selected project/entity/tab and must not reset the operator to another project.
20. Preserve accepted Stage 01–03 API/service behavior and existing single-project Admin behavior where still applicable. Do not start Stage 05 explorers.

## Required tests / acceptance proof

At minimum prove:

1. Projects page renders two online projects;
2. one offline project renders an error/status card without page failure;
3. disabled project remains visible and receives no remote read from UI rendering;
4. project selector deep link plus back/forward-compatible URL semantics;
5. same packet ID in two projects never cross-wires packet detail;
6. Feature/Wave/Packet tree contains only the selected project's entities;
7. typed wait reason is visibly rendered;
8. blocked/failed packet detail exposes the primary blocking reason without opening Logs;
9. run selection changes run-dependent context while retaining project/packet identity;
10. unknown stage key renders as a generic stage card;
11. sessions-unavailable capability renders a graceful banner;
12. polling partial preserves selected project/entity/tab;
13. project system view preserves concurrency/lease/wait/safety state and masks secrets;
14. mobile smoke passes at existing frontend acceptance viewport(s);
15. Task 007–009 isolation/read/aggregation regressions and relevant existing Admin UI tests remain green.

Prefer deterministic ASGI/template assertions plus the repository's existing frontend/browser acceptance harness where already used. Do not rely only on screenshots or brittle timing sleeps.

Also run relevant Ruff / `py_compile` / GRACE lint checks and `git diff --check`.

## Required result

Commit and push the implementation.

Then create:

`docs/work/agent_exchange/outbox/010_SUBMISSION.md`

Keep it short and include:

- implementation commit SHA;
- project-aware shell/dashboard/deep-link/entity drill-down work completed;
- packet detail/timeline/pipeline/runs/sessions/system work completed;
- polling/mobile/cross-project isolation proof summary;
- tests/checks run and results;
- any limitation or deviation from TZ04.

Do not start Task 011 until reviewer returns `ACCEPT 010`.