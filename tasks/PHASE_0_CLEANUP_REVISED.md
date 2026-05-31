# Phase 0: Cleanup & Preparation (REVISED)

**Длительность:** 2 дня
**Цель:** Подготовить проект БЕЗ удаления рабочего кода

**ВАЖНО:** Следуйте CANONICAL_DECISIONS.md — НЕ удаляем legacy code!

---

## Task 0.1: Add Prefect Compatibility Layer

**Приоритет:** Критично
**Время:** 2 часа
**Зависимости:** None

### Описание
Создать no-op декораторы для Prefect, чтобы legacy code работал без Prefect runtime.

### Что делать

#### 1. Создать prefect_compat.py

**src/prefect_grace/prefect_compat.py:**
```python
"""
Prefect compatibility layer - no-op decorators.

Allows legacy code to run without Prefect runtime.
"""
from functools import wraps
from typing import Any, Callable

def task(*args, **kwargs) -> Callable:
    """No-op @task decorator."""
    def decorator(func: Callable) -> Callable:
        @wraps(func)
        def wrapper(*args, **kwargs):
            return func(*args, **kwargs)
        return wrapper
    
    # Handle both @task and @task()
    if len(args) == 1 and callable(args[0]):
        return decorator(args[0])
    return decorator

def flow(*args, **kwargs) -> Callable:
    """No-op @flow decorator."""
    def decorator(func: Callable) -> Callable:
        @wraps(func)
        def wrapper(*args, **kwargs):
            return func(*args, **kwargs)
        return wrapper
    
    if len(args) == 1 and callable(args[0]):
        return decorator(args[0])
    return decorator

class State:
    """Mock State class."""
    def __init__(self, data: Any = None):
        self.data = data

def get_run_logger():
    """Return standard logger instead of Prefect logger."""
    import logging
    return logging.getLogger("prefect_grace")
```

#### 2. Обновить imports в legacy code

**src/prefect_grace/platform/e2e_packet_runner.py:**
```python
# OLD:
# from prefect import task, flow, get_run_logger

# NEW:
try:
    from prefect import task, flow, get_run_logger
except ImportError:
    from prefect_grace.prefect_compat import task, flow, get_run_logger
```

**Применить к файлам:**
- `src/prefect_grace/platform/e2e_packet_runner.py`
- `src/prefect_grace/platform/managed_packet_runner_flow.py`
- `src/prefect_grace/tasks/codex_launcher.py`

### Критерии готовности
- [ ] prefect_compat.py создан
- [ ] Legacy files обновлены (try/except import)
- [ ] Legacy code работает без Prefect runtime
- [ ] Тесты проходят

---

## Task 0.2: Create grace_control Package Structure

**Приоритет:** Критично
**Время:** 1 час
**Зависимости:** None

### Описание
Создать структуру нового пакета `grace_control`.

### Что делать

#### 1. Создать директории

```bash
mkdir -p src/grace_control/{api,core,worker,cli,adapters,db}
touch src/grace_control/__init__.py
touch src/grace_control/api/__init__.py
touch src/grace_control/core/__init__.py
touch src/grace_control/worker/__init__.py
touch src/grace_control/cli/__init__.py
touch src/grace_control/adapters/__init__.py
touch src/grace_control/db/__init__.py
```

#### 2. Создать __init__.py

**src/grace_control/__init__.py:**
```python
"""
GRACE Control Plane.

New control plane wrapper around legacy prefect_grace execution engine.
"""
__version__ = "0.1.0"
```

### Критерии готовности
- [ ] Директории созданы
- [ ] __init__.py файлы созданы
- [ ] Package importable: `import grace_control`

---

## Task 0.3: Update pyproject.toml

**Приоритет:** Критично
**Время:** 1 час
**Зависимости:** Task 0.2

### Описание
Обновить pyproject.toml для новых dependencies и scripts.

### Что делать

#### 1. Добавить dependencies

**pyproject.toml:**
```toml
[project]
dependencies = [
    "prefect>=3.0.0",
    "fastapi>=0.109.0",
    "uvicorn[standard]>=0.27.0",
    "sqlalchemy>=2.0.25",
    "httpx>=0.26.0",
    "click>=8.1.7",
    "rich>=13.7.0",
    "pydantic>=2.5.3",
    "pyyaml>=6.0.1",
]

[project.scripts]
grace = "grace_control.cli.main:cli"
grace-api = "grace_control.api.main:main"
grace-worker = "grace_control.worker.worker:main"
```

#### 2. Install dependencies

```bash
pip install -e .
```

### Критерии готовности
- [ ] Dependencies добавлены
- [ ] Scripts добавлены
- [ ] `pip install -e .` работает
- [ ] `grace --help` работает (после создания CLI)

---

## Task 0.4: Setup Development Environment

**Приоритет:** Средний
**Время:** 2 часа
**Зависимости:** Task 0.3

### Описание
Настроить dev environment (pytest, ruff, mypy).

### Что делать

#### 1. Добавить dev dependencies

**pyproject.toml:**
```toml
[project.optional-dependencies]
dev = [
    "pytest>=7.4.3",
    "pytest-asyncio>=0.21.1",
    "ruff>=0.1.9",
    "mypy>=1.8.0",
]
```

#### 2. Создать pytest.ini

**pytest.ini:**
```ini
[pytest]
testpaths = tests
python_files = test_*.py
python_classes = Test*
python_functions = test_*
asyncio_mode = auto
```

#### 3. Создать ruff.toml

**ruff.toml:**
```toml
line-length = 100
target-version = "py311"

[lint]
select = ["E", "F", "I"]
ignore = ["E501"]
```

### Критерии готовности
- [ ] Dev dependencies установлены
- [ ] pytest работает
- [ ] ruff check работает
- [ ] mypy работает

---

## Task 0.5: Verify Existing Code Works

**Приоритет:** Критично
**Время:** 2 часа
**Зависимости:** Task 0.1

### Описание
Проверить что legacy code работает с prefect_compat.

### Что делать

#### 1. Создать test script

**scripts/test_legacy.py:**
```python
"""Test that legacy code works with prefect_compat."""
from pathlib import Path
from prefect_grace.platform.e2e_packet_runner import run_e2e_packet

def test_legacy_runner():
    """Test legacy runner works."""
    project_root = Path.cwd()
    packet_path = project_root / "grace/packets/TEST/EXECUTION_PACKET.md"
    state_root = project_root / ".grace"
    worktree_root = project_root / ".grace/worktrees"
    
    # Create test packet
    packet_path.parent.mkdir(parents=True, exist_ok=True)
    packet_path.write_text("""# Test Packet

## Description
Test packet for verification.

## Specification
```yaml
scope: src/test.py
```
""")
    
    # Run (dry-run mode)
    result = run_e2e_packet(
        project_root=project_root,
        packet_path=packet_path,
        state_root=state_root,
        worktree_root=worktree_root,
        dry_run=True
    )
    
    print(f"Result: {result}")
    assert result is not None
    print("✅ Legacy runner works!")

if __name__ == "__main__":
    test_legacy_runner()
```

#### 2. Run test

```bash
python scripts/test_legacy.py
```

### Критерии готовности
- [ ] Test script создан
- [ ] Legacy runner работает с prefect_compat
- [ ] Dry-run mode работает
- [ ] No Prefect runtime errors

---

## Phase 0 Complete Checklist

### Все задачи Phase 0
- [ ] Task 0.1: Prefect Compatibility Layer ✅
- [ ] Task 0.2: Package Structure ✅
- [ ] Task 0.3: Update pyproject.toml ✅
- [ ] Task 0.4: Dev Environment ✅
- [ ] Task 0.5: Verify Legacy Code ✅

### Deliverables
- ✅ prefect_compat.py работает
- ✅ grace_control/ structure создана
- ✅ pyproject.toml обновлён
- ✅ Dev tools настроены
- ✅ Legacy code работает

### Что НЕ делаем в Phase 0
- ❌ НЕ удаляем flows/
- ❌ НЕ удаляем platform/
- ❌ НЕ удаляем tasks/
- ❌ НЕ удаляем briefs/

### Готовность к Phase 1
После завершения Phase 0 можно начинать Phase 1: Core Infrastructure
