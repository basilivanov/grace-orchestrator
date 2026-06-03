# ТЗ: Deterministic MVP Acceptance Pipeline для `basilivanov/grace-orchestrator`

## 0. Контекст и цель

Репозиторий: `basilivanov/grace-orchestrator`.

В этом репозитории active runtime находится в:

```text
src/grace_control/
```

Ключевой runtime-flow сейчас:

```text
Worker.claim()
  → PacketExecutionAdapter.execute()
  → _materialize_packet()
  → _call_legacy_runner()
  → _parse_result()
  → Worker.release_packet()
  → Worker.merge_packet() if result.accepted == True
```

Текущая проблема: `PacketExecutionAdapter._parse_result()` фактически доверяет verdict из legacy runner:

```python
accepted = result.ok and result.domain_status == "accepted"
```

После этого `Worker` делает merge, если `ExecutionResult.accepted == True`.

Это опасно, потому что verifier/reviewer внутри legacy runner сейчас могут быть fake/static accepted или недостаточно строгими. Нужно добавить deterministic acceptance gate между legacy runner и merge.

## 1. Архитектурное решение

### 1.1. Что делаем

Добавить deterministic MVP acceptance pipeline в active runtime:

```text
src/grace_control/
```

Новая логика должна жить в pure core-модулях:

```text
src/grace_control/core/contracts.py
src/grace_control/core/command_runner.py
src/grace_control/core/scope_guard.py
src/grace_control/core/evidence.py
src/grace_control/core/acceptance_pipeline.py
```

Интеграция в существующий adapter:

```text
src/grace_control/adapters/packet_executor.py
```

Тесты:

```text
tests/grace_control/core/test_contracts.py
tests/grace_control/core/test_command_runner.py
tests/grace_control/core/test_scope_guard.py
tests/grace_control/core/test_evidence.py
tests/grace_control/core/test_acceptance_pipeline.py
tests/grace_control/adapters/test_packet_executor_acceptance.py
```

### 1.2. Что НЕ делаем

Не добавлять новый execution loop.

Не переписывать worker полностью.

Не выкидывать legacy runner в этом MVP.

Не делать LLM verifier/reviewer.

Не строить второй orchestrator.

Не добавлять acceptance pipeline в старый SolarSage XML/CLI пакет, если он присутствует где-то в export.

### 1.3. Новая ответственность

Legacy runner остаётся как coder/agent runner:

```text
legacy runner = пишет код, запускает текущий e2e flow, возвращает worktree/branch/result
```

Но legacy verdict больше не является merge gate.

Новый merge gate:

```text
Deterministic AcceptanceReport
```

Только если `AcceptanceReport.final_verdict == "accepted"`, adapter может вернуть:

```python
ExecutionResult(accepted=True)
```

И только тогда worker может вызвать `merge_packet()`.

## 2. Точка внедрения

Файл:

```text
src/grace_control/adapters/packet_executor.py
```

Сейчас логика примерно такая:

```python
result = await self._call_legacy_runner(packet_path, state_root, worktree_root)
execution_result = self._parse_result(result)
evidence_path = self._save_evidence(...)
execution_result.evidence_path = evidence_path
return execution_result
```

Нужно изменить на:

```python
result = await self._call_legacy_runner(packet_path, state_root, worktree_root)

legacy_execution_result = self._parse_result(result)

acceptance_report = run_acceptance_pipeline(
    packet=packet_contract,
    legacy_result=result,
    worktree_path=Path(result.worktree_path),
    branch_name=result.branch_name,
    project_root=self.project_root,
    state_root=state_root,
    run_dir=run_dir,
)

evidence_path = self._save_evidence(...)
self._save_acceptance_report(...)

execution_result = self._build_execution_result_from_acceptance(
    legacy_execution_result=legacy_execution_result,
    acceptance_report=acceptance_report,
    result=result,
)
return execution_result
```

Важно:

```text
legacy_execution_result.accepted не должен напрямую попадать в final ExecutionResult.accepted.
```

Final accepted:

```python
execution_result.accepted = acceptance_report.final_verdict == "accepted"
```

## 3. Важное изменение legacy runner вызова

Сейчас `_call_legacy_runner()` вызывает `run_e2e_packet(... keep_worktree=False ...)`.

Для deterministic acceptance нужен worktree после работы агента.

Изменить:

```python
keep_worktree=False
```

на:

```python
keep_worktree=True
```

Worktree должен существовать до завершения acceptance pipeline и до merge/reject handling.

После rejected/failed можно чистить worktree отдельным cleanup, но не раньше acceptance.

## 4. Packet materialization: убрать жёсткий fallback как основной путь

Сейчас `_materialize_packet()` жёстко пишет:

```text
## Frozen Scope
- src/prefect_grace/**

## Verification
pytest -v
ruff check src/
```

Нужно:

1. Читать `allowed_write_scope` из `packet.spec_json`.
2. Читать `frozen_scope` из `packet.spec_json`.
3. Читать `verification` из `packet.spec_json`.
4. Читать `expected_evidence` из `packet.spec_json`.

Fallback разрешён только для старых пакетов, где полей нет.

Рекомендуемая структура `spec_json`:

```yaml
scope:
  - src/grace_control/core/**
  - tests/grace_control/core/**
frozen_scope:
  - src/grace_control/db/**
  - src/grace_control/api/**
verification:
  t0:
    - python -m py_compile {changed_python_files}
    - ruff check {changed_python_files}
  t1:
    - pytest tests/grace_control/core/test_acceptance_pipeline.py -q
  t2:
    - pytest tests/grace_control -q
expected_evidence:
  - id: tests
    kind: command
    required: true
    pattern: pytest
  - id: lint
    kind: command
    required: true
    pattern: ruff check
acceptance_profile: NORMAL
```

Поддержать также legacy-форму:

```yaml
verification:
  - pytest -q
  - ruff check src/
```

В этом случае считать эти команды T1.

## 5. Registry scope bug

В `_call_legacy_runner()` сейчас registry пишет:

```python
"allowed_write_scope": [],
"frozen_scope": [],
```

Это нужно исправить.

Registry должен получить scope из packet contract:

```python
"allowed_write_scope": packet_contract.allowed_write_scope,
"frozen_scope": packet_contract.frozen_scope,
```

Если legacy runner ожидает эти поля, он должен видеть реальные ограничения.

## 6. Новые контракты

Файл:

```text
src/grace_control/core/contracts.py
```

Использовать `dataclass` или Pydantic. Для MVP лучше `dataclass` + explicit validators, чтобы проще тестировать.

### 6.1. Enums

```python
from enum import Enum

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

class FinalVerdict(str, Enum):
    ACCEPTED = "accepted"
    REWORK_REQUIRED = "rework_required"
    BLOCKED = "blocked"
```

### 6.2. ExecutionPacketContract

```python
@dataclass(frozen=True)
class ExecutionPacketContract:
    packet_id: str
    acceptance_profile: AcceptanceProfile
    allowed_write_scope: list[str]
    frozen_scope: list[str]
    verification: dict[str, list[str]]
    expected_evidence: list["EvidenceRequirement"]
```

Rules:

```text
packet_id required
acceptance_profile defaults to NORMAL
allowed_write_scope required, non-empty
frozen_scope may be empty
verification may be empty only for FAST
expected_evidence may be empty for FAST
```

### 6.3. EvidenceRequirement

```python
@dataclass(frozen=True)
class EvidenceRequirement:
    id: str
    kind: str  # command | file | diff | log
    required: bool = True
    pattern: str | None = None
```

### 6.4. CommandResult

```python
@dataclass(frozen=True)
class CommandResult:
    command: str
    exit_code: int
    stdout_path: str
    stderr_path: str
    duration_ms: int
    timed_out: bool
```

### 6.5. StageResult

```python
@dataclass(frozen=True)
class StageResult:
    name: StageName
    status: StageStatus
    commands: list[CommandResult]
    blocking_issues: list[str]
    warnings: list[str]
    skipped_reason: str | None = None
```

### 6.6. AcceptanceReport

```python
@dataclass(frozen=True)
class AcceptanceReport:
    packet_id: str
    final_verdict: FinalVerdict
    profile: AcceptanceProfile
    stages: list[StageResult]
    scope_violations: list[str]
    evidence_issues: list[str]
    legacy_domain_status: str
    legacy_ok: bool
    summary: str
```

### 6.7. Validators

Не прятать validation в `__post_init__`.

Сделать explicit pure functions:

```python
validate_packet_contract(packet: ExecutionPacketContract) -> list[str]
validate_stage_result(stage: StageResult) -> list[str]
validate_acceptance_report(report: AcceptanceReport) -> list[str]
```

## 7. Packet contract parser

Можно сделать в `contracts.py` или отдельным файлом, если так чище:

```text
src/grace_control/core/packet_contract.py
```

Функция:

```python
build_packet_contract(packet_data: dict) -> ExecutionPacketContract
```

Источники:

```text
packet_data["id"]
packet_data["acceptance_profile"]
packet_data["spec_json"]
```

Поддерживаемые поля в `spec_json`:

```yaml
scope: []
allowed_write_scope: []
frozen_scope: []
verification:
  t0: []
  t1: []
  t2: []
expected_evidence: []
```

Priority:

```text
allowed_write_scope = spec_json.allowed_write_scope if exists else spec_json.scope
acceptance_profile = packet_data.acceptance_profile if exists else spec_json.acceptance_profile else NORMAL
```

Если scope отсутствует:

```text
contract invalid → final verdict BLOCKED
```

## 8. command_runner.py

Файл:

```text
src/grace_control/core/command_runner.py
```

Назначение: безопасно запускать shell-команды acceptance pipeline.

Функция:

```python
run_command(
    command: str,
    cwd: Path,
    output_dir: Path,
    timeout_seconds: int = 120,
    env: dict[str, str] | None = None,
) -> CommandResult
```

Требования:

1. Запускать команду через shell только если текущий проект уже так делает. Если нет — использовать `shlex.split`.
2. Всегда писать stdout/stderr в файлы.
3. Не падать exception при non-zero exit code.
4. Timeout возвращает `timed_out=True`, `exit_code=-1`.
5. Output filenames должны быть безопасными:
   - `cmd_001_stdout.log`
   - `cmd_001_stderr.log`
6. Команда должна запускаться в `worktree_path`, не в `project_root`.

## 9. scope_guard.py

Файл:

```text
src/grace_control/core/scope_guard.py
```

Назначение: deterministic check, что coder менял только allowed scope и не трогал frozen scope.

Функции:

```python
get_changed_files(project_root: Path, branch_name: str) -> list[str]
check_scope(
    changed_files: list[str],
    allowed_write_scope: list[str],
    frozen_scope: list[str],
) -> list[str]
```

Для MVP можно получить changed files одним из вариантов:

```bash
git diff --name-only main...HEAD
```

или, если branch_name есть:

```bash
git diff --name-only main...{branch_name}
```

Важно: если adapter работает внутри worktree, можно использовать:

```bash
git -C {worktree_path} diff --name-only main...HEAD
```

Поддержать patterns:

```text
src/foo/**
src/foo/*.py
src/foo/bar.py
tests/**
```

Использовать `fnmatch`/`pathlib.PurePosixPath.match`.

Rules:

```text
If changed file matches frozen_scope → violation.
If changed file does not match any allowed_write_scope → violation.
If changed_files is empty and legacy_result was accepted → warning, not blocker.
```

## 10. evidence.py

Файл:

```text
src/grace_control/core/evidence.py
```

Функция:

```python
check_expected_evidence(
    expected: list[EvidenceRequirement],
    stage_results: list[StageResult],
    worktree_path: Path,
) -> list[str]
```

MVP evidence rules:

```text
FAST:
  expected evidence optional.

NORMAL:
  require at least one successful command evidence from T1 or T0.

STRICT:
  require all required expected_evidence items.
```

Command evidence:

```text
kind=command passes if any executed command contains pattern and exit_code == 0.
```

File evidence:

```text
kind=file passes if file exists in worktree_path and optional pattern matches path.
```

Diff evidence:

```text
kind=diff passes if changed_files is non-empty and optional pattern matches at least one changed file.
```

## 11. acceptance_pipeline.py

Файл:

```text
src/grace_control/core/acceptance_pipeline.py
```

Main function:

```python
run_acceptance_pipeline(
    packet: ExecutionPacketContract,
    legacy_result,
    project_root: Path,
    worktree_path: Path,
    branch_name: str,
    run_dir: Path,
) -> AcceptanceReport
```

### 11.1. Pipeline stages

```text
T0: scope + syntax/lint
T1: targeted tests
T2: full tests
```

### 11.2. T0

T0 always runs.

T0 checks:

```text
1. packet contract validation
2. changed files
3. allowed/frozen scope
4. syntax/lint commands from packet.verification.t0
```

If no T0 commands exist:

```text
FAST: T0 command substage skipped with warning
NORMAL: T0 command substage skipped with warning
STRICT: T0 command substage failed
```

But scope check always runs.

If scope violation:

```text
final_verdict = rework_required
Do not run T1/T2.
```

If invalid packet contract:

```text
final_verdict = blocked
Do not run T1/T2.
```

### 11.3. T1

T1 runs if T0 passed.

T1 commands from:

```text
packet.verification["t1"]
```

If legacy verification is list-only, treat it as T1.

Behavior:

```text
FAST:
  T1 failures are warnings unless command is marked required later.
NORMAL:
  T1 failure → rework_required.
STRICT:
  T1 failure → rework_required.
```

If T1 missing:

```text
FAST: skipped
NORMAL: blocked
STRICT: blocked
```

### 11.4. T2

T2 runs only for NORMAL/STRICT if commands exist.

Behavior:

```text
FAST:
  T2 skipped.

NORMAL:
  T2 optional.
  If commands exist and fail → rework_required.
  If commands absent → skipped with warning.

STRICT:
  T2 required.
  If commands absent → blocked.
  If commands fail → rework_required.
```

### 11.5. Final verdict table

```text
Invalid packet contract
  → BLOCKED

Frozen scope touched
  → REWORK_REQUIRED

Out-of-scope file changed
  → REWORK_REQUIRED

T0 command failed
  → REWORK_REQUIRED

T1 failed on NORMAL/STRICT
  → REWORK_REQUIRED

T1 missing on NORMAL/STRICT
  → BLOCKED

T2 missing on STRICT
  → BLOCKED

T2 failed on NORMAL/STRICT
  → REWORK_REQUIRED

Required evidence missing on STRICT
  → BLOCKED

Required evidence missing on NORMAL
  → REWORK_REQUIRED

All required gates passed
  → ACCEPTED
```

### 11.6. Legacy result policy

Legacy result is evidence, not authority.

Rules:

```text
If legacy_result.ok is False:
  final_verdict cannot be ACCEPTED.

If legacy_result.domain_status != "accepted":
  final_verdict cannot be ACCEPTED.

If legacy result says accepted but deterministic T0/T1/T2 fails:
  final_verdict = REWORK_REQUIRED or BLOCKED according to table.

If deterministic gates pass but legacy result failed:
  final_verdict = REWORK_REQUIRED.
```

## 12. Adapter integration details

### 12.1. Extend ExecutionResult

Current:

```python
class ExecutionResult(BaseModel):
    accepted: bool
    reason: str | None = None
    evidence_path: str = ""
    duration_ms: int = 0
    domain_status: str = ""
    worktree_path: str = ""
    branch_name: str = ""
```

Add:

```python
acceptance_report_path: str = ""
acceptance_verdict: str = ""
acceptance_summary: str = ""
```

Do not remove existing fields.

### 12.2. Save acceptance report

Add method:

```python
def _save_acceptance_report(
    self,
    packet_id: str,
    run_number: int,
    report: AcceptanceReport,
    state_root: Path,
) -> str:
    ...
```

Path:

```text
{state_root}/packets/{packet_id}/runs/R{run_number:02d}/acceptance_report.json
```

JSON must include:

```text
packet_id
final_verdict
profile
stages
scope_violations
evidence_issues
legacy_domain_status
legacy_ok
summary
```

### 12.3. Build final ExecutionResult

Add method:

```python
def _build_execution_result_from_acceptance(
    self,
    legacy_execution_result: ExecutionResult,
    acceptance_report: AcceptanceReport,
    acceptance_report_path: str,
) -> ExecutionResult:
    ...
```

Logic:

```python
accepted = acceptance_report.final_verdict == FinalVerdict.ACCEPTED
reason = None if accepted else acceptance_report.summary
domain_status = acceptance_report.final_verdict.value
```

Preserve:

```text
worktree_path
branch_name
duration_ms
evidence_path
```

### 12.4. PacketRun result_json

Currently stores legacy `result.to_dict()`.

Change to store combined result:

```json
{
  "legacy_result": { ... },
  "acceptance_report": { ... }
}
```

Do not break if `result.to_dict()` is missing; fallback to safe dict.

## 13. Worker changes

Keep worker mostly unchanged.

Current worker behavior is acceptable:

```python
status = "accepted" if result.accepted else "rejected"
if status == "accepted":
    await self.api.merge_packet(...)
```

Because adapter will now return `accepted=True` only after deterministic acceptance.

Add only logging fields if simple:

```python
acceptance_verdict=result.acceptance_verdict
acceptance_report_path=result.acceptance_report_path
```

Do not rewrite worker loop in this task.

## 14. Tests

### 14.1. Coverage policy

100% coverage required for new pure modules:

```text
src/grace_control/core/contracts.py
src/grace_control/core/command_runner.py
src/grace_control/core/scope_guard.py
src/grace_control/core/evidence.py
src/grace_control/core/acceptance_pipeline.py
```

Adapter integration tests must cover all new acceptance branches, but do not require 100% line coverage for the whole existing `packet_executor.py`.

### 14.2. test_contracts.py

Test cases:

1. Valid minimal NORMAL packet.
2. FAST packet may have empty verification.
3. NORMAL packet with empty allowed scope invalid.
4. STRICT packet with missing T1/T2 invalid or blocked by pipeline.
5. Invalid acceptance profile rejected.
6. EvidenceRequirement parsing:
   - command
   - file
   - diff
   - log
7. `validate_acceptance_report()` accepts valid report.
8. `validate_acceptance_report()` rejects report without stages.

### 14.3. test_command_runner.py

Test cases:

1. Successful command returns exit_code 0.
2. Failing command returns non-zero but does not raise.
3. stdout is written to file.
4. stderr is written to file.
5. timeout returns timed_out=True and exit_code=-1.
6. command runs inside provided cwd.
7. output filenames are deterministic/safe.

Use tiny commands, e.g.:

```bash
python -c "print('ok')"
python -c "import sys; sys.exit(2)"
```

### 14.4. test_scope_guard.py

Test cases:

1. Changed file inside allowed scope passes.
2. Changed file outside allowed scope fails.
3. Changed file inside frozen scope fails.
4. File matching both allowed and frozen fails.
5. `src/foo/**` matches nested files.
6. Exact file pattern matches only that file.
7. Empty changed files returns no violations.
8. Git diff function returns changed files in temp git repo.

### 14.5. test_evidence.py

Test cases:

1. NORMAL with successful command evidence passes.
2. NORMAL with no successful commands returns issue.
3. STRICT missing required command evidence returns issue.
4. STRICT required file exists passes.
5. STRICT required file missing returns issue.
6. Optional evidence missing does not fail.
7. Diff evidence matches changed file.
8. Pattern mismatch returns issue.

### 14.6. test_acceptance_pipeline.py

Test cases:

1. Invalid packet contract → BLOCKED.
2. Scope violation → REWORK_REQUIRED and T1/T2 not run.
3. Frozen scope violation → REWORK_REQUIRED.
4. T0 command fail → REWORK_REQUIRED.
5. FAST T1 fail → ACCEPTED only if legacy result accepted and no required evidence missing.
6. NORMAL T1 fail → REWORK_REQUIRED.
7. STRICT T1 missing → BLOCKED.
8. FAST skips T2.
9. NORMAL T2 absent → ACCEPTED with warning if T0/T1 pass.
10. NORMAL T2 command fails → REWORK_REQUIRED.
11. STRICT T2 absent → BLOCKED.
12. STRICT required evidence missing → BLOCKED.
13. Legacy result failed → cannot ACCEPT even if deterministic commands pass.
14. Legacy accepted + deterministic all pass → ACCEPTED.
15. AcceptanceReport contains legacy status and summary.

### 14.7. test_packet_executor_acceptance.py

Use mocks; do not launch real agents.

Patch:

```python
PacketExecutionAdapter._call_legacy_runner
run_acceptance_pipeline
get_db / DB access if needed
```

Test cases:

1. Legacy accepted + acceptance accepted → ExecutionResult.accepted True.
2. Legacy accepted + acceptance rework_required → ExecutionResult.accepted False.
3. Legacy accepted + acceptance blocked → ExecutionResult.accepted False.
4. Legacy failed + acceptance would pass → ExecutionResult.accepted False.
5. Acceptance report path saved.
6. PacketRun status is accepted only when deterministic accepted.
7. PacketRun status rejected when deterministic rework/blocked.
8. `result_json` contains both `legacy_result` and `acceptance_report`.
9. `keep_worktree=True` passed to legacy runner.
10. Registry receives non-empty allowed/frozen scope from packet contract.

## 15. Test commands

Add or document commands:

```bash
pytest tests/grace_control/core \
  --cov=src/grace_control/core/contracts.py \
  --cov=src/grace_control/core/command_runner.py \
  --cov=src/grace_control/core/scope_guard.py \
  --cov=src/grace_control/core/evidence.py \
  --cov=src/grace_control/core/acceptance_pipeline.py \
  --cov-fail-under=100
```

Adapter integration:

```bash
pytest tests/grace_control/adapters/test_packet_executor_acceptance.py -q
```

Full relevant slice:

```bash
pytest tests/grace_control -q
```

Do not require 100% coverage for entire repository in this task.

## 16. Acceptance criteria for this task

Task is accepted only if:

1. `PacketExecutionAdapter` no longer trusts legacy accepted verdict directly.
2. Deterministic `AcceptanceReport` is required before `ExecutionResult.accepted=True`.
3. Scope guard blocks frozen/out-of-scope changes.
4. T0/T1/T2 behavior matches profile table.
5. Acceptance report is saved to run directory.
6. Worker merge path remains controlled by `ExecutionResult.accepted`.
7. `keep_worktree=True` until acceptance can inspect changes.
8. Registry gets real allowed/frozen scope.
9. New pure modules have 100% coverage.
10. Adapter acceptance integration branches are tested.
11. No LLM verifier/reviewer is added in this MVP.
12. Existing public APIs are not broken unless tests are updated intentionally.

## 17. Implementation order for coder

Do exactly in this order:

1. Add `contracts.py` with dataclasses/enums/validators.
2. Add `command_runner.py`.
3. Add `scope_guard.py`.
4. Add `evidence.py`.
5. Add `acceptance_pipeline.py`.
6. Add unit tests for all core modules.
7. Integrate acceptance into `packet_executor.py`.
8. Add adapter integration tests.
9. Run targeted tests.
10. Fix only failures in touched scope.

Do not start from adapter integration before pure modules are tested.

## 18. Non-goals

Do not refactor DB schema.

Do not rewrite worker.

Do not remove legacy runner.

Do not add new API endpoints.

Do not add frontend.

Do not add LLM reviewer.

Do not introduce heavy dependency.

Do not require global repo 100% coverage.

## 19. Notes for dumb coder

When unsure:

```text
Prefer deterministic pure functions.
Prefer explicit validation.
Prefer JSON artifacts over prose.
Do not trust legacy accepted.
Do not merge unless AcceptanceReport says accepted.
Do not modify unrelated files.
```
