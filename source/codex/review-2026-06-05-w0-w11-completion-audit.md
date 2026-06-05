# Review: W0-W11 completion audit

Date: 2026-06-05
Reviewed state: current `main` after reported W0-W11 completion.
Source spec: `source/codex/tz-api-first-cleanup-waves-w0-w11.md`

## Verdict

Not fully accepted.

Several waves are genuinely implemented, especially W0, W1, W2, W4, W5, and much of W8/W9. However, the claim "14/14 waves done" is too optimistic. There are still P0/P1 issues that break the intended API-first / no-legacy / no-hardcode architecture.

The biggest blockers:

1. Default runtime backend is still `legacy`, while legacy backend was removed and `select_backend("legacy")` now raises.
2. `packet_executor.py` is not actually cleanly split and still contains direct env reads, direct subprocess/git cleanup, hardcoded legacy branch format, and legacy runner naming/flow.
3. GraceLint is too permissive and has expired W11 allowlist entries that still allow the exact debt W3/W6/W10 were meant to eliminate.
4. Self-evolution still uses direct subprocess for git rollback metadata and routers still own DB mutation/query paths instead of being purely service-backed.
5. ApiAgentBackend is a structural stub: non-mock providers are still unsupported, so the API-agent path is not actually usable for real agents yet.

---

## Wave status table

| Wave | Status | Notes |
|---|---:|---|
| W0 merge atomicity | ✅ Accepted | `e89f410` fixed the last split-brain merge issue. |
| W1 API-first contract | ✅ Mostly accepted | Docs and OpenAPI inventory landed. |
| W2 remove CLI | ✅ Mostly accepted | Public package entrypoints removed; CLI package appears removed. Some deps remain. |
| W3 config cleanup | ⚠️ Partial | Project config exists, but defaults still contradict W8 (`execution_backend=legacy`) and executor still reads env directly. |
| W4 trace API | ✅ Mostly accepted | Trace/events/diagnostics routers and services exist. |
| W5 app factory split | ✅ Accepted | `api/main.py` is now wiring-only and app factory exists. |
| W6 executor split | ❌ Not accepted | `packet_executor.py` remains compressed, legacy-shaped, direct subprocess/env/hardcode still present. |
| W7 ApiAgentBackend | ⚠️ Partial | Backend exists but only `mock` actually succeeds; real API providers return unsupported. |
| W8 remove legacy Prefect | ⚠️ Partial | Packaging removed legacy, but settings default still says legacy and executor still contains legacy flow assumptions. |
| W9 docs restructure | ⚠️ Needs link/drift pass | Structure likely exists, but review found stale package metadata still says Prefect. |
| W10 GraceLint 14 rules | ❌ Not accepted | Rules exist but are too weak/permissive and allow expired debt. |
| W11 self-evolution safety | ⚠️ Partial | Router no longer spawns workers, but service still shells out and router still performs DB state/query logic. |

---

# P0 blockers

## P0-1. Default backend is still `legacy` after legacy removal

### Evidence

`src/grace_control/config/settings.py` still declares:

```python
execution_backend: str = "legacy"  # "legacy" | "api" | "mock" — see grace_control.agent.select_backend
```

But `src/grace_control/agent/__init__.py` explicitly rejects legacy:

```python
if backend_name == "legacy":
    raise ValueError("execution_backend='legacy' was removed in W8 ...")
```

### Impact

Default runtime is broken unless the operator explicitly sets `.grace/config.yaml` or `GRACE_EXECUTION_BACKEND`. A clean install / default config can instantiate `PacketExecutionAdapter`, call `select_backend()`, read `settings.execution_backend`, get `legacy`, and raise.

This directly contradicts W8 and API-first runtime.

### Required fix

1. Change default:

```python
execution_backend: str = "api"
```

or, if real API providers are not ready:

```python
execution_backend: str = "mock"
```

but do **not** default to `legacy`.

2. Update comment to:

```python
# "api" | "mock" — legacy removed in W8
```

3. Ensure `.grace/config.yaml` default template also uses `api` or `mock`.

4. Add regression tests:

- default `select_backend()` does not raise;
- `settings.execution_backend != "legacy"`;
- `select_backend("legacy")` raises a clear W8 error;
- clean environment + no config can start API and create PacketExecutionAdapter.

---

## P0-2. `packet_executor.py` still violates W3/W6/W8/W10

### Evidence

`src/grace_control/adapters/packet_executor.py` still:

- imports `os`;
- uses `os.environ.get("GRACE_BASE_REF", settings.base_branch)`;
- imports `subprocess` and `shutil` inside `_load_packet`;
- runs direct git worktree/branch cleanup;
- hardcodes branch format `agent/default/{packet_id}/{slug}`;
- calls `_call_legacy_runner`;
- logs `legacy_runner_completed`;
- is heavily compressed into semicolon-heavy lines;
- does not show the intended extracted services such as `PacketLoader`, `AcceptanceService`, `RunResultWriter`, `EvidenceVerifierService`, `ReviewerService`.

### Impact

This means W6 is not complete. The executor is still a legacy-shaped orchestration blob. It also reintroduces hardcode and direct subprocess patterns that W3/W10 were meant to prevent.

### Required fix

Do a focused W6 follow-up, not another broad wave:

1. Create/extract:

```text
src/grace_control/services/packet_loader.py
src/grace_control/services/acceptance_service.py
src/grace_control/services/evidence_verifier_service.py
src/grace_control/services/reviewer_service.py
src/grace_control/services/run_result_writer.py
src/grace_control/services/self_evolution_guard_service.py
```

2. Remove from `packet_executor.py`:

```text
import os
import subprocess
import shutil
os.environ.get(...)
_call_legacy_runner
legacy_runner_completed
agent/default/{packet_id}/{slug}
```

3. Use:

```text
settings.base_branch
GitService / WorktreeInspector
ExecutionBackend.run
RunResultWriter
AcceptanceService
```

4. Target style:

- no semicolon-compressed code;
- public methods have contracts;
- clear logical `START_BLOCK_*` sections;
- preferably <250 lines, but readability matters more than gaming the line count.

### Required tests

- GraceLint fails if `packet_executor.py` contains direct `subprocess` or `os.environ`.
- Packet execution works with `MockBackend`.
- PacketExecutionAdapter does not import/call legacy concepts.
- No hardcoded legacy branch format remains in executor.

---

# P1 high priority

## P1-1. GraceLint rules exist but are too permissive

### Evidence

`src/grace_control/tools/grace_lint/checker.py` defines `GRC100..GRC108`, but:

- `ALLOWED_SUBPROCESS = {"services/git_service.py", "services/", "scripts/", "tests/"}` allows subprocess in **any service**, including self-evolution service.
- `_check_subprocess()` ignores lines containing `import`, so `import subprocess` alone is not flagged.
- `.grace/lint_allowlist.yaml` still contains W11-expiring exceptions for `packet_executor.py` even though W11 is reported complete.
- Allowlist has no enforcement that `expires_wave` is already expired.

### Impact

The linter can report “14 rules implemented” while still allowing the debt the rules were designed to stop.

### Required fix

1. Tighten allowed subprocess paths to explicit files only:

```text
src/grace_control/services/git_service.py
scripts/
tests/
```

Do **not** allow all `services/`.

2. Flag both:

```python
import subprocess
subprocess.run(...)
```

outside allowlist.

3. Enforce `expires_wave`:

- if current wave is W11 or later, entries with `expires_wave: W11` are invalid;
- expired allowlist entries should fail lint.

4. Remove or update expired allowlist entries:

```text
GRC100 packet_executor.py expires W11
GRC101 packet_executor.py expires W11
GRC101 llm_runner.py expires W11
GRC103 packet_executor.py expires W11
```

5. Add regression tests for expired allowlist and import-only subprocess.

---

## P1-2. Self-evolution still uses direct subprocess and router owns DB mutation/query

### Evidence

`src/grace_control/services/self_evolution_service.py` uses direct `subprocess.run(["git", "rev-parse", "HEAD"], ...)` to build rollback metadata.

`src/grace_control/api/routers/self_evolution.py` directly queries `SelfEvolutionSession`, lists sessions, fetches session, and mutates `s.status = "cancelled"` in the router.

### Impact

W11 says self-evolution must be controlled by service/job model and not become a side-channel. The router no longer spawns workers, which is good, but business/query/mutation logic is still split between router and service, and direct git subprocess bypasses GitService.

### Required fix

1. Replace direct subprocess in self-evolution service with `GitService.current_sha()` or a dedicated `RollbackService` using GitService.
2. Move list/get/cancel logic into `SelfEvolutionService`:

```text
list_sessions(limit, offset)
get_session(session_id)
cancel_session(session_id)
```

3. Router should translate HTTP only.
4. Add tests:

- no subprocess import/use in self-evolution service;
- cancel goes through service;
- router has no direct `SelfEvolutionSession` DB mutation;
- rollback metadata still includes base commit.

---

## P1-3. ApiAgentBackend is structural only; real API providers are unsupported

### Evidence

`AgentGatewayService._call_provider()` succeeds only for `provider == "mock"`; all real providers return `provider '<x>' not yet implemented`.

### Impact

W7 “ApiAgentBackend MVP” exists structurally, but the project is not yet actually running agents through API unless `mock` is used. This is acceptable only if explicitly declared as MVP/mock-only. It is not enough for “CLI/legacy removed and everything runs through API agents”.

### Required fix options

Choose one and document it:

#### Option A — honest MVP

- Set default backend to `mock`.
- Document that real provider adapters are a follow-up W7.1.
- Add `docs/grace/API_AGENT_BACKEND_LIMITATIONS.md`.

#### Option B — usable API path

- Implement at least one real provider/router path used by the project.
- Persist request/response artifacts.
- Add tests with fake provider hook.

Recommended: Option A now, then W7.1 for real provider integration.

---

# P2 medium / cleanup

## P2-1. Package metadata still says “with Prefect”

`pyproject.toml` still has:

```toml
description = "GRACE methodology orchestrator — LLM-driven development with Prefect"
```

After W8 this is stale and misleading.

Required:

```toml
description = "GRACE methodology orchestrator — API-first LLM-driven development control plane"
```

## P2-2. Runtime dependencies still include CLI/UI libraries

`pyproject.toml` still includes `typer` and `rich` in runtime dependencies even after public CLI removal.

Required:

- Move `typer` / `rich` to dev optional dependencies unless used by runtime code.
- Add package metadata test: runtime deps do not include CLI-only packages.

## P2-3. Global exception handler leaks raw exception messages

`app_factory.py` returns:

```python
{"error": {"code": "INTERNAL_ERROR", "message": str(exc)[:200]}}
```

This is acceptable for local dev but not for remote API. Later replace with trace_id + generic message, log internal detail server-side.

Not a blocker for current wave, but should be tracked before multi-user/remote deployment.

---

## Positive findings

### Packaging cleanup is mostly correct

`pyproject.toml` now packages only:

```toml
packages = ["src/grace_control"]
```

and public CLI entrypoints are removed. Good.

### App factory split is good

`api/main.py` is now wiring-only and `api/app_factory.py` wires routers centrally. This satisfies the main W5 intent.

### Trace API exists

`api/routers/trace.py` exposes:

```text
GET /api/trace/packets/{packet_id}
GET /api/trace/features/{feature_id}
GET /api/trace/runs/{run_id}
GET /api/trace/search
```

This is aligned with W4.

### Legacy package import search looks clean at high level

A repository search for `prefect_grace` returned no direct results in current indexed search, which supports W8 direction. Still, the executor keeps legacy naming/flow assumptions and must be cleaned.

---

# Required next patch

Create a follow-up packet:

```text
fix: close W0-W11 completion audit blockers
```

Scope:

```text
src/grace_control/config/settings.py
src/grace_control/adapters/packet_executor.py
src/grace_control/services/* execution split files
src/grace_control/tools/grace_lint/checker.py
.grace/lint_allowlist.yaml
src/grace_control/services/self_evolution_service.py
src/grace_control/api/routers/self_evolution.py
pyproject.toml
tests/grace_control/*
```

Acceptance:

1. Default `settings.execution_backend` is not `legacy`.
2. Clean environment can instantiate default backend without raising.
3. `packet_executor.py` contains no direct `os.environ`, no direct `subprocess`, no hardcoded legacy branch format, no `_call_legacy_runner` naming.
4. GraceLint catches direct `import subprocess` outside explicit allowlist.
5. Expired allowlist entries fail lint.
6. Self-evolution uses GitService/Service methods, not direct subprocess or router DB mutation.
7. `pyproject.toml` no longer says Prefect and runtime deps do not include CLI-only packages unless runtime usage is proven.
8. Tests cover these regressions.

Do not claim W0-W11 complete until these pass.
