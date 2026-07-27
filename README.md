# GRACE Orchestrator

Автономный оркестратор разработки, который принимает задачу, изучает целевой репозиторий, строит план по волнам и пакетам, запускает AI-агентов, проверяет результат и управляет восстановлением после ошибок.

GRACE работает как отдельный control plane и может вести backend-, frontend- и смешанные проекты. Код изменяют только агенты в изолированных Git worktree; сам оркестратор отвечает за планирование, ограничения, проверки, evidence и слияние результата.

## Для кого

- Для разработчиков и небольших команд, которым нужно выполнять задачи через несколько AI-ролей, а не одним длинным запросом.
- Для проектов, где важны воспроизводимые проверки, контролируемый scope изменений и история решений.
- Для автономной разработки по ТЗ с разбиением на волны, пакетами работ и автоматическим recovery.

## Основные возможности

- Полный цикл: задача → контекст → архитектурный план → coder → verifier → reviewer → merge.
- GRACE-документы, knowledge graph, волны и пакеты работ.
- Детерминированное обнаружение окружения проекта: Python/Node, scripts, Makefile, compose-сервисы и правила `.gitignore`.
- Изолированный Git worktree для каждого пакета и запрет изменений вне разрешённого scope.
- Профили разных моделей и провайдеров через `mini-swe-agent`; поддерживаются CLI Proxy и прямой DeepSeek API.
- Acceptance pipeline T0/T1/T2, evidence-проверка и отдельный reviewer.
- Recovery ladder: повтор coder, смена модели, verifier и возврат к архитектору в зависимости от попытки и причины сбоя.
- Таймаут по отсутствию прогресса: длительные тесты не прерываются, пока обновляются stdout, stderr или артефакты запуска.
- API, web-панель, структурированные логи и полный trace выполнения.
- Supervisor запускает API и workers, следит за процессами и автоматически перезапускает их после сбоя или изменения кода.

## Быстрый запуск

Требования: Linux, Git, Python 3.11+ и целевой проект в Git-репозитории минимум с одним коммитом. Перед запуском рабочее дерево целевого проекта должно быть чистым.

### 1. Установить оркестратор

```bash
git clone https://github.com/basilivanov/grace-orchestrator.git
cd grace-orchestrator

python3 -m venv .venv
.venv/bin/pip install -U pip
.venv/bin/pip install -e ".[dev]"
.venv/bin/pip install "mini-swe-agent>=2.4,<2.5" fastapi uvicorn sqlalchemy httpx
```

### 2. Указать проект и runtime-каталог

Runtime-каталог хранит БД, логи, evidence и служебные worktree отдельно от исходников проекта.

```bash
export GRACE_SOURCE_DIR="$PWD"
export GRACE_PROJECT=/absolute/path/to/your-project
export GRACE_RUNTIME="$HOME/.local/state/grace/my-project"

mkdir -p "$GRACE_RUNTIME"
git -C "$GRACE_PROJECT" status
```

### 3. Настроить модели

Supervisor читает секреты из `$GRACE_RUNTIME/.env`. Файл не нужно добавлять в Git.

Текущая конфигурация использует CLI Proxy на `127.0.0.1:18317` для основного coder и reviewer, а DeepSeek API — как прямой резервный coder:

```dotenv
# $GRACE_RUNTIME/.env
GRACE_MINI_SWE_OPENAI_BASE_URL=http://127.0.0.1:18317/v1
GRACE_MINI_SWE_OPENAI_API_KEY=dummy
DEEPSEEK_API_KEY=replace_with_your_key
```

Модели по умолчанию:

- coder: `openai/gemini-3.6-flash-high` через CLI Proxy;
- резервный coder: `openai/deepseek-v4-flash` через DeepSeek API;
- reviewer: `openai/gpt-5.6-sol`, reasoning effort `xhigh`.

Имена моделей можно переопределить переменными `GRACE_MINI_SWE_CODER_MODEL`, `GRACE_MINI_SWE_DEEPSEEK_CODER_MODEL` и `GRACE_MINI_SWE_REVIEWER_MODEL`.

### 4. Запустить API и worker

```bash
scripts/live_supervisor.sh \
  --source-dir "$GRACE_SOURCE_DIR" \
  --target-dir "$GRACE_RUNTIME" \
  --repo-dir "$GRACE_PROJECT" \
  --workers 1
```

Supervisor работает в foreground. Для остановки нажмите `Ctrl+C`.

После запуска доступны:

- web-панель: <http://127.0.0.1:8042/admin.html>;
- Swagger/OpenAPI: <http://127.0.0.1:8042/docs>;
- health check: <http://127.0.0.1:8042/health>;
- логи: `$GRACE_RUNTIME/api.log` и `$GRACE_RUNTIME/worker.log`.

### 5. Отправить задачу

```bash
curl -X POST http://127.0.0.1:8042/api/features/ \
  -H 'Content-Type: application/json' \
  -d "{
    \"title\": \"Добавить новую функцию\",
    \"description\": \"Подробное ТЗ и критерии готовности\",
    \"target_repo_root\": \"$GRACE_PROJECT\",
    \"mode\": \"draft_plan\",
    \"approval_mode\": \"auto\"
  }"
```

`approval_mode: "auto"` автоматически материализует принятый план и ставит пакеты в очередь. Значение `"manual"` оставляет план на ручное подтверждение.

Статус системы и выполнение задачи можно смотреть в web-панели или через API:

```bash
curl http://127.0.0.1:8042/api/admin/lifecycle/status
curl http://127.0.0.1:8042/api/features/
curl http://127.0.0.1:8042/api/trace/features/FEATURE_ID
```

## Конфигурация

Приоритет настроек: переменные окружения `GRACE_*` → `.grace/config.yaml` → безопасные значения по умолчанию.

Основные параметры:

| Переменная | Назначение |
|---|---|
| `GRACE_TARGET_REPO_ROOT` | Репозиторий, в котором агенты изменяют код |
| `GRACE_DATABASE_URL` | SQLite или PostgreSQL URL control plane |
| `GRACE_STATE_ROOT` | Состояние пакетов и evidence |
| `GRACE_WORKTREE_ROOT` | Изолированные Git worktree |
| `GRACE_WORKERS` | Количество worker-процессов |
| `GRACE_AGENT_TIMEOUT` | Допустимое время без прогресса, по умолчанию 600 секунд |
| `GRACE_AGENT_MAX_TIMEOUT` | Абсолютный предел одного запуска, по умолчанию 3600 секунд |
| `GRACE_API_AUTH_ENABLED` | Включить авторизацию API |
| `GRACE_API_AUTH_TOKEN` | Bearer-токен API |

Полное описание: [конфигурация](docs/grace/CONFIGURATION.md), [supervisor](docs/SUPERVISOR.md), [pipeline выполнения](docs/grace/EXECUTION_PIPELINE.md), [trace и observability](docs/grace/TRACE_AND_OBSERVABILITY.md).

## Важно

Проект находится в статусе alpha. Оркестратор автоматически запускает команды, создаёт ветки, изменяет код и выполняет merge, поэтому используйте отдельный runtime-каталог, защищайте API при внешнем доступе и не запускайте его на репозитории с несохранёнными изменениями.

Лицензия: MIT.
