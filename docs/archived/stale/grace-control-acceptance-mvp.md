# ТЗ: Deterministic MVP Acceptance Pipeline для `basilivanov/grace-orchestrator`

## 0. Контекст и цель

Репозиторий: `basilivanov/grace-orchestrator`.

Active runtime находится в:

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

Проблема: `PacketExecutionAdapter._parse_result()` доверяет verdict из legacy runner:

```python
accepted = result.ok and result.domain_status == "accepted"
```

После этого `Worker` делает merge, если `ExecutionResult.accepted == True`.

Нужно добавить deterministic acceptance gate между legacy runner и merge. Legacy runner остаётся coder/agent runner, но его verdict больше не является merge gate.

## 1. Что делаем

Добавить deterministic MVP acceptance pipeline в active runtime:

```text
src/grace_control/
```

Новые pure core-модули:

```text
src/grace_control/core/contracts.py
src/grace_control/core/command_runner.py
src/grace_control/core/scope_guard.py
src/grace_control/core/evidence.py
src/grace_control/core/acceptance_pipeline.py
```

Интеграция:

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

## 2. Что НЕ делаем

Не добавлять новый execution loop.

Не переписывать worker полностью.

Не выкидывать legacy runner в этом MVP.

Не делать LLM verifier/reviewer.

Не строить второй orchestrator.

Не добавлять acceptance pipeline в старый SolarSage XML/CLI пакет, если он присутствует где-то в export.

Не требовать 100% coverage для всего репозитория.

## 3. Главный новый merge gate

Legacy runner остаётся как coder/agent runner:

```text
legacy runner = пишет код, запускает текущий e2e flow, возвращает worktree/branch/result
```

Но legacy verdict больше не является merge gate.

Новый merge gate:

```text
Deterministic AcceptanceReport
```

Только если:

```python
acceptance_report.final_verdict == "accepted"
```

adapter может вернуть:

```python
ExecutionResult(accepted=True)
```

И только тогда worker может вызвать:

```python
merge_packet()
```

## 4. P0: durable worktree before merge

Сейчас adapter создаёт временный worktree root через `TemporaryDirectory()` и делает `_tmp.cleanup()` до возврата результата worker-у.

Это несовместимо с accepted merge path: worker вызывает `merge_packet()` уже после возврата из adapter.

Требование:

```text
Never return accepted=True with worktree_path inside a cleaned TemporaryDirectory.
```

Реализация на выбор, но должна быть детерминированной:

```text
Option A, preferred for MVP:
  Use persistent self.worktree_root for actual agent worktrees.
  Do not wrap accepted worktree path in TemporaryDirectory.

Option B:
  Keep temp dir only for rejected/failed runs.
  For accepted runs, move/copy worktree to durable self.worktree_root before returning ExecutionResult.

Option C:
  Move cleanup responsibility after merge_packet(), but do not rewrite worker deeply in this task.
```

MVP recommendation:

```text
Use self.worktree_root / f"{packet_id}-attempt-{run_number:04d}" as durable worktree root.
Clean it only before a new attempt or after rejected/failed handling.
Do not cleanup accepted worktree before worker merge.
```

Acceptance test required:

```text
Accepted result returns a worktree_path that still exists after PacketExecutionAdapter.execute() returns.
```

## 5. Adapter integration point

Файл:

```text
src/grace_control/adapters/packet_executor.py
```

Текущую логику:

```python
result = await self._call_legacy_runner(packet_path, state_root, worktree_root)
execution_result = self._parse_result(result)
evidence_path = self._save_evidence(...)
execution_result.evidence_path = evidence_path
return execution_result
```

заменить на:

```python
packet_contract = build_packet_contract(packet_data)
packet_path = self._materialize_packet(packet_data, state_root, packet_contract)

result = await self._call_legacy_runner(
    packet_path=packet_path,
    state_root=state_root,
    worktree_root=worktree_root,
    packet_contract=packet_contract,
)

legacy_execution_result = self._parse_result(result)
run_dir = state_root / "packets" / packet_id / "runs" / f"R{run_number:02d}"

acceptance_report = run_acceptance_pipeline(
    packet=packet_contract,
    legacy_result=result,
    worktree_path=Path(result.worktree_path),
    branch_name=result.branch_name,
    project_root=self.project_root,
    run_dir=run_dir,
)

evidence_path = self._save_evidence(packet_id, run_number, safe_legacy_dict, state_root)
acceptance_report_path = self._save_acceptance_report(packet_id, run_number, acceptance_report, state_root)

execution_result = self._build_execution_result_from_acceptance(
    legacy_execution_result=legacy_execution_result,
    acceptance_report=acceptance_report,
    acceptance_report_path=acceptance_report_path,
)
execution_result.evidence_path = evidence_path
execution_result.duration_ms = int((time.time() - start_time) * 1000)
return execution_result
```

Важно:

```text
legacy_execution_result.accepted не должен напрямую попадать в final ExecutionResult.accepted.
```

Final accepted:

```python
execution_result.accepted = acceptance_report.final_verdict == FinalVerdict.ACCEPTED
```

## 6. P0: `_call_legacy_runner()` должен получить packet_contract

Текущая сигнатура:

```python
async def _call_legacy_runner(self, packet_path: Path, state_root: Path, worktree_root: Path)
```

Новая сигнатура:

```python
async def _call_legacy_runner(
    self,
    packet_path: Path,
    state_root: Path,
    worktree_root: Path,
    packet_contract: ExecutionPacketContract,
):
```

Зачем: registry сейчас пишет пустые scope:

```python
"allowed_write_scope": [],
"frozen_scope": [],
```

Нужно писать реальные scope:

```python
"allowed_write_scope": packet_contract.allowed_write_scope,
"frozen_scope": packet_contract.frozen_scope,
```

Также изменить legacy runner call:

```python
keep_worktree=True
```

но помнить: `keep_worktree=True` сам по себе недостаточен, если worktree лежит внутри очищаемого `TemporaryDirectory`.

## 7. Packet materialization

`_materialize_packet()` должен читать из `packet.spec_json`:

```text
allowed_write_scope или scope
frozen_scope
verification
expected_evidence
acceptance_profile
```

Fallback разрешён только для старых пакетов, где полей нет.

Рекомендуемый `spec_json`:

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

Legacy verification form:

```yaml
verification:
  - pytest -q
  - ruff check src/
```

Treat legacy list form as T1 commands.

## 8. contracts.py

Файл:

```text
src/grace_control/core/contracts.py
```

Использовать `dataclass` + explicit validators.

Enums:

```python
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

Dataclasses:

```python
@dataclass(frozen=True)
class EvidenceRequirement:
    id: str
    kind: str  # command | file | diff | log
    required: bool = True
    pattern: str | None = None

@dataclass(frozen=True)
class ExecutionPacketContract:
    packet_id: str
    acceptance_profile: AcceptanceProfile
    allowed_write_scope: list[str]
    frozen_scope: list[str]
    verification: dict[str, list[str]]
    expected_evidence: list[EvidenceRequirement]

@dataclass(frozen=True)
class CommandResult:
    command: str
    exit_code: int
    stdout_path: str
    stderr_path: str
    duration_ms: int
    timed_out: bool

@dataclass(frozen=True)
class StageResult:
    name: StageName
    status: StageStatus
    commands: list[CommandResult]
    blocking_issues: list[str]
    warnings: list[str]
    skipped_reason: str | None = None

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

Validators:

```python
validate_packet_contract(packet: ExecutionPacketContract) -> list[str]
validate_stage_result(stage: StageResult) -> list[str]
validate_acceptance_report(report: AcceptanceReport) -> list[str]
build_packet_contract(packet_data: dict) -> ExecutionPacketContract
```

Rules:

```text
packet_id required
acceptance_profile defaults to NORMAL
allowed_write_scope required, non-empty
frozen_scope may be empty
verification may be empty only for FAST
expected_evidence may be empty for FAST
invalid scope → contract invalid → BLOCKED
```

## 9. command_runner.py

Файл:

```text
src/grace_control/core/command_runner.py
```

Function:

```python
run_command(
    command: str,
    cwd: Path,
    output_dir: Path,
    timeout_seconds: int = 120,
    env: dict[str, str] | None = None,
) -> CommandResult
```

MVP rule:

```text
Use shlex.split() and subprocess.run(..., shell=False).
If command requires shell features such as pipes, redirects, &&, ||, return failed CommandResult with reason unsupported_shell_syntax.
```

Requirements:

```text
Always write stdout/stderr to files.
Do not raise on non-zero exit code.
Timeout returns timed_out=True and exit_code=-1.
Output filenames must be deterministic/safe: cmd_001_stdout.log, cmd_001_stderr.log.
Command runs inside worktree_path, not project_root.
```

## 10. scope_guard.py

Файл:

```text
src/grace_control/core/scope_guard.py
```

Primary function:

```python
get_changed_files(
    worktree_path: Path,
    base_ref: str = "main",
) -> list[str]
```

Not this:

```python
get_changed_files(project_root: Path, branch_name: str)
```

Primary diff source is the produced agent worktree.

Use:

```bash
git -C {worktree_path} diff --name-only {base_ref}...HEAD
```

Fallback only if needed:

```bash
git -C {worktree_path} diff --name-only {base_ref}
```

Scope check:

```python
check_scope(
    changed_files: list[str],
    allowed_write_scope: list[str],
    frozen_scope: list[str],
) -> list[str]
```

Patterns:

```text
src/foo/**
src/foo/*.py
src/foo/bar.py
tests/**
```

Rules:

```text
If changed file matches frozen_scope → violation.
If changed file does not match any allowed_write_scope → violation.
If changed_files is empty and legacy_result was accepted → warning, not blocker.
```

## 11. evidence.py

Файл:

```text
src/grace_control/core/evidence.py
```

Function:

```python
check_expected_evidence(
    expected: list[EvidenceRequirement],
    stage_results: list[StageResult],
    worktree_path: Path,
    changed_files: list[str],
    profile: AcceptanceProfile,
) -> list[str]
```

Rules:

```text
FAST:
  expected evidence optional.

NORMAL:
  require at least one successful command evidence from T1 or T0.

STRICT:
  require all required expected_evidence items.
```

Evidence kinds:

```text
command: any executed command contains pattern and exit_code == 0
file: file exists in worktree_path and optional pattern matches path
diff: changed_files is non-empty and optional pattern matches at least one changed file
log: matching log file exists and optional pattern is present
```

## 12. acceptance_pipeline.py

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

Stages:

```text
T0: contract + worktree diff + scope + syntax/lint
T1: targeted tests
T2: full tests
```

T0 always runs.

T0 checks:

```text
1. packet contract validation
2. changed files from worktree_path
3. allowed/frozen scope
4. syntax/lint commands from packet.verification.t0
```

If invalid packet contract:

```text
final_verdict = BLOCKED
Do not run T1/T2.
```

If scope violation:

```text
final_verdict = REWORK_REQUIRED
Do not run T1/T2.
```

T1 behavior:

```text
FAST:
  T1 may be absent.
  If T1 commands are present and executed, any failed T1 command → REWORK_REQUIRED.

NORMAL:
  T1 missing → BLOCKED.
  T1 failure → REWORK_REQUIRED.

STRICT:
  T1 missing → BLOCKED.
  T1 failure → REWORK_REQUIRED.
```

T2 behavior:

```text
FAST:
  T2 skipped.

NORMAL:
  T2 optional.
  If T2 commands exist and fail → REWORK_REQUIRED.
  If T2 absent → SKIPPED with warning.

STRICT:
  T2 required.
  If T2 absent → BLOCKED.
  If T2 fails → REWORK_REQUIRED.
```

Legacy result policy:

```text
Legacy result is evidence, not authority.

If legacy_result.ok is False:
  final_verdict cannot be ACCEPTED.

If legacy_result.domain_status != "accepted":
  final_verdict cannot be ACCEPTED.

If legacy accepted but deterministic gates fail:
  final_verdict = REWORK_REQUIRED or BLOCKED.

If deterministic gates pass but legacy failed:
  final_verdict = REWORK_REQUIRED.
```

Final verdict table:

```text
Invalid packet contract → BLOCKED
Frozen scope touched → REWORK_REQUIRED
Out-of-scope file changed → REWORK_REQUIRED
T0 command failed → REWORK_REQUIRED
T1 missing on NORMAL/STRICT → BLOCKED
T1 failed on FAST/NORMAL/STRICT → REWORK_REQUIRED
T2 missing on STRICT → BLOCKED
T2 failed on NORMAL/STRICT → REWORK_REQUIRED
Required evidence missing on STRICT → BLOCKED
Required evidence missing on NORMAL → REWORK_REQUIRED
Legacy result failed → REWORK_REQUIRED
All required gates passed → ACCEPTED
```

## 13. Adapter integration details

Extend `ExecutionResult`:

```python
acceptance_report_path: str = ""
acceptance_verdict: str = ""
acceptance_summary: str = ""
```

Add:

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

Add:

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

Preserve from legacy result:

```text
worktree_path
branch_name
duration_ms
evidence_path
```

`PacketRun.result_json` should become:

```json
{
  "legacy_result": { ... },
  "acceptance_report": { ... }
}
```

## 14. Worker changes

Keep worker mostly unchanged.

Allowed small logging addition:

```python
acceptance_verdict=result.acceptance_verdict
acceptance_report_path=result.acceptance_report_path
```

Do not rewrite worker loop in this task.

## 15. Tests

Coverage policy:

```text
100% coverage required for new pure modules:
- src/grace_control/core/contracts.py
- src/grace_control/core/command_runner.py
- src/grace_control/core/scope_guard.py
- src/grace_control/core/evidence.py
- src/grace_control/core/acceptance_pipeline.py

Adapter tests must cover all new acceptance integration branches.
Do not require 100% line coverage for whole packet_executor.py.
```

### 15.1. contracts tests

```text
valid minimal NORMAL packet
FAST packet may have empty verification
NORMAL empty allowed scope invalid
STRICT missing T1/T2 handled as invalid/blocked by pipeline
invalid profile rejected
EvidenceRequirement command/file/diff/log parsing
valid AcceptanceReport passes validation
AcceptanceReport without stages rejected
```

### 15.2. command_runner tests

```text
successful command exit_code 0
failing command non-zero and no raise
stdout file written
stderr file written
timeout returns timed_out=True and exit_code=-1
command runs inside provided cwd
shell syntax like && returns unsupported_shell_syntax failure
output filenames deterministic/safe
```

### 15.3. scope_guard tests

```text
allowed file passes
out-of-scope file fails
frozen file fails
file matching allowed and frozen fails
src/foo/** matches nested files
exact file pattern matches only exact file
empty changed files has no violations
git diff reads changed files from temp git worktree
```

### 15.4. evidence tests

```text
NORMAL successful command evidence passes
NORMAL no successful commands returns issue
STRICT missing required command returns issue
STRICT required file exists passes
STRICT required file missing returns issue
optional evidence missing does not fail
diff evidence matches changed file
pattern mismatch returns issue
```

### 15.5. acceptance_pipeline tests

```text
invalid packet contract → BLOCKED
scope violation → REWORK_REQUIRED and T1/T2 not run
frozen scope violation → REWORK_REQUIRED
T0 command fail → REWORK_REQUIRED
FAST T1 absent can pass if legacy accepted and no required evidence missing
FAST T1 present and failing → REWORK_REQUIRED
NORMAL T1 fail → REWORK_REQUIRED
STRICT T1 missing → BLOCKED
FAST skips T2
NORMAL T2 absent → ACCEPTED with warning if T0/T1 pass
NORMAL T2 command fails → REWORK_REQUIRED
STRICT T2 absent → BLOCKED
STRICT required evidence missing → BLOCKED
legacy result failed → cannot ACCEPT even if deterministic commands pass
legacy accepted + deterministic all pass → ACCEPTED
AcceptanceReport contains legacy status and summary
```

### 15.6. packet_executor acceptance tests

Use mocks; do not launch real agents.

Patch:

```python
PacketExecutionAdapter._call_legacy_runner
run_acceptance_pipeline
get_db / DB access if needed
```

Test cases:

```text
legacy accepted + acceptance accepted → ExecutionResult.accepted True
legacy accepted + acceptance rework_required → ExecutionResult.accepted False
legacy accepted + acceptance blocked → ExecutionResult.accepted False
legacy failed + acceptance would pass → ExecutionResult.accepted False
acceptance report path saved
PacketRun status accepted only when deterministic accepted
PacketRun status rejected when deterministic rework/blocked
result_json contains legacy_result and acceptance_report
keep_worktree=True passed to legacy runner
registry receives non-empty allowed/frozen scope from packet contract
accepted result worktree_path still exists after execute() returns
rejected result may cleanup worktree after evidence/report saved
```

## 16. Test commands

Core coverage:

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

Relevant slice:

```bash
pytest tests/grace_control -q
```

## 17. Acceptance criteria

Task is accepted only if:

```text
PacketExecutionAdapter no longer trusts legacy accepted verdict directly.
Deterministic AcceptanceReport is required before ExecutionResult.accepted=True.
Accepted ExecutionResult never points to cleaned TemporaryDirectory worktree.
Scope guard checks produced worktree diff, not stale project_root diff.
Scope guard blocks frozen/out-of-scope changes.
T0/T1/T2 behavior matches profile table.
FAST does not ignore failing T1 commands when they are present.
Acceptance report is saved to run directory.
Worker merge path remains controlled by ExecutionResult.accepted.
keep_worktree=True until acceptance can inspect changes.
Registry gets real allowed/frozen scope.
New pure modules have 100% coverage.
Adapter acceptance integration branches are tested.
No LLM verifier/reviewer is added in this MVP.
Existing public APIs are not broken unless tests are updated intentionally.
```

## 18. Implementation order

Do exactly in this order:

```text
1. Add contracts.py with dataclasses/enums/validators/build_packet_contract.
2. Add command_runner.py.
3. Add scope_guard.py.
4. Add evidence.py.
5. Add acceptance_pipeline.py.
6. Add unit tests for all core modules.
7. Fix durable worktree handling in packet_executor.py.
8. Pass packet_contract into _call_legacy_runner and registry.
9. Integrate acceptance into packet_executor.py.
10. Add adapter integration tests.
11. Run targeted tests.
12. Fix only failures in touched scope.
```

## 19. Non-goals

```text
Do not refactor DB schema.
Do not rewrite worker.
Do not remove legacy runner.
Do not add new API endpoints.
Do not add frontend.
Do not add LLM reviewer.
Do not introduce heavy dependency.
Do not require global repo 100% coverage.
```

## 20. Notes for coder

```text
Prefer deterministic pure functions.
Prefer explicit validation.
Prefer JSON artifacts over prose.
Do not trust legacy accepted.
Do not merge unless AcceptanceReport says accepted.
Do not return accepted=True with missing/cleaned worktree.
Do not modify unrelated files.
```
