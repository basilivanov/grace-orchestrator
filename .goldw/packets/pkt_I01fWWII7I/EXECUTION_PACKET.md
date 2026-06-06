# Execution Packet: pkt_I01fWWII7I

## Objective
Check result file

## Scope
- src/gold-test/

## Frozen (do not modify)
- docs/archived/legacy_prefect_grace/

## Verification
- [t0] grep 'GOLDEN TEST' /tmp/grace-orchestrator-export/src/gold-test/result.txt && echo PASS

## Expected Evidence
- test results
- lint output

## Spec JSON
```yaml
_context:
  complexity_score: 200
  estimated_scope: []
  file_count: 23
  files:
  - content_preview: "# GRACE Control Plane - API Contract\n\n**Версия:** 1.0 MVP\n\
      **Base URL:** `http://localhost:8042/api`\n\nЭтот документ — единственный источник\
      \ правды для всех API endpoints.\n\n---\n\n## Authentication\n\n**MVP:** No\
      \ authentication (localhost only)\n\n**Post-MVP:** API keys via `Authorization:\
      \ Bearer <token>`\n\n---\n\n## Common Response Format\n\n### Success Response\n\
      ```json\n{\n  \"data\": { ... },\n  \"timestamp\": \"2026-05-31T10:00:00Z\"\n\
      }\n```\n\n### Error Response\n```json\n{\n  \"error\": {\n    \"code\": \"PACKET_NOT_FOUND\"\
      ,\n    \"message\": \"Packet PKT-001 not found\",\n    \"details\": {}\n  },\n\
      \  \"timestamp\": \"2026-05-31T10:00:00Z\"\n}\n```\n\n---\n\n## Features API\n\
      \n### List Features\n\n```\nGET /api/features/\n```\n\n**Response:**\n```json\n\
      {\n  \"data\": [\n    {\n      \"id\": \"FEAT-USER-AUTH\",\n      \"slug\":\
      \ \"user-auth\",\n      \"title\": \"User Authentication\",\n      \"description\"\
      : \"Add JWT-based authentication\",\n      \"status\": \"IN_PROGRESS\",\n  \
      \    \"created_at\": \"2026-05-31T10:00:00Z\",\n      \"updated_at\": \"2026-05-31T10:05:00Z\"\
      \n    }\n  ]\n}\n```\n\n### Get Feature\n\n```\nGET /api/features/{feature_id}\n\
      ```\n\n**Response:**\n```json\n{\n  \"data\": {\n    \"id\": \"FEAT-USER-AUTH\"\
      ,\n    \"slug\": \"user-auth\",\n    \"title\": \"User Authentication\",\n \
      \   \"description\": \"Add JWT-based authentication\",\n    \"status\": \"IN_PROGRESS\"\
      ,\n    \"spec_json\": { ... },\n    \"waves\": [\n      {\n        \"id\": \"\
      W01-FOUNDATION\",\n        \"title\": \"Foundation\",\n        \"packets_count\"\
      : 3\n      }\n    ],\n    \"created_at\": \"2026-05-31T10:00:00Z\",\n    \"\
      updated_at\": \"2026-05-31T10:05:00Z\"\n  }\n}\n```\n\n---\n\n## Packets API\n\
      \n### List Packets\n\n```\nGET /api/packets/?state=ready&feature_id=FEAT-USER-AUTH\n\
      ```\n\n**Query Parameters:**\n- `state` (optional): Filter by state\n- `feature_id`\
      \ (optional): Filter by feature\n\n**Response:**\n```json\n{\n  \"data\": [\n\
      \    {\n      \"id\": \"FEAT-USER-AUTH-W01-P01-ADD-JWT-UTILS\",\n      \"feature_id\"\
      : \"FEAT-USER-AUTH\",\n      \"wave_id\": \"W01-FOUNDATION\",\n      \"slug\"\
      : \"add-jwt-utils\",\n      \"title\": \"Add JWT utilities\",\n      \"state\"\
      : \"ready\",\n... (469 lines total)"
    exports: []
    path: docs/.archived/API_CONTRACT.md
    relevant: true
    size_lines: 469
  - content_preview: "# `API_CONTRACT.md` is archived.\n\nThe hand-written API contract\
      \ has been **superseded by auto-generated docs**.\n\n| Old | New |\n|-----|-----|\n\
      | `docs/API_CONTRACT.md` | [`docs/openapi.json`](./openapi.json) — OpenAPI 3\
      \ spec from the FastAPI app |\n| `docs/API_CONTRACT.md` | Swagger UI at `/docs`\
      \ on the running API |\n| (state machine tables) | [`docs/state-diagram.md`](./state-diagram.md)\
      \ + [`docs/packet-states.md`](./packet-states.md) |\n| (git history) | [`docs/.archived/API_CONTRACT.md`](./.archived/API_CONTRACT.md)\
      \ — kept for history |\n\nRegenerate the auto-generated docs with:\n    make\
      \ docs           # writes docs/openapi.json, state-diagram.md, packet-states.md\n\
      \    make docs-check     # CI: exits 1 if any of the above drift\n\nDo not hand-edit\
      \ `docs/openapi.json`, `docs/state-diagram.md`, or\n`docs/packet-states.md`\
      \ — re-run `make docs` instead.\n"
    exports: []
    path: docs/API_CONTRACT.archived.md
    relevant: true
    size_lines: 18
  - content_preview: '# GRACE Documentation


      ## Grace (active docs)


      | Doc | Owner | Generated | Update |

      | --- | --- | --- | --- |

      | [CANON](grace/CANON.md) | code | manual | code review |

      | [Architecture](grace/ARCHITECTURE.md) | code | manual | code review |

      | [API First Control Plane](grace/API_FIRST_CONTROL_PLANE.md) | code | manual
      | W1 |

      | [Configuration](grace/CONFIGURATION.md) | code | manual | W3 |

      | [Execution Backends](grace/EXECUTION_BACKENDS.md) | code | manual | W7 |

      | [Execution Pipeline](grace/EXECUTION_PIPELINE.md) | code | manual | W9 |

      | [State Machine](grace/STATE_MACHINE.md) | code | manual | W9 |

      | [Acceptance Pipeline](grace/ACCEPTANCE_PIPELINE.md) | code | manual | W9 |

      | [Trace & Observability](grace/TRACE_AND_OBSERVABILITY.md) | code | manual
      | W4 |

      | [Testing Strategy](grace/TESTING_STRATEGY.md) | code | manual | W9 |

      | [Self-Evolution](grace/SELF_EVOLUTION.md) | code | manual | W9 |

      | [Legacy Removal](grace/LEGACY_REMOVAL.md) | code | manual | W8 |

      | [GraceLint Rules](grace/GRACE_LINT_RULES.md) | code | manual | W9/W10 |


      ## Generated docs (do not edit)


      | Doc | Update command |

      | --- | --- |

      | `openapi.json` | `make docs` |

      | `packet-states.md` | `make docs` |

      | `state-diagram.md` | `make docs` |


      ## Archived


      - W15: all historical/transitional docs removed from repo. See git history.

      '
    exports: []
    path: docs/README.md
    relevant: true
    size_lines: 32
  - content_preview: '# Acceptance Pipeline


      The deterministic acceptance pipeline (`core/acceptance_pipeline.py`) runs

      three stages (`core/contracts.py:StageName`):


      | Stage | Purpose | Command source |

      | --- | --- | --- |

      | `T0_SCOPE_AND_LINT` | Lint, format, compile check | `spec_json.verification.t0`
      |

      | `T1_UNIT_TESTS` | Unit/integration tests | `spec_json.verification.t1` |

      | `T2_E2E_OR_SMOKE` | End-to-end verification | `spec_json.verification.t2`
      |


      If any stage fails, the report carries `blocking_issues` that feed the

      trace API (`TraceService.last_failure.blocking_issues`).


      After the deterministic pipeline:


      1. **FAST** profile → skip evidence verifier + reviewer, wire accepted

      2. **NORMAL** profile → run evidence verifier, skip reviewer if pass

      3. **STRICT** profile → run evidence verifier + reviewer gate


      Evidence verifier (`core/evidence_verifier.py`) reads

      `core/prompts/evidence_verifier_prompt.md` for its prompt template. It

      returns one of `PASS`, `REWORK_TO_CODER`, `RETURN_TO_ARCHITECT`.


      Reviewer gate (`core/reviewer_gate.py`) reads

      `core/prompts/reviewer_prompt.md`. Returns `PASS`, `REWORK_TO_CODER`,

      `RETURN_TO_ARCHITECT`.


      Recovery ladder (odd/even attempts) is evaluated via

      `core/recovery_rules.evaluate_ladder()`:

      - Odd attempts (1, 3, 5): skip verifier, fast path to coder

      - Even attempts (2, 4, 6): run verifier, classify, switch coder or architect

      - Attempt 7+: new architect with full context

      '
    exports: []
    path: docs/grace/ACCEPTANCE_PIPELINE.md
    relevant: true
    size_lines: 34
  - content_preview: "# API-First Control Plane\n\nDate: 2026-06-05\nStatus: enforced\
      \ (W1 of `source/codex/tz-api-first-cleanup-waves-w0-w11.md`)\n\n## Canonical\
      \ runtime contract\n\nThe OpenAPI document published by `src/grace_control/api/main.py:create_app()`\
      \ is the\nsingle canonical runtime contract of the GRACE Control Plane. There\
      \ is no second\ncontrol plane.\n\n```text\nServices = the only business-logic\
      \ core\nFastAPI + OpenAPI = the only public runtime interface\nCLI = deprecated\
      \ as a runtime interface; if present at all, it is a thin HTTP\n      client\
      \ that calls the same OpenAPI endpoints\nscripts/ = CI/dev wrappers only; they\
      \ must not hold runtime orchestration logic\nLegacy Prefect = isolated behind\
      \ a single boundary file\n                  (`src/grace_control/agent/legacy_backend.py`);\
      \ removed in W8\nMCP = not part of current scope; only a future optional thin\
      \ adapter over services\n```\n\n## Discovery contract for agents and humans\n\
      \n```text\n1. Open the document at /openapi.json (generated from the FastAPI\
      \ app).\n2. The document lists every runtime capability and the typed request/response\n\
      \   schemas behind it.\n3. Agents must call HTTP endpoints; they must not invoke\
      \ CLI commands, scripts,\n   or internal Python services directly.\n4. New capabilities\
      \ land by adding a router endpoint and re-generating the\n   OpenAPI document.\
      \ New CLI commands, new prefect flows, or new side-channel\n   scripts are not\
      \ acceptable.\n```\n\n## What this document replaces\n\n| Old surface      \
      \                    | New surface                                  |\n|--------------------------------------|----------------------------------------------|\n\
      | `grace` CLI                          | `/api/architect/plan`, `/api/packets/*`,\
      \ etc. |\n| `grace trace ...`                    | `/api/trace/packets/{id}`,\
      \ `/api/trace/search`, etc. |\n| `grace lint` (runtime)               | `scripts/grace_lint.py`\
      \ (CI) + `/api/tools/grace-lint/run` (agent) |\n| `grace eval run`         \
      \            | `/api/tools/smoke/run`                       |\n| `grace up`\
      \ / `grace worker start`    | deployment / systemd unit calling `/api/workers/register`\
      \ and `/api/packets/claim` |\n| direct prefect flows                 | normal\
      \ packet pipeline over services         |\n\n## Architectural guarantees\n\n\
      The control plane MUST hold these invariants. Each is enforced by an\nexplicit\
      \ test or a GraceLint rule; see `docs/grace/GRACE_LINT_RULES.md` (W10)\nand\
      \ `docs/grace/TESTING_STRATEGY.md` for the catalog.\n\n1. **OpenAPI is canonical.**\
      \ The file `docs/openapi.json` is generated and\n   committed; a test fails\
      \ CI if it is stale.\n2. **No parallel business logic.** Routers do not run\
      \ DB aggregation loops\n   or business decisions; they call services. Services\
      \ do not know about\n   HTTP, CLI, or Prefect.\n3. **No public CLI entrypoint\
      \ with business logic.** The `grace` package\n   metadata MUST NOT expose a\
      \ `grace` script that runs business code. If a\n   CLI is shipped at all (for\
      \ dev migration), it must be a thin HTTP client\n   over the same endpoints,\
      \ and the tes\n... [truncated]"
    exports: []
    path: docs/grace/API_FIRST_CONTROL_PLANE.md
    relevant: true
    size_lines: 110
  - content_preview: "# Architecture\n\n## Layers\n\n```\nHTTP (FastAPI) → Routers\
      \ → Services → DB / AgentBackend / Git\n                    ↓\n            \
      \  AcceptancePipeline (T0/T1/T2)\n                    ↓\n              EvidenceVerifier\
      \ / ReviewerGate\n                    ↓\n              MergeService → PacketService\n\
      ```\n\n## Key components\n\n| Layer | Location | Role |\n| --- | --- | --- |\n\
      | Routers | `api/routers/*.py` | HTTP binding, no DB aggregation |\n| App factory\
      \ | `api/app_factory.py` | `create_app()` builds FastAPI |\n| Lifespan | `api/lifespan.py`\
      \ | DB init, lease/wave_gate/feature_gate loops |\n| Services | `services/*.py`\
      \ | Business logic, own SQL |\n| Execution backend | `agent/api_backend.py`\
      \ | Provider-agnostic agent runner |\n| Worktree helpers | `services/worktree_inspector.py`\
      \ | Git read-only helpers |\n| Agent commit | `services/agent_commit_service.py`\
      \ | `git add -A` + `git commit` |\n\n## Execution backends\n\n`select_backend()`\
      \ returns one of:\n- `api` → `ApiAgentBackend` (strategic, delegates to `AgentGatewayService`)\n\
      - `mock` → `MockBackend` (in-process, no subprocess, for tests/CI)\n- `legacy`\
      \ → removed in W8\n\n## File budgets\n\n- `api/main.py` < 150 lines (currently\
      \ 45)\n- `adapters/packet_executor.py` < 300 lines (currently ~700, target for\
      \ follow-up)\n"
    exports: []
    path: docs/grace/ARCHITECTURE.md
    relevant: true
    size_lines: 38
  - content_preview: "# GRACE Canon — Module Contracts\n\nEvery module in `src/grace_control/`\
      \ follows a strict comment canon:\n\n```\nAI_HEADER         — One-line role\
      \ description\nSTART_MODULE_CONTRACT / END_MODULE_CONTRACT\n               \
      \   — purpose, inputs, returns, side_effects, emitted_logs, error_behavior\n\
      START_MODULE_MAP / END_MODULE_MAP\n                  — JSON-like listing of\
      \ all public classes/functions\nSTART_FUNCTION_CONTRACT / END_FUNCTION_CONTRACT\n\
      \                  — per-function equivalent of the module contract\nSTART_BLOCK_*\
      \ / END_BLOCK_*\n                  — DTO helpers, private blocks (< 20 lines)\n\
      ```\n\nAll structured logs use `GraceLogger(\"component_name\")` and emit JSONL\
      \ to\nstderr with keys `component`, `msg`, `trace_id`, and `ctx.reason`.\n\n\
      No module may import `prefect_grace` (enforced by GraceLint GRC100).\n\nConvention:\
      \ frozen dataclass DTOs (e.g. `ClaimResult`, `CancelResult`) for\nORM session\
      \ safety. Routers never contain DB-aggregation loops.\n"
    exports: []
    path: docs/grace/CANON.md
    relevant: true
    size_lines: 24
  - content_preview: "# GRACE Project Configuration\n\nDate: 2026-06-05\nStatus: shipped\
      \ (W3 of `source/codex/tz-api-first-cleanup-waves-w0-w11.md`)\n\n## Overview\n\
      \nGRACE has a three-layer configuration model, with strict precedence:\n\n```text\n\
      env (GRACE_*)   >   .grace/config.yaml   >   safe local defaults\n```\n\nThe\
      \ three layers and their owners:\n\n| layer | location | owner |\n|-------|----------|-------|\n\
      | env vars | `GRACE_*` shell env | deployment |\n| project config | `<project>/.grace/config.yaml`\
      \ | project repo |\n| defaults | `src/grace_control/config/settings.py` | source\
      \ tree |\n\nA field set at a higher layer is **never overwritten** by a lower\
      \ layer.\nThe merge is performed once, at `import` time, by\n`src/grace_control/config/settings.py:_apply_project_fallbacks`.\
      \ The rule\nis: if the env-resolved value still equals the env-less default,\
      \ the\nproject-config value takes its place; otherwise the env value wins.\n\
      \n## Schema\n\nThe typed schema lives in\n`src/grace_control/config/project_config.py:ProjectConfig`.\
      \ A complete\nfile looks like:\n\n```yaml\nproject:\n  name: grace-orchestrator\n\
      \  key: default\n\napi:\n  host: 127.0.0.1\n  port: 8042\n\ndatabase:\n  url:\
      \ sqlite:///./grace.db\n\ngit:\n  remote: origin\n  base_branch: main\n  target_branch:\
      \ main\n\nexecution:\n  backend: legacy          # \"legacy\" | \"api\" | \"\
      mock\"\n  state_root: .grace/state\n  worktree_root: .grace/worktrees\n  timeout_seconds:\
      \ 600\n\nsafety:\n  sandbox_mode: danger-full-access\n  allow_sandbox_bypass:\
      \ false\n```\n\nAll fields are optional. A missing file is treated as an empty\
      \ config\nand the safe local defaults take effect. Unknown keys are silently\n\
      ignored (Pydantic default).\n\n## How to find the project root\n\n`GRACE_PROJECT_ROOT`\
      \ env var, falling back to the current working\ndirectory. The loader looks\
      \ for `<root>/.grace/config.yaml`.\n\n## How to override\n\n| I want to… | How\
      \ |\n|------------|-----|\n| change a value for one process | set `GRACE_FOO=bar`\
      \ in the shell |\n| change a value for the project | put it in `.grace/config.yaml`\
      \ |\n| change a default for everyone | edit `src/grace_control/config/settings.py`\
      \ |\n| override `.grace/config.yaml` for one process | set the env var, it wins\
      \ |\n\n## New fields added in W3\n\nW3 expands `GraceSettings` with the fields\
      \ that were previously\nduplicated as direct `os.environ.get(\"GRACE_...\")`\
      \ calls in\nrouters/services:\n\n| field | type | replaces |\n|-------|------|----------|\n\
      | `git_remote` | str | `os.environ.get(\"GRACE_GIT_REMOTE\", \"origin\")` (future)\
      \ |\n| `architect_timeout_seconds` | int | `os.environ.get(\"GRACE_ARCHITECT_TIMEOUT\"\
      , \"120\")` |\n| `context_timeout_seconds` | int | `os.environ.get(\"GRACE_CONTEXT_TIMEOUT\"\
      , \"60\")` |\n| `worktree_root` | str | hardcoded `worktree_root` in `cli/main.py:up`\
      \ |\n| `allow_sandbox_bypass` | bool | `os.environ.get(\"GRACE_ALLOW_SANDBOX_BYPASS\"\
      )` (W2) |\n| `self_evolution_max_sessions` | int | `os.environ.get(\"GRACE_SELF_MAX_SESSIONS\"\
      , \"3\")` |\n| `recovery_controller_enabled` | bool | `os.environ.get(\"GRACE_RECOVERY_CONTROLLER_ENABLED\"\
      )` |\n| `telegram_token` | str |\n... [truncated]\n... (143 lines total)"
    exports: []
    path: docs/grace/CONFIGURATION.md
    relevant: true
    size_lines: 143
  - content_preview: "# Execution Backends\n\nGRACE Control Plane supports three execution\
      \ backends. The choice is driven\nby `grace_control.config.settings.execution_backend`\
      \ (env:\n`GRACE_EXECUTION_BACKEND`) and read by `grace_control.agent.select_backend()`.\n\
      \n| Backend | Module | Use case |\n| --- | --- | --- |\n| `cli` | `grace_control.agent.universal_cli_backend.UniversalCliAgentBackend`\
      \ | **Default runtime backend.** Runs local CLI agents (`opencode`, `codex`,\
      \ `agy`, etc.) by declarative profile. |\n| `mock` | `grace_control.agent.mock_backend.MockBackend`\
      \ | In-process, no subprocess, no LLM. Tests, CI, local smoke. |\n| `api` |\
      \ `grace_control.agent.api_backend.ApiAgentBackend` | HTTP provider adapter\
      \ (mock provider only; real providers pending W7.1). |\n| `legacy` | removed\
      \ in W8 | Raises `ValueError` with migration hint. |\n\nThe packet executor\
      \ (`adapters/packet_executor.PacketExecutionAdapter`)\ndepends only on the `ExecutionBackend`\
      \ Protocol. The backend is selected\nonce per process — never per packet.\n\n\
      ## How a backend is selected\n\n```python\nfrom grace_control.agent import select_backend\n\
      backend = select_backend()  # reads settings.execution_backend\nresult = await\
      \ backend.run(execution_request)\n```\n\nThe factory accepts an explicit `backend_name`\
      \ (used by tests) or, when\nempty, reads the `execution_backend` field. `BACKEND_CLI`\
      \ is the default\nand is aliased as `BACKEND_NEW` for back-compat with older\
      \ test code.\n\n## UniversalCliAgentBackend (strategic path)\n\n`UniversalCliAgentBackend`\
      \ is the strategic default. It does **not**\nhardcode any CLI tool names (`opencode`,\
      \ `codex`, `agy`, `gemini`,\n`claude`). Instead, it reads agent profiles from\
      \ `agent_profiles.yaml`\nand renders command templates dynamically.\n\nThe implementation\
      \ stack:\n\n- `AgentRunService` — orchestrator\n- `CommandTemplateRenderer`\
      \ — `{model}`, `{effort}`, `{packet_id}`, `{worktree_path}`, `{packet_markdown}`\n\
      - `AgentEnvBuilder` — `${ENV_VAR}` expansion, inherits parent `PATH`, redacts\
      \ secrets\n- `ProcessSupervisor` — subprocess with process group timeout kill\n\
      - `AgentArtifactCollector` — persists `agent_stdout.log` to canonical evidence\
      \ dir\n\n### Agent profile example (`agent_profiles.yaml`)\n\n```yaml\nagents:\n\
      \  coder_opencode:\n    backend: cli\n    command:\n      - opencode\n     \
      \ - run\n      - \"--model\"\n      - \"{model}\"\n      - \"--effort\"\n  \
      \    - \"{effort}\"\n    model: \"codex-5.1\"\n    effort: \"high\"\n    cwd:\
      \ \"{worktree_path}\"\n    timeout_seconds: 900\n    env:\n      OPENAI_API_KEY:\
      \ \"${OPENAI_API_KEY}\"\n    input:\n      mode: stdin\n      template: \"{packet_markdown}\"\
      \n```\n\n### `/api/agents/run`\n\n```http\nPOST /api/agents/run\nContent-Type:\
      \ application/json\n\n{\n  \"packet_id\": \"pkt_001\",\n  \"executor_id\": \"\
      coder_opencode\",\n  \"role\": \"coder\",\n  \"model\": \"optional override\"\
      ,\n  \"effort\": \"optional override\",\n  \"worktree_path\": \"/path/to/worktree\"\
      ,\n  \"packet_markdown\": \"# ...\",\n  \"timeout_seconds\": 900\n}\n```\n\n\
      Response:\n\n```json\n{\n  \"accepted\": false,\n  \"domain_status\": \"completed|rejected|blocked|failed|timeout\"\
      ,\n  \"executor_\n... [truncated]\n... (157 lines total)"
    exports: []
    path: docs/grace/EXECUTION_BACKENDS.md
    relevant: true
    size_lines: 157
  - content_preview: "# Execution Pipeline\n\nThe full packet execution pipeline:\n\
      \n```\nPacket (DB row)\n  → claim (PacketService.claim)\n  → materialize (PacketMaterializer\
      \ → EXECUTION_PACKET.md)\n  → resolve executor (executor_selector.select_executor)\n\
      \  → _call_legacy_runner → execution backend (ApiAgentBackend / MockBackend)\n\
      \  → acceptance pipeline (run_acceptance_pipeline → T0/T1/T2)\n  → evidence\
      \ verifier (run_evidence_verifier)\n  → reviewer gate (run_reviewer_gate — STRICT\
      \ profile only)\n  → finish: accepted / rejected / blocked\n  → PacketRun saved\
      \ with result_json\n  → (on success) MergeService.merge_packet → update DB state\n\
      ```\n\nControl flow lives in `adapters/packet_executor.py:PacketExecutionAdapter.execute()`.\n\
      The adapter is stateless — it does not call mark_running / mark_accepted /\n\
      mark_rejected / mark_failed. State ownership belongs to the API endpoint.\n\n\
      ## Agent commit\n\nAfter a successful agent run, the worktree changes are committed\
      \ with\n`git add -A` + `git commit -m \"agent: {packet_id} attempt {n}\"`.\n\
      This is handled by `services/agent_commit_service.py`.\n\n## Worktree inspection\n\
      \n`services/worktree_inspector.py` exposes `is_git_worktree`, `has_changes`,\n\
      `base_sha`, `collect_changed_files`, and an aggregate `inspect`. All\ngit subprocess\
      \ calls live here.\n"
    exports: []
    path: docs/grace/EXECUTION_PIPELINE.md
    relevant: true
    size_lines: 34
  - content_preview: "# GraceLint Rules\n\nEnforced by `scripts/grace_lint.py` (thin\
      \ wrapper around\n`grace_control.tools.grace_lint.checker`).\n\n## Rule table\n\
      \n| Code | Check | Scope | Allowlist |\n| --- | --- | --- | --- |\n| `GRC001`\
      \ | AI_HEADER present | All `.py` | — |\n| `GRC002` | MODULE_CONTRACT START/END\
      \ balanced | All `.py` | — |\n| `GRC003` | MODULE_MAP START/END balanced | All\
      \ `.py` | — |\n| `GRC004` | START_BLOCK/END_BLOCK pairing | All `.py` | — |\n\
      | `GRC005` | File ≤ 1000 lines | All `.py` | — |\n| `GRC010` | Public function\
      \ has FUNCTION_CONTRACT | All `.py` | — |\n| `GRC011` | FUNCTION_CONTRACT has\
      \ required fields | All `.py` | — |\n| `GRC012` | Function ≤ 4000 tokens | All\
      \ `.py` | — |\n| `GRC020` | MODULE_CONTRACT present | All `.py` | — |\n| `GRC021`\
      \ | MODULE_MAP present | All `.py` | — |\n| `GRC030` | No compressed file |\
      \ All `.py` | — |\n| `GRC100` | No `os.environ` outside config/tests/scripts\
      \ | `src/grace_control/` | `.grace/lint_allowlist.yaml` |\n| `GRC101` | No `subprocess`\
      \ outside service/tests/scripts boundary | `src/grace_control/` | `.grace/lint_allowlist.yaml`\
      \ |\n| `GRC102` | No `prefect_grace` import in runtime code | `src/grace_control/`\
      \ | `.grace/lint_allowlist.yaml` |\n| `GRC103` | No `Packet.state` mutation\
      \ outside `PacketService` | `src/grace_control/` (-services/tests) | `.grace/lint_allowlist.yaml`\
      \ |\n| `GRC104` | No `for`/`db.query` loop in routers | `api/routers/` | `.grace/lint_allowlist.yaml`\
      \ |\n| `GRC105` | No hardcoded `/tmp/grace-*` paths | `src/grace_control/` |\
      \ `.grace/lint_allowlist.yaml` |\n| `GRC106` | No hardcoded `\"main\"` / `\"\
      origin\"` outside config | `src/grace_control/` | `.grace/lint_allowlist.yaml`\
      \ |\n| `GRC107` | Generated docs in sync | `docs/` | Covered by `make docs-check`\
      \ |\n| `GRC108` | Modules > 300 lines must have `START_BLOCK` sections | `src/grace_control/`\
      \ | `.grace/lint_allowlist.yaml` |\n\n## Allowlist\n\nThe file `.grace/lint_allowlist.yaml`\
      \ contains temporary exemptions. Each\nentry includes:\n\n```yaml\n- rule: GRC100\n\
      \  path: src/grace_control/adapters/packet_executor.py\n  reason: os.environ.setdefault\
      \ for sandbox bypass (W11 target)\n  expires_wave: W11\n```\n\n## How to run\n\
      \n```bash\n# Default: all rules, all files\nmake lint\n\n# Specific rules\n\
      python3 scripts/grace_lint.py src/ --rules GRC100 GRC101\n\n# Skip function\
      \ contracts (faster)\npython3 scripts/grace_lint.py src/ --skip-function-contracts\n\
      \n# Via API\ncurl -X POST http://localhost:8042/api/tools/grace-lint/run \\\n\
      \  -H \"Content-Type: application/json\" \\\n  -d '{\"paths\": [\"src/grace_control/api/routers\"\
      ], \"strict\": true}'\n```\n\n## Adding a new rule\n\n1. Add a `_check_*` function\
      \ in `checker.py`\n2. Wire it into `lint_text()` and add to `DEFAULT_RULES`\n\
      3. Write a fixture test in `tests/grace_control/core/test_grace_lint.py`\n4.\
      \ Add a row to this table\n5. Add any necessary allowlist entries in `.grace/lint_allowlist.yaml`\n"
    exports: []
    path: docs/grace/GRACE_LINT_RULES.md
    relevant: true
    size_lines: 68
  - content_preview: "# Runbook: Agent Profiles\n\n## Profile schema\n\nProfiles live\
      \ under `agents:` in `config/agent_profiles.yaml`.\n\n```yaml\nagents:\n  <executor_id>:\n\
      \    backend: cli                    # required, must be \"cli\"\n    command:\
      \                         # required, list of strings\n      - opencode\n  \
      \    - run\n      - \"--model\"\n      - \"{model}\"\n      - \"--effort\"\n\
      \      - \"{effort}\"\n    model: \"codex-5.1\"              # default model\n\
      \    effort: \"high\"                  # default effort\n    cwd: \"{worktree_path}\"\
      \          # cwd template\n    timeout_seconds: 900\n    env:              \
      \              # optional env overrides\n      OPENAI_API_KEY: \"${OPENAI_API_KEY}\"\
      \n    input:\n      mode: stdin|file|none          # default: none\n      template:\
      \ \"{packet_markdown}\"  # for stdin mode\n```\n\n## opencode example\n\nSee\
      \ `coder_opencode` profile in `agent_profiles.yaml`.\n\n## Validation and dry-run\n\
      \n```bash\n# List all profiles\ncurl http://localhost:8042/api/agents/profiles\n\
      \n# Get specific profile\ncurl http://localhost:8042/api/agents/profiles/coder_opencode\n\
      \n# Validate (checks command shape, timeouts, input mode)\ncurl -X POST http://localhost:8042/api/agents/profiles/coder_opencode/validate\n\
      \n# Validate with executable check\ncurl -X POST http://localhost:8042/api/agents/profiles/coder_opencode/validate\
      \ \\\n  -H \"Content-Type: application/json\" \\\n  -d '{\"check_executable\"\
      : true}'\n\n# Dry-run (renders command/env/cwd without spawning)\ncurl -X POST\
      \ http://localhost:8042/api/agents/profiles/coder_opencode/dry-run \\\n  -H\
      \ \"Content-Type: application/json\" \\\n  -d '{\"worktree_path\": \"/tmp/test-wt\"\
      }'\n```\n\n## Common failures\n\n| Symptom | Likely cause |\n| --- | --- |\n\
      | `command must be a list` | String command found; use `[opencode, run, ...]`\
      \ |\n| `executable not found` | CLI tool not installed or not on `$PATH` |\n\
      | `timeout_seconds must be > 0` | Missing or zero timeout |\n| Secrets in env\
      \ preview | Redacted automatically for `API_KEY`, `TOKEN`, `SECRET`, `PASSWORD`,\
      \ `CREDENTIAL` |\n"
    exports: []
    path: docs/grace/RUNBOOK_AGENT_PROFILES.md
    relevant: true
    size_lines: 64
  - content_preview: '# Runbook: Debug a Packet


      ## Find the packet by trace API


      ```bash

      curl http://localhost:8042/api/trace/packets/{packet_id}

      ```


      ## Inspect run timeline


      The trace response includes `runs[]` with status, executor_id, duration, and

      `timeline[]` with event sequence.


      ## Inspect artifacts


      ```bash

      # List artifacts

      curl http://localhost:8042/api/packets/{packet_id}/runs/{run_id}/artifacts


      # Read stdout

      curl "http://localhost:8042/api/packets/{packet_id}/runs/{run_id}/artifacts/file?path=agent_stdout.log"


      # Read stderr (tail)

      curl "http://localhost:8042/api/packets/{packet_id}/runs/{run_id}/artifacts/file?path=agent_stderr.log&tail=50"

      ```


      ## Common failures


      | Symptom | Likely cause |

      | --- | --- |

      | `domain_status=timeout` | Agent took too long; increase `timeout_seconds`
      in profile |

      | `no_changes_produced` | Agent ran but did not modify any allowed files |

      | `merge 409` | Packet already merged or state transition conflict |

      | `executor_id not found` | Profile missing from `agent_profiles.yaml` |

      | `Command not found: opencode` | CLI tool not installed or not on PATH |


      ## Rerun a packet


      Packets can be retried through the recovery pipeline or by creating a new

      packet with the same spec. Manual retry is not exposed via API for safety.

      '
    exports: []
    path: docs/grace/RUNBOOK_DEBUG_PACKET.md
    relevant: true
    size_lines: 41
  - content_preview: "# Runbook: Local Development\n\n## Install\n\n```bash\ngit clone\
      \ <repo>\ncd grace-orchestrator\npython3 -m venv .venv\nsource .venv/bin/activate\n\
      pip install -e \".[dev]\"\n```\n\n## Configuration\n\nDefault config works for\
      \ local dev. Override via env vars:\n\n```bash\nexport GRACE_DB_URL=sqlite:///./grace.db\n\
      export GRACE_EXECUTION_BACKEND=mock\n```\n\nSee `docs/grace/CONFIGURATION.md`\
      \ for full reference.\n\n## Run API server\n\n```bash\nuvicorn grace_control.api.main:app\
      \ --host 127.0.0.1 --port 8042\n```\n\n## Run a fake CLI profile\n\n```bash\n\
      # Create a fake agent script\necho '#!/bin/sh\necho \"{\\\"result\\\": \\\"\
      ok\\\"}\"' > /tmp/fake-agent.sh\nchmod +x /tmp/fake-agent.sh\nexport PATH=/tmp:$PATH\n\
      \n# Run a packet through the API\ncurl -X POST http://localhost:8042/api/agents/run\
      \ \\\n  -H \"Content-Type: application/json\" \\\n  -d '{\"packet_id\":\"test-1\"\
      ,\"executor_id\":\"coder_opencode\",\"worktree_path\":\"/tmp\",\"packet_markdown\"\
      :\"# test\",\"timeout_seconds\":10}'\n```\n\n## Run tests / lint / docs-check\n\
      \n```bash\nmake test\nmake lint\nmake docs-check\nmake ci          # full CI\
      \ gate suite\n```\n\n## Run GraceLint\n\n```bash\npython scripts/grace_lint.py\
      \ src/grace_control/\n```\n"
    exports: []
    path: docs/grace/RUNBOOK_LOCAL_DEV.md
    relevant: true
    size_lines: 59
  - content_preview: "# Runbook: Self-Evolution\n\n## What self-evolution can/cannot\
      \ do\n\nSelf-evolution allows GRACE to modify its own source code through the\
      \ same\npacket pipeline as user-created work.\n\n**Can do:**\n- Modify `src/grace_control/`,\
      \ `tests/`, `docs/grace/`, `.grace/`\n- Add new features through the architect\
      \ → coder → acceptance → merge flow\n\n**Cannot do:**\n- Modify `config/agent_profiles.yaml`\
      \ or security-related config\n- Spawn worker processes directly from the API\n\
      - Create hidden side-channel mutations\n\n## Approval gates\n\n| Risk class\
      \ | Scope | Auto-merge |\n| --- | --- | --- |\n| low | `docs/*`, `*.md` only\
      \ | Yes |\n| medium | Code changes | Requires approval |\n| high | `config/`,\
      \ `security/`, `execution/` | Manual |\n\n## Rollback metadata\n\nEvery self-evolution\
      \ session stores:\n\n```json\n{\n  \"base_commit\": \"abc123...\",\n  \"changed_files\"\
      : [\"src/x.py\"],\n  \"merge_commit\": \"def456...\",\n  \"rollback_command\"\
      : \"git revert --no-commit def456...\"\n}\n```\n\n## Create a session\n\n```bash\n\
      curl -X POST http://localhost:8042/api/self/evolve \\\n  -H \"Content-Type:\
      \ application/json\" \\\n  -d '{\"title\": \"refactor trace service\", \"description\"\
      : \"improve observability\"}'\n```\n\nResponse:\n```json\n{\"session_id\": \"\
      se-...\", \"status\": \"session_created\", \"risk_class\": \"medium\", \"requires_approval\"\
      : true}\n```\n\n## Inspect sessions\n\n```bash\n# List\ncurl http://localhost:8042/api/self/sessions\n\
      \n# Get with rollback metadata\ncurl http://localhost:8042/api/self/sessions/{session_id}\n\
      ```\n\n## Manual recovery\n\nIf a self-evolution session produces unwanted changes:\n\
      \n1. Find `rollback_plan.rollback_command` via `GET /api/self/sessions/{id}`\n\
      2. Execute the rollback command in the repo\n3. Cancel the session: `POST /api/self/sessions/{id}/cancel`\n"
    exports: []
    path: docs/grace/RUNBOOK_SELF_EVOLUTION.md
    relevant: true
    size_lines: 68
  - content_preview: ''
    exports: []
    path: docs/grace/RUNBOOK_SERVER_DEPLOY.md
    relevant: false
    size_lines: 73
  - content_preview: ''
    exports: []
    path: docs/grace/SELF_EVOLUTION.md
    relevant: false
    size_lines: 53
  - content_preview: ''
    exports: []
    path: docs/grace/STATE_MACHINE.md
    relevant: false
    size_lines: 30
  - content_preview: ''
    exports: []
    path: docs/grace/TESTING_STRATEGY.md
    relevant: false
    size_lines: 41
  - content_preview: ''
    exports: []
    path: docs/grace/TRACE_AND_OBSERVABILITY.md
    relevant: false
    size_lines: 176
  - content_preview: ''
    exports: []
    path: docs/openapi.json
    relevant: false
    size_lines: 1908
  - content_preview: ''
    exports: []
    path: docs/packet-states.md
    relevant: false
    size_lines: 18
  - content_preview: ''
    exports: []
    path: docs/state-diagram.md
    relevant: false
    size_lines: 28
  summary: 'Fallback analysis for: 2-Wave Golden Test'
acceptance_profile: FAST
frozen_scope:
- docs/archived/legacy_prefect_grace/
scope:
- src/gold-test/
title: Check result file
verification:
  t0:
  - grep 'GOLDEN TEST' /tmp/grace-orchestrator-export/src/gold-test/result.txt &&
    echo PASS

```
