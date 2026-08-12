# API-First Control Plane

Date: 2026-06-05
Status: enforced (W1 of `source/codex/tz-api-first-cleanup-waves-w0-w11.md`)

## Canonical runtime contract

The OpenAPI document published by `src/grace_control/api/main.py:create_app()` is the
single canonical runtime contract of the GRACE Control Plane. There is no second
control plane.

```text
Services = the only business-logic core
FastAPI + OpenAPI = the only public runtime interface
Control CLI = removed; after bootstrap operators use the HTTP/OpenAPI surface
scripts/ = CI/dev wrappers only; they must not hold runtime orchestration logic
Legacy Prefect = isolated behind a single boundary file
                  (`src/grace_control/agent/legacy_backend.py`); removed in W8
MCP = not part of current scope; only a future optional thin adapter over services
```

## Discovery contract for agents and humans

```text
1. Open the document at /openapi.json (generated from the FastAPI app).
2. The document lists every runtime capability and the typed request/response
   schemas behind it.
3. Agents must call HTTP endpoints; they must not invoke CLI commands, scripts,
   or internal Python services directly.
4. New capabilities land by adding a router endpoint and re-generating the
   OpenAPI document. New control CLI commands, new prefect flows, or new
   side-channel scripts are not acceptable.
```

## What this document replaces

| Old surface                          | New surface                                  |
|--------------------------------------|----------------------------------------------|
| `grace` CLI                          | `/api/architect/plan`, `/api/packets/*`, etc. |
| `grace trace ...`                    | `/api/trace/packets/{id}`, `/api/trace/search`, etc. |
| `grace lint` (runtime)               | `scripts/grace_lint.py` (CI) + `/api/tools/grace-lint/run` (agent) |
| `grace eval run`                     | `/api/tools/smoke/run`                       |
| `grace up` / `grace worker start`    | deployment / systemd unit calling `/api/workers/register` and `/api/packets/claim` |
| direct prefect flows                 | normal packet pipeline over services         |

## Architectural guarantees

The control plane MUST hold these invariants. Each is enforced by an
explicit test or a GraceLint rule; see `docs/grace/GRACE_LINT_RULES.md` (W10)
and `docs/grace/TESTING_STRATEGY.md` for the catalog.

1. **OpenAPI is canonical.** The file `docs/openapi.json` is generated and
   committed; a test fails CI if it is stale.
2. **No parallel business logic.** Routers do not run DB aggregation loops
   or business decisions; they call services. Services do not know about
   HTTP, CLI, or Prefect.
3. **No public control CLI entrypoint.** The package metadata MUST NOT expose
   the removed control CLI or any alias for it. The architecture guard
   `test_no_control_cli_surface` fails if a control command reappears.
4. **No direct environment reads outside `config/`.** The only files allowed
   to call `os.environ.get("GRACE_...")` are
   `src/grace_control/config/*`, `tests/*`, and the legacy boundary
   (until W8). GraceLint rule GRC100 enforces this.
5. **No direct subprocess / git / prefect in API routers.** Routers call
   services. Services call `GitService` for git. GraceLint rules
   GRC101 / GRC102 enforce this.
6. **No `Packet.state` mutation outside `PacketService` / `wave_gate` /
   DB migrations / tests.** GraceLint rule GRC103 enforces this.
7. **Self-evolution is not a side channel.** Self-modification requests
   go through `/api/self_evolution/...`, produce a packet, and go through
   the same acceptance/review/merge pipeline. See `docs/grace/SELF_EVOLUTION.md`.

## OpenAPI version policy

The OpenAPI document is generated, not hand-edited. The generation flow
is:

```text
1. Source of truth: src/grace_control/api/routers/*.py
2. Generator: scripts/generate_docs.py
3. Artifact: docs/openapi.json
4. CI check: make docs-check
```

If `docs/openapi.json` is missing or older than the routers, the
`make docs-check` target fails. See `docs/grace/CI_CD.md` for the exact
job wiring.

## What lives where

```text
src/grace_control/services/      business logic; no HTTP, no CLI, no Prefect
src/grace_control/api/routers/   thin FastAPI bindings; call services
src/grace_control/api/main.py    wiring-only (W5)
src/grace_control/supervisor_client.py
                                  internal UDS transport used by API/tests;
                                  not an operator-facing CLI
scripts/                         CI/dev wrappers; no runtime orchestration
src/prefect_grace/               legacy; isolated, removed in W8
```

## Migration to API-first

Waves W1..W11 progressively move the codebase into this shape. See
`source/codex/roadmap-api-first-legacy-cli-hardcode-cleanup.md` for the
high-level story and `source/codex/tz-api-first-cleanup-waves-w0-w11.md`
for the per-wave acceptance criteria.
