# Phase 0: Cleanup & Preparation

**Длительность:** 2-3 дня
**Цель:** Удалить legacy код, подготовить структуру для нового Control Plane

---

## Task 0.1: Remove Prefect Dependencies

**Приоритет:** Критично
**Время:** 4 часа
**Зависимости:** Нет

### Описание
Удалить все зависимости от Prefect из проекта.

### Что делать

#### 1. Удалить из pyproject.toml
```toml
# Удалить эти строки:
prefect = "^2.14.0"
prefect-docker = "^0.4.0"
```

#### 2. Удалить Prefect-специфичные файлы
```bash
rm -rf src/prefect_grace/flows/
rm -f src/prefect_grace/deploy_live.py
rm -f src/prefect_grace/runtime.py
rm -f src/prefect_grace/platform/prefect_*.py
```

**Список файлов для удаления:**
- `src/prefect_grace/flows/live_dashboard.py`
- `src/prefect_grace/flows/packet_lifecycle.py`
- `src/prefect_grace/deploy_live.py`
- `src/prefect_grace/runtime.py`
- `src/prefect_grace/platform/prefect_e2e_real_dry_run_smoke.py`
- `src/prefect_grace/platform/prefect_worker_binding.py`

#### 3. Создать prefect_compat.py (no-op декораторы)
```python
# src/prefect_grace/prefect_compat.py
"""
Compatibility layer for code that still has @task/@flow decorators.
These are no-ops that allow gradual migration.
"""

def task(*args, **kwargs):
    """No-op task decorator."""
    def decorator(func):
        return func
    if len(args) == 1 and callable(args[0]):
        return args[0]
    return decorator

def flow(*args, **kwargs):
    """No-op flow decorator."""
    def decorator(func):
        return func
    if len(args) == 1 and callable(args[0]):
        return args[0]
    return decorator
```

#### 4. Обновить импорты
Найти все файлы с импортами Prefect:
```bash
grep -r "from prefect import" src/
grep -r "import prefect" src/
```

Заменить на:
```python
# Было:
from prefect import task, flow

# Стало:
from prefect_grace.prefect_compat import task, flow
```

### Критерии готовности
- [ ] Prefect удалён из pyproject.toml
- [ ] Все Prefect-специфичные файлы удалены
- [ ] prefect_compat.py создан
- [ ] Все импорты обновлены
- [ ] `poetry install` работает без ошибок
- [ ] Существующие тесты проходят

---

## Task 0.2: Remove Old Briefs

**Приоритет:** Средний
**Время:** 1 час
**Зависимости:** Нет

### Описание
Удалить старые briefs (будут заменены на новый формат feature specs).

### Что делать

#### 1. Удалить директорию briefs
```bash
rm -rf briefs/
```

#### 2. Удалить код работы с briefs
```bash
# Найти файлы работающие с briefs
grep -r "briefs/" src/
grep -r "brief.yaml" src/
```

Удалить или закомментировать:
- `src/prefect_grace/platform/brief_parser.py` (если есть)
- Функции загрузки briefs

### Критерии готовности
- [ ] Директория briefs/ удалена
- [ ] Код работы с briefs удалён
- [ ] Проект запускается без ошибок

---

## Task 0.3: Create New Project Structure

**Приоритет:** Критично
**Время:** 2 часа
**Зависимости:** Task 0.1

### Описание
Создать новую структуру директорий для Control Plane.

### Что делать

#### 1. Создать новую структуру
```bash
mkdir -p src/grace_control/{api,core,worker,cli,models}
mkdir -p src/grace_control/api/{routers,middleware}
mkdir -p src/grace_control/core/{state_machine,executors,policies,routers}
mkdir -p src/grace_control/worker
mkdir -p src/grace_control/cli
```

**Финальная структура:**
```
src/
├── grace_control/              # Новый Control Plane
│   ├── __init__.py
│   ├── api/                    # FastAPI server
│   │   ├── __init__.py
│   │   ├── main.py            # FastAPI app
│   │   ├── routers/           # API routers
│   │   │   ├── features.py
│   │   │   ├── packets.py
│   │   │   ├── workers.py
│   │   │   ├── architect.py
│   │   │   ├── artifacts.py
│   │   │   └── system.py
│   │   └── middleware/
│   │       ├── logging.py
│   │       └── tracing.py
│   ├── core/                   # Core logic
│   │   ├── __init__.py
│   │   ├── state_machine.py   # Packet state machine
│   │   ├── executors/         # Executor abstraction
│   │   │   ├── base.py
│   │   │   ├── api_provider.py
│   │   │   └── local_provider.py
│   │   ├── policies/          # Acceptance policies
│   │   │   ├── base.py
│   │   │   └── simple_policy.py
│   │   └── routers/           # Complexity routers
│   │       ├── base.py
│   │       └── heuristic_router.py
│   ├── worker/                 # Worker process
│   │   ├── __init__.py
│   │   ├── worker.py          # Main worker loop
│   │   └── api_client.py      # API client
│   ├── cli/                    # CLI wrapper
│   │   ├── __init__.py
│   │   ├── main.py            # Click app
│   │   └── commands/
│   │       ├── architect.py
│   │       ├── packet.py
│   │       └── worker.py
│   ├── db/                     # Database
│   │   ├── __init__.py
│   │   ├── schema.py          # SQLAlchemy models
│   │   └── migrations/        # Alembic migrations
│   ├── logging.py              # Structured logging
│   ├── config.py               # Configuration
│   └── models.py               # Domain models (Pydantic)
│
└── prefect_grace/              # Existing code (reuse)
    ├── platform/               # Reuse: execution engine, worktree, git
    ├── tasks/                  # Reuse: codex_launcher
    └── prefect_compat.py       # No-op decorators
```

#### 2. Создать __init__.py файлы
```bash
touch src/grace_control/__init__.py
touch src/grace_control/api/__init__.py
touch src/grace_control/api/routers/__init__.py
touch src/grace_control/core/__init__.py
touch src/grace_control/core/executors/__init__.py
touch src/grace_control/core/policies/__init__.py
touch src/grace_control/core/routers/__init__.py
touch src/grace_control/worker/__init__.py
touch src/grace_control/cli/__init__.py
touch src/grace_control/cli/commands/__init__.py
touch src/grace_control/db/__init__.py
```

#### 3. Создать базовые файлы

**src/grace_control/__init__.py:**
```python
"""
GRACE Control Plane - AI-first orchestration system.
"""

__version__ = "0.1.0"
```

**src/grace_control/config.py:**
```python
"""
Configuration management.
"""
from pathlib import Path
from pydantic import BaseModel
from typing import Optional
import yaml

class LoggingConfig(BaseModel):
    level: str = "INFO"
    format: str = "jsonl"
    output: str = "file"
    components: dict[str, str] = {}
    debug_mode: bool = False

class ProjectConfig(BaseModel):
    key: str
    root: Path
    logging: LoggingConfig = LoggingConfig()

def load_config(config_path: Path) -> ProjectConfig:
    """Load project configuration from YAML."""
    with open(config_path) as f:
        data = yaml.safe_load(f)
    return ProjectConfig(**data)
```

### Критерии готовности
- [ ] Новая структура директорий создана
- [ ] Все __init__.py файлы созданы
- [ ] Базовые файлы (config.py) созданы
- [ ] Импорты работают: `from grace_control.config import load_config`

---

## Task 0.4: Setup Development Environment

**Приоритет:** Средний
**Время:** 2 часа
**Зависимости:** Task 0.3

### Описание
Настроить окружение для разработки нового Control Plane.

### Что делать

#### 1. Обновить pyproject.toml
```toml
[tool.poetry.dependencies]
python = "^3.11"
fastapi = "^0.109.0"
uvicorn = {extras = ["standard"], version = "^0.27.0"}
sqlalchemy = "^2.0.25"
alembic = "^1.13.1"
pydantic = "^2.5.3"
pydantic-settings = "^2.1.0"
httpx = "^0.26.0"
click = "^8.1.7"
rich = "^13.7.0"
python-telegram-bot = "^20.7"
pillow = "^10.2.0"  # Для thumbnails
pytest = "^7.4.4"
pytest-asyncio = "^0.23.3"
pytest-xdist = "^3.5.0"  # Параллельные тесты
pytest-rerunfailures = "^13.0"  # Retry failed tests

[tool.poetry.scripts]
grace-api = "grace_control.api.main:main"
grace = "grace_control.cli.main:cli"
grace-worker = "grace_control.worker.worker:main"
```

#### 2. Установить зависимости
```bash
poetry install
```

#### 3. Настроить pre-commit hooks
```yaml
# .pre-commit-config.yaml
repos:
  - repo: https://github.com/astral-sh/ruff-pre-commit
    rev: v0.1.14
    hooks:
      - id: ruff
        args: [--fix]
      - id: ruff-format
  
  - repo: https://github.com/pre-commit/mirrors-mypy
    rev: v1.8.0
    hooks:
      - id: mypy
        additional_dependencies: [types-all]
```

```bash
pre-commit install
```

#### 4. Создать .env.example
```bash
# .env.example
GRACE_LOG_LEVEL=INFO
GRACE_DEBUG_MODE=false
GRACE_DB_URL=sqlite:///./grace.db
ANTHROPIC_API_KEY=sk-ant-xxx
GOOGLE_API_KEY=xxx
TELEGRAM_BOT_TOKEN=xxx
TELEGRAM_CHAT_ID=xxx
```

### Критерии готовности
- [ ] pyproject.toml обновлён
- [ ] Все зависимости установлены
- [ ] pre-commit hooks настроены
- [ ] .env.example создан
- [ ] `poetry run grace --help` работает (даже если пустой)

---

## Task 0.5: Verify Existing Code Works

**Приоритет:** Критично
**Время:** 2 часа
**Зависимости:** Task 0.1, 0.2, 0.3

### Описание
Проверить что существующий код (который переиспользуем) работает после cleanup.

### Что делать

#### 1. Проверить execution engine
```python
# Тест что run_e2e_packet работает
from prefect_grace.platform.packet_executor import run_e2e_packet

# Должен импортироваться без ошибок
```

#### 2. Проверить worktree management
```python
from prefect_grace.platform.worktree_manager import WorktreeManager

# Должен работать
```

#### 3. Проверить agent launcher
```python
from prefect_grace.tasks.codex_launcher import launch_codex

# Должен работать
```

#### 4. Запустить существующие тесты
```bash
pytest tests/ -v
```

#### 5. Исправить сломанные импорты
Если тесты падают из-за Prefect импортов:
```python
# Заменить на prefect_compat
from prefect_grace.prefect_compat import task, flow
```

### Критерии готовности
- [ ] run_e2e_packet импортируется
- [ ] WorktreeManager работает
- [ ] launch_codex работает
- [ ] Существующие тесты проходят (или исправлены)
- [ ] Нет ошибок импорта Prefect

---

## Phase 0 Checklist

### Готовность к Phase 1
- [ ] Task 0.1: Prefect dependencies удалены ✅
- [ ] Task 0.2: Old briefs удалены ✅
- [ ] Task 0.3: Новая структура создана ✅
- [ ] Task 0.4: Dev environment настроен ✅
- [ ] Task 0.5: Existing code работает ✅

### Deliverables
- ✅ Проект без Prefect зависимостей
- ✅ Новая структура директорий
- ✅ Dev environment готов
- ✅ Существующий код работает
- ✅ Готовы начинать Phase 1

---

## Следующий шаг
После завершения Phase 0 → **Phase 1: Core Infrastructure**
