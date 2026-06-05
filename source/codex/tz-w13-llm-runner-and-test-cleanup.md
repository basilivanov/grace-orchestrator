# ТЗ: W13 — resolve `llm_runner.py` and final test cleanup

Date: 2026-06-05
Repo: `basilivanov/grace-orchestrator`

Related reviews:

```text
source/codex/review-2026-06-05-866509c-final-canon-drift.md
source/codex/final-audit-2026-06-05-w0-w12-vs-tz.md
```

## Контекст

W0–W12 refactor/audit loop accepted the new architecture:

```text
GRACE API/OpenAPI = public control plane
UniversalCliAgentBackend = local CLI agent execution adapter by config
Legacy Prefect = removed from runtime package
Public GRACE CLI = removed as control plane
Trace/artifacts/evidence = API-visible canonical paths
GraceLint = executable canon guardrail
```

Остались два follow-up хвоста:

1. `src/grace_control/core/llm_runner.py` — pre-W7 runner, который всё ещё напрямую строит CLI-команды (`opencode`, `agy`) и запускает subprocess.
2. Один pre-existing failing test — сейчас отчёт выглядит как `401 passed, 1 pre-existing fail`.

Цель W13 — не продолжать широкий рефакторинг, а закрыть эти два хвоста аккуратным maintenance-пакетом.

---

# Часть A — Resolve `core/llm_runner.py`

## Проблема

`src/grace_control/core/llm_runner.py` сейчас оставлен в allowlist как W13 debt:

```yaml
- rule: GRC101
  path: src/grace_control/core/llm_runner.py
  reason: pre-W7 runner — architect/verifier/reviewer gate use run_llm; to be refactored through UniversalCliAgentBackend in W13
  expires_wave: W13

- rule: GRC109
  path: src/grace_control/core/llm_runner.py
  reason: pre-W7 runner hardcodes opencode/agy; to be refactored in W13
  expires_wave: W13
```

Это честная временная отсрочка, но не финальное состояние. После W13 этих исключений быть не должно.

## Required first step: call-site audit

Перед изменением кода найти все реальные call sites:

```bash
grep -RIn "run_llm\|llm_runner" src tests scripts docs .grace 2>/dev/null
```

Составить короткий список в PR/evidence summary:

```text
call site
role/use case
sync/async path
can delete? yes/no
replacement path
```

Особенно проверить:

```text
architect flow
context collector
verifier/reviewer gate
self-evolution
legacy/archive docs/tests
```

## Допустимые решения

Выбрать один путь. Предпочтительный порядок — A, потом B, потом C.

### Option A — delete/archive if unused

Если `run_llm()` реально не используется runtime-кодом:

1. Удалить `src/grace_control/core/llm_runner.py`.
2. Удалить allowlist entries `GRC101` и `GRC109` для `llm_runner.py`.
3. Если исторический контекст нужен — добавить короткий archived note:

```text
docs/archived/stale/llm_runner-pre-w7.md
```

4. Добавить тест/grep, что runtime source не импортирует `llm_runner`.

Acceptance:

```text
No src runtime import references llm_runner.
No allowlist entries for llm_runner.py.
GraceLint passes without llm_runner exceptions.
```

### Option B — refactor through UniversalCliAgentBackend

Если `run_llm()` всё ещё нужен architect/verifier/reviewer flow:

1. Не строить команды напрямую в `llm_runner.py`.
2. Не использовать direct `asyncio.create_subprocess_exec` там.
3. Не читать `os.environ` там.
4. Сделать thin adapter over W7 components:

```text
run_llm(...)
  -> load agent profile by role/executor_id
  -> build ExecutionRequest
  -> UniversalCliAgentBackend.run(request)
  -> parse/return stdout or structured error
```

5. Команды (`opencode`, `agy`, `codex`, etc.) должны жить только в `agent_profiles.yaml` / project config.
6. `llm_runner.py` после refactor не должен требовать `GRC101` или `GRC109` allowlist.

Acceptance:

```text
llm_runner.py contains no hardcoded opencode/codex/agy/gemini/claude.
llm_runner.py contains no subprocess usage.
llm_runner.py contains no direct os.environ usage.
run_llm() still satisfies call sites.
Tests cover run_llm via fake UniversalCliAgentBackend/local fake command.
```

### Option C — remove run_llm API and migrate call sites

Если `run_llm()` нужен только из старых flows, но лучше убрать API:

1. Переписать call sites напрямую на service/backend path.
2. Удалить `llm_runner.py`.
3. Удалить allowlist entries.
4. Добавить regression tests по каждому migrated call site.

Acceptance:

```text
No run_llm public function remains.
All former call sites use UniversalCliAgentBackend/AgentRunService or domain-specific service.
No llm_runner allowlist entries remain.
```

## Что НЕ делать

Не делать так:

```text
- не продлевать llm_runner.py на expires_wave: never
- не оставлять hardcoded opencode/agy в runtime source
- не добавлять новый parallel runner рядом с UniversalCliAgentBackend
- не возвращать public CLI control plane
- не отключать GRC109 ради прохождения lint
```

---

# Часть B — GraceLint / allowlist cleanup

## Цель

После W13 allowlist не должен содержать W13 debt по `llm_runner.py`.

## Требования

1. Удалить из `.grace/lint_allowlist.yaml`:

```yaml
GRC101 src/grace_control/core/llm_runner.py
GRC109 src/grace_control/core/llm_runner.py
```

если выбран Option A/C.

2. Если выбран Option B, `llm_runner.py` должен пройти GRC101/GRC109 без исключений.

3. Добавить или усилить тесты GraceLint:

```text
- hardcoded opencode/codex/agy/gemini/claude in runtime service fails GRC109
- same names in config/docs/tests are allowed
- allowlist has no entries with expires_wave <= W13 after W13 completes
- no duplicate (rule, path) allowlist pairs
```

4. Если в allowlist остаются permanent `never` entries, у них reason должен описывать постоянное ownership-правило, а не “to be refactored”.

## Acceptance criteria

```text
.grace/lint_allowlist.yaml has no llm_runner.py entries after W13.
.grace/lint_allowlist.yaml has no expires_wave: W13 entries after W13.
GRC109 remains enabled by default.
GraceLint tests cover hardcoded CLI agent names.
```

---

# Часть C — One pre-existing failing test

## Проблема

Текущее состояние отчётов:

```text
401 passed, 1 pre-existing fail
```

Даже если fail не связан с W0–W12/W13, его нужно либо исправить, либо формально заquarantine’ить с причиной.

## Required first step: identify exact failure

Запустить полный тестовый набор и сохранить точное имя failing test:

```bash
pytest -q
```

В evidence summary записать:

```text
failing test name
file
failure message
first failing assertion/exception
is product bug or stale test?
```

Если уже известно, что это `test_recovery_real_db`, всё равно подтвердить текущим запуском.

## Decision tree

### Case 1 — real bug

Если тест показывает реальный bug:

1. Исправить код.
2. Добавить regression test, если текущий тест слишком broad.
3. Убедиться, что полный suite зелёный.

Acceptance:

```text
pytest passes fully.
Bug behavior documented in PR/evidence summary.
```

### Case 2 — stale test

Если тест устарел после API-first/legacy removal:

1. Переписать тест под новую архитектуру.
2. Не удалять coverage молча.
3. Если старое поведение больше не поддерживается, добавить explicit assertion на новый expected behavior.

Acceptance:

```text
Test updated to current architecture.
No coverage hole introduced.
pytest passes fully.
```

### Case 3 — environment-only flaky/integration test

Если тест требует внешней среды / реальной DB / timing и не должен блокировать unit suite:

1. Mark with explicit pytest marker, e.g.:

```python
@pytest.mark.integration
@pytest.mark.requires_real_db
```

2. Exclude from default unit command only intentionally.
3. Document exact command to run it:

```text
pytest -m integration
```

4. Add reason in docs/tests note.

Acceptance:

```text
Default pytest command is green.
Integration test is still runnable by explicit marker.
Quarantine has documented reason and owner.
```

## Что НЕ делать

Не делать так:

```text
- не просто skip без reason
- не удалять тест без replacement/evidence
- не считать “pre-existing” достаточной причиной оставить красным default suite
```

---

# Files likely involved

```text
src/grace_control/core/llm_runner.py
src/grace_control/agent/universal_cli_backend.py
src/grace_control/services/agent_run_service.py
src/grace_control/config/agent_profiles.py
src/grace_control/config/agent_profiles.yaml
.grace/lint_allowlist.yaml
tests/grace_control/core/test_grace_lint.py
tests/grace_control/agent/*
tests/grace_control/api/test_agents_api.py
failing test file from pytest output
docs/grace/EXECUTION_BACKENDS.md if behavior changes
docs/grace/TESTING_STRATEGY.md if quarantine/markers are introduced
```

---

# W13 Definition of Done

W13 is done when:

1. `llm_runner.py` is deleted, archived, or refactored through `UniversalCliAgentBackend`.
2. There are no `llm_runner.py` entries in `.grace/lint_allowlist.yaml` after W13.
3. No runtime source hardcodes local CLI agent command names outside config/tests/docs.
4. GRC109 is still enabled and has regression tests.
5. The one pre-existing failing test is either fixed or explicitly quarantined with marker/reason/command.
6. Default test command is green, or the only excluded tests are documented integration/quarantine cases.
7. Evidence summary lists the selected option, call-site audit, tests run, and remaining risks.

## Recommended packet title

```text
fix(W13): resolve legacy llm_runner and make default tests green
```

## Non-goals

```text
- do not implement new product features
- do not redesign UniversalCliAgentBackend
- do not add MCP
- do not reintroduce public GRACE CLI
- do not do broad docs rewrite beyond required changes
```
