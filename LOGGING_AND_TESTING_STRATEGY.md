# GRACE Control Plane — Logging & Testing Strategy

## 🔍 Logging Strategy

### Текущее состояние
✅ У вас уже есть structured logs с trace_id
✅ Формат: JSONL
✅ Проброс trace_id через все компоненты

### Что нужно добавить

#### 1. Уровни логирования с возможностью включения/выключения

**Конфигурация:**
```yaml
# project.yaml
logging:
  level: INFO              # DEBUG | INFO | WARNING | ERROR
  format: jsonl            # jsonl | text
  output: file             # file | stdout | both
  
  # Детальное управление по компонентам
  components:
    worker: DEBUG          # Детальные логи worker
    executor: INFO         # Логи запуска агентов
    state_machine: DEBUG   # Все переходы состояний
    acceptance: DEBUG      # Решения по приёмке
    api: INFO              # API requests
    db: WARNING            # Только ошибки DB
  
  # Trace ID
  trace_id_header: X-Trace-ID
  propagate_trace_id: true
  
  # Rotation
  max_size_mb: 100
  max_files: 10
  
  # Debug mode (очень детальные логи)
  debug_mode: false        # true = логи ВЕЗДЕ
```

#### 2. Структура логов

**Базовый формат (JSONL):**
```json
{
  "timestamp": "2026-05-31T10:05:00.123Z",
  "level": "info",
  "component": "worker",
  "trace_id": "FEAT-USER-AUTH-W01-P01-CREATE-JWT-UTILS-R01",
  "message": "Starting packet execution",
  "context": {
    "packet_id": "FEAT-USER-AUTH-W01-P01-CREATE-JWT-UTILS",
    "run_id": "R01",
    "worker_id": "worker-1",
    "attempt": 1
  }
}
```

**С дополнительными данными:**
```json
{
  "timestamp": "2026-05-31T10:05:45.678Z",
  "level": "info",
  "component": "acceptance",
  "trace_id": "FEAT-USER-AUTH-W01-P01-CREATE-JWT-UTILS-R01",
  "message": "Acceptance decision made",
  "context": {
    "packet_id": "FEAT-USER-AUTH-W01-P01-CREATE-JWT-UTILS",
    "run_id": "R01",
    "decision": "ACCEPT",
    "reason": "All tests passed",
    "profile": "STRICT",
    "tests": {
      "T0": "passed",
      "T1": "passed",
      "T2": "passed"
    }
  },
  "duration_ms": 45000
}
```

#### 3. Где логировать (везде!)

**Worker loop:**
```python
# Каждый шаг worker loop
logger.info("Worker started", extra={
    "component": "worker",
    "worker_id": worker_id,
    "trace_id": None  # Пока нет packet
})

logger.info("Claiming packet", extra={
    "component": "worker",
    "worker_id": worker_id
})

logger.info("Packet claimed", extra={
    "component": "worker",
    "worker_id": worker_id,
    "trace_id": packet_id,
    "packet_id": packet_id
})
```

**State machine transitions:**
```python
# Каждый переход состояния
logger.info("State transition", extra={
    "component": "state_machine",
    "trace_id": packet_id,
    "packet_id": packet_id,
    "from_state": "READY",
    "to_state": "RUNNING",
    "trigger": "worker_claimed"
})
```

**Acceptance pipeline (ступенчатая приёмка):**
```python
# Каждый шаг pipeline
logger.info("Starting acceptance step", extra={
    "component": "acceptance",
    "trace_id": run_id,
    "packet_id": packet_id,
    "run_id": run_id,
    "step": "T0",
    "step_name": "Lint & GRACE Canon"
})

logger.info("Acceptance step completed", extra={
    "component": "acceptance",
    "trace_id": run_id,
    "packet_id": packet_id,
    "run_id": run_id,
    "step": "T0",
    "status": "passed",
    "duration_ms": 1200
})

# Если fail
logger.warning("Acceptance step failed", extra={
    "component": "acceptance",
    "trace_id": run_id,
    "packet_id": packet_id,
    "run_id": run_id,
    "step": "T0",
    "status": "failed",
    "reason": "Lint errors found",
    "errors": ["missing contract in auth.py"]
})
```

**Executor (запуск агентов):**
```python
logger.info("Starting executor", extra={
    "component": "executor",
    "trace_id": run_id,
    "packet_id": packet_id,
    "run_id": run_id,
    "executor_id": "claude-opus-api",
    "role": "coder"
})

logger.debug("Executor command", extra={
    "component": "executor",
    "trace_id": run_id,
    "command": "codex1 --model claude-opus-4-8 ...",
    "workdir": "/tmp/worktree/PKT-001"
})

logger.info("Executor completed", extra={
    "component": "executor",
    "trace_id": run_id,
    "packet_id": packet_id,
    "run_id": run_id,
    "status": "success",
    "duration_ms": 45000,
    "tokens": {
        "input": 12000,
        "output": 8500
    }
})
```

**API requests:**
```python
# FastAPI middleware
logger.info("API request", extra={
    "component": "api",
    "trace_id": request.headers.get("X-Trace-ID"),
    "method": "POST",
    "path": "/api/packets/PKT-001/accept",
    "client_ip": request.client.host
})

logger.info("API response", extra={
    "component": "api",
    "trace_id": request.headers.get("X-Trace-ID"),
    "method": "POST",
    "path": "/api/packets/PKT-001/accept",
    "status_code": 200,
    "duration_ms": 150
})
```

**Database operations:**
```python
# Только если debug_mode или db component = DEBUG
logger.debug("DB query", extra={
    "component": "db",
    "trace_id": trace_id,
    "query": "UPDATE packets SET state=? WHERE id=?",
    "params": ["RUNNING", "PKT-001"]
})
```

#### 4. Debug mode (детальные логи ВЕЗДЕ)

**Когда включён debug_mode:**
```yaml
logging:
  debug_mode: true
```

**Что логируется дополнительно:**
- Все DB queries
- Все API requests/responses с телами
- Все промпты агентам (input)
- Все ответы агентов (output)
- Все файловые операции
- Все git операции
- Все проверки GRACE Canon
- Все решения complexity router

**Пример debug лога:**
```json
{
  "timestamp": "2026-05-31T10:05:10.123Z",
  "level": "debug",
  "component": "executor",
  "trace_id": "FEAT-USER-AUTH-W01-P01-CREATE-JWT-UTILS-R01",
  "message": "Agent prompt",
  "context": {
    "packet_id": "FEAT-USER-AUTH-W01-P01-CREATE-JWT-UTILS",
    "run_id": "R01",
    "prompt": "You are a coder agent. Implement JWT utilities...",
    "prompt_length": 12000
  }
}
```

#### 5. Trace ID propagation

**Через все компоненты:**
```
User request → API (генерирует trace_id)
  ↓
Worker (получает trace_id из packet)
  ↓
Executor (передаёт trace_id агенту)
  ↓
Agent (логирует с trace_id)
  ↓
Tests (логируют с trace_id)
  ↓
Acceptance (логирует с trace_id)
  ↓
DB (сохраняет с trace_id)
```

**Все логи одного packet run имеют один trace_id:**
```bash
# Фильтрация логов по trace_id
grep "FEAT-USER-AUTH-W01-P01-CREATE-JWT-UTILS-R01" logs/grace.jsonl

# Или через jq
cat logs/grace.jsonl | jq 'select(.trace_id == "FEAT-USER-AUTH-W01-P01-CREATE-JWT-UTILS-R01")'
```

#### 6. Log aggregation в UI

**UI может показывать логи:**
```
GET /api/packets/{packet_id}/runs/{run_id}/logs
→ Возвращает все логи для этого run

GET /api/packets/{packet_id}/runs/{run_id}/logs?component=acceptance
→ Фильтр по компоненту

GET /api/packets/{packet_id}/runs/{run_id}/logs?level=error
→ Только ошибки
```

**В UI:**
```
┌─────────────────────────────────────────────────┐
│ Logs for R01                                    │
├─────────────────────────────────────────────────┤
│ Filter: [All components ▼] [All levels ▼]      │
│                                                 │
│ [10:05:00] INFO  worker: Packet claimed        │
│ [10:05:05] INFO  executor: Starting executor   │
│ [10:05:10] DEBUG executor: Agent prompt sent   │
│ [10:05:45] INFO  executor: Executor completed  │
│ [10:05:46] INFO  acceptance: Starting T0       │
│ [10:05:47] INFO  acceptance: T0 passed         │
│ [10:05:48] INFO  acceptance: Starting T1       │
│ [10:05:51] INFO  acceptance: T1 passed         │
│ [10:05:52] INFO  acceptance: Decision: ACCEPT  │
│                                                 │
│ [Download full logs]                            │
└─────────────────────────────────────────────────┘
```

---

## 🧪 Testing Strategy

### Уровни тестов

#### T0: Mechanical checks (быстро, дёшево)
```yaml
test_tiers:
  T0:
    name: "Mechanical checks"
    timeout_seconds: 60
    commands:
      - "ruff check ."
      - "ruff format --check ."
      - "mypy src"
      - "grace-lint check"  # GRACE Canon
    fail_fast: true
```

**Что проверяет:**
- Lint (ruff)
- Type checking (mypy)
- Formatting (ruff format)
- GRACE Canon (contracts, file sizes, function sizes)

**Когда запускается:** Всегда (первый шаг acceptance)

#### T1: Touched scope tests (средне)
```yaml
test_tiers:
  T1:
    name: "Touched scope tests"
    timeout_seconds: 300
    resolver: touched_scope  # Определяет какие тесты запускать
    fallback: "pytest tests -k 'not slow'"
    fail_fast: true
```

**Что проверяет:**
- Тесты для изменённых файлов
- Тесты которые импортируют изменённые модули

**Как определяет touched scope:**
```python
def resolve_touched_tests(changed_files: list[str]) -> list[str]:
    """Определяет какие тесты нужно запустить."""
    tests = []
    
    for file in changed_files:
        # Прямое соответствие
        if file.startswith("src/"):
            test_file = file.replace("src/", "tests/").replace(".py", "_test.py")
            if Path(test_file).exists():
                tests.append(test_file)
        
        # Тесты которые импортируют этот модуль
        module = file_to_module(file)
        tests.extend(find_tests_importing(module))
    
    return tests
```

**Когда запускается:** Всегда (второй шаг acceptance)

#### T2: Full unit tests (долго)
```yaml
test_tiers:
  T2:
    name: "Full unit tests"
    timeout_seconds: 600
    commands:
      - "pytest tests/unit -v"
    required_for: [NORMAL, STRICT]  # Только для NORMAL/STRICT
    fail_fast: true
```

**Что проверяет:**
- Все unit тесты
- Полное покрытие

**Когда запускается:** Только для NORMAL/STRICT packets

#### T3: Integration tests (опционально)
```yaml
test_tiers:
  T3:
    name: "Integration tests"
    timeout_seconds: 1200
    commands:
      - "pytest tests/integration -v"
    required_for: [STRICT]  # Только для STRICT
    fail_fast: false  # Запускаем все даже если есть failures
```

**Что проверяет:**
- Интеграция между компонентами
- E2E сценарии

**Когда запускается:** Только для STRICT packets (опционально)

#### T4: Visual tests (для frontend)
```yaml
test_tiers:
  T4:
    name: "Visual tests"
    timeout_seconds: 300
    commands:
      - "playwright test --project=chromium"
      - "npm run visual-regression"
    required_for: [NORMAL, STRICT]  # Если packet трогает frontend
    artifacts:
      - "screenshots/*.png"
      - "visual-regression/*.png"
```

**Что проверяет:**
- UI компоненты рендерятся
- Visual regression (сравнение скриншотов)
- Accessibility (a11y)

**Когда запускается:** Только если packet трогает frontend файлы

### Test execution strategy

#### Параллельное выполнение тестов
```yaml
testing:
  parallel: true
  max_workers: 4  # Количество параллельных pytest workers
  
  # pytest-xdist
  pytest_args: "-n 4 --dist loadscope"
```

#### Retry failed tests
```yaml
testing:
  retry_failed: true
  max_retries: 2
  
  # pytest-rerunfailures
  pytest_args: "--reruns 2 --reruns-delay 1"
```

#### Test isolation
```yaml
testing:
  isolation: true
  
  # Каждый test tier запускается в чистом окружении
  # Используем pytest fixtures для setup/teardown
```

### Test artifacts

**Что сохраняем после тестов:**
```
.grace/packets/{packet_id}/runs/{run_id}/tests/
├── T0-lint.json          # Результаты lint
├── T1-tests.json         # Результаты touched tests
├── T2-tests.json         # Результаты full tests
├── coverage/             # Coverage reports
│   ├── coverage.json
│   └── htmlcov/
├── pytest-report.html    # HTML отчёт pytest
└── screenshots/          # Скриншоты (если T4)
    ├── test-login-form.png
    └── test-dashboard.png
```

### Test result format (JSON)

```json
{
  "tier": "T1",
  "name": "Touched scope tests",
  "status": "passed",
  "started_at": "2026-05-31T10:05:48Z",
  "finished_at": "2026-05-31T10:05:51Z",
  "duration_ms": 3400,
  "command": "pytest tests/auth/test_jwt.py -v",
  "exit_code": 0,
  "summary": {
    "total": 3,
    "passed": 3,
    "failed": 0,
    "skipped": 0,
    "errors": 0
  },
  "tests": [
    {
      "name": "test_generate_token",
      "file": "tests/auth/test_jwt.py",
      "line": 10,
      "status": "passed",
      "duration_ms": 1100
    },
    {
      "name": "test_validate_token",
      "file": "tests/auth/test_jwt.py",
      "line": 25,
      "status": "passed",
      "duration_ms": 1200
    },
    {
      "name": "test_expired_token",
      "file": "tests/auth/test_jwt.py",
      "line": 40,
      "status": "passed",
      "duration_ms": 1100
    }
  ],
  "coverage": {
    "total": 95.5,
    "files": {
      "src/auth/jwt.py": 100.0,
      "src/auth/utils.py": 85.0
    }
  }
}
```

---

## 🔧 Implementation

### Logger setup

```python
# src/grace_control/logging.py
import logging
import json
from datetime import datetime
from contextvars import ContextVar

# Context var для trace_id
trace_id_var: ContextVar[str | None] = ContextVar("trace_id", default=None)

class StructuredLogger:
    def __init__(self, component: str, config: LoggingConfig):
        self.component = component
        self.config = config
        self.logger = logging.getLogger(f"grace.{component}")
        
        # Setup handler
        if config.output in ["file", "both"]:
            handler = logging.FileHandler(f"logs/{component}.jsonl")
            handler.setFormatter(JsonFormatter())
            self.logger.addHandler(handler)
        
        if config.output in ["stdout", "both"]:
            handler = logging.StreamHandler()
            handler.setFormatter(JsonFormatter())
            self.logger.addHandler(handler)
        
        # Set level
        level = config.components.get(component, config.level)
        self.logger.setLevel(getattr(logging, level))
    
    def _log(self, level: str, message: str, **context):
        """Internal log method."""
        trace_id = trace_id_var.get()
        
        extra = {
            "component": self.component,
            "trace_id": trace_id,
            **context
        }
        
        getattr(self.logger, level)(message, extra=extra)
    
    def info(self, message: str, **context):
        self._log("info", message, **context)
    
    def debug(self, message: str, **context):
        self._log("debug", message, **context)
    
    def warning(self, message: str, **context):
        self._log("warning", message, **context)
    
    def error(self, message: str, **context):
        self._log("error", message, **context)

class JsonFormatter(logging.Formatter):
    def format(self, record):
        log_data = {
            "timestamp": datetime.utcnow().isoformat() + "Z",
            "level": record.levelname.lower(),
            "component": record.__dict__.get("component"),
            "trace_id": record.__dict__.get("trace_id"),
            "message": record.getMessage(),
        }
        
        # Add context
        if hasattr(record, "context"):
            log_data["context"] = record.context
        
        # Add duration if present
        if hasattr(record, "duration_ms"):
            log_data["duration_ms"] = record.duration_ms
        
        return json.dumps(log_data)

# Usage
logger = StructuredLogger("worker", config)
logger.info("Packet claimed", packet_id="PKT-001", worker_id="worker-1")
```

### Trace ID propagation

```python
# Set trace ID at the start of packet execution
trace_id_var.set(packet_id)

# All subsequent logs will include this trace_id
logger.info("Starting execution")  # trace_id автоматически добавляется

# Clear at the end
trace_id_var.set(None)
```

---

## 📊 Monitoring & Observability

### Metrics to track

**Worker metrics:**
- Active workers count
- Packets processed per worker
- Average packet duration
- Worker failures

**Packet metrics:**
- Packets by state (READY, RUNNING, ACCEPTED, REJECTED)
- Average attempts per packet
- Acceptance rate by profile (FAST/NORMAL/STRICT)
- Test tier pass rates

**Test metrics:**
- T0/T1/T2 pass rates
- Average test duration by tier
- Flaky tests (fail then pass on retry)

**System metrics:**
- API response times
- DB query times
- Queue depth

### Log analysis queries

**Find all logs for a packet run:**
```bash
cat logs/grace.jsonl | jq 'select(.trace_id == "FEAT-X-W01-P01-CREATE-JWT-R01")'
```

**Find all acceptance decisions:**
```bash
cat logs/grace.jsonl | jq 'select(.component == "acceptance" and .message == "Acceptance decision made")'
```

**Find all failures:**
```bash
cat logs/grace.jsonl | jq 'select(.level == "error" or .level == "warning")'
```

**Average packet duration:**
```bash
cat logs/grace.jsonl | jq 'select(.component == "worker" and .message == "Packet completed") | .duration_ms' | awk '{sum+=$1; count++} END {print sum/count}'
```

---

## ✅ Summary

**Logging:**
- ✅ Structured JSONL logs с trace_id
- ✅ Уровни логирования по компонентам
- ✅ Debug mode для детальных логов
- ✅ Логи ВЕЗДЕ (worker, executor, state machine, acceptance, API, DB)
- ✅ Trace ID propagation через все компоненты
- ✅ Log viewer в UI

**Testing:**
- ✅ 4 уровня тестов (T0/T1/T2/T3/T4)
- ✅ Ступенчатое выполнение с early exit
- ✅ Touched scope resolver для T1
- ✅ Parallel execution
- ✅ Retry failed tests
- ✅ Structured test results (JSON)
- ✅ Test artifacts (coverage, screenshots)
- ✅ Visual regression для frontend

**Время реализации:**
- Logging infrastructure: 1 день
- Testing infrastructure: 2 дня
- **Итого: 3 дня**
