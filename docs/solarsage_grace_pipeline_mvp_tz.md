# ТЗ: SolarSage GRACE MVP Acceptance Pipeline

Дата: 2026-06-03  
Репозиторий: `basilivanov/solarsage-astro`  
Цель: заменить fake verifier/reviewer на минимально жизнеспособный deterministic pipeline, где дешёвые machine-gates отсекают ошибки до запуска дорогих LLM-ролей.

---

## 0. Коротко: что нужно получить

Сейчас `grace/orchestrator` — это в основном adapter/каркас: `core.py` умеет загрузить waves из `development-plan.xml`, CLI показывает `status/next/complete/validate`, `PacketValidator` проверяет несколько markdown-секций. Реального execution/acceptance loop нет. По текущему своду ролей Verifier и Reviewer сейчас fake/static accepted.

Нужно сделать MVP так:

```text
Coder finished
  ↓
T0 Machine Gate
  - packet/schema valid
  - allowed/frozen scope valid
  - grace_lint self-tests green
  - grace_lint changed Python files / backend slice green
  - ruff/mypy/basic syntax green when applicable
  ↓ if T0 failed: stop, return rework_required, do NOT run verifier/reviewer
T1 Verifier Evidence Collector
  - run packet verification commands
  - collect exact command evidence
  - produce FINAL_GRACE_VERIFIER_REPORT_JSON
  ↓ if evidence missing/failed: return rework_required or blocked
T2 Reviewer / Accepter
  - deterministic review of packet + scope + verifier JSON
  - produce FINAL_GRACE_REVIEWER_VERDICT_JSON
  ↓
accepted / rework_required / blocked / architect_review_required
```

Главный принцип MVP: **не делать параноидальный enterprise-CI**, но убрать ситуацию, где агент “принял” пакет без evidence.

---

## 1. Что уже есть в коде

### 1.1. GRACE artifacts

Есть:

- `docs/GRACE_CANON.md` — методологический канон.
- `docs/10_GRACE_Project_Agent_Guide.md` — локальная адаптация проекта.
- `grace/requirements.xml`
- `grace/technology.xml`
- `grace/development-plan.xml`
- `grace/knowledge-graph.xml`
- `grace/verification-matrix.md`
- `grace/packets/*.md`
- `grace/orchestrator/project.yml`
- `grace/orchestrator/verification_profiles.yml`
- `grace/orchestrator/packet.schema.json`
- `grace/orchestrator/roles/*.md`

### 1.2. Orchestrator сейчас

Файлы:

- `grace/orchestrator/core.py`
- `grace/orchestrator/cli.py`
- `grace/orchestrator/validator.py`
- `grace/orchestrator/__init__.py`
- `scripts/grace-orch`

Текущее поведение:

- `GraceOrchestrator` грузит waves из `development-plan.xml`.
- `get_ready_waves()` проверяет completed dependencies.
- `mark_completed()` меняет статус только в памяти.
- `PacketValidator` проверяет наличие `# Decision`, `## Acceptance Criteria`, `## Evidence`.
- CLI умеет `status`, `next`, `complete`, `validate`.

Проблемы:

- acceptance pipeline отсутствует;
- verifier/reviewer execution отсутствует;
- нет stage ordering: T0 → T1 → T2;
- нет hard-stop при T0 fail;
- нет allowed/frozen scope guard;
- нет machine-readable acceptance report;
- текущие orchestrator-файлы выглядят сжатыми в 1–2 строки, что должно быть исправлено и впредь ловиться linter/format gate;
- `test_validate_packet()` сейчас слабый: `assert is_valid or len(errors) > 0`, то есть тест проходит почти всегда.

### 1.3. Guardrails сейчас

Есть `scripts/guardrails.sh` с командами:

- `docs`
- `secrets`
- `orchestrator`
- `contracts`
- `backend`
- `backend-grace`
- `frontend`
- `vercel`
- `full`
- `strict`

Важно: `backend` сейчас запускает self-tests для `grace_lint.py`, потом `ruff`, `mypy`, alembic round-trip, pytest. Но сам `grace_lint.py apps/api/app` запускается только в `backend-grace`. Для MVP acceptance T0 должен уметь запускать `grace_lint` по изменённым Python-файлам / активному backend slice до дорогих ролей.

### 1.4. Linter сейчас

Есть:

- `scripts/grace_lint.py`
- `scripts/test_grace_lint.py`

`grace_lint.py` уже умеет:

- `GRC000` syntax error;
- `GRC001` missing `AI_HEADER`;
- `GRC002` module contract pairing;
- `GRC003` module map pairing;
- `GRC004` semantic block pairing;
- `GRC010` missing public function contract;
- `GRC011` missing required function contract fields;
- `GRC020` missing module contract;
- `GRC021` missing module map.

Проблемы:

- тесты есть, но покрывают не все ветки;
- нет теста на mismatched id;
- нет теста на unmatched END marker;
- нет теста на syntax error;
- нет теста на `main()` exit code;
- нет теста на пустой `__init__.py` skip;
- нет проверки “файл сжат в одну строку / много top-level statements на одной строке”;
- function contract сейчас применяется ко всем public functions; для MVP это ок для active strict slice, но нельзя расширять на весь репозиторий без осознанной whitelist/policy.

---

## 2. Что НЕ делать в этом пакете

Не делать сейчас:

- полноценный Prefect worker runtime;
- LLM verifier/reviewer;
- автоматический merge;
- parallel packet execution;
- сложный DAG scheduler;
- self-improvement guard;
- Telegram уведомления;
- UI для pipeline;
- перегенерацию всех GRACE artifacts;
- переписывание всего `docs/GRACE_CANON.md`.

MVP должен быть маленький: **CLI + deterministic acceptance library + тесты + контракты**.

---

## 3. Новый пакет работ

Создать новый controller packet:

`grace/packets/W-ORCH-2.md`

Название:

```md
# Controller Packet — W-ORCH-2: Real MVP Acceptance Pipeline
```

Frontmatter:

```yaml
---
id: packet-w-orch.2
status: ready
wave: W-ORCH-2
last_review: 2026-06-03
---
```

Содержимое packet должно быть строго по текущему shape:

```md
## IDs
- Phase: PHASE-ORCH-MVP
- Wave: W-ORCH-2
- Modules:
  - M-ORCH-ACCEPTANCE
  - M-ORCH-CONTRACTS
  - M-ORCH-SCOPE
  - M-GRACE-LINT

## Goal
Replace fake verifier/reviewer acceptance with deterministic MVP acceptance loop.

## Allowed Write Scope
- grace/orchestrator/__init__.py
- grace/orchestrator/core.py
- grace/orchestrator/cli.py
- grace/orchestrator/validator.py
- grace/orchestrator/contracts.py
- grace/orchestrator/packet_parser.py
- grace/orchestrator/scope_guard.py
- grace/orchestrator/acceptance.py
- grace/orchestrator/test_orchestrator.py
- grace/orchestrator/test_contracts.py
- grace/orchestrator/test_packet_parser.py
- grace/orchestrator/test_scope_guard.py
- grace/orchestrator/test_acceptance.py
- grace/orchestrator/test_cli_acceptance.py
- scripts/grace-orch
- scripts/grace_lint.py
- scripts/test_grace_lint.py
- scripts/check_orchestrator_contracts.py
- scripts/test_orchestrator_contracts.py
- scripts/guardrails.sh
- grace/orchestrator/README.md
- grace/packets/W-ORCH-2.md

## Frozen / Out Of Scope
- apps/api/app/** except only if required by grace_lint fixture discovery; no product logic edits
- apps/api/alembic/**
- app/**
- components/**
- packages/contracts/**
- docs/GRACE_CANON.md except additive note only if absolutely required
- grace/requirements.xml
- grace/technology.xml
- grace/knowledge-graph.xml
- production deploy scripts

## Must Preserve
- Existing guardrails command names must keep working.
- `pnpm guardrails:backend`, `pnpm guardrails:orchestrator`, `pnpm guardrails:full`, `pnpm guardrails:strict` must keep their public interface.
- No LLM call is allowed inside `grace/orchestrator/acceptance.py`.
- Missing evidence must never produce `accepted`.
- T0 failure must never run verifier/reviewer.
- Out-of-scope diff must always reject the packet.
- All new/modified Python orchestrator code must be formatted into normal multi-line Python, not compressed one-line code.

## Verification
- python3 -m pytest grace/orchestrator scripts/test_grace_lint.py scripts/test_orchestrator_contracts.py -q
- python3 scripts/check_orchestrator_contracts.py
- python3 scripts/grace_lint.py grace/orchestrator scripts
- bash scripts/guardrails.sh orchestrator
- bash scripts/guardrails.sh backend-grace

## Expected Evidence
- Test output for orchestrator + linter tests.
- Coverage report showing 100% line coverage for new `grace/orchestrator/contracts.py`, `packet_parser.py`, `scope_guard.py`, `acceptance.py` and modified linter branches.
- Sample rejected report for T0 scope failure.
- Sample rejected report for missing evidence.
- Sample accepted report for a synthetic clean packet.
- `git diff --stat` only inside allowed scope.

## Escalation
Stop and return `architect_review_required` if implementation requires product backend changes, packet schema weakening, or removing any existing guardrails command.
```

---

## 4. Файлы и конкретные изменения

### 4.1. `grace/orchestrator/contracts.py` — новый файл

Назначение: единые dataclass-контракты для acceptance pipeline. Использовать stdlib only.

Добавить:

```python
from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any, Literal

Verdict = Literal[
    "accepted",
    "rework_required",
    "blocked",
    "pipeline_invalid",
    "architect_review_required",
]
StageName = Literal["T0", "T1", "T2"]
StageStatus = Literal["passed", "failed", "skipped"]

@dataclass(frozen=True)
class CommandResult:
    command: str
    cwd: str
    exit_code: int
    stdout: str = ""
    stderr: str = ""
    duration_ms: int = 0

    @property
    def passed(self) -> bool:
        return self.exit_code == 0

@dataclass(frozen=True)
class ScopeViolation:
    path: str
    reason: Literal["outside_allowed_scope", "inside_frozen_scope"]

@dataclass(frozen=True)
class StageResult:
    stage: StageName
    status: StageStatus
    summary: str
    commands: list[CommandResult] = field(default_factory=list)
    blocking_issues: list[str] = field(default_factory=list)
    scope_violations: list[ScopeViolation] = field(default_factory=list)

@dataclass(frozen=True)
class VerifierReport:
    packet_id: str
    verdict: Verdict
    requirement_results: list[dict[str, Any]]
    test_verdict: Literal["passed", "failed", "not_run"]
    commands_run: list[str]
    evidence_paths: list[str]
    blocking_issues: list[str]

@dataclass(frozen=True)
class ReviewerVerdict:
    packet_id: str
    packet_verdict: Verdict
    follow_up_action: Literal["none", "localized_rework", "architect_decision"]
    route_classification: Literal[
        "self_resolvable_rework",
        "requires_user_decision",
        "requires_planner",
        "accepted",
    ]
    rework_mode: Literal["none", "light_resume", "bounded_fresh", "decision_required"]
    reasons: list[str]

@dataclass(frozen=True)
class AcceptanceReport:
    packet_id: str
    final_verdict: Verdict
    stages: list[StageResult]
    verifier_report: VerifierReport | None
    reviewer_verdict: ReviewerVerdict | None
    reviewer_called: bool

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)
```

Обязательные GRACE markers:

- module contract: `M-ORCH-CONTRACTS`
- module map
- function contracts для public methods/functions:
  - `CommandResult.passed`
  - `AcceptanceReport.to_dict`

### 4.2. `grace/orchestrator/packet_parser.py` — новый файл

Назначение: строгий parser для packet markdown. Не использовать PyYAML. Только flat frontmatter и markdown sections.

Контракт:

```python
@dataclass(frozen=True)
class PacketContract:
    path: Path
    packet_id: str
    status: str
    wave: str
    phase: str
    modules: list[str]
    allowed_write_scope: list[str]
    frozen_scope: list[str]
    must_preserve: list[str]
    verification: list[str]
    expected_evidence: list[str]
    escalation_triggers: list[str]
    verification_profile: str | None = None
```

Public API:

```python
class PacketParseError(ValueError):
    pass

def parse_packet(path: Path) -> PacketContract:
    ...
```

Parsing rules:

1. Packet must have YAML-like frontmatter starting with `---`.
2. Required frontmatter keys:
   - `id`
   - `status`
   - `wave`
   - `last_review`
3. Required sections:
   - `## IDs`
   - `## Goal`
   - `## Allowed Write Scope`
   - `## Frozen / Out Of Scope`
   - `## Must Preserve`
   - `## Verification`
   - `## Expected Evidence`
   - `## Escalation`
4. Section list items are markdown bullets `- value`.
5. If a required section is missing or empty → `PacketParseError`.
6. Legacy packets may still be validated by existing `PacketValidator`, but `accept` command must require strict packet shape.

Important: do not silently infer allowed/frozen scope from prose.

### 4.3. `grace/orchestrator/scope_guard.py` — новый файл

Назначение: deterministic allowed/frozen scope guard.

Public API:

```python
@dataclass(frozen=True)
class DiffSnapshot:
    changed_paths: list[str]
    untracked_paths: list[str]

class ScopeGuardError(RuntimeError):
    pass

def collect_git_snapshot(repo_root: Path) -> DiffSnapshot:
    ...

def match_scope(path: str, patterns: list[str]) -> bool:
    ...

def check_scope(
    changed_paths: list[str],
    allowed_write_scope: list[str],
    frozen_scope: list[str],
) -> list[ScopeViolation]:
    ...
```

Rules:

- `changed_paths` = tracked modified/added/deleted + untracked files.
- A path is allowed if it matches at least one `allowed_write_scope` item.
- A path is forbidden if it matches any `frozen_scope` item.
- Frozen wins over allowed.
- Support exact file paths and glob patterns:
  - `grace/orchestrator/*.py`
  - `scripts/**`
  - `apps/api/app/**`
- Use POSIX-style paths internally.
- If git is unavailable or command fails, return `ScopeGuardError`, not accepted.

Implementation note:

Use:

```bash
git diff --name-only --diff-filter=ACMRTUXB HEAD --
git ls-files --others --exclude-standard
```

Do not include ignored files.

### 4.4. `grace/orchestrator/acceptance.py` — новый файл

Назначение: deterministic MVP acceptance loop.

Public API:

```python
def run_acceptance(
    packet_path: Path,
    repo_root: Path,
    acceptance_profile: str = "NORMAL",
    command_runner: CommandRunner | None = None,
) -> AcceptanceReport:
    ...
```

`acceptance_profile` values:

- `FAST`
- `NORMAL`
- `STRICT`

Stage behavior:

#### T0 — mandatory machine gate

Always run before verifier/reviewer.

T0 checks:

1. `parse_packet(packet_path)` succeeds.
2. `check_scope()` returns no violations.
3. `python3 -m unittest scripts/test_grace_lint.py -v`
4. `python3 -m unittest scripts/test_orchestrator_contracts.py -v`
5. `python3 scripts/check_orchestrator_contracts.py`
6. `python3 scripts/grace_lint.py <changed python files under allowed scope>`

If no changed Python files under allowed scope, linter command may be skipped with summary `no changed Python files`.

If any T0 check fails:

- final verdict: `rework_required` or `pipeline_invalid`
- `reviewer_called=false`
- `verifier_report=None`
- `reviewer_verdict=None`
- no T1/T2 commands run

Classification:

- invalid packet shape → `pipeline_invalid`
- scope violation → `rework_required`
- linter/tests fail → `rework_required`

#### T1 — verifier evidence collector

Run only after T0 passed.

Behavior:

- Run every command from packet `## Verification`.
- Capture command, cwd, exit code, stdout, stderr, duration.
- Build `VerifierReport`.

Verifier verdict rules:

- all commands exit 0 and expected evidence list is non-empty → `accepted`
- command exit non-zero → `rework_required`
- command cannot run / timeout / no evidence → `blocked` or `pipeline_invalid`

MVP timeout:

- default 300 seconds per command.
- no background work.

#### T2 — reviewer/accepter

Run only after T1 verifier verdict is `accepted`.

Reviewer rules:

- Re-check scope from current git snapshot.
- Reject if any scope violation appears after T1.
- Reject if verifier report missing.
- Reject if verifier has blocking issues.
- Accept only if T0 and T1 passed.

Verdict mapping:

- clean → `accepted`
- scope violation → `rework_required`
- missing evidence → `blocked`
- architecture/scope pressure phrase in blocking issues → `architect_review_required`

### 4.5. `grace/orchestrator/cli.py`

Add command:

```bash
python scripts/grace-orch accept grace/packets/W-ORCH-2.md --profile NORMAL --json
```

Options:

```text
accept PACKET_PATH
  --repo-root PATH     default: .
  --profile TEXT       FAST|NORMAL|STRICT, default NORMAL
  --json               print machine-readable JSON only
```

Rules:

- exit code `0` only when final verdict is `accepted`;
- exit code `1` for `rework_required`, `blocked`, `architect_review_required`;
- exit code `2` for `pipeline_invalid` or CLI usage error;
- human output allowed only when `--json` is not passed.

### 4.6. `scripts/guardrails.sh`

Minimal changes only.

Required:

1. In `run_orchestrator()`, run orchestrator acceptance tests:

```bash
section "orchestrator: acceptance tests"
python3 -m pytest "$ROOT/grace/orchestrator" -q
```

If pytest is not available globally, use `python3 -m unittest discover grace/orchestrator -p 'test_*.py' -v`, but pytest is preferred because backend already uses pytest.

2. In `run_backend()`, add actual backend GRACE lint after self-tests and before ruff:

```bash
section "backend: grace_lint app slice"
"$python_bin" "$ROOT/scripts/grace_lint.py" "$API_ROOT/app" --quiet
```

This makes linter a real T0-style gate, not just self-tested tooling.

3. Do not remove `backend-grace`; it stays as stricter explicit command.

### 4.7. `scripts/grace_lint.py`

Keep stdlib only.

Required fixes:

1. Add a lightweight formatting/sanity violation for compressed Python files:

Code:

```text
GRC030: suspicious compressed Python module; too many top-level statements on one physical line
```

Rule:

- If a `.py` file has fewer than 5 physical lines AND AST has more than 5 top-level statements/classes/functions/imports, report `GRC030` at line 1.
- Exempt empty `__init__.py`.

Why: current orchestrator files are readable by Python but bad for review and semantic blocks.

2. Add CLI option:

```text
--skip-function-contracts
```

Use case: transitional MVP for non-active helper scripts if needed. Default remains strict for active backend/orchestrator slices.

3. Add CLI option:

```text
--changed-only-from-git HEAD
```

Optional for this packet. If too much, skip. Acceptance can collect changed files itself.

4. Do not weaken existing violation codes.

### 4.8. `scripts/check_orchestrator_contracts.py`

Required changes:

- Add new required orchestrator files:
  - `contracts.py`
  - `packet_parser.py`
  - `scope_guard.py`
  - `acceptance.py`
- Check role final markers remain present.
- Check `verification_profiles.yml` entries still point to `pnpm guardrails:*` or `bash scripts/guardrails.sh *`.
- Check `packet.schema.json` still requires:
  - `allowed_write_scope`
  - `frozen_scope`
  - `verification`
  - `expected_evidence`
  - `escalation_triggers`
- Add warning, not failure, for legacy packets that do not yet match strict shape. But `W-ORCH-2.md` must pass strict shape.

---

## 5. Тесты: что есть и чего не хватает

### 5.1. Уже есть backend/product tests

В `apps/api/tests` уже много backend-тестов: auth, day endpoints, profile, payment, referral, pipeline, scoring, semantic layer, Solarsage client, subscription ledger, Telegram HMAC, today important и т.д.

Для этого пакета их не надо плодить. Они не проверяют GRACE acceptance loop.

### 5.2. Уже есть linter tests

`script/test_grace_lint.py` уже проверяет:

- clean source;
- missing AI header;
- unclosed module contract;
- unclosed module map;
- unclosed block;
- missing module contract;
- missing function contract;
- missing required field;
- private function exempt.

Недостаточно:

- no syntax error test;
- no unmatched END test;
- no mismatched id test;
- no missing module map presence test;
- no empty `__init__.py` skip test;
- no `main()` exit code test;
- no multiple-file report test;
- no compressed file `GRC030` test.

### 5.3. Уже есть orchestrator tests

`grace/orchestrator/test_orchestrator.py` сейчас проверяет:

- load plan;
- get wave;
- mark completed;
- get progress;
- validate packet smoke.

Проблема: `test_validate_packet` не утверждает конкретный expected result.

### 5.4. Уже есть orchestrator contract tests

`scripts/test_orchestrator_contracts.py` сейчас проверяет только:

- flat yaml parse;
- nested yaml rejection;
- frontmatter extraction.

Недостаточно:

- не проверяет missing required project key;
- не проверяет profiles portability;
- не проверяет role markers;
- не проверяет schema required fields;
- не проверяет strict packet sections;
- не проверяет warnings vs errors.

---

## 6. Новые и обновлённые тесты

Цель: **100% line coverage для нового orchestrator acceptance кода и изменённых linter branches**. Не пытаться в этом пакете выбить 100% по всему продукту: это отдельная большая работа. Для этого пакета 100% означает:

- `grace/orchestrator/contracts.py`
- `grace/orchestrator/packet_parser.py`
- `grace/orchestrator/scope_guard.py`
- `grace/orchestrator/acceptance.py`
- новые ветки в `scripts/grace_lint.py`
- новые ветки в `scripts/check_orchestrator_contracts.py`

### 6.1. `grace/orchestrator/test_contracts.py`

Tests:

1. `test_command_result_passed_true_for_zero_exit`
2. `test_command_result_passed_false_for_nonzero_exit`
3. `test_acceptance_report_to_dict_serializes_nested_dataclasses`
4. `test_reviewer_verdict_contract_fields_are_preserved`
5. `test_verifier_report_contract_fields_are_preserved`

### 6.2. `grace/orchestrator/test_packet_parser.py`

Use temp packet files.

Tests:

1. `test_parse_strict_packet_success`
   - packet has all required sections;
   - returns `PacketContract` with expected lists.
2. `test_parse_packet_requires_frontmatter`
3. `test_parse_packet_requires_id_status_wave_last_review`
4. `test_parse_packet_requires_allowed_scope`
5. `test_parse_packet_requires_frozen_scope`
6. `test_parse_packet_requires_verification`
7. `test_parse_packet_requires_expected_evidence`
8. `test_parse_packet_requires_escalation`
9. `test_parse_packet_does_not_infer_scope_from_prose`
10. `test_parse_packet_supports_verification_profile_optional`

### 6.3. `grace/orchestrator/test_scope_guard.py`

Tests:

1. `test_exact_allowed_path_passes`
2. `test_glob_allowed_path_passes`
3. `test_outside_allowed_scope_rejected`
4. `test_frozen_scope_rejected_even_if_allowed`
5. `test_multiple_violations_are_reported`
6. `test_match_scope_normalizes_posix_paths`
7. `test_collect_git_snapshot_includes_untracked_files`
   - use temp git repo;
   - init, commit one file, modify it, create untracked file.
8. `test_collect_git_snapshot_raises_clear_error_outside_git_repo`

### 6.4. `grace/orchestrator/test_acceptance.py`

Use fake command runner, no real shell commands except maybe parser/scope unit tests.

Create helper:

```python
class FakeRunner:
    def __init__(self, results_by_command: dict[str, CommandResult]): ...
    def run(self, command: str, cwd: Path, timeout_seconds: int) -> CommandResult: ...
```

Tests:

1. `test_t0_packet_parse_failure_returns_pipeline_invalid`
   - invalid packet;
   - final `pipeline_invalid`;
   - `reviewer_called is False`.
2. `test_t0_scope_failure_returns_rework_and_skips_t1_t2`
   - changed file outside allowed;
   - no verifier report;
   - reviewer not called.
3. `test_t0_command_failure_stops_before_verifier`
   - fake `grace_lint` exits 1;
   - no packet verification commands run.
4. `test_t1_verification_command_failure_returns_rework`
   - T0 passes;
   - packet verification command exits 1;
   - reviewer not called.
5. `test_t1_missing_expected_evidence_blocks`
   - packet expected evidence empty or parser rejects before T1.
6. `test_t2_accepts_when_t0_t1_clean`
   - final accepted;
   - reviewer_called true;
   - reviewer verdict accepted.
7. `test_t2_rechecks_scope_after_verifier`
   - fake snapshot changes between T0 and T2;
   - final rework.
8. `test_fast_profile_skips_full_profile_stage`
   - FAST does not run `guardrails full/strict`.
9. `test_normal_profile_runs_packet_commands`
10. `test_strict_profile_runs_strict_guardrail_when_configured`
11. `test_report_contains_exact_commands_stdout_stderr_exit_code`
12. `test_no_llm_or_network_dependency`
   - assert no role prompt file is invoked; implementation uses command runner only.

### 6.5. `grace/orchestrator/test_cli_acceptance.py`

Use `click.testing.CliRunner`.

Tests:

1. `test_accept_command_json_success_exit_zero`
2. `test_accept_command_rework_exit_one`
3. `test_accept_command_pipeline_invalid_exit_two`
4. `test_accept_command_human_output_contains_verdict`
5. `test_accept_command_json_output_is_valid_json`

### 6.6. Update `grace/orchestrator/test_orchestrator.py`

Replace weak assertion:

```python
assert is_valid or len(errors) > 0
```

With deterministic tests:

1. `test_validate_existing_packet_reports_expected_result`
   - choose one known strict packet or temp packet.
2. `test_validate_missing_packet_returns_error`
3. `test_validate_packet_missing_required_section_returns_named_error`
4. `test_load_invalid_xml_raises_clear_value_error`
5. `test_get_ready_waves_ignores_missing_dependency_or_reports_policy`
   - choose expected policy and pin it.
6. `test_mark_completed_nonexistent_wave_noop_or_error`
   - current behavior is noop; either keep and document, or change to return false. Pin one behavior.

### 6.7. Update `scripts/test_grace_lint.py`

Add tests:

1. `test_syntax_error_reports_grc000`
2. `test_unmatched_end_module_contract_reports_grc002`
3. `test_mismatched_module_contract_id_reports_grc002`
4. `test_mismatched_module_map_id_reports_grc003`
5. `test_mismatched_block_id_reports_grc004`
6. `test_missing_module_map_block_reports_grc021`
7. `test_empty_init_py_is_exempt`
8. `test_compressed_module_reports_grc030`
9. `test_main_returns_one_on_violation`
10. `test_main_returns_zero_on_clean_file`
11. `test_main_no_files_found_returns_zero`
12. `test_skip_function_contracts_option_allows_public_def_without_contract`

Do not add redundant tests for every possible marker spelling. One test per branch/code is enough.

### 6.8. Update `scripts/test_orchestrator_contracts.py`

Add tests:

1. `test_check_project_fails_missing_required_key`
2. `test_check_profiles_rejects_non_portable_command`
3. `test_check_packet_schema_fails_missing_required_field`
4. `test_check_roles_fails_missing_heading`
5. `test_check_roles_fails_missing_final_marker`
6. `test_check_packets_fails_missing_frontmatter_key`
7. `test_check_packets_warns_for_legacy_packet_but_does_not_fail`
8. `test_check_packets_requires_at_least_one_packet`

---

## 7. Coverage requirement

Add either:

Option A — minimal pytest-cov:

- Add `pytest-cov` to `apps/api/pyproject.toml` dev dependencies if root test env uses the API venv.
- Add command to orchestrator guardrail:

```bash
python3 -m pytest \
  grace/orchestrator \
  scripts/test_grace_lint.py \
  scripts/test_orchestrator_contracts.py \
  --cov=grace.orchestrator \
  --cov=scripts.grace_lint \
  --cov=scripts.check_orchestrator_contracts \
  --cov-report=term-missing \
  --cov-fail-under=100
```

If `scripts` cannot be imported as package, add empty `scripts/__init__.py` only if safe. Otherwise use coverage config with `coverage run` and `coverage report --include='grace/orchestrator/*.py,scripts/grace_lint.py,scripts/check_orchestrator_contracts.py' --fail-under=100`.

Option B — no new dependency:

- Skip enforced coverage in guardrails for MVP.
- Still write tests that cover all branches.
- Include manual `coverage` command in evidence only if available.

Preferred: Option A, because user asked for 100% backend coverage for this implementation.

---

## 8. Minimal prompt changes

Do not put long GRACE canon into every prompt. Prompts should reference packet contract and output contract.

### 8.1. Coder prompt MVP

Replace/shorten role runtime prompt to:

```text
You are the Coder for one GRACE packet.
Read the packet. Work only inside Allowed Write Scope.
Never touch Frozen / Out Of Scope.
Preserve GRACE markers and contracts.
Run the packet Verification commands that are possible locally.
Return only:
1. changed files
2. commands run with exit codes
3. evidence paths
4. risks/follow-ups
End with FINAL_GRACE_CODER_REPORT_JSON.
```

### 8.2. Verifier prompt MVP

For MVP preferably no LLM verifier. If role prompt is still used elsewhere, reduce to:

```text
You are the Verifier for one GRACE packet.
Do not modify code.
Run the declared verification commands or inspect provided command evidence.
Do not accept missing evidence.
Return FINAL_GRACE_VERIFIER_REPORT_JSON with verdict, commands, evidence, blocking issues.
```

### 8.3. Reviewer prompt MVP

For MVP preferably deterministic reviewer. If role prompt is still used elsewhere:

```text
You are the Reviewer for one GRACE packet.
Check scope first. Then check verifier evidence.
Accept only if allowed scope is respected and all required evidence passed.
Reject with concrete reasons otherwise.
End with FINAL_GRACE_REVIEWER_VERDICT_JSON.
```

---

## 9. Expected final behavior examples

### 9.1. Bad scope

Input:

- packet allows `grace/orchestrator/**`
- diff changes `apps/api/app/main.py`

Output:

```json
{
  "packet_id": "packet-w-orch.2",
  "final_verdict": "rework_required",
  "reviewer_called": false,
  "stages": [
    {
      "stage": "T0",
      "status": "failed",
      "summary": "scope violations",
      "scope_violations": [
        {
          "path": "apps/api/app/main.py",
          "reason": "outside_allowed_scope"
        }
      ]
    }
  ],
  "verifier_report": null,
  "reviewer_verdict": null
}
```

### 9.2. Missing evidence

Output:

```json
{
  "packet_id": "packet-w-orch.2",
  "final_verdict": "blocked",
  "reviewer_called": false,
  "verifier_report": {
    "verdict": "blocked",
    "blocking_issues": ["expected evidence missing: coverage report"]
  }
}
```

### 9.3. Accepted

Output:

```json
{
  "packet_id": "packet-w-orch.2",
  "final_verdict": "accepted",
  "reviewer_called": true,
  "reviewer_verdict": {
    "packet_verdict": "accepted",
    "follow_up_action": "none",
    "route_classification": "accepted",
    "rework_mode": "none",
    "reasons": ["T0 passed", "T1 evidence passed", "scope clean"]
  }
}
```

---

## 10. Acceptance criteria for this implementation

Implementation is accepted only if all are true:

- Fake/static accepted path is gone for `accept` command.
- T0 failure stops pipeline before verifier/reviewer.
- Scope violation always rejects.
- Missing packet sections reject with `pipeline_invalid`.
- Missing evidence cannot be accepted.
- Verifier report contains exact commands and exit codes.
- Reviewer verdict is deterministic and JSON-serializable.
- `scripts/guardrails.sh orchestrator` runs new orchestrator tests.
- `scripts/guardrails.sh backend` runs real backend `grace_lint.py`, not only linter self-tests.
- New/modified Python files are readable multi-line files.
- 100% coverage for new acceptance/orchestrator code is either enforced in guardrails or included as required evidence.
- No product backend/frontend behavior changes.

---

## 11. Suggested implementation order for coder

1. Reformat current `grace/orchestrator/*.py` and `scripts/grace-orch` into normal multi-line Python without behavior changes.
2. Add/repair module contracts and semantic blocks for orchestrator files.
3. Add `contracts.py` and tests.
4. Add `packet_parser.py` and tests.
5. Add `scope_guard.py` and tests.
6. Add `acceptance.py` and tests with fake runner.
7. Add CLI `accept` command and CLI tests.
8. Extend `grace_lint.py` with `GRC030` and missing tests.
9. Extend `check_orchestrator_contracts.py` tests.
10. Wire `guardrails.sh orchestrator/backend`.
11. Create `grace/packets/W-ORCH-2.md` and fill evidence.
12. Run full verification commands.

---

## 12. Notes for reviewer

Do not accept if:

- reviewer/verifier can still return accepted without command evidence;
- any acceptance path uses hardcoded accepted verdict;
- tests only assert “does not crash”;
- `test_validate_packet` still accepts both valid and invalid result;
- coverage is claimed but not generated;
- `apps/api/app/**` product code changed without explicit scope update;
- LLM prompt got bigger instead of smaller;
- guardrails command names changed;
- failures are swallowed as warnings.

