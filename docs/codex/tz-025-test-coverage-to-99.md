# TZ-025: Доведение покрытия тестами до 99%

**Статус:** ACTIVE
**Дата:** 2026-06-05
**Цель:** Довести line coverage control plane (`src/grace_control/`) до 99% за счёт тестов для непокрытых модулей.

---

## 1. Анализ текущего состояния

### 1.1 Текущее покрытие

| Метрика | Значение |
|---------|----------|
| Тест-файлов в `tests/` | 37 |
| Тест-функций | 254 |
| Модулей core без тестов | 11 |
| API роутеров без тестов | 3 |
| CLI команд без тестов | 6+ |

### 1.2 Модули С тестами (покрыты adequately)

- `acceptance_pipeline.py` — `tests/grace_control/core/test_acceptance_pipeline.py`
- `command_runner.py` — `tests/grace_control/core/test_command_runner.py`
- `contracts.py` — `tests/grace_control/core/test_contracts.py`
- `evidence_verifier.py` — `tests/grace_control/core/test_evidence_verifier.py`
- `feature_recovery.py` — `tests/grace_control/core/test_feature_recovery.py` (58 tests)
- `packet_operations.py` — `tests/unit/test_packet_ops_extended.py`
- `recovery_controller.py` — `tests/grace_control/core/test_recovery_controller.py`
- `recovery_rules.py` — `tests/grace_control/core/test_recovery_rules.py`
- `reviewer_gate.py` — `tests/grace_control/core/test_reviewer_gate.py`
- `scope_guard.py` — `tests/grace_control/core/test_scope_guard.py`
- `state_machine.py` — `tests/test_state_machine.py` + `tests/unit/test_state_machine_extended.py`
- `uid.py` — `tests/grace_control/core/test_uid.py`
- `event_recorder.py` — `tests/unit/test_event_recorder.py`
- `feature_gate.py` — `tests/unit/test_feature_gate.py`
- `wave_gate.py` — `tests/unit/test_wave_gate.py`
- `dag_validator.py` — `tests/unit/test_dag_validator_extended.py`
- `lease_manager.py` — `tests/test_lease_manager.py` + `tests/unit/test_lease_manager_extended.py`
- `complexity_router.py` — `tests/grace_control/core/test_contracts.py` (间接)

### 1.3 Модули БЕЗ тестов (пробелы)

| Модуль | Путь | Кол-во строк | Приоритет |
|--------|------|-------------|-----------|
| `structured_logger.py` | `core/` | 101 | HIGH |
| `telegram_notify.py` | `core/` | 59 | HIGH |
| `git_context.py` | `core/` | 58 | HIGH |
| `hello.py` | `core/` | 35 | LOW |
| `self_reload.py` | `core/` | 104 | HIGH |
| `context_collector.py` | `core/` | 252 | HIGH |
| `evidence.py` | `core/` | 137 | HIGH |
| `grace_canon.py` | `core/` | 183 | MEDIUM |
| `executor_selector.py` | `core/` | 91 | HIGH |
| `llm_runner.py` | `core/` | 147 | HIGH |
| `self_evolution_guard.py` | `core/` | 151 | HIGH |
| `health.py` | `core/` | 59 | MEDIUM |
| `architect.py` | `api/routers/` | 436 | HIGH |
| `recovery.py` | `api/routers/` | 113 | HIGH |
| `self_evolution.py` | `api/routers/` | 363 | HIGH |
| `ws_broadcast.py` | `api/` | 69 | HIGH |
| `trace.py` | `cli/` | 128 | MEDIUM |
| `main.py` | `api/` | 353 | MEDIUM |

---

## 2. Требования к тестам

### 2.1 Общие правила

- Все тесты — в `tests/` (не в `src/`)
- Используем `pytest` + `pytest-asyncio` (auto mode)
- DB-тесты через in-memory SQLite (`conftest.py:db` fixture)
- API-тесты через `httpx.AsyncClient` + `ASGITransport` (`conftest.py:api` fixture)
- Внешние зависимости (LLM, Telegram, git subprocess) — mock через `monkeypatch` или `unittest.mock`
- Не импортируем `mocker` из `pytest-mock` — только `monkeypatch` (built-in)
- Каждый тест —独立, без state между тестами
- Обязательно проверять edge cases: None, пустые списки, исключения

### 2.2 Покрытие каждого модуля

Минимум тестов для 99% coverage:

| Модуль | Мин. тестов | Покрытие |
|--------|------------|----------|
| `structured_logger.py` | 6 | Все методы GraceLogger, log_event, trace_context, get_trace_id |
| `telegram_notify.py` | 5 | set_telegram_config, notify_event (успех/ошибка/не сконфигурирован) |
| `git_context.py` | 4 | resolve с env/без env, дефолты, кастомные пути |
| `hello.py` | 1 | greet() |
| `self_reload.py` | 5 | disabled, no uvicorn, success, failure+rollback, rollback failure |
| `context_collector.py` | 7 | collect (успех/LLM fallback/summarize fallback), _scan_files, _extract_* |
| `evidence.py` | 8 | check_expected_evidence (FAST/NORMAL/STRICT), EvidenceCollector, _check_evidence_kind (command/file/diff/log) |
| `grace_canon.py` | 6 | check_file (all rules), check_directory, edge cases |
| `executor_selector.py` | 5 | load_profiles, select_executor, get_escalation, resolve_model, default fallback |
| `llm_runner.py` | 4 | run_llm (успех/stall/timeout/empty), _load_role_config |
| `self_evolution_guard.py` | 6 | check (all 4 checks), FORBIDDEN_FILES, edge cases |
| `health.py` | 3 | healthy/degraded/unhealthy, dead worker cleanup |
| `architect.py` | 5 | create_plan (YAML/LLM/DAG error/timeout), _slugify, _extract_action |
| `recovery.py` | 4 | evaluate, get_packet_recovery, get_feature_recovery |
| `self_evolution.py` | 6 | create_evolution, list/get/cancel session, guard_check |
| `ws_broadcast.py` | 3 | handle_websocket, broadcast_event, dead client cleanup |
| `trace.py` | 4 | collect_events, collect_packet_runs, format_timeline, trace command |
| `main.py` | 2 | health endpoint, dashboard endpoint |

**Итого:** ~89 новых тестов

---

## 3. Детальный план по модулям

### 3.1 `tests/unit/test_structured_logger.py` (6 тестов)

```python
# Тестируемые функции:
# - GraceLogger.__init__, info, warn, error, debug
# - log_event
# - trace_context (context manager)
# - get_trace_id

# Тесты:
# test_logger_info_outputs_json - проверяет JSON на stderr
# test_logger_warn_outputs_json - проверяет level=WARN
# test_logger_error_outputs_json - проверяет level=ERROR
# test_logger_debug_outputs_json - проверяет level=DEBUG
# test_log_event_standalone - проверяет log_event без component
# test_trace_context_sets_and_restores - trace_context устанавливает/снимает trace_id
# test_get_trace_id_returns_none_outside_context - get_trace_id возвращает None
# test_logger_includes_ctx_kwargs - проверяет ctx поле в JSON
```

### 3.2 `tests/unit/test_telegram_notify.py` (5 тестов)

```python
# Тестируемые функции:
# - set_telegram_config(token, chat_id)
# - notify_event(event_type, packet_id, **kwargs)

# Тесты:
# test_set_config_from_args - set_telegram_config с аргументами
# test_set_config_from_env - set_telegram_config из env vars
# test_notify_skipped_when_not_configured - notify_event без конфига = no-op
# test_notify_sends_http_post - mock httpx, проверяет POST
# test_notify_handles_http_error - mock httpx raising, silent failure
```

### 3.3 `tests/unit/test_git_context.py` (4 теста)

```python
# Тестируемые функции:
# - resolve_git_execution_context(**kwargs)

# Тесты:
# test_resolve_defaults - все дефолты из cwd
# test_resolve_from_env_vars - GRACE_TARGET_REPO_ROOT, GRACE_STATE_ROOT, etc
# test_resolve_custom_overrides - кастомные пути перебивают env
# test_base_ref_default - base_ref по умолчанию HEAD
```

### 3.4 `tests/unit/test_hello.py` (1 тест)

```python
# test_greet_returns_string - greet() == "hello from self-evolution"
```

### 3.5 `tests/unit/test_self_reload.py` (5 тестов)

```python
# Тестируемые классы:
# - GraceSelfReloader
# - ReloadResult

# Тесты:
# test_disabled_returns_success - GRACE_SELF_RELOAD_ENABLED=false
# test_no_uvicorn_returns_success - pgrep не находит uvicorn
# test_success_signal_sent - mock os.kill, pgrep находит pid
# test_failure_triggers_rollback - mock os.kill raising, проверяет git revert
# test_rollback_failure - mock git revert тоже падает
```

### 3.6 `tests/unit/test_context_collector.py` (7 тестов)

```python
# Тестируемые функции:
# - _scan_files(root, scopes)
# - _analyze_file(filepath, root)
# - _read_content(filepath)
# - _extract_module_contract(text)
# - _extract_exports(text)
# - _extract_json_block(text)
# - ContextCollector.collect (с mock LLM)

# Тесты:
# test_scan_files_finds_python - _scan_files находит .py файлы
# test_scan_files_skips_pycache - пропускает __pycache__
# test_analyze_file_extracts_contract - _analyze_file извлекает MODULE_CONTRACT
# test_analyze_file_extracts_exports - _analyze_file извлекает def/class names
# test_read_content_truncates - _read_content обрезает длинные файлы
# test_extract_module_contract_returns_none - когда нет контракта
# test_collect_uses_fallback_on_llm_error - collect fallback при ошибке LLM
```

### 3.7 `tests/unit/test_evidence.py` (8 тестов)

```python
# Тестируемые функции:
# - check_expected_evidence(expected, stage_results, worktree_path, changed_files, profile)
# - EvidenceCollector.collect_from_stage
# - EvidenceCollector.has_required_evidence

# Тесты:
# test_fast_profile_skips_all - FAST = всегда пустой issues
# test_normal_requires_successful_command - NORMAL без successful command = ошибка
# test_strict_requires_evidence - STRICT с пустым expected = False
# test_check_command_evidence_found - kind=command, pattern найден
# test_check_command_evidence_missing - kind=command, pattern не найден
# test_check_file_evidence - kind=file, glob совпадает
# test_check_diff_evidence - kind=diff, fnmatch совпадает
# test_collector_collect_from_stage - collect_from_stage извлекает команды
```

### 3.8 `tests/unit/test_grace_canon.py` (6 тестов)

```python
# Тестируемые классы:
# - GraceCanonChecker.check_file
# - GraceCanonChecker.check_directory

# Тесты:
# test_check_file_valid - файл с всеми контрактами проходит
# test_check_file_missing_header - нет AI_HEADER
# test_check_file_missing_contract - нет MODULE_CONTRACT
# test_check_file_too_large - > 1000 строк
# test_check_directory - check_directory находит violations
# test_check_file_unreadable - нечитаемый файл = violation
```

### 3.9 `tests/unit/test_executor_selector.py` (5 тестов)

```python
# Тестируемые функции:
# - load_profiles
# - select_executor(role, attempt)
# - get_escalation(role)
# - resolve_model(role)

# Тесты:
# test_load_profiles_returns_dict - load_profiles возвращает dict
# test_select_executor_default_fallback - нет roles = DEFAULT_EXECUTOR
# test_select_executor_escalation - attempt 1 vs 2 vs 3
# test_get_escalation_sorted - сортировка по priority
# test_resolve_model_default - нет matching = DEFAULT_MODEL
```

### 3.10 `tests/unit/test_llm_runner.py` (4 теста)

```python
# Тестируемые функции:
# - _load_role_config(role)
# - run_llm(prompt, role=, model=, cli=, cwd=)

# Тесты:
# test_load_role_config_defaults - дефолтные stall/hard timeouts
# test_load_role_config_from_yaml - чтение из agent_profiles.yaml
# test_run_llm_empty_output_raises - mock subprocess, пустой stdout = RuntimeError
# test_run_llm_stall_raises - mock subprocess зависший = RuntimeError
```

### 3.11 `tests/unit/test_self_evolution_guard.py` (6 тестов)

```python
# Тестируемые классы:
# - SelfEvolutionGuard.check
# - 4 внутренних проверки

# Тесты:
# test_all_checks_pass - чистые файлы = passed=True
# test_api_routes_removed_fails - удалён маршрут = check failed
# test_db_schema_drop_fails - DROP TABLE = check failed
# test_self_loop_fails - FORBIDDEN_FILES в changed = check failed
# test_canon_compliance_fails - нет AI_HEADER = check failed
# test_no_api_files_skipped - нет api/ файлов = api_contracts OK
```

### 3.12 `tests/unit/test_health.py` (3 теста)

```python
# Тестируемые функции:
# - check_health()

# Тесты:
# test_healthy_no_workers - нет workers = unhealthy
# test_healthy_all_active - все active = healthy
# test_dead_worker_cleanup - dead worker = degraded, packet reset to READY
```

### 3.13 `tests/api/test_architect_api.py` (5 тестов)

```python
# Тестируемые функции:
# - POST /api/architect/plan
# - _slugify, _extract_action

# Тесты:
# test_plan_yaml_mode - YAML с waves = создаёт feature+packets
# test_plan_no_title_400 - нет title = 400
# test_plan_dag_cycle_422 - цикл в DAG = 422
# test_slugify - _slugify("Hello World!") == "hello-world"
# test_extract_action - _extract_action("Add login endpoint") == "ADD-LOGIN"
```

### 3.14 `tests/api/test_recovery_api.py` (4 теста)

```python
# Тестируемые эндпоинты:
# - POST /api/recovery/evaluate/{packet_id}
# - GET /api/recovery/packets/{packet_id}
# - GET /api/recovery/features/{feature_id}

# Тесты:
# test_evaluate_returns_decision - evaluate возвращает decision
# test_get_packet_recovery - get recovery history
# test_get_feature_recovery - get feature recovery summary
# test_evaluate_with_apply - apply=true вызывает apply
```

### 3.15 `tests/api/test_self_evolution_api.py` (6 тестов)

```python
# Тестируемые эндпоинты:
# - POST /api/self/evolve
# - GET /api/self/sessions
# - GET /api/self/sessions/{id}
# - POST /api/self/sessions/{id}/cancel
# - GET /api/self/guard/check

# Тесты:
# test_create_evolution_no_title_400 - нет title = 400
# test_list_sessions_empty - нет sessions = пустой список
# test_get_session_not_found_404 - несуществующий session = 404
# test_cancel_terminal_session_400 - cancel completed = 400
# test_guard_check - guard/check возвращает结果
# test_create_evolution_max_sessions_429 - > MAX_SESSIONS = 429
```

### 3.16 `tests/api/test_ws_broadcast.py` (3 теста)

```python
# Тестируемые функции:
# - broadcast_event(event_type, data)
# - handle_websocket(ws)

# Тесты:
# test_broadcast_sends_to_clients - broadcast_event отправляет payload
# test_broadcast_recovery_extra_event - recovery_ тип = доп. recovery_update
# test_dead_client_cleanup - ошибка отправки = клиент удалён
```

### 3.17 `tests/cli/test_trace.py` (4 теста)

```python
# Тестируемые функции:
# - collect_events
# - collect_packet_runs
# - format_timeline
# - trace command (CLI)

# Тесты:
# test_collect_events_from_db - collect_events читает events
# test_collect_packet_runs - collect_packet_runs читает runs
# test_format_timeline_output - format_timeline форматирует строку
# test_trace_no_args_shows_help - trace без аргументов = "Specify --packet..."
```

### 3.18 `tests/api/test_main.py` (2 теста)

```python
# Тестируемые эндпоинты:
# - GET /health
# - GET /api/dashboard

# Тесты:
# test_health_endpoint - /health возвращает status
# test_dashboard_endpoint - /api/dashboard возвращает features/waves/packets
```

---

## 4. Приоритеты реализации

### Phase 1: Core модули без внешних зависимостей (highest ROI)
1. `test_structured_logger.py` — 6 тестов
2. `test_git_context.py` — 4 теста
3. `test_hello.py` — 1 тест
4. `test_evidence.py` — 8 тестов
5. `test_executor_selector.py` — 5 тестов
6. `test_grace_canon.py` — 6 тестов
7. `test_context_collector.py` — 7 тестов (с mock LLM)

### Phase 2: Core модули с внешними зависимостями
8. `test_telegram_notify.py` — 5 тестов (mock httpx)
9. `test_self_reload.py` — 5 тестов (mock os.kill, subprocess)
10. `test_self_evolution_guard.py` — 6 тестов (mock subprocess)
11. `test_llm_runner.py` — 4 теста (mock subprocess)
12. `test_health.py` — 3 теста (DB)

### Phase 3: API роутеры
13. `test_architect_api.py` — 5 тестов
14. `test_recovery_api.py` — 4 теста
15. `test_self_evolution_api.py` — 6 тестов
16. `test_ws_broadcast.py` — 3 теста
17. `test_main.py` — 2 теста

### Phase 4: CLI
18. `test_trace.py` — 4 теста

---

## 5. Приёмочные критерии

- [ ] Все 89 тестов написаны и проходят
- [ ] `pytest tests/ -v` — 0 failures (кроме 7 pre-existing в test_acceptance_pipeline.py)
- [ ] Line coverage `src/grace_control/` >= 99%
- [ ] Нет новых зависимостей (только pytest, pytest-asyncio, monkeypatch)
- [ ] Все внешние зависимости замоканы (LLM, Telegram, git, httpx)
- [ ] Каждый тест независим (нет state leakage)
- [ ] Edge cases покрыты: None, пустые списки, ошибки чтения файлов

---

## 6. Файлы для создания

```
tests/unit/test_structured_logger.py
tests/unit/test_telegram_notify.py
tests/unit/test_git_context.py
tests/unit/test_hello.py
tests/unit/test_self_reload.py
tests/unit/test_context_collector.py
tests/unit/test_evidence.py
tests/unit/test_grace_canon.py
tests/unit/test_executor_selector.py
tests/unit/test_llm_runner.py
tests/unit/test_self_evolution_guard.py
tests/unit/test_health.py
tests/api/test_architect_api.py
tests/api/test_recovery_api.py
tests/api/test_self_evolution_api.py
tests/api/test_ws_broadcast.py
tests/api/test_main.py
tests/cli/test_trace.py
```

---

## 7. Зависимости

- Нет новых pip-зависимостей
- Используем `conftest.py:db`, `conftest.py:api`, `conftest.py:make_packet`, `conftest.py:make_feature`
- `monkeypatch` для mock (built-in pytest)
- `unittest.mock.patch` для contextlib.mock если нужен async mock
