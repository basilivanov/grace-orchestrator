# TZ_GRACE_ARCHITECTURE_REFACTOR_V2_02_CONTROL_CLI_REMOVAL — Packet 02: control/user CLI removal

## Packet identity

- `TZ_NAME`: `TZ_GRACE_ARCHITECTURE_REFACTOR_V2_02_CONTROL_CLI_REMOVAL`
- Role: Coder
- Repository: `/opt/grace-orchestrator`
- Upstream: `origin/main`
- Parent source: `docs/work/TZ_GRACE_ARCHITECTURE_REFACTOR_V2.md`
- Normative detail: Architecture Refactor V2 Wave 1 — **control/user CLI removal only**.
- Previous new-cycle packet: `TZ_GRACE_ARCHITECTURE_REFACTOR_V2_01_OPENCODE_LEGACY_REMOVAL` — ACCEPTED.
- Historical agent-exchange packets from earlier cycles are evidence only. Do not edit/reuse their outbox/review files.

Implement only this named packet. Do not start Admin dependency inversion, aggregation-cycle removal, lifecycle extraction, typed read models, dead-code cleanup, or CI consolidation.

## Mandatory fast-forward sync

Before inspecting implementation files or editing anything:

```bash
cd /opt/grace-orchestrator
git switch main
git fetch origin --prune
git pull --ff-only origin main
git status --short --branch
git rev-parse HEAD
```

Record synced base SHA and initial status in the submission. Preserve unrelated untracked files. Do not use `git reset --hard`, `git clean`, destructive checkout, or repo-side orchestration metadata/state/lock files.

## Current-state rule

This is a verification/refactor cycle over a repository that may already contain earlier accepted Architecture Refactor V2 implementation.

1. Current `main` is authoritative.
2. Do not recreate a removed CLI merely because the parent TZ describes the historical starting state.
3. If all acceptance criteria are already satisfied, perform the full audit/checks and submit a **verified no-op** using the synced `HEAD` as `WEB_ORCH_COMMIT`.
4. Do not manufacture implementation changes merely to produce a diff.
5. If gaps exist, make only the smallest in-scope corrections, commit and push them, then report the real implementation SHA.

## Product decision

The public/operator control surface after process bootstrap is **HTTP/FastAPI/OpenAPI only**.

Remove/keep removed:

- `src/grace_control/cli.py` as a user/control CLI;
- `python -m grace_control.cli ...` operator flows;
- `grace_ctl` / `gracectl` / equivalent supported operator entrypoints;
- CLI-only tests and active runbook instructions;
- `typer` only if no remaining live non-control import requires it.

Do **not** remove or break:

- `src/grace_control/agent/universal_cli_backend.py`;
- `src/grace_control/runtime/mini_swe_runner.py`;
- `src/grace_control/services/agent_run_service.py`;
- generic internal CLI/subprocess backend execution used by mini-swe/Agy;
- deployment/bootstrap ability to start the supervisor/process before HTTP exists.

A bootstrap script may invoke `grace_control.supervisor` directly. After startup, status/restart/reload/control operations must be HTTP/API-driven.

## Frozen invariants

Do not change:

- packet lifecycle/state values;
- reviewer/verifier/acceptance/recovery/merge semantics;
- DB schema/Alembic;
- HTTP routes, field names, response/status contracts;
- mini-swe role contracts;
- admin/lifecycle architecture beyond a directly necessary CLI-reference removal;
- OpenCode removal state from Packet 01.

No new `GRC005`/`GRC012` allowlist entries. No test weakening. Do not introduce a replacement wrapper CLI or hidden alias that forwards operator commands to HTTP.

## Baseline inventory before edits

Run and retain concise evidence:

```bash
git status --short
git rev-parse HEAD

rg -n 'grace_control\.cli|python -m grace_control\.cli|grace_ctl|gracectl' \
  src tests scripts docs/grace docs/SUPERVISOR.md README.md AGENTS.md \
  pyproject.toml docker .github Makefile || true

rg -n 'typer|Typer\(' src tests scripts pyproject.toml || true
```

Classify every hit as one of:

- live operator CLI implementation/reference to remove;
- bootstrap process-start path to migrate/preserve correctly;
- internal generic agent CLI/subprocess infrastructure to keep;
- negative architecture guard;
- historical evidence outside active docs.

Do not fix later-wave architecture discovered by the scan.

## Required target state

### 1. No control/user CLI module or entrypoint

There must be no supported `src/grace_control/cli.py` control surface and no package script exposing it.

Inspect `pyproject.toml` and active packaging metadata. Remove CLI-only dependency metadata only when proven unused elsewhere.

### 2. Bootstrap remains possible without a control CLI

Inspect `scripts/live_supervisor.sh`, supervisor module entrypoints, systemd/deployment/dev bootstrap references and active docs.

Required model:

```text
process bootstrap -> supervisor module / deployment mechanism
runtime operator control -> HTTP/OpenAPI
```

Do not create a new user-facing shell/Python command surface.

### 3. Active docs are API-first

Active docs/runbooks must not instruct operators to use the removed control CLI for status/restart/reload/control.

Historical `docs/work/` evidence may retain old commands and must not be rewritten merely for keyword cleanliness.

### 4. Internal agent execution remains intact

The word `cli` in `UniversalCliAgentBackend` is not evidence of the removed operator CLI. Preserve generic agent command execution and mini-swe/Agy paths.

### 5. Durable guard

A focused architecture guard must prove directly or equivalently:

- `src/grace_control/cli.py` is absent;
- package metadata exposes no removed control CLI entrypoint;
- active source/scripts/runbooks do not invoke `python -m grace_control.cli` or `grace_ctl`/`gracectl` as operator control;
- bootstrap points directly to the supervisor/module as appropriate;
- internal generic execution modules are not forbidden by the guard.

If an equivalent strong guard already exists and passes, do not duplicate it just to create a diff.

## Required verification

Run current focused tests discovered by the audit plus at minimum:

```bash
rg -n 'grace_control\.cli|python -m grace_control\.cli|grace_ctl|gracectl' \
  src tests scripts docs/grace docs/SUPERVISOR.md README.md AGENTS.md \
  pyproject.toml docker .github Makefile || true

pytest -q tests/grace_control/architecture/test_no_control_cli_surface.py || true
pytest -q tests/grace_control/runtime tests/grace_control/agent
make lint
make docs-check
make hygiene
git diff --check
```

If the exact guard filename differs on current `main`, run the equivalent control-CLI architecture test and report its path.

For baseline-aware lint, report canonical gate success separately from raw Ruff/GraceLint debt; do not misstate raw non-zero audits as zero.

## Submission protocol

If source changes are required, commit and push them and use the full 40-character implementation SHA. If the packet is already fully satisfied, use the synced `HEAD` SHA and state `verified no-op` explicitly.

Then create **only**:

`docs/work/agent_exchange/outbox/TZ_GRACE_ARCHITECTURE_REFACTOR_V2_02_CONTROL_CLI_REMOVAL_SUBMISSION.md`

The file MUST begin exactly:

```text
WEB_ORCH_REPORT: SUBMISSION TZ_GRACE_ARCHITECTURE_REFACTOR_V2_02_CONTROL_CLI_REMOVAL
WEB_ORCH_STATUS: DONE
WEB_ORCH_COMMIT: <full-40-character-implementation-sha>
WEB_ORCH_CHECKS: PASS
```

Then include:

- synced base SHA;
- implementation SHA or verified-no-op statement;
- classified CLI/entrypoint scan;
- bootstrap preservation evidence;
- internal mini-swe/generic backend preservation evidence;
- exact checks/results;
- changed paths, or `none` for verified no-op;
- interpreted remaining CLI-like hits.

Do not create/start the next packet. Wait for Architect ACCEPT/REVIEW.

## Acceptance criteria

Architect ACCEPT requires all of:

1. No user/control CLI implementation or supported package entrypoint remains.
2. No active operator instructions invoke the removed CLI.
3. Supervisor/process bootstrap still works without reintroducing a second control surface.
4. HTTP/OpenAPI remains the only runtime/operator control interface after bootstrap.
5. `UniversalCliAgentBackend`, mini-swe, Agy and generic internal subprocess execution remain supported.
6. No API/DB/lifecycle/state/merge semantic drift is introduced.
7. Strong negative architecture coverage exists and passes.
8. No later-wave Admin/lifecycle/typed-model/dead-code/CI work is mixed into this delta.
9. Required checks are truthfully reported.
10. Submission follows the exact named-file protocol with a full SHA.
