# TZ: GRACE Orchestrator Runtime / Scope / Context Hardening

Дата: 2026-06-15
Статус: рабочее ТЗ для реализации волнами
Репозиторий: `basilivanov/grace-orchestrator`

## 1. Цель

Устранить системные причины, из-за которых GRACE Orchestrator:

- допускает невалидный или слишком широкий scope;
- запускает кодера без достаточного контекста;
- теряет структуру evidence requirements;
- допускает гонки lease / worker / release;
- зависает на RUNNING / subprocess / stale worker;
- молча подставляет опасные дефолты вместо fail-closed поведения;
- содержит дублирующие и конфликтующие промпты / профили / fallback-логику.

Результат работы: пайплайн planner → materializer → worker → executor → acceptance → verifier/reviewer → recovery должен стать fail-closed, наблюдаемым и безопасным для целевых репозиториев.

## 2. Основной диагноз

Текущая система частично пытается валидировать план, scope, worktree и evidence, но во многих местах продолжает выполнение при плохих входных данных. Это создаёт не один баг, а класс повторяющихся проблем.

Ключевой root cause:

> GRACE сейчас местами работает по принципу fail-open: если architect output неполный, scope пустой, evidence урезан, worktree неочевиден или lease устарел, система часто подставляет дефолт, продолжает работу или молча глотает ошибку.

Нужно заменить это на fail-closed поведение:

> Неясный scope, устаревший lease, пустой packet input, конфликтный prompt contract, недоказуемый worktree root, потерянный evidence contract — это blocking error до запуска кодера.

## 3. Non-goals

В рамках этого ТЗ не нужно:

- переписывать весь orchestrator;
- менять UI радикально, кроме отображения новых diagnostics / compiler errors / stuck state;
- внедрять новый agent framework;
- менять бизнес-логику очередей feature/wave сверх lease/recovery safety;
- добавлять distributed queue / Kafka / Celery;
- оптимизировать скорость агентов до устранения correctness/safety проблем.

## 4. Термины

- **Feature** — пользовательская задача верхнего уровня.
- **Plan** — JSON-план архитектора.
- **Wave** — последовательная фаза внутри feature.
- **Packet** — атомарная задача для кодера/верификатора.
- **Scope** — список repo-relative путей, которые пакет имеет право создавать/менять.
- **Frozen scope** — список repo-relative путей, которые пакет не имеет права менять.
- **Lease** — временное право конкретного worker исполнять конкретный packet.
- **Fencing token** — lease_id/lease_version, который доказывает, что release делает актуальный владелец lease.
- **Execution packet** — `EXECUTION_PACKET.md`, передаваемый агенту.
- **Evidence requirement** — структурированное требование к артефактам/доказательствам.

## 5. Общие принципы реализации

1. **Fail closed вместо fallback.** Пустой scope, неизвестный schema field, отсутствующий packet input, невозможный worktree или stale lease должны останавливать выполнение до запуска кодера.
2. **Один canonical contract.** Architect prompt, YAML profiles, plan compiler, materializer и contract parser должны ожидать одну и ту же JSON-схему.
3. **No silent normalization.** Нельзя молча заменять `scope: []` на `src/`, удалять absolute paths, выкидывать fields evidence или превращать конфликт в default.
4. **Runtime ownership must be fenced.** Любой release/renew/merge должен доказывать владение worker + lease_id.
5. **Coder must have enough context.** Packet должен содержать не только список scope paths, но и дерево, previews, nearby tests/config, contracts и explicit constraints.
6. **Recovery must be observable.** Stuck states, stale leases, dead workers, retry decisions и repair attempts должны оставлять события и diagnostics.
7. **Удаляем дубли и легаси.** Всё, что создаёт второй источник истины или опасный fallback, должно быть удалено, выключено или приведено к canonical interface.

## 6. Target state

После выполнения всех волн:

- architect использует один canonical prompt/contract;
- plan compiler отклоняет invalid plan до materialize;
- packet без scope не может попасть в READY;
- execution packet содержит достаточный контекст для кодера;
- evidence requirements сохраняются структурно до verifier/reviewer;
- worker heartbeat продлевает lease активного пакета;
- stale worker не может release чужой или уже переclaim-нутый packet;
- timeout/runtime failure не убивает feature преждевременно, а идёт по retry/recovery ladder;
- recovery scanner периодически находит stale RUNNING / expired lease / dead worker;
- subprocess runner не зависает навсегда;
- ненужные prompt/profile/default дубли удалены;
- regressions покрыты тестами.

## 7. Волны реализации

Ниже волны идут в порядке выполнения. Не объединять всё в один большой packet. Каждая волна должна иметь отдельные acceptance gates.

---

# Wave 0 — Baseline audit fixtures and safety snapshots

## Цель

Перед изменениями зафиксировать текущее поведение тестами/fixtures, чтобы дальнейшие волны проверяли именно проблемные сценарии.

## Scope candidates

- `tests/`
- `tests/services/`
- `tests/core/`
- `tests/worker/`
- `tests/api/`
- `docs/work/`

## Задачи

1. Добавить regression fixtures для следующих сценариев:
   - plan с `scope: []`;
   - packet без `expected_evidence`;
   - evidence item с полями `stage`, `owner`, `producer`, `profile`, `coder_blocking`, `artifact_patterns`;
   - lease истёк во время активного выполнения;
   - stale worker пытается release после reclaim;
   - timeout agent run;
   - `coder_agy` без input;
   - process closes stdout/stderr but does not exit;
   - scoped_copy + pytest verification;
   - wrong target_repo_root vs orchestrator project_root.
2. Добавить документированный список expected failures до фиксов.
3. Зафиксировать minimal unit/integration test matrix для последующих волн.

## Acceptance criteria

- Есть regression tests, которые до фиксов либо падают, либо помечены как xfail с причиной.
- Каждый xfail содержит ссылку на wave, которая должна его починить.
- Нет изменений runtime behavior в этой волне, только тесты/документация.

## Verification

- `python3 -m pytest tests -q` или targeted subset, если full suite сейчас нестабилен.
- `grep -R "xfail" tests | grep "Wave"` должен показывать осмысленные причины.

---

# Wave 1 — Lease fencing, renewal, and release ownership

## Цель

Исключить двойное выполнение и stale release. Это самый критичный runtime safety слой.

## Problems addressed

- Lease TTL меньше execution timeout.
- Worker heartbeat не продлевает lease.
- `release_packet` принимает `worker_id`, но не проверяет владение lease.
- `PacketService.release()` удаляет lease по `packet_id`, не проверяя `worker_id` / `lease_id`.
- Lease manager может вернуть packet в READY, пока старый worker всё ещё выполняет процесс.

## Scope candidates

- `src/grace_control/services/packet_service.py`
- `src/grace_control/api/routers/packets.py`
- `src/grace_control/api/routers/workers.py`
- `src/grace_control/worker/api_client.py`
- `src/grace_control/worker/worker.py`
- `src/grace_control/core/lease_manager.py`
- `src/grace_control/db/schema.py`
- migrations / schema migration layer, если есть
- related tests

## Required design

### 1. Lease identity / fencing

Release API must require:

- `packet_id`
- `worker_id`
- `lease_id`

Optional but recommended:

- `lease_version` or `fencing_token`
- `claimed_attempt`

`PacketService.release()` must verify:

- lease exists;
- lease.packet_id == packet_id;
- lease.worker_id == worker_id;
- lease.id == lease_id;
- packet.state == RUNNING;
- packet.attempt_count == claimed attempt, если передан.

If verification fails:

- do not mutate packet state;
- do not delete current lease;
- return 409 stale lease / ownership mismatch;
- write event `packet_release_rejected_stale_lease`.

### 2. Lease renewal

Add API endpoint or extend heartbeat:

- `POST /api/packets/{packet_id}/renew-lease`
- or `POST /api/workers/heartbeat` with active `packet_id`, `lease_id`.

Worker must renew active lease while executing.

Renewal rules:

- only current worker + lease_id can renew;
- renewal extends `expires_at = now + lease_ttl`;
- if packet is no longer RUNNING, renewal fails with 409;
- if lease not found, renewal fails with 404/409;
- renewal emits event only on state change or sampled interval to avoid noisy event spam.

### 3. Configurable lease TTL

Add settings:

- `lease_ttl_seconds`, default >= max reasonable heartbeat gap, e.g. 120 or 300;
- `lease_renew_interval_seconds`, default 30;
- `lease_expiration_grace_seconds`, default 30.

Important: lease TTL should not be confused with agent execution timeout. Long tasks are safe because renewal keeps lease alive.

### 4. Release status correction

Timeout/runtime failures with attempts remaining should normally release as `rejected`, not `failed`, so queue retry logic can work.

Rules:

- agent timeout -> `rejected` with failure_class `timeout`, unless max attempts exhausted;
- infrastructure fatal error before agent start may be `failed` only when non-retryable;
- `FAILED` remains terminal.

## Delete / remove / deprecate

- Remove unused or misleading `LEASE_TIMEOUT_MINUTES` constant if not used.
- Remove hardcoded `/tmp/grace_worktrees/...` cleanup path from lease manager; use configured worktree root and packet attempt metadata.
- Remove release paths that do not pass lease_id.
- Remove silent `except Exception: pass` in lease expiration loop; replace with structured warning/error event.

## Acceptance criteria

- Stale worker cannot release a packet after lease expiry/reclaim.
- Worker heartbeat renews lease during long execution.
- Expired lease scanner only returns packet to READY if no valid renewal happened.
- Timeout with attempts remaining results in retryable state, not immediate feature degradation.
- All release/renew failures are visible in packet diagnostics/events.

## Tests

Required tests:

1. `test_release_requires_matching_lease_id`
2. `test_stale_release_does_not_overwrite_new_claim`
3. `test_worker_heartbeat_renews_active_lease`
4. `test_expired_lease_returns_running_to_ready_only_when_not_renewed`
5. `test_timeout_releases_retryable_when_attempts_remaining`
6. `test_failed_remains_terminal_only_for_non_retryable_or_exhausted`

---

# Wave 2 — Fail-closed plan compiler and scope contract

## Цель

Запретить packet без строгого scope и убрать опасные scope defaults.

## Problems addressed

- `scope: []` нормализуется и проходит дальше.
- `build_packet_contract()` подставляет `src/grace_control/` при пустом scope.
- `PacketMaterializer.DEFAULT_SCOPE = "src/"` расширяет права.
- Absolute paths silently stripped instead of rejected.
- Frozen/scope overlaps silently fixed.
- Fallback plan создаёт packet с пустым scope.

## Scope candidates

- `src/grace_control/services/feature_planning_service.py`
- `src/grace_control/core/plan_compiler.py`
- `src/grace_control/core/contracts.py`
- `src/grace_control/services/packet_materializer.py`
- `src/grace_control/services/scope_path_canonicalizer.py`
- tests

## Required behavior

### 1. Empty scope is invalid

Plan compiler must reject:

- missing `scope`;
- `scope: []`;
- `scope: ""`;
- non-list scope except explicit compatibility path with hard error/warning;
- scope with absolute path;
- scope with `..`;
- scope pointing outside target repo;
- scope that names Python import path instead of repo path.

No default fallback to `src/`, `src/grace_control/`, or any broad directory.

### 2. Unknown / incompatible packet schema

Plan compiler should reject packet if it uses incompatible schema such as:

- `allowed_files` instead of `scope`, unless canonicalizer explicitly maps it with warning;
- `forbidden_files` instead of `frozen_scope`, unless mapped;
- `evidence_required` instead of `expected_evidence`, unless mapped.

Decision:

- Either support a short transitional canonicalizer with explicit warnings,
- or reject incompatible schema immediately.

Preferred: transitional canonicalizer for one release, then remove.

### 3. No silent mutation

Stop silently doing:

- `pkt.setdefault("scope", [])`;
- strip absolute paths;
- remove frozen overlap without reporting;
- default verification to broad commands;
- default frozen scope only to archive folder.

Instead:

- compiler error for unsafe conditions;
- compiler warning for safe canonicalization;
- persisted `_plan_compiler.errors/warnings` visible in UI/API.

### 4. Fallback plan behavior

If architect LLM fails:

- do not create executable coder packet with empty scope;
- feature status must become `PLAN_FAILED`;
- store diagnostic artifact with raw error;
- optionally create a non-executable `architect_repack_needed` record, not READY packet.

## Delete / remove / deprecate

- Remove `PacketMaterializer.DEFAULT_SCOPE` or make it impossible to use for executable packets.
- Remove `scope_list = scope_list or ["src/grace_control/"]` from contract build path.
- Remove fallback plan that creates executable empty-scope packet.
- Remove silent absolute path stripping.
- Remove automatic frozen/scope overlap removal; convert to compiler error.

## Acceptance criteria

- A packet with missing/empty scope cannot be approved/materialized.
- A packet with absolute/parent paths is rejected with clear compiler error.
- A packet with scope/frozen overlap is rejected.
- A fallback architect failure does not enqueue executable code work.
- UI/API can show compiler errors.

## Tests

Required tests:

1. `test_plan_compiler_rejects_empty_scope`
2. `test_build_packet_contract_does_not_default_empty_scope`
3. `test_materializer_refuses_packet_without_scope`
4. `test_absolute_scope_path_is_error_not_silently_stripped`
5. `test_scope_frozen_overlap_is_error`
6. `test_architect_fallback_does_not_enqueue_empty_scope_packet`

---

# Wave 3 — Canonical architect prompt and profile unification

## Цель

Убрать конфликтующие источники истины для architect output.

## Problems addressed

Сейчас есть несколько конкурирующих слоёв:

- inline `_build_architect_prompt()`;
- `deepseek-v4-pro` prompt в `agent_profiles.yaml`;
- `architect-premium` prompt в `agent_profiles.yaml`;
- возможно отдельные markdown prompts, если они есть/будут;
- runtime contract ожидает одни поля, часть профилей описывает другие поля.

## Scope candidates

- `src/grace_control/services/feature_planning_service.py`
- `src/grace_control/config/agent_profiles.yaml`
- `src/grace_control/config/agent_profiles.py`
- `prompts/` or `src/grace_control/prompts/`, если будет создано
- `docs/grace/`
- tests

## Required design

### 1. Single source of prompt truth

Create canonical prompt file:

- `src/grace_control/prompts/architect_prompt.md`

or if project convention prefers config:

- `src/grace_control/config/prompts/architect_prompt.md`

Runtime must build prompt as:

1. canonical system prompt from file;
2. task description;
3. context bundle;
4. strict JSON schema block;
5. examples only if schema-compatible.

`_build_architect_prompt()` should become a thin renderer, not a second prompt source.

### 2. Single JSON schema

Canonical architect output must use only:

Top-level:

- `title`
- `description`
- `assumptions`
- `open_questions`
- `waves`
- `constraints`
- `verification`
- `canon_update_decision`

Packet:

- `title`
- `role`
- `scope`
- `frozen_scope` optional packet-level override only if needed
- `acceptance_profile`
- `depends_on`
- `description`
- `coder_instructions`
- `acceptance_criteria`
- `verification`
- `expected_evidence`
- `workspace_requirements` optional

Evidence item:

- `id`
- `kind`
- `stage`
- `owner`
- `producer`
- `profile`
- `required`
- `coder_blocking`
- `artifact_patterns`
- `description`

### 3. Profile cleanup

All architect profiles must reference the same contract.

Options:

- keep `deepseek-v4-pro` as canonical architect executor;
- remove or repurpose `architect-premium` if unused;
- if both remain, both must produce identical JSON schema.

No profile may require fields like `allowed_files`, `forbidden_files`, `evidence_required` unless compiler canonicalizes them explicitly.

### 4. Prompt/profile compatibility test

Add test that loads every architect profile and checks:

- prompt references canonical schema terms;
- no forbidden legacy terms unless listed in transitional mapping;
- profile input mode is valid;
- prompt file exists;
- `_build_architect_prompt()` includes canonical prompt content.

## Delete / remove / deprecate

- Remove duplicate architect contract text from YAML where possible.
- Remove conflicting `allowed_files/forbidden_files/evidence_required/risk_level` contract or map it explicitly and mark deprecated.
- Remove hardcoded long prompt body from `_build_architect_prompt()` after canonical prompt renderer exists.
- Remove unused architect profiles or rename them to explicit experimental profiles not used by runtime.

## Acceptance criteria

- There is one canonical architect JSON schema.
- Runtime architect call and YAML architect profiles do not disagree.
- Architect prompt is testable as file content.
- Any schema mismatch fails before LLM call or before plan approval.

## Tests

Required tests:

1. `test_architect_prompt_file_exists_and_loads`
2. `test_build_architect_prompt_uses_canonical_prompt`
3. `test_architect_profiles_match_canonical_schema`
4. `test_legacy_allowed_files_schema_rejected_or_canonicalized`
5. `test_architect_output_schema_required_fields`

---

# Wave 4 — Execution packet context bundle for coder

## Цель

Кодер не должен работать вслепую. `EXECUTION_PACKET.md` должен содержать enough context, а workspace должен включать необходимые nearby файлы/config.

## Problems addressed

- Architect видит rich context, coder видит почти только flat packet markdown.
- `scoped_copy` копирует мало файлов.
- Config allowlist слишком узкий.
- Tests/imports/config могут отсутствовать в workspace.
- Agent может запуститься в пустой cwd.

## Scope candidates

- `src/grace_control/services/packet_materializer.py`
- `src/grace_control/services/agent_workspace_builder.py`
- `src/grace_control/adapters/packet_executor.py`
- `src/grace_control/services/agent_run_service.py`
- `src/grace_control/core/context_collector.py`
- tests

## Required execution packet sections

`EXECUTION_PACKET.md` must include:

1. Objective
2. Business requirement
3. Explicit role and non-goals
4. Allowed write scope
5. Frozen scope
6. Existing relevant file tree
7. Selected file previews
8. Nearby tests
9. Config/build files available
10. Import/dependency hints
11. Coder instructions
12. Acceptance criteria
13. Verification commands by T0/T1/T2
14. Expected evidence with full structured fields
15. Workspace mode and limitations
16. Target repo root diagnostics
17. Spec JSON full dump

## Context source

Materializer should receive or load context from:

- feature `context_builder` output;
- plan compiler enriched data;
- target repo file inspection;
- packet scope paths and nearby tests.

If context is missing:

- for FAST docs-only packet: can proceed with warning;
- for NORMAL/STRICT code packet: block before coder or require explicit `context_not_required: true`.

## Workspace rules

### scoped_copy

Allowed only when:

- all scope paths are copied;
- required config files are copied;
- relevant tests are copied if verification references them;
- imports can resolve or verification is pure text/diff check;
- compiler marks packet safe for scoped_copy.

Default config allowlist should include, when present:

- `pyproject.toml`
- `pytest.ini`
- `setup.cfg`
- `tox.ini`
- `mypy.ini`
- `ruff.toml`
- `.ruff.toml`
- `package.json`
- `pnpm-lock.yaml`
- `package-lock.json`
- `yarn.lock`
- `tsconfig.json`
- `vite.config.*`
- `vitest.config.*`
- `playwright.config.*`
- `conftest.py`
- `.env.example` only, never `.env`

### target_repo_worktree

Should be default for real target repo work unless explicitly safe minimal copy.

### cwd behavior

`AgentRunService` must not silently create missing cwd for agent execution.

Required:

- if cwd does not exist before run, fail preflight;
- if cwd is not inside expected worktree, fail preflight;
- if cwd is not git repo for full/target worktree mode, fail preflight.

## Delete / remove / deprecate

- Remove or gate `cwd.mkdir(parents=True, exist_ok=True)` in agent run path.
- Remove minimal `config_allowlist=["pyproject.toml"]` as production default.
- Remove any execution path where coder receives neither `{packet_path}` nor `{packet_markdown}`.

## Acceptance criteria

- Coder packet includes meaningful context, not only scope list.
- NORMAL/STRICT packets with missing context are blocked before execution.
- `scoped_copy` is allowed only when safe; otherwise auto-upgrade or compiler reject.
- Agent cannot run in silently-created empty cwd.

## Tests

Required tests:

1. `test_execution_packet_contains_file_tree_and_previews`
2. `test_execution_packet_renders_full_evidence_requirements`
3. `test_normal_packet_requires_context_or_explicit_override`
4. `test_scoped_copy_includes_required_config_allowlist`
5. `test_agent_run_fails_if_cwd_missing_instead_of_creating_it`
6. `test_coder_profiles_all_have_input_mode_or_packet_arg`

---

# Wave 5 — Evidence contract end-to-end

## Цель

Сохранить structured evidence requirements от architect output до verifier/reviewer без потери полей.

## Problems addressed

- `EvidenceRequirement` хранит только `id/kind/required/pattern`.
- `stage/owner/producer/profile/coder_blocking/artifact_patterns` теряются.
- Materializer показывает только id.
- Verifier не получает достаточно информации для проверки evidence.

## Scope candidates

- `src/grace_control/core/contracts.py`
- `src/grace_control/services/packet_materializer.py`
- `src/grace_control/core/evidence_verifier.py`
- `src/grace_control/core/reviewer_gate.py`
- `src/grace_control/services/evidence_service.py`
- tests

## Required model

Update `EvidenceRequirement` to include:

- `id: str`
- `kind: str`
- `stage: str`
- `owner: str`
- `producer: str`
- `profile: str | None`
- `required: bool`
- `coder_blocking: bool`
- `artifact_patterns: list[str]`
- `description: str`
- `validation_hint: str | None`

Backward compatibility:

- if old `pattern` exists, convert to `artifact_patterns=[pattern]` with warning;
- string item becomes minimal evidence requirement with explicit defaults and warning;
- after transition, string evidence should be rejected for STRICT packets.

## Materializer behavior

`EXECUTION_PACKET.md` should render evidence as table or YAML block:

- id
- kind
- required
- coder_blocking
- owner
- producer
- stage
- artifact_patterns
- description

The full raw JSON/YAML remains in Spec JSON too.

## Verifier behavior

Evidence verifier must use structured fields:

- `coder_blocking=true` missing evidence -> return `REWORK_TO_CODER`;
- `owner=architect` missing/invalid evidence -> return `RETURN_TO_ARCHITECT`;
- `kind=screenshot` requires matching screenshot artifact;
- `kind=diff` validates changed_files/diff artifact;
- `kind=file` validates file exists and matches path pattern;
- `kind=command` validates command result artifact.

## Delete / remove / deprecate

- Remove evidence rendering that only shows `- EV-ID`.
- Remove `pattern` as primary field after compatibility window.
- Remove verifier prompt wording that says to blindly trust architect when scope/evidence is impossible.

## Acceptance criteria

- Evidence fields survive architect plan → packet spec → contract → materializer → verifier.
- Missing coder-blocking evidence rejects to coder.
- Architect-owned impossible evidence returns to architect.
- Evidence verifier diagnostics show exact missing artifact pattern.

## Tests

Required tests:

1. `test_evidence_requirement_preserves_all_fields`
2. `test_materializer_renders_structured_evidence`
3. `test_string_evidence_gets_warning_or_rejected_for_strict`
4. `test_missing_coder_blocking_evidence_rework_to_coder`
5. `test_architect_owned_evidence_issue_returns_to_architect`
6. `test_artifact_patterns_replace_legacy_pattern`

---

# Wave 6 — Process supervisor and command runner hardening

## Цель

Исключить вечные зависания subprocess и опасное/неконсистентное выполнение shell commands.

## Problems addressed

- `ProcessSupervisor` делает `proc.wait()` без timeout после stream read.
- Timeout branch тоже ждёт `proc.wait()` без timeout после kill.
- `CommandRunner` в contract пишет no shell=True, но class path использует `shell=True`.
- shell commands могут убегать от timeout через child processes.
- Errors местами глотаются без diagnostics.

## Scope candidates

- `src/grace_control/services/process_supervisor.py`
- `src/grace_control/core/command_runner.py`
- `src/grace_control/core/acceptance_pipeline.py`
- tests

## Required behavior

### ProcessSupervisor

- Use one timeout budget for communicate/read/wait.
- After streams finish, `proc.wait()` must have small timeout.
- On timeout:
  - kill process group;
  - wait with timeout;
  - if still alive, log hard failure and return timeout result;
  - never hang forever.
- Capture partial stdout/stderr on timeout.
- Return diagnostics:
  - timed_out
  - killed_pgid
  - wait_after_kill_timed_out
  - duration_ms
  - command preview

### CommandRunner

Choose one of two options:

Preferred:

- remove `shell=True` by default;
- support shell commands only via explicit `ShellCommandRunner` or `allow_shell=True` with strict timeout/process group kill.

Alternative transitional:

- update contract honestly;
- run shell commands through process group supervisor;
- enforce timeout on whole process group.

Verification commands generated by architect should be POSIX-safe and preferably list-form or simple string parsed safely.

## Delete / remove / deprecate

- Remove misleading “no shell=True” contract if shell remains.
- Remove shell execution from generic `CommandRunner.run()` unless explicit.
- Remove silent catch-all timeout handling without process group cleanup.

## Acceptance criteria

- Process that closes pipes but does not exit cannot hang supervisor.
- Process that forks child cannot outlive timeout unobserved.
- Timeout result includes partial logs.
- Command runner contract matches implementation.

## Tests

Required tests:

1. `test_process_supervisor_wait_after_stream_has_timeout`
2. `test_process_supervisor_kills_process_group_on_timeout`
3. `test_process_supervisor_returns_partial_output_on_timeout`
4. `test_command_runner_no_shell_by_default_or_explicit_shell_only`
5. `test_shell_command_timeout_kills_child_process`

---

# Wave 7 — Worker error handling and retry semantics

## Цель

Сделать worker loop понятным, без dead except, с корректным retry/failure routing.

## Problems addressed

- `worker.py` содержит дублирующий/мёртвый `except Exception`.
- `status` может быть неинициализирован.
- Runtime exception часто release as `failed`, что может деградировать feature.
- Merge failure keeps ACCEPTED but может оставлять packet в неоднозначном состоянии.
- Worker heartbeat отдельно от active packet lease.

## Scope candidates

- `src/grace_control/worker/worker.py`
- `src/grace_control/worker/api_client.py`
- `src/grace_control/services/packet_service.py`
- `src/grace_control/api/routers/packets.py`
- tests

## Required behavior

1. Refactor `_main_loop()` into explicit phases:
   - claim
   - execute
   - release
   - merge
   - post-release retry/recovery
2. Initialize execution state object instead of ad-hoc `status` local.
3. Remove duplicate unreachable except.
4. Distinguish failure classes:
   - `agent_timeout` -> rejected/retryable if attempts remain;
   - `agent_nonzero` -> rejected/retryable;
   - `scope_violation` -> rejected or blocked depending verifier/reviewer;
   - `worktree_preflight_failed` -> rejected/retryable or blocked depending deterministic classification;
   - `stale_lease` -> do not retry/release, worker logs and abandons;
   - `api_error` -> do not mutate packet locally.
5. Merge failure should have explicit state/event:
   - accepted_but_merge_failed, or
   - remain ACCEPTED with `packet_merge_failed` event and visible action required.

## Delete / remove / deprecate

- Remove dead duplicate `except Exception` block.
- Remove release calls that do not include lease_id.
- Remove broad `except: pass` around release failure; replace with logged event/diagnostic.

## Acceptance criteria

- Worker loop has deterministic state transitions.
- Timeout does not immediately terminal-fail a packet with attempts remaining.
- Stale lease release is handled without corrupting packet state.
- Merge failure is visible and actionable.

## Tests

Required tests:

1. `test_worker_timeout_releases_retryable_status`
2. `test_worker_generic_agent_failure_rejected_not_failed_when_retryable`
3. `test_worker_stale_lease_release_does_not_loop_forever`
4. `test_worker_dead_except_removed_or_unreachable_tested`
5. `test_merge_failure_records_action_required_event`

---

# Wave 8 — Recovery controller and proactive stuck scanner

## Цель

Система должна сама находить stale RUNNING, expired lease, dead worker, blocked recoverable и repairable plan failures.

## Problems addressed

- Recovery controller выключен по умолчанию.
- `/health` работает только по запросу.
- Lease scanner может быть не запущен или молча умереть.
- Queue блокируется на RUNNING.
- Repair loop может быть недостижим, если `approve_plan()` кидает exception.

## Scope candidates

- `src/grace_control/core/recovery_controller.py`
- `src/grace_control/core/lease_manager.py`
- `src/grace_control/services/feature_planning_service.py`
- `src/grace_control/api/health.py` or health router
- server startup / background tasks
- tests

## Required behavior

### 1. Background scanners

Add or verify startup of:

- lease expiration scanner;
- worker liveness scanner;
- stuck packet scanner;
- plan repair scanner if applicable.

Scanner checks:

- RUNNING packet with expired lease;
- RUNNING packet whose worker heartbeat is stale;
- Worker current_packet_id but no matching lease;
- Lease exists but packet not RUNNING;
- Feature active but no progress for configured threshold;
- BLOCKED_RECOVERABLE waiting too long;
- PLAN_FAILED with repairable compiler errors.

### 2. Recovery controller default

Decision required:

- enable `recovery_controller_enabled=true` by default for local/dev orchestrator;
- or leave destructive apply disabled but enable read-only scanner by default.

Preferred:

- scanner enabled by default;
- auto-apply only for deterministic safe actions;
- LLM repair needs explicit flag or bounded attempts.

### 3. Plan repair loop fix

`try_approve_or_repair_plan()` must actually catch compiler rejection and run repair/autofix.

Options:

- make `approve_plan()` return structured `PLAN_FAILED` instead of raising for compiler errors;
- or catch ValueError and reload `_plan_compiler.errors`.

Preferred:

- service method returns structured result for expected compiler failures;
- truly unexpected exceptions still raise.

## Delete / remove / deprecate

- Remove silent scanner loops.
- Remove recovery paths that require manual HTTP health call to notice stale runtime.
- Remove unreachable repair loop behavior.

## Acceptance criteria

- Stale RUNNING packet is recovered without manual API call.
- Dead worker is marked stale/inactive.
- Expired lease recovery creates event and clears worker current_packet_id.
- Repairable compiler errors can trigger autofix/repair path.
- Scanner actions are visible in events/diagnostics.

## Tests

Required tests:

1. `test_stuck_running_with_expired_lease_recovered_by_scanner`
2. `test_worker_stale_heartbeat_marks_worker_inactive`
3. `test_lease_without_running_packet_is_cleaned`
4. `test_blocked_recoverable_emits_recovery_waiting_event`
5. `test_try_approve_or_repair_plan_handles_compiler_rejection`
6. `test_recovery_scanner_does_not_apply_unsafe_llm_repair_by_default`

---

# Wave 9 — Profile cleanup and agent input validation

## Цель

Ни один executor profile не должен запускаться без task input, неправильного cwd или конфликтного runtime contract.

## Problems addressed

- `coder_agy` может запускаться без `{packet_path}`/stdin.
- Profiles могут иметь несовместимые input modes.
- Loader не валидирует, что command/input реально передаёт packet.
- Некоторые profile prompts конфликтуют с runtime schema.

## Scope candidates

- `src/grace_control/config/agent_profiles.yaml`
- `src/grace_control/config/agent_profiles.py`
- `src/grace_control/services/agent_run_service.py`
- tests

## Required behavior

Profile validation must reject profile if:

- role coder/architect/reviewer requires packet but neither command nor stdin/file input references packet;
- `input.mode=file` but command does not reference `{packet_path}` and backend does not read default path;
- `input.mode=stdin` but template missing `{packet_markdown}` or equivalent;
- command has unresolved placeholders after render;
- cwd template can resolve outside worktree unless explicitly allowed;
- resume_mode requires resume_flag but missing;
- inject_dir behavior conflicts with backend.

Specific required cleanup:

- Fix `coder_agy` to receive task via stdin/file/packet path.
- Add `input` block for every profile that needs it.
- Mark experimental profiles as disabled or exclude from selection.
- Ensure `select_executor()` cannot choose disabled/invalid profile.

## Delete / remove / deprecate

- Remove profiles that are not used and not tested.
- Remove stale prompts inside YAML if canonical prompt renderer replaces them.
- Remove profile fields that are ignored by loader or runtime.

## Acceptance criteria

- Loading profiles fails fast on invalid input configuration.
- Every selected coder profile receives execution packet.
- `coder_agy` no longer runs empty.
- Disabled/experimental profiles cannot be selected accidentally.

## Tests

Required tests:

1. `test_all_enabled_coder_profiles_receive_packet_input`
2. `test_coder_agy_has_valid_input_mode`
3. `test_profile_loader_rejects_unresolved_packetless_coder`
4. `test_select_executor_skips_disabled_invalid_profiles`
5. `test_architect_profiles_use_canonical_schema`

---

# Wave 10 — Remove legacy defaults, duplicates, and misleading config

## Цель

Выпилить лишнее/ненужное, которое создаёт неоднозначность и повторные баги.

## Removal candidates

### Planning / scope

- `PacketMaterializer.DEFAULT_SCOPE = "src/"` for executable packets.
- `build_packet_contract()` fallback to `src/grace_control/`.
- `pkt.setdefault("scope", [])` in plan normalization.
- fallback executable plan with empty scope.
- silent absolute path stripping.
- silent frozen/scope overlap removal.

### Prompts / profiles

- duplicate architect prompt bodies in YAML if canonical prompt file exists.
- schema-incompatible `architect-premium` contract or unused architect profiles.
- legacy field names: `allowed_files`, `forbidden_files`, `evidence_required`, unless temporary canonicalizer explicitly maps them.

### Runtime / lease

- unused `LEASE_TIMEOUT_MINUTES`.
- hardcoded `/tmp/grace_worktrees/...` cleanup.
- release without lease_id.
- worker heartbeat that cannot renew lease.

### Process / command

- misleading no-shell contract if shell remains.
- `shell=True` generic path unless explicitly isolated.
- `proc.wait()` without timeout.
- silent cwd creation.

### Settings

- duplicate `opencode_server_url` declarations if present.
- unused settings fields not read anywhere.
- settings that are only legacy but still look active.

### Worker

- dead duplicate `except Exception` block.
- broad `except: pass` around critical release/recovery operations.

## Required process

For each removal:

1. Search references.
2. If no runtime references and no tests require it, delete.
3. If tests require it only for legacy compatibility, update tests or move to explicit compatibility module.
4. If user-facing behavior changes, document migration note.
5. Add regression test that old dangerous behavior is gone.

## Acceptance criteria

- No executable path uses broad default scope.
- No selected profile uses conflicting schema.
- No duplicate setting creates ambiguity.
- No critical runtime exception is swallowed without event/log.
- Tests cover removed dangerous defaults.

## Tests

Required tests:

1. `test_no_default_broad_scope_constants_used_for_execution`
2. `test_no_duplicate_opencode_server_url_setting`
3. `test_no_selected_profile_uses_legacy_architect_schema`
4. `test_critical_exceptions_are_logged_not_silently_passed`
5. `test_no_release_endpoint_without_lease_fencing`

---

# Wave 11 — UI/API diagnostics for plan/runtime failures

## Цель

Сделать новые fail-closed ошибки видимыми в Mission Control/UI/API, чтобы пользователь понимал, почему пакет не стартовал.

## Scope candidates

- API routers for features/packets/runs
- UI templates/static JS/CSS if present
- `src/grace_control/services/evidence_service.py`
- runtime artifacts/events
- tests

## Required UI/API surfaces

For feature planning:

- plan compiler errors;
- canonicalizer warnings/errors;
- architect raw error;
- repair attempts;
- reason why PLAN_FAILED.

For packet runtime:

- lease owner;
- lease expires_at;
- lease last_renewed_at;
- worker current_packet_id;
- stale lease release attempts;
- failure_class;
- failure_stage;
- scope enforcement result;
- evidence missing fields;
- merge failed/action required.

For queue/recovery:

- reason no packet available: `running_packet_exists`, `waiting_for_retry`, `waiting_for_recovery`, etc.;
- stuck scanner latest decision;
- next safe action.

## Acceptance criteria

- User can distinguish: plan invalid vs coder failed vs verifier failed vs stale lease vs merge failed.
- API returns structured diagnostics, not only string error.
- UI shows enough information to decide whether to repack, retry, cancel, or inspect logs.

## Tests

Required tests:

1. `test_packet_api_exposes_lease_diagnostics`
2. `test_feature_api_exposes_plan_compiler_errors`
3. `test_ui_renders_plan_failed_reason_without_js_error`
4. `test_ui_renders_stale_running_packet_state`
5. `test_runtime_diagnostics_schema_stable`

---

# Wave 12 — End-to-end hardening scenarios

## Цель

Проверить, что весь pipeline работает безопасно после изменений.

## Required E2E scenarios

1. **Happy path small code packet**
   - architect creates valid plan;
   - materializer writes rich execution packet;
   - coder changes allowed scope;
   - acceptance passes;
   - verifier/reviewer pass;
   - packet merges.

2. **Invalid empty scope**
   - architect output has empty scope;
   - compiler rejects;
   - no packet reaches READY.

3. **Stale release race**
   - worker A claims;
   - lease expires;
   - worker B claims;
   - worker A tries release;
   - release rejected;
   - worker B remains owner.

4. **Long-running agent with renewal**
   - worker executes longer than initial lease TTL;
   - heartbeat renews;
   - no second worker claims.

5. **Coder with insufficient context**
   - NORMAL/STRICT code packet lacks context;
   - execution blocked preflight;
   - diagnostics explain missing context.

6. **Evidence missing artifact**
   - coder changes files but misses coder_blocking evidence;
   - verifier returns REWORK_TO_CODER.

7. **Process timeout**
   - child process hangs;
   - supervisor kills process group;
   - packet gets retryable failure if attempts remain.

8. **Recovery scanner**
   - worker dies;
   - scanner detects stale worker/lease;
   - packet becomes safely retryable;
   - event recorded.

## Acceptance criteria

- All E2E scenarios pass in CI/local test suite.
- No scenario requires manual DB mutation.
- Diagnostics are sufficient to explain every failure.

---

## 8. Global acceptance gates

The full project is accepted only when all of the following are true:

1. No packet can execute with empty or missing scope.
2. No packet can release without current lease ownership.
3. Long-running valid execution does not lose lease.
4. Stale worker cannot overwrite newer worker result.
5. Timeout/retry semantics match queue service rules.
6. Coder receives task input in every enabled coder profile.
7. Evidence requirement fields are preserved end-to-end.
8. ProcessSupervisor cannot hang forever after pipe close or timeout.
9. Recovery scanner can detect stale RUNNING without manual health call.
10. Conflicting architect prompt/profile contracts are removed or unified.
11. All removed dangerous defaults have regression tests.
12. UI/API exposes plan/runtime/recovery diagnostics.

## 9. Suggested implementation order

Recommended order if implementation capacity is limited:

1. Wave 1 — lease fencing/renewal/release ownership.
2. Wave 2 — fail-closed scope contract.
3. Wave 9 — profile input validation, especially `coder_agy`.
4. Wave 6 — process supervisor hardening.
5. Wave 3 — canonical architect prompt.
6. Wave 4 — rich coder context.
7. Wave 5 — evidence contract.
8. Wave 8 — proactive recovery scanner.
9. Wave 10 — cleanup/removal.
10. Wave 11/12 — UI/API diagnostics and E2E scenarios.

Reason: first remove corruption/race risks, then remove bad planning/execution inputs, then improve quality/context/evidence.

## 10. Definition of done per wave

Each wave must finish with:

- implementation committed;
- focused unit tests;
- at least one regression test for the original bug class;
- docs update if behavior changed;
- no unrelated formatting churn;
- no package/lockfile changes unless explicitly required by that wave;
- clear report in `docs/work/` or PR body:
  - changed files;
  - behavior before/after;
  - tests run;
  - known limitations.

## 11. Risks and mitigations

### Risk: too many fail-closed rejections initially

Mitigation:

- add transitional canonicalizer warnings for legacy fields;
- keep explicit escape hatches only behind settings;
- diagnostics must explain exact field/path causing rejection.

### Risk: existing tests assume broad defaults

Mitigation:

- update tests to provide explicit scope;
- keep compatibility helper for tests only if needed;
- do not keep production broad defaults.

### Risk: recovery scanner mutates too aggressively

Mitigation:

- scanner enabled by default in observe/deterministic mode;
- LLM repair/manual-risk actions require explicit flag;
- every scanner mutation must write event.

### Risk: context packet becomes too large

Mitigation:

- cap previews by chars/lines;
- include selected relevant files, not whole repo;
- include file tree and signatures/contracts compactly;
- add artifact link/path to full context bundle when available.

### Risk: shell command compatibility breaks

Mitigation:

- support explicit shell runner for commands that need shell syntax;
- require process group timeout;
- update architect prompt to prefer simple commands/scripts.

## 12. Open decisions

1. Should `recovery_controller_enabled` become true by default, or only scanner true / auto-apply false?
2. Should legacy architect fields be rejected immediately or canonicalized for one transition window?
3. Should `scoped_copy` remain a production mode or be limited to fixtures/docs-only packets?
4. Should merge failure create a new explicit packet state, or remain ACCEPTED with action-required event?
5. Should architect prompt live under `src/grace_control/prompts/` or `docs/grace/prompts/`?

## 13. Recommended decisions

1. Enable deterministic scanner by default; keep LLM repair auto-apply disabled unless explicitly enabled.
2. Canonicalize legacy fields for one release with warnings, then reject.
3. Make `target_repo_worktree` default for real code packets; keep `scoped_copy` for docs-only/simple fixture-safe packets.
4. Keep ACCEPTED on merge failure for now, but add explicit `packet_merge_failed` diagnostics and UI action.
5. Put runtime prompt under `src/grace_control/prompts/architect_prompt.md`; mirror human docs in `docs/grace/` if needed.

## 14. Final expected architecture

After all waves, the execution chain should look like this:

```text
Feature request
  ↓
Context Builder
  → context artifact: file tree, relevant previews, contracts, nearby tests
  ↓
Architect using canonical prompt + schema
  ↓
Plan Compiler / Canonicalizer
  → fail closed on invalid scope/schema/evidence
  ↓
Materializer
  → rich EXECUTION_PACKET.md with context + structured evidence
  ↓
Worker claim
  → lease_id/fencing token
  ↓
Worker execution
  → heartbeat renews lease
  ↓
Executor / ProcessSupervisor
  → bounded subprocess, no silent cwd, no stale session/input
  ↓
Scope enforcement + Acceptance
  ↓
Evidence verifier / Reviewer
  ↓
Release with worker_id + lease_id
  ↓
Merge or retry/recovery
  ↓
Scanner monitors stale states continuously
```

## 15. Minimal first PR recommendation

If this TZ is implemented by GRACE itself, first generated feature should be:

**Title:** P0 Runtime Safety: lease fencing, renewal, and fail-closed empty scope

Packets:

1. Add lease_id/fencing to claim/release API and worker client.
2. Add active lease renewal from worker heartbeat.
3. Reject stale release and add tests.
4. Remove empty scope fallback in contract/materializer/compiler.
5. Adjust timeout release semantics from terminal FAILED to retryable REJECTED when attempts remain.

This gives immediate safety improvement before larger prompt/context cleanup.
