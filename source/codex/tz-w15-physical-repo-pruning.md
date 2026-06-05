# ТЗ: W15 — physical repo pruning / удалить всё лишнее

Date: 2026-06-05
Repo: `basilivanov/grace-orchestrator`

## Цель

После W0–W14 проект приведён к новой API-first архитектуре, но в репозитории всё ещё видны следы переходного периода: архивы, временные ТЗ/ревью, устаревшие docs, legacy-like back-compat конфиги и optional backend’и. W15 — destructive cleanup: физически удалить всё, что не относится к текущему состоянию проекта.

Правило W15:

```text
Если файл не нужен текущему runtime / tests / CI / canonical docs — удалить из репозитория.
Не архивировать внутри repo без сильной причины. История уже есть в git.
```

---

## Current architecture baseline

Оставляем только эту архитектуру:

```text
GRACE API/OpenAPI = public control plane
UniversalCliAgentBackend = default execution adapter for local CLI agents
MockBackend = tests/smoke
scripts/ = CI/dev wrappers only
docs/grace = current canonical docs only
docs/openapi.json, packet-states.md, state-diagram.md = generated docs
```

Удаляем всё, что описывает/поддерживает старую схему:

```text
legacy Prefect archive
old API backend as strategic path
old codex.executors profile format if no live call site remains
source/codex review chain and old TZ artifacts
stale docs that point to source/codex waves as current truth
unused scripts/utilities
runtime artifacts / generated local state
```

---

# Inventory I checked from current repo snapshot

This is not a full `git ls-files` output, but these are concrete files/areas observed during audit and must be handled by W15.

## A. Docs / archive candidates

### Delete candidates

```text
docs/archived/legacy_prefect_grace/**
docs/archived/codex/**
docs/archived/stale/**
docs/grace/LEGACY_REMOVAL.md
source/codex/roadmap-api-first-legacy-cli-hardcode-cleanup.md
source/codex/tz-api-first-cleanup-waves-w0-w11.md
source/codex/tz-w13-llm-runner-and-test-cleanup.md
source/codex/tz-w14-production-readiness-and-ops-hardening.md
source/codex/review-2026-*.md
source/codex/final-audit-2026-*.md
source/codex/tz-w15-physical-repo-pruning.md  # keep only until W15 is accepted; then remove or replace by final note
```

Rationale:

- `docs/README.md` currently links archived legacy/codex/stale docs. After W15, docs should not advertise internal archaeology.
- `docs/grace/LEGACY_REMOVAL.md` is only useful because the legacy archive remains. If the archive is physically deleted, this doc should be deleted too or reduced to one line in release history.
- `source/codex/*` is an implementation/audit trail, not product/runtime documentation. It should not be part of the long-term clean repo.

### Rewrite/keep candidates

```text
README.md
docs/README.md
docs/grace/ARCHITECTURE.md
docs/grace/API_FIRST_CONTROL_PLANE.md
docs/grace/CONFIGURATION.md
docs/grace/EXECUTION_BACKENDS.md
docs/grace/EXECUTION_PIPELINE.md
docs/grace/GRACE_LINT_RULES.md
docs/grace/TESTING_STRATEGY.md
docs/grace/TRACE_AND_OBSERVABILITY.md
docs/grace/SELF_EVOLUTION.md
docs/grace/RUNBOOK_*.md
docs/openapi.json
docs/packet-states.md
docs/state-diagram.md
```

But these must be updated to current truth.

Observed stale doc examples that must be fixed:

```text
docs/grace/ARCHITECTURE.md
  says execution backend is api_backend strategic and packet_executor ~700 lines.

docs/grace/CONFIGURATION.md
  shows execution.backend: legacy and old allowlist/direct env-read notes.

docs/grace/API_FIRST_CONTROL_PLANE.md
  says Legacy Prefect is isolated behind legacy_backend.py until W8 and links old source/codex roadmap/TZ.

docs/grace/EXECUTION_PIPELINE.md
  says _call_legacy_runner and ApiAgentBackend / MockBackend, not UniversalCliAgentBackend.

docs/grace/GRACE_LINT_RULES.md
  misses GRC109 and shows old allowlist example expiring W11.

docs/grace/TESTING_STRATEGY.md
  still mentions one pre-existing fail, but suite is now green by report.
```

---

## B. Runtime code / legacy-like candidates

### Must review/delete/refactor

```text
src/grace_control/core/executor_selector.py
src/grace_control/agent/api_backend.py
src/grace_control/services/agent_gateway_service.py
src/grace_control/config/agent_profiles.yaml  # remove `codex:` section if executor_selector removed
```

Rationale:

- Current strategic path is `UniversalCliAgentBackend` + top-level `agents:` profiles.
- `core/executor_selector.py` still reads `codex.executors`, hardcodes default `command: agy`, and uses `GRACE_AGENT_PROFILES_PATH` directly.
- `agent_profiles.yaml` still contains a large `codex:` back-compat section with old `command: opencode/agy` string shape.
- `ApiAgentBackend` + `AgentGatewayService` are optional HTTP-provider MVP with only mock/unsupported providers. If not used by runtime/tests, remove them and delete `execution_backend=api` support.

### Must keep unless unused by grep/tests

```text
src/grace_control/agent/backend.py
src/grace_control/agent/universal_cli_backend.py
src/grace_control/agent/mock_backend.py
src/grace_control/services/agent_run_service.py
src/grace_control/services/command_template_renderer.py
src/grace_control/services/agent_env_builder.py
src/grace_control/services/process_supervisor.py
src/grace_control/services/agent_artifact_collector.py
src/grace_control/config/agent_profiles.py
src/grace_control/config/agent_profiles.yaml  # only `agents:` + verification if still used
```

### Review for active use, do not delete blindly

```text
src/grace_control/core/context_collector.py
src/grace_control/core/telegram_notify.py
src/grace_control/core/self_evolution_guard.py
src/grace_control/core/command_runner.py
src/grace_control/core/prompts/*.md
```

Rationale:

- `context_collector.py` still defaults to `cli="opencode"` and reads env directly. Refactor to profile id/settings if active, delete if unused.
- `telegram_notify.py` is optional notification channel. If not wired into current product, delete; if desired, move to explicit notification service/config and tests.
- `self_evolution_guard.py` uses subprocess by design for guard checks. Keep if current self-evolution path uses it; otherwise delete.
- `command_runner.py` is current deterministic acceptance command runner; likely keep.
- prompts are used by evidence verifier/reviewer/architect flows; keep only prompts with live call sites.

---

## C. Scripts / root utilities

### Keep candidates

```text
Makefile
.github/workflows/ci.yml
scripts/generate_docs.py
scripts/grace_lint.py
scripts/ci_repo_hygiene.py
```

### Review/delete candidates

Run:

```bash
git ls-files scripts/ .github/ | sort
```

Then delete any script that is not called by:

```text
Makefile
.github/workflows/ci.yml
docs/runbooks
tests
```

Known current scripts from audit:

```text
scripts/generate_docs.py        # keep: docs/openapi/state generation
scripts/grace_lint.py           # keep: CI wrapper
scripts/ci_repo_hygiene.py      # keep and strengthen
```

W15 should explicitly fail if root utilities/scripts exist with no caller.

---

## D. Tests

### Delete/refactor candidates

```text
tests referencing ApiAgentBackend / AgentGatewayService if backend is removed
tests referencing codex.executors / executor_selector if that path is removed
tests referencing docs/archived or source/codex after docs are deleted
tests expecting legacy/select_backend('api') if api backend removed
tests that only protect deleted transitional behavior
```

### Keep candidates

```text
tests for API routers/services
tests for UniversalCliAgentBackend
tests for GraceLint / GRC109
tests for acceptance pipeline
tests for trace/artifacts/evidence
tests for self-evolution current path
tests for CI repo hygiene
```

---

# Required W15 implementation steps

## Step 1 — Produce exact repo inventory

Coder must run and paste summary into evidence:

```bash
git ls-files | sort > /tmp/grace-files-before.txt
find . -maxdepth 2 -type f | sort > /tmp/grace-root-before.txt
```

Also run focused inventories:

```bash
git ls-files docs source scripts src tests .github .grace | sort
find docs -maxdepth 4 -type f | sort
git ls-files | grep -E 'legacy|prefect|archive|stale|codex|review-2026|tz-w|roadmap|packet_registry|agents/' || true
```

## Step 2 — Call-site audit before every deletion

Before deleting any Python module or config section:

```bash
grep -RIn "module_or_symbol_name" src tests scripts docs .github .grace pyproject.toml Makefile || true
```

Required audits:

```text
executor_selector
select_executor
get_escalation
resolve_model
codex:
ApiAgentBackend
AgentGatewayService
execution_backend.*api
legacy_prefect_grace
LEGACY_REMOVAL
source/codex
prefect_grace
grace_control.cli
packet_registry.yaml
```

## Step 3 — Delete physical legacy/docs archive

Delete, unless a live call site proves otherwise:

```text
docs/archived/**
docs/grace/LEGACY_REMOVAL.md
source/codex/*.md  # except this W15 file while implementing
```

Then update:

```text
docs/README.md
README.md
```

Docs should no longer link to archive/source/codex history.

## Step 4 — Remove old execution compatibility

Preferred final state:

```text
select_backend supports only: cli, mock
ApiAgentBackend removed unless there is a hard current product reason to keep it
AgentGatewayService removed with ApiAgentBackend
executor_selector removed or rewritten to top-level agents profiles
agent_profiles.yaml removes codex: section
anthropic dependency removed from pyproject.toml if only used by removed API backend path
```

If keeping `api` backend, coder must justify in evidence:

```text
why current product needs it
which tests cover it
which docs describe it as non-default
why it is not legacy debt
```

## Step 5 — Rewrite active docs to current truth only

Canonical docs after W15 should be small and current:

```text
README.md
docs/README.md
docs/grace/ARCHITECTURE.md
docs/grace/API_FIRST_CONTROL_PLANE.md
docs/grace/CONFIGURATION.md
docs/grace/EXECUTION_BACKENDS.md
docs/grace/EXECUTION_PIPELINE.md
docs/grace/STATE_MACHINE.md
docs/grace/ACCEPTANCE_PIPELINE.md
docs/grace/TRACE_AND_OBSERVABILITY.md
docs/grace/TESTING_STRATEGY.md
docs/grace/SELF_EVOLUTION.md
docs/grace/GRACE_LINT_RULES.md
docs/grace/RUNBOOK_*.md
docs/openapi.json
docs/packet-states.md
docs/state-diagram.md
```

No active doc should say:

```text
legacy is archived in docs/archived
source/codex is the source of truth
execution backend defaults to api
execution.backend: legacy
_call_legacy_runner
packet_executor is ~700 lines
one pre-existing fail
codex.executors is the new profile format
```

## Step 6 — Strengthen hygiene checks

Extend `scripts/ci_repo_hygiene.py` to fail on:

```text
tracked docs/archived/**
tracked source/codex/review-*.md
tracked source/codex/final-audit-*.md
tracked source/codex/tz-w0..tz-w14 old specs after W15
tracked agents/**
tracked packet_registry.yaml
tracked src/prefect_grace/**
tracked grace_control/cli/**
`prefect_grace` imports in src/tests/scripts/docs except historical release note if kept
`legacy_backend` references
`_call_legacy_runner` references
`execution.backend: legacy` in active docs
`ApiAgentBackend` if api backend is removed
`codex:` section in agent_profiles.yaml if executor_selector removed
```

## Step 7 — Regenerate docs and run gates

```bash
make docs
make ci
pytest tests/grace_control/ -q
python scripts/grace_lint.py src/grace_control tests scripts
python scripts/ci_repo_hygiene.py
```

---

# W15 acceptance criteria

W15 is accepted only when:

1. `docs/archived/**` is gone or explicitly justified file-by-file.
2. Old `source/codex` review/TZ chain is gone from long-term repo state.
3. No active docs point to source/codex or archived legacy as current reference.
4. No active doc contains stale architecture claims listed above.
5. No `src/prefect_grace`, `grace_control.cli`, `legacy_backend`, `_call_legacy_runner`, `packet_registry.yaml` references remain outside git history.
6. `agent_profiles.yaml` contains only current profile format unless old `codex:` path is justified and tested.
7. `executor_selector.py`, `ApiAgentBackend`, `AgentGatewayService`, and `anthropic` dependency are either removed or explicitly justified with current call sites and tests.
8. CI/repo hygiene fails if these deleted categories return.
9. `make ci` passes.
10. Evidence summary includes before/after file counts and deleted-file list.

---

# Suggested packet title

```text
fix(W15): physically prune legacy archives, stale docs, and unused compatibility code
```

## Non-goals

```text
do not add features
do not redesign API
do not add MCP
do not keep files only for archaeology
do not create another archive directory inside repo
do not silently delete active prompts/services without grep evidence
```
