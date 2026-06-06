# ТЗ: Исправление worktree-изоляции и портабельности GRACE orchestrator

**Статус:** implemented ✓
**Приоритет:** P0 — блокирует live-запуск воркеров
**Дата:** 2026-06-06
**Реализовано:** 2026-06-06

---

## Контекст проблемы

При запуске живых воркеров возникают три класса ошибок:

1. **Агент (opencode run) пишет файлы в корень проекта, а не в per-packet worktree**
2. **git worktree add молча падает** — агент работает в пустой/main директории
3. **Рассинхрон путей между компонентами** — settings/env/cleanup используют разные naming conventions

---

## ПРОБЛЕМА 1: Агент пишет не туда (cwd mismatch)

### Корневая причина

`opencode run` подключается к opencode-серверу на :4096. Сервер работает из
**своего** cwd (корень проекта), а не из cwd CLI-процесса. Даже если
`ProcessSupervisor` (`process_supervisor.py:45`) ставит `PWD=worktree_path` и
`cwd=worktree_path` — сервер это игнорирует.

### Текущий фикс (частичный)

В `agent_run_service.py:67-71` есть инъекция `--dir <worktree_path>`:

```python
if command and command[0] == "opencode":
    for i, part in enumerate(command):
        if part == "run":
            command = command[:i + 1] + ["--dir", str(worktree_path)] + command[i + 1:]
            break
```

### Что не работает

- Фикс написан, но мог не применяться из-за кэшированных `.pyc` + зомби-процессов supervisor.
- Фикс хрупкий — `command[0] == "opencode"` не покрывает случай `/usr/bin/opencode` или `python -m opencode`.
- `--dir` инъектируется **только** для `opencode`, но не для `agy` и других бэкендов.
- Нет валидации, что `worktree_path` **реально существует и является git worktree** перед запуском агента.

### Задачи

| # | Что сделать | Файл | Приоритет |
|---|------------|------|-----------|
| 1.1 | Перенести `--dir` инъекцию из хардкода в `agent_profiles.yaml` — каждый профиль должен декларативно указывать `cwd: "{worktree_path}"` и `--dir {worktree_path}` в command template | `agent_profiles.yaml`, `agent_run_service.py` | P0 |
| 1.2 | Добавить **pre-flight check** перед запуском агента: `assert worktree_path.exists() and is_git_worktree(worktree_path)`. Если false — fail fast с ясным сообщением, не запускать агента | `packet_executor.py:229-257` (метод `_call_executor`) | P0 |
| 1.3 | Убить хардкод `command[0] == "opencode"` в `agent_run_service.py:67`. Вместо этого ввести поле `inject_dir: true` в профиле агента | `agent_run_service.py`, `agent_profiles.yaml` | P0 |
| 1.4 | Добавить в `ProcessSupervisor` логирование effective cwd и env для дебага | `process_supervisor.py` | P1 |

---

## ПРОБЛЕМА 2: git worktree add молча падает

### Корневая причина

В `packet_executor.py:242-250`:

```python
add_result = GitService().worktree_add(self.project_root, wt_path, branch, base_ref=base_ref)
if not add_result.success and "already exists" not in add_result.stderr:
    GraceLogger("packet_executor").warn("worktree_add_failed", ...)
    # НО ПРОДОЛЖАЕТ ВЫПОЛНЕНИЕ! Нет return/raise
```

Если `worktree_add` падает — **выполнение продолжается**, агент запускается с
`wt_path`, который может не существовать или быть пустой директорией.
`cwd.mkdir(parents=True, exist_ok=True)` в `agent_run_service.py:110` создаст
пустую папку — и агент работает в ней без кода проекта.

### Также: cleanup_attempt ищет worktree не там

В `worktree_cleanup_service.py:48`:

```python
wt = project_root / slug  # НО worktree создаётся в worktree_root / slug!
```

Cleanup ищет worktree по `project_root / slug`, но `packet_executor.py:235`
создаёт worktree по `worktree_root / slug`. Если это разные пути — cleanup
ничего не чистит, и `worktree_add` падает с "already exists".

### Задачи

| # | Что сделать | Файл | Приоритет |
|---|------------|------|-----------|
| 2.1 | **FAIL FAST** при неудачном `worktree_add`: если `add_result.success == False` и это не "already exists" — вернуть `ExecutionResult(accepted=False, reason="worktree_add_failed: {stderr}")`. НЕ продолжать выполнение | `packet_executor.py:242-250` | P0 |
| 2.2 | Исправить `WorktreeCleanupService.cleanup_attempt`: передавать `worktree_root` вместо `project_root` как базовый путь для поиска. `wt = worktree_root / slug`, не `project_root / slug` | `worktree_cleanup_service.py:48`, `packet_executor.py:108` (вызов cleanup_attempt) | P0 |
| 2.3 | Обрабатывать случай "branch already exists": перед `worktree_add` проверять и удалять старую ветку `agent/{slug}` | `packet_executor.py` или `worktree_cleanup_service.py` | P0 |
| 2.4 | Добавить `git worktree prune` перед каждым `worktree_add` для очистки stale entries | `packet_executor.py:_call_executor` | P1 |
| 2.5 | После успешного `worktree_add` — валидировать что `wt_path` содержит `.git` или `.git` файл (является реальным worktree) | `packet_executor.py` | P1 |

---

## ПРОБЛЕМА 3: Рассинхрон путей

### 3.1. Два разных GraceSettings

Есть **две** версии `GraceSettings`:

- `src/grace_control/config/__init__.py` — старая, с `state_root: str = "/tmp/grace-eval"`, `execution_backend: str = "legacy"`
- `src/grace_control/config/settings.py` — новая, с `state_root: str = ".grace/state"`, `execution_backend: str = "cli"`

Какой из них импортируется зависит от import path. Это бомба замедленного действия.

### 3.2. Несовпадение имён директорий

| Компонент | state_root по умолчанию | worktree_root по умолчанию |
|-----------|------------------------|---------------------------|
| `settings.py` | `.grace/state` | `.grace/worktrees` |
| `project_config.py` | `.grace/state` | `.grace/worktrees` |
| `git_context.py` | `{target}/.grace_state` | `{target}/.grace_worktrees` |
| `live_supervisor.sh` | `$TARGET_DIR/.grace_state` | `$TARGET_DIR/.grace_worktrees` |
| `live_worker.py` | `{project_root}/.grace_state` | `{project_root}/.grace_worktrees` |
| `config/__init__.py` (старый) | `/tmp/grace-eval` | *нет поля* |

**Три разных naming convention**: `.grace/state` vs `.grace_state` vs `/tmp/grace-eval`.
Worker использует `.grace_state`, а settings по умолчанию `.grace/state` — они
**никогда не совпадут** без явного env override.

### 3.3. DB fallback расхождение

| Компонент | DB URL fallback |
|-----------|----------------|
| `run_api.py:10` | `sqlite:////tmp/grace_live.db` |
| `live_worker.py:21` | `sqlite:////tmp/grace_live.db` |
| `settings.py:73` | `sqlite:///./grace.db` |
| `config/__init__.py:56` | `sqlite:///./grace.db` |
| `Makefile:3` | `sqlite:////tmp/grace-orchestrator-export/test_grace.db` |

### 3.4. Hardcoded paths

| Файл | Строка | Значение |
|------|--------|---------|
| `agent_profiles.yaml:8` | `workdir` | `/tmp/grace-orchestrator-export` |
| `grace/project.yaml:5` | `root` | `/tmp/grace-orchestrator-export` |
| `grace/runtime.yaml:8` | `working_directory` | `/tmp/grace-orchestrator-export` |
| `live_supervisor.sh:20` | `DEFAULT_SOURCE_DIR` | `/tmp/grace-orchestrator-export` |

### Задачи

| # | Что сделать | Файл | Приоритет |
|---|------------|------|-----------|
| 3.1 | **Удалить** дублирующий Settings класс из `config/__init__.py`. Все imports должны идти через `config.settings`. Если есть код, который импортирует `from grace_control.config import GraceSettings` — перенаправить на `config.settings` | `src/grace_control/config/__init__.py` | P0 |
| 3.2 | **Унифицировать** naming: выбрать ОДНО имя для state/worktree директорий. Каноническое: `.grace/state` и `.grace/worktrees` (как в `settings.py`). Обновить `git_context.py:49-50`, `live_supervisor.sh:59-60`, `live_worker.py:45-46` | `git_context.py`, `live_supervisor.sh`, `live_worker.py` | P0 |
| 3.3 | **Убрать** hardcoded `/tmp/grace-orchestrator-export` из: `agent_profiles.yaml:8`, `grace/project.yaml:5`, `grace/runtime.yaml:8`, `live_supervisor.sh:20`. Заменить на `"."` или вычислять через env/cwd | все перечисленные файлы | P0 |
| 3.4 | **Единый DB URL resolution**: убрать дублирование в `run_api.py`, `live_worker.py`. Оба должны использовать `settings.database_url` без собственных fallback-ов | `run_api.py`, `live_worker.py` | P1 |
| 3.5 | Сделать `agent_profiles.yaml` → `workdir` relative или вычисляемым через `{project_root}` template var | `agent_profiles.yaml`, `command_template_renderer.py` | P1 |

---

## ПРОБЛЕМА 4: Портабельность (работа на других проектах)

### Текущее состояние

Оркестратор привязан к самому себе: пути, конфиги, yaml-файлы содержат
`/tmp/grace-orchestrator-export`. Чтобы запустить на другом проекте, нужно:

- `target_dir` — где live DB + state + worktrees
- `source_dir` — где код grace-orchestrator
- `target_repo_root` — целевой репо, в котором работают агенты

Эти три пути сейчас путаются и пересекаются.

### Задачи

| # | Что сделать | Файл | Приоритет |
|---|------------|------|-----------|
| 4.1 | Добавить `target_repo_root` в `.grace/config.yaml` schema как **обязательное** поле при работе на внешнем проекте | `project_config.py` | P0 |
| 4.2 | `git_context.py` — при отсутствии `target_repo_root` и `GRACE_TARGET_REPO_ROOT` использовать `GRACE_PROJECT_ROOT` или cwd. Документировать приоритет | `git_context.py` | P1 |
| 4.3 | Worker должен получать `target_repo_root` от API/settings, а не вычислять из cwd | `worker.py`, `live_worker.py` | P1 |
| 4.4 | Написать `scripts/init_project.sh` — инициализация `.grace/config.yaml` для нового проекта с подсказками | новый файл | P2 |

---

## Порядок выполнения

### P0 (блокирующие, ломают live-запуск)

```
3.1 → Удалить дублирующий config/__init__.py (Settings)
3.2 → Унифицировать state/worktree naming (.grace/state, .grace/worktrees)
3.3 → Убрать hardcoded пути из yaml + sh
2.1 → Fail fast при worktree_add failure
2.2 → Fix cleanup_attempt path mismatch (worktree_root vs project_root)
2.3 → Handle "branch already exists"
1.1 → --dir в профили агентов
1.2 → Pre-flight check worktree перед запуском агента
1.3 → Убить хардкод command[0] == "opencode"
4.1 → target_repo_root в config schema
```

### P1 (стабильность)

```
1.4 → Логирование cwd/env в ProcessSupervisor
2.4 → worktree prune перед add
2.5 → Post-add validation worktree
3.4 → Единый DB URL resolution
3.5 → workdir template var в agent_profiles
4.2 → git_context fallback documentation
4.3 → Worker target_repo_root from API
```

### P2 (удобство)

```
4.4 → init_project.sh
```

---

## Затронутые файлы (полный список)

### Обязательные изменения (P0)

| Файл | Тип изменения |
|------|--------------|
| `src/grace_control/config/__init__.py` | Удалить дублирующий Settings, оставить re-export |
| `src/grace_control/config/settings.py` | Без изменений (каноническая версия) |
| `src/grace_control/core/git_context.py:49-50` | Заменить `.grace_state` → `.grace/state`, `.grace_worktrees` → `.grace/worktrees` |
| `src/grace_control/adapters/packet_executor.py:242-250` | Fail fast при worktree_add failure |
| `src/grace_control/adapters/packet_executor.py:108` | Передавать worktree_root в cleanup_attempt |
| `src/grace_control/services/worktree_cleanup_service.py:47-48` | Принимать worktree_root, использовать worktree_root / slug |
| `src/grace_control/services/agent_run_service.py:67-71` | Убрать хардкод `command[0] == "opencode"`, использовать поле профиля |
| `src/grace_control/config/agent_profiles.yaml:8` | Убрать hardcoded workdir |
| `src/grace_control/config/agent_profiles.yaml` (все профили) | Добавить `--dir {worktree_path}` в command template для opencode-профилей |
| `scripts/live_supervisor.sh:20,59-60,68` | Убрать hardcoded пути, унифицировать naming |
| `scripts/live_worker.py:45-46` | Унифицировать naming state/worktree |
| `grace/project.yaml:5` | Убрать hardcoded root |
| `grace/runtime.yaml:8` | Убрать hardcoded working_directory |
| `src/grace_control/config/project_config.py` | Добавить target_repo_root в schema |

### Желательные изменения (P1)

| Файл | Тип изменения |
|------|--------------|
| `src/grace_control/services/process_supervisor.py` | Добавить логирование cwd/env |
| `scripts/run_api.py` | Убрать собственный DB fallback |
| `scripts/live_worker.py` | Убрать собственный DB fallback |
| `src/grace_control/services/command_template_renderer.py` | Добавить `{project_root}` в KNOWN_KEYS |

---

## Критерии приёмки

1. ✅ `scripts/live_supervisor.sh --target-dir /tmp/test-project` запускается без hardcoded путей (`DEFAULT_SOURCE_DIR` вычисляется через `dirname`)
2. ✅ Воркер создаёт worktree в `{target_dir}/.grace/worktrees/{slug}` — единообразно во всех компонентах
3. ✅ При неудачном `worktree_add` — пакет переходит в FAILED, агент НЕ запускается
4. ✅ `opencode run` получает `--dir {worktree_path}` через `inject_dir: true` в профиле (не хардкод)
5. ✅ Cleanup корректно находит worktree по `worktree_root/slug`, а не `project_root/slug`
6. ✅ Нет дублирующих GraceSettings — один канонический класс в `config/settings.py`
7. ✅ `make test` (grace_control suite): 445 passed, 0 failed (pre-existing failures не изменились)
