# Final audit: W0-W12 vs TZ

Date: 2026-06-05
Scope: full audit against `source/codex/tz-api-first-cleanup-waves-w0-w11.md` plus W12 evidence-dir follow-up.

## Verdict

Not fully accepted yet.

The main runtime architecture is now in the intended shape:

- API/OpenAPI is the control plane.
- Public GRACE CLI entrypoints are removed.
- Legacy Prefect is not packaged in runtime.
- `UniversalCliAgentBackend` exists and runs local CLI agents by declarative profiles.
- W12 evidence path propagation is implemented: `PacketExecutionAdapter -> ExecutionRequest.evidence_dir -> UniversalCliAgentBackend -> AgentRunService.run_dir -> AgentArtifactCollector`.

However, the project is not fully ready under the written TZ because several canon/documentation guardrails still contradict the implementation.

The remaining issues are mostly not runtime blockers, but they are blockers for claiming “W0-W12 fully complete” because the TZ explicitly requires executable canon, no stale docs, and no hidden hardcoded agent command execution code.

---

## Accepted areas

### A1. Runtime package and CLI removal

Accepted.

`pyproject.toml` packages only `src/grace_control`, and public GRACE/legacy CLI entrypoints are removed. The file explicitly documents that public entrypoints were removed in W2 and legacy scripts were removed in W8.

### A2. Legacy Prefect removed from runtime package

Accepted.

A repository search for `prefect_grace` returned no current indexed runtime references during this audit, and `pyproject.toml` no longer packages `src/prefect_grace`.

### A3. API app factory and routers

Accepted.

`api/main.py` is no longer the old monolith; `api/app_factory.py` wires routers centrally, including trace, tools, agents, artifacts, diagnostics, self-evolution, etc.

### A4. UniversalCliAgentBackend direction

Accepted functionally.

The project now has:

- `UniversalCliAgentBackend` implementing `ExecutionBackend`;
- `AgentRunService`;
- `CommandTemplateRenderer`;
- `AgentEnvBuilder`;
- `ProcessSupervisor`;
- `AgentArtifactCollector`;
- top-level `agents:` profiles.

The previous W7 blockers around profile lookup, worktree path, exit-code semantics, stdin mode, env inheritance, cwd rendering, and async route were addressed.

### A5. W12 evidence directory propagation

Accepted.

`ExecutionRequest` now has:

```python
evidence_dir: Path | None = None
```

`PacketExecutionAdapter` computes:

```python
evidence_dir = self.state_root / "packets" / packet_id / "runs" / f"R{run_number:02d}"
```

passes it into `ExecutionRequest`, and `UniversalCliAgentBackend` forwards it as `run_dir=request.evidence_dir` into `AgentRunService`. `AgentRunService` then passes that directory to `AgentArtifactCollector`, which writes `agent_stdout.log`, `agent_stderr.log`, and `agent_command.log` there.

---

# Remaining blockers

## P1-1. GraceLint is out of sync with the revised W7 architecture

### Problem

The revised TZ allows direct env building only in config/tests/explicit agent env builder, and direct subprocess only in GitService/WorktreeCleanupService/UniversalCliAgentBackend/process runner style code.

Current GraceLint rules are too narrow for the new W7 services:

```python
ALLOWED_ENV = {"config/", "tests/", "scripts/", "tools/"}
ALLOWED_SUBPROCESS = {"services/git_service.py", "services/worktree_cleanup_service.py", "scripts/", "tests/"}
```

But W7 intentionally introduced:

- `src/grace_control/services/agent_env_builder.py`, which reads `os.environ` by design;
- `src/grace_control/services/process_supervisor.py`, which uses `asyncio.subprocess` by design.

### Impact

The canonical W7 implementation is likely to be flagged by the canonical linter. This means the “executable canon” is internally inconsistent.

### Required fix

Update GraceLint allow/ownership rules to include explicit W7 execution boundary files, not broad directories:

```text
GRC100 allowed:
- src/grace_control/config/*
- src/grace_control/services/agent_env_builder.py
- tests/*
- scripts/*

GRC101 allowed:
- src/grace_control/services/git_service.py
- src/grace_control/services/worktree_cleanup_service.py
- src/grace_control/services/process_supervisor.py
- tests/*
- scripts/*
```

Do not allow all `services/`.

Add tests:

- `agent_env_builder.py` passes GRC100 by design;
- arbitrary service using `os.environ` fails GRC100;
- `process_supervisor.py` passes GRC101 by design;
- arbitrary service using subprocess fails GRC101.

---

## P1-2. GRC109 from the revised TZ is not implemented

### Problem

The revised TZ explicitly requires:

```text
GRC109 no hardcoded agent command names in execution code; commands must come from profiles/config
```

But `checker.py` currently enables rules only up to GRC108 plus GRC030/GRC100–GRC106. There is no GRC109 implementation or entry in `DEFAULT_RULES`.

### Impact

The linter does not enforce one of the central guarantees of the revised W7: local CLI commands like `opencode`, `codex`, `agy`, `gemini`, `claude` must live in config profiles, not execution code.

### Required fix

Implement GRC109:

- scan runtime execution code for hardcoded CLI agent command names;
- allow them in `src/grace_control/config/agent_profiles.yaml`, docs, tests, and maybe explicit examples;
- fail if hardcoded names appear in backend/executor/services code outside config/tests/docs.

Add tests:

- hardcoded `opencode` in service code fails GRC109;
- same string in config profile is allowed;
- same string in docs/tests is allowed.

---

## P1-3. `core/llm_runner.py` remains a hidden hardcoded CLI runner

### Problem

`src/grace_control/core/llm_runner.py` still exists in runtime source and hardcodes CLI agent commands:

```python
cli: str = "opencode"
...
cmd = ["opencode", "run", "--model", model, instruction]
...
cmd = ["agy", "--print", prompt_text]
```

It also reads `os.environ` directly and spawns subprocesses directly.

This conflicts with the revised architecture:

```text
GRACE API/OpenAPI = control plane
UniversalCliAgentBackend = configurable local CLI execution adapter
opencode/codex/agy/etc. = config, not hardcoded in orchestration code
```

### Impact

Even if it is currently unused, it is still runtime source under `src/grace_control/core/`, and it preserves exactly the hardcoded local-agent execution path the revised W7/TZ was meant to remove.

### Required fix options

Choose one:

#### Option A — delete/archive

If unused, move it to archived docs/test fixture or delete it.

#### Option B — refactor through UniversalCliAgentBackend

Replace direct command construction with agent profile lookup + `AgentRunService` / `UniversalCliAgentBackend`.

#### Option C — explicitly mark as temporary and enforce expiry

Keep it only with a strict allowlist expiry and a dedicated cleanup task, but then W0-W12 should not be claimed fully complete.

Recommended: Option A if no current production imports use it.

---

## P1-4. W12-expiring allowlist entries remain after W12

### Problem

`.grace/lint_allowlist.yaml` still contains entries with:

```yaml
expires_wave: W12
```

for:

```text
GRC101 src/grace_control/core/llm_runner.py
GRC103 src/grace_control/adapters/packet_executor.py
GRC108 src/grace_control/adapters/packet_executor.py
GRC108 src/grace_control/services/evidence_service.py
```

### Impact

If W12 is complete, W12-expiring entries should either be removed, converted to `never` with a strong permanent ownership reason, or handled by an explicit `W13` cleanup plan. Keeping expired W12 entries makes the allowlist expiry mechanism meaningless.

### Required fix

- Remove `llm_runner.py` GRC101 allowlist by deleting/refactoring `llm_runner.py`.
- Either remove or reclassify `packet_executor.py` and `evidence_service.py` GRC108 entries with precise long-term ownership.
- Implement/enforce allowlist expiry validation, so expired entries fail lint.

---

## P1-5. Documentation is stale after the revised W7

### Problem

`README.md` still links Execution Backends as:

```text
Execution Backends — `api` / `mock` (legacy removed in W8)
```

but the current default backend is `cli`, and the revised W7 strategic path is `UniversalCliAgentBackend`.

`docs/grace/EXECUTION_BACKENDS.md` is also stale:

- it still says GRACE supports `legacy`, `api`, and `mock`;
- it says `ApiAgentBackend` is the strategic path;
- it documents `/api/agents/run` with `provider` instead of `executor_id`;
- it says legacy remains default until W8, which is no longer true.

### Impact

W9 documentation cleanup is not fully valid anymore after the revised W7. The active docs now contradict the code and the updated TZ.

### Required fix

Update at minimum:

```text
README.md
docs/grace/EXECUTION_BACKENDS.md
docs/grace/CONFIGURATION.md
docs/grace/API_FIRST_CONTROL_PLANE.md if it mentions api/mock only
```

Execution Backends doc should now say:

```text
cli  -> UniversalCliAgentBackend, default runtime backend
mock -> tests/smoke
api  -> optional/legacy-ish HTTP provider adapter if retained, not strategic default
legacy -> removed in W8 and rejected by select_backend("legacy")
```

Also regenerate docs/OpenAPI if `/api/agents/run` schema changed.

---

# P2 / non-blocking issues

## P2-1. Test suite still has one pre-existing failure

Reported state:

```text
399 passed, 1 pre-existing fail
```

This does not block the architecture audit if truly unrelated, but it blocks a “fully green” readiness claim. It should be isolated into a maintenance packet and either fixed or explicitly quarantined with reason.

## P2-2. Global API exception handler still exposes raw error text

`api/app_factory.py` still returns `str(exc)[:200]` in 500 responses. This is acceptable for local/dev but should be changed before remote/multi-user deployment.

---

## Final readiness assessment

### Runtime architecture

Mostly ready.

The project now has the intended shape:

```text
API/OpenAPI control plane
UniversalCliAgentBackend local CLI execution adapter
Legacy Prefect removed from package
CLI control plane removed
Trace/artifacts/evidence API in place
```

### TZ/canon completion

Not fully ready.

The following must be fixed before saying “everything is done by TZ”:

1. Sync GraceLint with W7 execution boundary (`agent_env_builder`, `process_supervisor`).
2. Implement GRC109.
3. Delete/refactor/archive `core/llm_runner.py`.
4. Remove or reclassify W12-expiring allowlist entries and enforce expiry.
5. Update stale docs, especially `README.md` and `docs/grace/EXECUTION_BACKENDS.md`.
6. Address or quarantine the one pre-existing failing test.

## Recommended next packet

Title:

```text
fix: close final TZ/canon drift after W12
```

Scope:

```text
src/grace_control/core/llm_runner.py
src/grace_control/tools/grace_lint/checker.py
.grace/lint_allowlist.yaml
README.md
docs/grace/EXECUTION_BACKENDS.md
docs/grace/CONFIGURATION.md
docs/openapi.json if schema changed
tests/grace_control/tools/test_grace_lint.py
tests/grace_control/agent/*
```

Acceptance:

1. GraceLint allows only explicit W7 env/subprocess boundary files.
2. GRC109 exists and is enabled by default.
3. No hardcoded local CLI agent command names exist in runtime execution code outside config/tests/docs.
4. `llm_runner.py` is deleted, archived, or refactored through UniversalCliAgentBackend.
5. No `expires_wave: W12` entries remain after W12, unless converted to explicit permanent ownership.
6. Active docs describe `cli`/UniversalCliAgentBackend as the default runtime backend.
7. Test suite is either fully green or the one pre-existing failure is explicitly quarantined with a documented reason.
