# ТЗ: SolarSage / GRACE Control — MVP deterministic acceptance pipeline

Дата: 2026-06-03  
Проект: `basilivanov/solarsage-astro` / export `grace-orchestrator-export`  
Цель: заменить fake verifier/reviewer в активном runtime-оркестраторе на минимально жизнеспособный deterministic acceptance pipeline: `T0 → T1 → T2 → merge gate`.

---

## 0. Архитектурная правка: куда вносить изменения

В проекте есть два оркестратора:

```text
/tmp/grace-orchestrator-export/
├── src/grace_control/          ← ACTIVE runtime orchestrator
│   ├── api/routers/architect.py
│   ├── worker/worker.py
│   ├── adapters/packet_executor.py
│   └── core/llm_runner.py
│
└── grace/orchestrator/         ← LEGACY SolarSage XML CLI orchestrator
    ├── core.py
    ├── cli.py
    └── validator.py
```

### 0.1. Active runtime

`src/grace_control/` — это основной runtime pipeline:

```text
architect API → plan → worker → packet executor adapter → coder → verifier/reviewer → merge
```

Именно здесь сейчас fake verifier/reviewer, которые статически принимают пакет.

### 0.2. Legacy orchestrator

`grace/orchestrator/` — старый XML/CLI orchestrator:

```text
grace-orch status / next / complete / validate
```

Он:

- читает `development-plan.xml`;
- показывает статус волн;
- валидирует markdown-секции;
- не имеет execution loop;
- не должен получать новый runtime acceptance pipeline.

### 0.3. Главное правило этой задачи

**Не развивать `grace/orchestrator/` как второй runtime.**

Все новые runtime-фичи писать только в:

```text
src/grace_control/
```

В `grace/orchestrator/` можно добавить только короткий deprecation note/README, если нужно, чтобы следующие агенты не продолжали старую ветку.

---

## 1. Что именно нужно получить

Сейчас pipeline примерно такой:

```text
PacketExecutionAdapter.execute()
  ├─ materialize EXECUTION_PACKET.md
  ├─ call coder
  ├─ fake verifier → accepted
  ├─ fake reviewer → accepted
  └─ merge
```

Нужно сделать так:

```text
PacketExecutionAdapter.execute()
  ├─ materialize EXECUTION_PACKET.md
  ├─ call coder
  ├─ collect coder handoff
  ├─ run deterministic acceptance pipeline
  │    ├─ T0: packet contract + scope guard + GRACE lint + cheap checks
  │    ├─ T1: targeted packet tests / verification commands
  │    └─ T2: full profile checks only for NORMAL/STRICT
  ├─ if acceptance failed → rework_required, no merge
  ├─ if acceptance blocked → blocked/escalate, no merge
  ├─ if acceptance passed → accepted
  └─ merge only after accepted report
```

Главный принцип MVP:

> Нельзя принимать пакет без machine-readable `AcceptanceReport` и evidence.

---

## 2. Что НЕ делать в этом пакете

Не делать:

- новый LLM reviewer;
- новый LLM verifier;
- сложный self-evolution policy;
- новую UI-админку;
- Prefect/worker redesign;
- parallel packet execution;
- новый DAG scheduler;
- автоматическое исправление кода acceptance pipeline;
- перенос legacy `grace/orchestrator/` в active runtime;
- покрытие всего репозитория 100%.

Важно:

> Требование 100% coverage относится к новому/изменённому backend-slice `src/grace_control/core/*`, `src/grace_control/adapters/packet_executor.py` и связанным тестам. Не нужно пытаться за один пакет довести весь SolarSage repo до 100%.

---

## 3. Новый пакет работ

Создать новый controller packet, например:

```text
docs/grace-control/W-GC-ACCEPTANCE-MVP.md
```

Если в проекте уже есть каталог для active control-packets, использовать его. Если нет — создать `docs/grace-control/`.

### 3.1. Название

```md
# Controller Packet — W-GC-ACCEPTANCE-MVP: Real deterministic verifier/reviewer gate
```

### 3.2. Allowed write scope

Кодеру разрешено менять только:

```text
src/grace_control/core/contracts.py                 # new
src/grace_control/core/command_runner.py            # new
src/grace_control/core/scope_guard.py               # new
src/grace_control/core/evidence.py                  # new
src/grace_control/core/acceptance_pipeline.py        # new
src/grace_control/core/__init__.py                  # update exports only if needed
src/grace_control/adapters/packet_executor.py        # integrate acceptance before merge
src/grace_control/worker/worker.py                  # only if status/rework handling requires it
src/grace_control/api/routers/architect.py           # only if API status enum serialization requires it
src/grace_control/core/llm_runner.py                 # only if fake verifier/reviewer currently live here
scripts/grace_lint.py                               # small fixes only if acceptance T0 needs them
scripts/test_grace_lint.py                          # tests for small fixes only
scripts/guardrails.sh                               # add acceptance test command only if needed

tests/grace_control/core/test_contracts.py           # new
tests/grace_control/core/test_command_runner.py      # new
tests/grace_control/core/test_scope_guard.py         # new
tests/grace_control/core/test_evidence.py            # new
tests/grace_control/core/test_acceptance_pipeline.py # new
tests/grace_control/adapters/test_packet_executor_acceptance.py # new/extend

docs/grace-control/W-GC-ACCEPTANCE-MVP.md            # new packet doc
grace/orchestrator/README.md                         # optional deprecation note only
```

### 3.3. Frozen / out of scope

Запрещено менять:

```text
grace/orchestrator/core.py
grace/orchestrator/cli.py
grace/orchestrator/validator.py
grace/orchestrator/packet.schema.json
apps/api/app/**
apps/api/alembic/**
app/**
components/**
packages/contracts/**
infra/**
docs/GRACE_CANON.md
production deploy scripts
```

Исключение:

- `grace/orchestrator/README.md` можно добавить/обновить только как deprecation note.

---

## 4. Runtime flow: как должно работать

### 4.1. Active adapter

Найти active execution point:

```text
src/grace_control/adapters/packet_executor.py
```

Там должен быть метод уровня:

```python
PacketExecutionAdapter.execute(...)
```

или аналогичный entrypoint, который сейчас:

1. материализует packet;
2. вызывает coder;
3. получает результат;
4. вызывает fake verifier/reviewer;
5. merge-ит.

Нужно заменить fake acceptance на deterministic pipeline.

### 4.2. Новый flow внутри adapter

Псевдокод:

```python
from src.grace_control.core.acceptance_pipeline import AcceptancePipeline
from src.grace_control.core.contracts import AcceptanceProfile

class PacketExecutionAdapter:
    def execute(self, packet, ...):
        execution_packet = self._materialize_packet(packet)
        coder_result = self._run_coder(execution_packet)

        report = self.acceptance_pipeline.run(
            packet=execution_packet,
            coder_result=coder_result,
            repo_root=self.repo_root,
            base_ref=self.base_ref,
            head_ref=self.head_ref,
        )

        if not report.is_accepted:
            return self._return_rework_or_blocked(packet, report)

        return self._merge_after_acceptance(packet, report)
```

### 4.3. Merge rule

Merge разрешён только если:

```python
report.final_verdict == PacketVerdict.ACCEPTED
and report.t0.status == StageStatus.PASSED
and report.has_required_evidence is True
and report.scope_violations == []
```

Если acceptance не запускался или вернул invalid JSON/dataclass — merge запрещён.

---

## 5. Контракты: `src/grace_control/core/contracts.py`

Создать файл:

```text
src/grace_control/core/contracts.py
```

### 5.1. Обязательные enum

```python
from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any, Literal


class AcceptanceProfile(str, Enum):
    FAST = "FAST"
    NORMAL = "NORMAL"
    STRICT = "STRICT"


class StageName(str, Enum):
    T0_SCOPE_AND_LINT = "T0_SCOPE_AND_LINT"
    T1_TARGETED_TESTS = "T1_TARGETED_TESTS"
    T2_FULL_TESTS = "T2_FULL_TESTS"


class StageStatus(str, Enum):
    PASSED = "passed"
    FAILED = "failed"
    SKIPPED = "skipped"


class PacketVerdict(str, Enum):
    ACCEPTED = "accepted"
    REWORK_REQUIRED = "rework_required"
    BLOCKED = "blocked"
    ESCALATE_TO_ARCHITECT = "escalate_to_architect"
```

### 5.2. Command result

```python
@dataclass(frozen=True)
class CommandResult:
    command: list[str]
    cwd: str
    exit_code: int
    stdout: str = ""
    stderr: str = ""
    duration_ms: int | None = None

    @property
    def passed(self) -> bool:
        return self.exit_code == 0
```

### 5.3. Scope violation

```python
@dataclass(frozen=True)
class ScopeViolation:
    path: str
    reason: str
    violation_type: Literal[
        "out_of_scope",
        "frozen_scope",
        "missing_allowed_scope",
        "invalid_path",
    ]
```

### 5.4. Stage result

```python
@dataclass(frozen=True)
class StageResult:
    name: StageName
    status: StageStatus
    summary: str
    commands: list[CommandResult] = field(default_factory=list)
    blocking_issues: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    skipped_reason: str | None = None
```

Rules:

- `FAILED` требует хотя бы один `blocking_issue` или failed command.
- `SKIPPED` требует `skipped_reason`.
- `PASSED` не должен иметь `blocking_issues`.

### 5.5. Execution packet contract

```python
@dataclass(frozen=True)
class ExecutionPacketContract:
    packet_id: str
    title: str
    allowed_write_scope: list[str]
    frozen_scope: list[str]
    acceptance_profile: AcceptanceProfile
    verification_commands: list[list[str]]
    expected_evidence: list[str] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)
```

Validation rules:

- `packet_id` non-empty.
- `title` non-empty.
- `allowed_write_scope` non-empty.
- `acceptance_profile` required.
- `verification_commands` may be empty only for `FAST`; for `NORMAL/STRICT` must be non-empty.
- All paths must be repo-relative, not absolute.
- No `..` path traversal.

### 5.6. Acceptance report

```python
@dataclass(frozen=True)
class AcceptanceReport:
    packet_id: str
    final_verdict: PacketVerdict
    stages: list[StageResult]
    scope_violations: list[ScopeViolation] = field(default_factory=list)
    evidence_paths: list[str] = field(default_factory=list)
    reasons: list[str] = field(default_factory=list)

    @property
    def is_accepted(self) -> bool:
        return self.final_verdict == PacketVerdict.ACCEPTED
```

Validation rules:

- accepted report requires T0 passed;
- accepted report requires no scope violations;
- accepted report requires no failed stages;
- accepted report requires evidence for `NORMAL/STRICT`;
- if T0 failed, T1/T2 must not be run;
- if final verdict is `ACCEPTED`, `reasons` may be empty or contain positive summary;
- if final verdict is not `ACCEPTED`, `reasons` must be non-empty.

---

## 6. Command runner: `src/grace_control/core/command_runner.py`

Создать файл:

```text
src/grace_control/core/command_runner.py
```

### 6.1. Назначение

Безопасный deterministic runner для acceptance-команд.

Требования:

- не использовать shell=True;
- принимать command as `list[str]`;
- cwd должен быть внутри repo root;
- timeout обязателен;
- stdout/stderr сохранять в `CommandResult`;
- не падать exception наружу при failed command, а возвращать `exit_code != 0`;
- exception runner-а превращать в `CommandResult(exit_code=124/1, stderr=...)`.

### 6.2. API

```python
class CommandRunner:
    def __init__(self, repo_root: Path, default_timeout_s: int = 300) -> None: ...

    def run(
        self,
        command: list[str],
        *,
        cwd: Path | None = None,
        timeout_s: int | None = None,
    ) -> CommandResult: ...
```

### 6.3. Минимальные команды для T0/T1/T2

Pipeline не должен hardcode-ить конкретный package manager везде. Но MVP может использовать команды из packet/verification profile.

T0 defaults:

```python
[
    ["python", "-m", "py_compile", "src/grace_control/core/contracts.py"],
]
```

Если есть `scripts/grace_lint.py`, запускать его только для релевантных changed Python files, где применим GRACE contract.

---

## 7. Scope guard: `src/grace_control/core/scope_guard.py`

Создать файл:

```text
src/grace_control/core/scope_guard.py
```

### 7.1. Назначение

Проверить, что coder не вышел за `allowed_write_scope` и не тронул `frozen_scope`.

### 7.2. API

```python
class ScopeGuard:
    def __init__(self, repo_root: Path) -> None: ...

    def get_changed_files(self, base_ref: str | None = None, head_ref: str | None = None) -> list[str]: ...

    def validate_changed_files(
        self,
        *,
        changed_files: list[str],
        allowed_write_scope: list[str],
        frozen_scope: list[str],
    ) -> list[ScopeViolation]: ...
```

### 7.3. Path matching rules

Поддержать:

```text
exact file: src/grace_control/adapters/packet_executor.py
folder glob: src/grace_control/core/**
folder prefix: src/grace_control/core/
```

Правила:

- frozen scope сильнее allowed scope;
- absolute paths запрещены;
- paths with `..` запрещены;
- deleted files тоже считаются changed;
- empty changed_files допустим, но не accepted для NORMAL/STRICT без evidence.

### 7.4. Git diff command

Если base/head переданы:

```bash
git diff --name-only <base_ref>...<head_ref>
```

Если нет:

```bash
git diff --name-only
```

Для staged changes можно позже добавить отдельный режим, но не в этом MVP.

---

## 8. Evidence collector: `src/grace_control/core/evidence.py`

Создать файл:

```text
src/grace_control/core/evidence.py
```

### 8.1. Назначение

Собрать machine-readable evidence по командам acceptance pipeline.

### 8.2. API

```python
class EvidenceCollector:
    def collect_from_stage(self, stage: StageResult) -> list[str]: ...

    def has_required_evidence(
        self,
        *,
        expected_evidence: list[str],
        collected_evidence: list[str],
        acceptance_profile: AcceptanceProfile,
    ) -> bool: ...
```

### 8.3. MVP policy

Для MVP evidence — это не обязательно физические файлы-артефакты. Достаточно:

```text
command:<command string>
exit_code:<code>
```

Для `NORMAL/STRICT` обязательно наличие хотя бы одного успешного command evidence.

Для `FAST` допускается accepted без T1/T2, но T0 должен пройти.

---

## 9. Acceptance pipeline: `src/grace_control/core/acceptance_pipeline.py`

Создать файл:

```text
src/grace_control/core/acceptance_pipeline.py
```

### 9.1. API

```python
class AcceptancePipeline:
    def __init__(
        self,
        *,
        repo_root: Path,
        command_runner: CommandRunner | None = None,
        scope_guard: ScopeGuard | None = None,
        evidence_collector: EvidenceCollector | None = None,
    ) -> None: ...

    def run(
        self,
        *,
        packet: ExecutionPacketContract,
        changed_files: list[str] | None = None,
        base_ref: str | None = None,
        head_ref: str | None = None,
    ) -> AcceptanceReport: ...
```

### 9.2. T0: scope + cheap machine gates

T0 делает:

1. validate packet contract;
2. determine changed files;
3. check allowed/frozen scope;
4. run cheap syntax/import/lint commands;
5. optionally run `scripts/grace_lint.py` for changed Python files in GRACE-controlled directories.

Если T0 failed:

```text
final_verdict = rework_required
T1 must not run
T2 must not run
merge forbidden
```

### 9.3. T1: targeted packet verification

T1 запускает `packet.verification_commands`.

Rules by profile:

```text
FAST:
  - if no commands: T1 skipped with reason "FAST profile without targeted commands"
  - if commands exist and fail: final verdict rework_required

NORMAL:
  - commands required
  - any failed command → rework_required

STRICT:
  - commands required
  - any failed command → rework_required
```

Не делать “ignore fail” в MVP. Если нужен мягкий FAST — пусть команда не задаётся.

### 9.4. T2: full checks

T2 policy:

```text
FAST:
  - skipped

NORMAL:
  - run full check command if configured
  - if no full command configured: skipped with warning, not failure

STRICT:
  - full command required
  - missing full command → blocked
  - failed full command → rework_required
```

Full command можно передавать через metadata:

```python
packet.metadata["full_verification_commands"] = [["bash", "scripts/guardrails.sh", "backend"]]
```

### 9.5. Final decision table

```text
T0 failed                         → rework_required
scope violation                   → rework_required
invalid packet contract            → blocked
T1 failed FAST/NORMAL/STRICT       → rework_required
T2 failed NORMAL/STRICT            → rework_required
STRICT missing full command         → blocked
NORMAL missing full command         → allowed with warning
FAST T1/T2 skipped, T0 passed       → accepted
all required stages passed          → accepted
```

---

## 10. Packet parsing / materialization

Не создавать новый `packet_parser.py` в legacy `grace/orchestrator`.

Для active runtime использовать один из двух вариантов:

### Preferred

Если `PacketExecutionAdapter._materialize_packet()` уже создаёт структурированный объект, маппить его в `ExecutionPacketContract` прямо в adapter-е:

```python
contract = ExecutionPacketContract(
    packet_id=packet.id,
    title=packet.title,
    allowed_write_scope=packet.allowed_write_scope,
    frozen_scope=packet.frozen_scope,
    acceptance_profile=AcceptanceProfile(packet.acceptance_profile),
    verification_commands=packet.verification.commands,
    expected_evidence=packet.expected_evidence,
    metadata={...},
)
```

### Fallback

Если packet существует только как markdown `EXECUTION_PACKET.md`, добавить small parser в active namespace:

```text
src/grace_control/core/execution_packet_parser.py
```

Но только если реально нужно. Не плодить parser, если объект packet уже есть.

---

## 11. Замена fake verifier/reviewer

Найти fake/static accepted path в `src/grace_control`.

Возможные места:

```text
src/grace_control/adapters/packet_executor.py
src/grace_control/worker/worker.py
src/grace_control/core/llm_runner.py
```

Заменить на:

```text
AcceptancePipeline.run(...)
```

### 11.1. Запрещённый код

Удалить/заменить любые варианты:

```python
return {"packet_verdict": "accepted"}
return ReviewerDecision(packet_verdict="accepted")
verifier_status = "accepted"
reviewer_status = "accepted"
```

если они не зависят от реального `AcceptanceReport`.

### 11.2. Новый accepted path

Accepted можно вернуть только так:

```python
report = acceptance_pipeline.run(...)
if report.final_verdict == PacketVerdict.ACCEPTED:
    # allow merge
```

### 11.3. Новый rework path

Если report failed:

```python
return PacketExecutionResult(
    status="rework_required",
    acceptance_report=report,
    merge_performed=False,
)
```

Если в проекте другой result-class, не создавать второй параллельный формат. Расширить существующий минимально.

---

## 12. Legacy deprecation note

Опционально добавить:

```text
grace/orchestrator/README.md
```

Содержимое:

```md
# Legacy GRACE XML CLI orchestrator

This package is legacy SolarSage XML/CLI tooling.

It supports only:

- reading `grace/development-plan.xml`;
- showing wave status;
- simple packet markdown validation.

It is not the active runtime execution pipeline.

Active architect/worker/packet execution lives in:

```text
src/grace_control/
```

Do not add verifier, reviewer, acceptance pipeline, merge gates, or self-evolution runtime logic here.
```

---

## 13. Tests: что добавить

Тесты должны быть backend/unit-level, быстрые, без реальных LLM и без реального merge.

Создать каталог, если его нет:

```text
tests/grace_control/
```

или использовать существующий test layout проекта. Главное — не класть новые runtime-тесты в legacy `grace/orchestrator/test_*`, кроме deprecation smoke если нужно.

---

## 14. `test_contracts.py`

Файл:

```text
tests/grace_control/core/test_contracts.py
```

Покрыть:

1. `CommandResult.passed == True` for exit_code 0.
2. `CommandResult.passed == False` for non-zero.
3. `AcceptanceReport.is_accepted == True` only for `ACCEPTED`.
4. `AcceptanceReport.is_accepted == False` for `REWORK_REQUIRED/BLOCKED/ESCALATE_TO_ARCHITECT`.
5. valid `ExecutionPacketContract` with NORMAL and commands.
6. invalid packet: empty `packet_id`.
7. invalid packet: empty `allowed_write_scope`.
8. invalid packet: absolute path in `allowed_write_scope`.
9. invalid packet: `../` traversal.
10. invalid packet: NORMAL without verification commands.
11. FAST may have empty verification commands.
12. STRICT without commands invalid.
13. `StageResult` failed without blocking issue/failed command invalid.
14. `StageResult` skipped without reason invalid.
15. `StageResult` passed with blocking issues invalid.

Если dataclass-и не имеют `.validate()`, добавить pure function:

```python
validate_packet_contract(packet) -> list[str]
validate_stage_result(stage) -> list[str]
validate_acceptance_report(report) -> list[str]
```

И тестировать эти функции.

---

## 15. `test_command_runner.py`

Файл:

```text
tests/grace_control/core/test_command_runner.py
```

Покрыть:

1. successful command returns exit_code 0.
2. failing command returns non-zero, not exception.
3. stdout captured.
4. stderr captured.
5. cwd outside repo rejected.
6. absolute cwd outside repo rejected.
7. shell string command rejected if API receives string instead of list.
8. timeout returns non-zero result with timeout message.
9. command with empty list rejected safely.
10. command runner does not use `shell=True`.

Implementation hint for tests:

```python
runner.run([sys.executable, "-c", "print('ok')"])
runner.run([sys.executable, "-c", "import sys; sys.exit(7)"])
```

---

## 16. `test_scope_guard.py`

Файл:

```text
tests/grace_control/core/test_scope_guard.py
```

Покрыть:

1. exact file allowed.
2. folder prefix allowed.
3. `**` glob allowed.
4. changed file outside allowed → `out_of_scope`.
5. changed file inside frozen → `frozen_scope`.
6. frozen wins over allowed.
7. absolute changed file → `invalid_path`.
8. `../secret.py` → `invalid_path`.
9. empty allowed scope → `missing_allowed_scope`.
10. deleted file path still checked as changed path.
11. no changed files → no scope violations.
12. `get_changed_files()` parses git output into repo-relative paths.

Use fake runner or monkeypatch subprocess for git diff. Не требовать реальный git repo в unit-тесте.

---

## 17. `test_evidence.py`

Файл:

```text
tests/grace_control/core/test_evidence.py
```

Покрыть:

1. collect evidence from passed command.
2. collect evidence from failed command.
3. NORMAL requires at least one passed command evidence.
4. STRICT requires at least one passed command evidence.
5. FAST may pass without T1/T2 evidence if T0 passed.
6. expected evidence exact match works.
7. missing expected evidence returns false.
8. failed command evidence alone does not satisfy required evidence.

---

## 18. `test_acceptance_pipeline.py`

Файл:

```text
tests/grace_control/core/test_acceptance_pipeline.py
```

Покрыть все ветки final decision table.

### 18.1. T0 behavior

1. T0 passes when scope valid and cheap commands pass.
2. T0 fails on out-of-scope diff.
3. T0 fails on frozen scope diff.
4. T0 fails on invalid packet contract.
5. T0 fails on failed cheap command.
6. If T0 fails, T1 commands are not run.
7. If T0 fails, T2 commands are not run.

### 18.2. FAST profile

8. FAST + T0 passed + no T1 commands → accepted.
9. FAST + T1 command provided and fails → rework_required.
10. FAST always skips T2.

### 18.3. NORMAL profile

11. NORMAL without T1 commands → blocked or invalid contract.
12. NORMAL T1 failed → rework_required.
13. NORMAL T1 passed + no T2 full command → accepted with warning.
14. NORMAL T2 failed when configured → rework_required.
15. NORMAL all passed → accepted.

### 18.4. STRICT profile

16. STRICT without T1 commands → blocked/invalid.
17. STRICT without T2 full command → blocked.
18. STRICT T1 failed → rework_required.
19. STRICT T2 failed → rework_required.
20. STRICT all passed → accepted.

### 18.5. Evidence and report validity

21. accepted report has no scope violations.
22. accepted report has T0 passed.
23. non-accepted report has reasons.
24. missing expected evidence prevents accepted for NORMAL/STRICT.
25. no fake accepted path: acceptance cannot return accepted if no stages exist.

Use fake `CommandRunner`, fake `ScopeGuard`, fake `EvidenceCollector` where needed. Не запускать реальные линтеры в этих unit-тестах.

---

## 19. `test_packet_executor_acceptance.py`

Файл:

```text
tests/grace_control/adapters/test_packet_executor_acceptance.py
```

Цель: проверить интеграцию adapter-а с acceptance pipeline.

Покрыть:

1. adapter calls acceptance pipeline after coder success.
2. adapter does not call merge if acceptance returns `REWORK_REQUIRED`.
3. adapter does not call merge if acceptance returns `BLOCKED`.
4. adapter calls merge only if acceptance returns `ACCEPTED`.
5. adapter stores/returns acceptance report in execution result.
6. fake verifier/reviewer static accepted no longer used.
7. coder failure skips acceptance and merge.
8. acceptance exception becomes blocked/rework result, not accepted.
9. packet allowed/frozen scope passed into acceptance pipeline correctly.
10. acceptance profile passed correctly: FAST/NORMAL/STRICT.

Use mocks/fakes. Не запускать реальные агенты.

---

## 20. `scripts/grace_lint.py` small hardening

Менять только если нужно для T0.

Добавить/проверить тесты в:

```text
scripts/test_grace_lint.py
```

Покрыть недостающие ветки:

1. syntax error → `GRC000`.
2. missing `AI_HEADER` → `GRC001`.
3. module contract start without end → `GRC002`.
4. module contract end without start → `GRC002`.
5. module map start without end → `GRC003`.
6. semantic block start without end → `GRC004`.
7. semantic block end without start → `GRC004`.
8. mismatched block id → `GRC004`.
9. missing public function contract → `GRC010`.
10. function contract missing required field → `GRC011`.
11. empty `__init__.py` can be skipped if current policy allows.
12. CLI `main()` returns non-zero on findings.
13. CLI `main()` returns zero on clean file.
14. one-line compressed Python orchestrator file should fail formatting/sanity check if policy implemented.

Do not make grace_lint scan whole repo by default if it will create too much noise. T0 should apply to changed files / controlled slice.

---

## 21. Coverage requirement

For this packet require 100% coverage for the new acceptance slice.

Add command:

```bash
pytest \
  tests/grace_control/core \
  tests/grace_control/adapters/test_packet_executor_acceptance.py \
  --cov=src/grace_control/core \
  --cov=src/grace_control/adapters/packet_executor.py \
  --cov-report=term-missing \
  --cov-fail-under=100
```

If project uses `pytest-cov` config elsewhere, integrate without duplicating global config.

Important:

- Do not chase 100% for unrelated product backend.
- Do not add low-value tests just to hit numbers.
- For untestable defensive branches, refactor into pure functions instead of excluding lines.
- Avoid `# pragma: no cover` unless branch is truly impossible and justified in comment.

---

## 22. Guardrails integration

If `scripts/guardrails.sh` already has backend/orchestrator commands, add a small command for active control acceptance tests:

```bash
bash scripts/guardrails.sh grace-control
```

It should run:

```bash
pytest tests/grace_control -q
```

For strict mode, add coverage:

```bash
pytest tests/grace_control \
  --cov=src/grace_control/core \
  --cov=src/grace_control/adapters/packet_executor.py \
  --cov-report=term-missing \
  --cov-fail-under=100
```

Do not break existing commands:

```text
backend
backend-grace
frontend
full
strict
orchestrator
contracts
```

---

## 23. Acceptance JSON output

At the end of acceptance pipeline, adapter should be able to serialize report to JSON.

Shape:

```json
{
  "packet_id": "packet-id",
  "final_verdict": "accepted",
  "stages": [
    {
      "name": "T0_SCOPE_AND_LINT",
      "status": "passed",
      "summary": "Scope and cheap checks passed",
      "commands": [
        {
          "command": ["python", "-m", "pytest", "tests/grace_control/core"],
          "cwd": "/repo",
          "exit_code": 0,
          "stdout": "...",
          "stderr": "...",
          "duration_ms": 1234
        }
      ],
      "blocking_issues": [],
      "warnings": [],
      "skipped_reason": null
    }
  ],
  "scope_violations": [],
  "evidence_paths": ["command:python -m pytest tests/grace_control/core"],
  "reasons": []
}
```

For failed:

```json
{
  "packet_id": "packet-id",
  "final_verdict": "rework_required",
  "stages": [
    {
      "name": "T0_SCOPE_AND_LINT",
      "status": "failed",
      "summary": "Scope guard failed",
      "commands": [],
      "blocking_issues": ["Changed file app/page.tsx is outside allowed scope"],
      "warnings": [],
      "skipped_reason": null
    }
  ],
  "scope_violations": [
    {
      "path": "app/page.tsx",
      "reason": "Changed file is outside allowed write scope",
      "violation_type": "out_of_scope"
    }
  ],
  "evidence_paths": [],
  "reasons": ["T0 failed; packet requires coder rework"]
}
```

---

## 24. Prompt minimization

Промпты verifier/reviewer в MVP не должны раздуваться.

### 24.1. Coder prompt addition

Добавить в coder packet только короткую инструкцию:

```md
After implementation, return a concise handoff:

- Changed files
- Tests added/updated
- Commands run
- Known risks

Do not claim acceptance. Acceptance is decided by deterministic pipeline.
```

### 24.2. Verifier prompt

Для MVP verifier prompt не нужен, потому что verifier = deterministic evidence collector.

Если в коде обязательно требуется роль verifier, промпт должен быть stub:

```md
Verifier is disabled for MVP runtime acceptance.
Deterministic AcceptancePipeline collects evidence.
Do not call LLM verifier unless acceptance_profile=STRICT and explicitly enabled.
```

### 24.3. Reviewer prompt

Для MVP reviewer prompt не нужен, потому что reviewer = deterministic decision from `AcceptanceReport`.

Если роль reviewer обязательна в конфиге:

```md
Reviewer is disabled for MVP runtime acceptance.
Deterministic AcceptancePipeline produces final verdict.
Do not call LLM reviewer unless premium_review_enabled=true.
```

---

## 25. Definition of Done

Задача считается выполненной, если:

1. Active runtime acceptance реализован в `src/grace_control/`, а не в legacy `grace/orchestrator/`.
2. Fake/static accepted verifier/reviewer больше не может привести к merge.
3. `PacketExecutionAdapter` вызывает `AcceptancePipeline` после coder и до merge.
4. T0 проверяет allowed/frozen scope и cheap commands.
5. T0 failure останавливает pipeline до T1/T2.
6. T1 запускает targeted verification commands.
7. T2 запускается только по policy профиля.
8. FAST может быть accepted после T0 без full tests.
9. NORMAL требует targeted commands.
10. STRICT требует targeted + full commands.
11. Missing evidence не может дать accepted для NORMAL/STRICT.
12. Adapter не merge-ит при `REWORK_REQUIRED/BLOCKED/ESCALATE_TO_ARCHITECT`.
13. Все новые контракты покрыты тестами.
14. Все ветки acceptance decision table покрыты тестами.
15. Coverage нового acceptance slice = 100%.
16. Existing guardrails commands не сломаны.
17. Legacy `grace/orchestrator/` не получил новый execution loop.
18. Опционально добавлен deprecation note для legacy orchestrator.

---

## 26. Suggested implementation order for coder

Делать строго в таком порядке:

```text
1. Add contracts.py + tests.
2. Add command_runner.py + tests.
3. Add scope_guard.py + tests.
4. Add evidence.py + tests.
5. Add acceptance_pipeline.py + tests.
6. Integrate acceptance into packet_executor.py + adapter tests.
7. Remove/disable fake static accepted path.
8. Add guardrails command if needed.
9. Add legacy README deprecation note if useful.
10. Run coverage and fix missing branches.
```

Не начинать с adapter-а, пока нет протестированного pure acceptance core.

---

## 27. Final verification commands

Минимум:

```bash
pytest tests/grace_control -q
```

Coverage gate:

```bash
pytest \
  tests/grace_control/core \
  tests/grace_control/adapters/test_packet_executor_acceptance.py \
  --cov=src/grace_control/core \
  --cov=src/grace_control/adapters/packet_executor.py \
  --cov-report=term-missing \
  --cov-fail-under=100
```

Existing backend guardrails should still pass if environment is ready:

```bash
bash scripts/guardrails.sh backend
```

Strict optional:

```bash
bash scripts/guardrails.sh strict
```

---

## 28. Important note for reviewer

Reviewer must reject the implementation if any of these happen:

- new acceptance files are added to `grace/orchestrator/` instead of `src/grace_control/`;
- legacy orchestrator becomes second runtime;
- fake accepted path remains reachable;
- merge can happen without `AcceptanceReport`;
- T0 failure still runs expensive verifier/reviewer;
- tests use real LLM calls;
- tests depend on real git repo state instead of fakes where unit tests are enough;
- 100% coverage is claimed globally but not enforced for the new acceptance slice;
- prompts are expanded instead of minimized.
