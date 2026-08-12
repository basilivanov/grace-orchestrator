# GRACE Documentation

## Grace (active docs)

| Doc | Owner | Generated | Update |
| --- | --- | --- | --- |
| [CANON](grace/CANON.md) | code | manual | code review |
| [Architecture](grace/ARCHITECTURE.md) | code | manual | code review |
| [API First Control Plane](grace/API_FIRST_CONTROL_PLANE.md) | code | manual | W1 |
| [Configuration](grace/CONFIGURATION.md) | code | manual | W3 |
| [Execution Backends](grace/EXECUTION_BACKENDS.md) | code | manual | W7 |
| [Execution Pipeline](grace/EXECUTION_PIPELINE.md) | code | manual | W9 |
| [State Machine](grace/STATE_MACHINE.md) | code | manual | W9 |
| [Acceptance Pipeline](grace/ACCEPTANCE_PIPELINE.md) | code | manual | W9 |
| [Trace & Observability](grace/TRACE_AND_OBSERVABILITY.md) | code | manual | W4 |
| [Testing Strategy](grace/TESTING_STRATEGY.md) | code | manual | W9 |
| [Self-Evolution](grace/SELF_EVOLUTION.md) | code | manual | W9 |
| [Legacy Removal](grace/LEGACY_REMOVAL.md) | code | manual | W8 |
| [GraceLint Rules](grace/GRACE_LINT_RULES.md) | code | manual | W9/W10 |

CI policy is owned by the repository `Makefile`: `make test`, `make lint`,
`make docs-check`, and `make hygiene` are the canonical gates; `make ci`
composes them without a second workflow implementation. The public operator
surface is HTTP/OpenAPI. The control CLI and OpenCode runtime are removed;
the internal mini-swe/generic CLI backend remains an execution detail.

## Generated docs (do not edit)

| Doc | Update command |
| --- | --- |
| `openapi.json` | `make docs` |
| `packet-states.md` | `make docs` |
| `state-diagram.md` | `make docs` |

Deterministic tests run with `make test`; tests requiring a running API,
browser, or external provider are explicitly marked `external`/`live` and
run through `make test-live` when the environment is available.

## Archived

- W15: all historical/transitional docs removed from repo. See git history.
