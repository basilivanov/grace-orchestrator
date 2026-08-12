# TZ_GRACE_ARCHITECTURE_REFACTOR_V2_CONTROL_CLI_REMOVAL — Packet 2: API-only control surface

## Packet identity

- `TZ_NAME`: `TZ_GRACE_ARCHITECTURE_REFACTOR_V2_CONTROL_CLI_REMOVAL`
- Role: Coder
- Repository: `/opt/grace-orchestrator`
- Upstream: `origin/main`
- Parent programme: GRACE Architecture Refactor V2
- Previous named packet `TZ_GRACE_ARCHITECTURE_REFACTOR_V2` is ACCEPTED.
- Implement **only control CLI removal / API-only control surface cleanup** in this packet.
- Do **not** start Admin dependency inversion, Admin aggregation cycle removal, lifecycle service extraction, typed DTO work, dead-code cleanup, or CI consolidation.

This packet is self-contained. Do not read or invent another packet. Do not start the next packet until Architect returns ACCEPT for this `TZ_NAME`.

## Mandatory sync before any work

Before inspecting implementation files or editing anything:

```bash
cd /opt/grace-orchestrator
git switch main
git fetch origin main
git merge --ff-only origin/main
git status --short
git rev-parse HEAD
```

Record synced base SHA and initial `git status --short` in the submission.

Preserve unrelated pre-existing untracked files. In particular, do not delete `.env.bak-mini-endpoint-20260705170600` or `parse_list.py` if they are still present. Do not run `git reset --hard` or `git clean`.

Do not create `state.json`, lock files, orchestration metadata, or any repository-side web-orch state.

## Product/architecture decision

GRACE Control Plane is API-first.

After process bootstrap, the canonical operator/control surface is HTTP/OpenAPI. The old user/control CLI must be physically removed, not deprecated, wrapped, aliased, or replaced with a thin HTTP CLI client.

Important distinction:

- **REMOVE** `src/grace_control/cli.py`, `grace_ctl`, `python -m grace_control.cli ...`, and public control-CLI packaging/docs/tests.
- **KEEP** the internal generic subprocess execution path used by mini-swe, including `src/grace_control/agent/universal_cli_backend.py`, `src/grace_control/services/agent_run_service.py`, and `src/grace_control/runtime/mini_swe_runner.py`.
- A deployment/dev bootstrap script may start the supervisor directly because HTTP cannot start itself before the process exists.
- Do not redesign HTTP control APIs in this packet.

## Required work

### 1. Inventory before deletion

Capture and classify live references before editing:

```bash
rg -n 'grace_control\.cli|grace_ctl|python -m grace_control\.cli' \
  src tests scripts docs/grace docs/SUPERVISOR.md README.md AGENTS.md pyproject.toml docker || true

rg -n '(^| )import typer|from typer' src scripts tests || true
```

Also inspect package entry points/dependencies in `pyproject.toml` and relevant Docker/requirements files.

Historical `docs/work/` evidence is not part of the active-reference zero requirement and must not be rewritten merely to erase history.

### 2. Physically remove the user/control CLI

Delete:

```text
src/grace_control/cli.py
```

Do not create:

- `cli2.py`;
- a deprecated stub;
- a re-export alias;
- a shell alias that recreates runtime control commands;
- a Typer/Click HTTP forwarding client;
- any second operator/control surface.

Remove imports/references whose only purpose was the deleted CLI.

### 3. Preserve direct supervisor bootstrap

Inspect the actual supported entry point in:

```text
src/grace_control/supervisor.py
scripts/live_supervisor.sh
```

If `scripts/live_supervisor.sh` still starts through `python -m grace_control.cli start`, migrate it to the real direct supervisor module/entry point and its **existing supported arguments**.

Preferred architectural shape is equivalent to:

```text
python -m grace_control.supervisor ...
```

but use the arguments the module actually supports; do not invent flags.

Bootstrap/startup scripts are allowed. Status/restart/reload/control after startup must remain HTTP API operations.

Do not refactor supervisor internals beyond what is necessary to remove the CLI dependency.

### 4. Remove active CLI references from lifecycle messages only

Inspect:

```text
src/grace_control/api/routers/lifecycle.py
```

Replace user-facing bootstrap/error text that recommends `python -m grace_control.cli ...` or `grace_ctl`.

Do **not** perform Wave 4 lifecycle architecture extraction here. In this packet the lifecycle router may be changed only as needed to stop referencing the deleted CLI and preserve current API behavior.

### 5. Remove CLI-only packaging/dependencies

Inspect `pyproject.toml` package scripts/entry points and dependency declarations.

There must be no public package script exposing old control commands under names equivalent to:

```text
grace
grace-dev
prefect-grace
gracectl
grace_ctl
```

when those entry points map to the removed control CLI.

Search Typer usage after deleting `cli.py`:

```bash
rg -n '(^| )import typer|from typer' src scripts tests || true
```

If there are zero live imports, remove `typer` from project/Docker requirements where it exists solely for the removed CLI. Update tracked lock/requirements files only if required by this repository's dependency workflow.

Do not remove unrelated dependencies such as `rich` without equivalent evidence.

### 6. Replace obsolete CLI-presence test with a removal guard

Inspect the current test:

```text
tests/grace_control/api/test_no_cli_business_logic.py
```

The old rule “CLI may exist but contain no business logic” is obsolete.

Replace/delete it in favor of an architecture guard, preferred path:

```text
tests/grace_control/api/test_no_control_cli_surface.py
```

The guard must prove at least:

1. `src/grace_control/cli.py` does not exist.
2. Active package entry points do not expose the removed control CLI.
3. Active source/scripts/operator docs do not invoke `grace_control.cli`, `python -m grace_control.cli`, or `grace_ctl`, except deliberate negative assertions in the guard itself.
4. The API app/OpenAPI surface remains constructible/available through existing deterministic API tests.
5. Direct supervisor bootstrap path remains present and does not depend on the deleted CLI.

Avoid brittle whole-file snapshots. AST/config/text checks for banned identifiers are appropriate.

### 7. Update active operator/developer docs

Inspect and update only current docs as needed, at minimum:

```text
docs/SUPERVISOR.md
docs/grace/API_FIRST_CONTROL_PLANE.md
docs/grace/RUNBOOK_LOCAL_DEV.md
README.md
AGENTS.md
scripts/live_supervisor.sh
```

Any current wording equivalent to “CLI is deprecated but may remain as a thin HTTP client” must become “control CLI removed / use HTTP API after bootstrap”.

Do not edit historical task/submission/evidence documents merely to make a global historical search empty.

## Frozen / out-of-scope work

Do not in this packet:

- change packet lifecycle/state/recovery/reviewer/verifier/merge semantics;
- change DB schema;
- rename HTTP API fields or routes;
- refactor lifecycle router into new services/ports (later packet);
- refactor Admin Control Center dependencies/mixins/aggregation;
- remove mini-swe or `UniversalCliAgentBackend`;
- remove the supported `agy` path/session resume established by the accepted prior packet;
- perform dead-code sweep outside control-CLI-only artifacts;
- consolidate CI/Makefile yet;
- add GRC005/GRC012 allowlist entries;
- weaken or skip supported tests to force green.

## Required verification

Run focused zero-reference scans:

```bash
rg -n 'grace_control\.cli|grace_ctl|python -m grace_control\.cli' \
  src tests scripts docs/grace docs/SUPERVISOR.md README.md AGENTS.md pyproject.toml docker || true
```

Expected: zero active hits except deliberate negative assertions in the removal guard.

Run Typer scan and document whether the dependency is still needed:

```bash
rg -n '(^| )import typer|from typer' src scripts tests || true
```

Run at minimum:

```bash
PYTHONPATH=src .venv/bin/pytest -q tests/grace_control/api
PYTHONPATH=src .venv/bin/pytest -q tests/grace_control/runtime tests/grace_control/agent
python3 scripts/grace_lint.py src/grace_control tests scripts
.venv/bin/ruff check src/grace_control tests scripts
git diff --check
```

If repository-wide GRACE lint/Ruff still have pre-existing baseline failures, report exact before/after evidence and prove this packet introduced no new violation. Do not broaden scope to clean unrelated baseline debt.

Also run focused tests for the direct supervisor bootstrap and any package-entry-point/dependency behavior you change.

## Acceptance criteria

PASS only if all are true:

1. `src/grace_control/cli.py` is physically absent.
2. No replacement/deprecation/alias control CLI exists.
3. `scripts/live_supervisor.sh` or the canonical deployment/dev bootstrap starts the supervisor without importing/invoking `grace_control.cli`.
4. Runtime operator control after bootstrap remains HTTP/OpenAPI.
5. Active lifecycle/bootstrap messages do not recommend removed CLI commands.
6. Old control-CLI package entry points are absent.
7. `typer` is removed if and only if no remaining live import requires it.
8. Active docs/scripts no longer instruct operators to use `grace_ctl` or `python -m grace_control.cli`.
9. A durable architecture guard prevents the control CLI surface from returning.
10. Existing API routes/contracts remain stable.
11. mini-swe, `UniversalCliAgentBackend`, and accepted `agy` behavior remain operational.
12. No later architecture wave was started.
13. Required focused tests pass; any repository-wide pre-existing lint failure is documented with no new regression.

## Submission protocol

After implementation, commit and push to `main`.

Create **only** this agent-exchange result file:

```text
docs/work/agent_exchange/outbox/TZ_GRACE_ARCHITECTURE_REFACTOR_V2_CONTROL_CLI_REMOVAL_SUBMISSION.md
```

Do not create another task, review, state, lock, report, or orchestration file.

The submission must contain these exact protocol lines with the full commit SHA:

```text
WEB_ORCH_REPORT: SUBMISSION TZ_GRACE_ARCHITECTURE_REFACTOR_V2_CONTROL_CLI_REMOVAL
WEB_ORCH_STATUS: DONE
WEB_ORCH_COMMIT: <full-commit-sha>
WEB_ORCH_CHECKS: PASS
```

Then summarize:

- synced base SHA and initial status;
- exact deleted/migrated CLI surfaces;
- supervisor bootstrap path used after deletion;
- package entry point and Typer decision/evidence;
- zero-reference scan result;
- tests/checks with counts/results;
- any pre-existing failures proven unchanged.

Do not start any next packet until Architect returns:

```text
WEB_ORCH_DECISION: ACCEPT TZ_GRACE_ARCHITECTURE_REFACTOR_V2_CONTROL_CLI_REMOVAL
```
