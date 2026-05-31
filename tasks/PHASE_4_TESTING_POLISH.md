# Phase 4: Testing & Polish

**Длительность:** 1 неделя (7 дней)
**Цель:** E2E тестирование, документация, финальная полировка

---

## Task #17: Test End-to-End Packet Execution

**Приоритет:** Критично
**Время:** 3 дня
**Зависимости:** All previous phases

### Описание
Провести полное E2E тестирование всего flow от создания feature до merge.

### Что делать

#### 1. Создать E2E test script

**tests/e2e/test_full_flow.py:**
```python
"""
End-to-end test of full packet lifecycle.
"""
import pytest
import asyncio
import httpx
from pathlib import Path
import yaml

API_BASE = "http://localhost:8000/api"

@pytest.mark.e2e
@pytest.mark.asyncio
async def test_full_packet_lifecycle():
    """
    Test complete flow:
    1. Start API server
    2. Start worker
    3. Create feature via architect
    4. Worker executes packets
    5. Tests run, evidence collected
    6. Acceptance decision
    7. Auto-merge
    8. Verify artifacts
    """
    
    # Step 1: Create feature spec
    feature_spec = {
        "title": "Test Feature",
        "description": "E2E test feature",
        "waves": [
            {
                "title": "Foundation",
                "packets": [
                    {
                        "title": "Add test utility",
                        "description": "Create simple utility function",
                        "scope": "src/utils/test_util.py",
                        "acceptance_profile": "FAST"
                    }
                ]
            }
        ]
    }
    
    # Step 2: Create plan via architect
    async with httpx.AsyncClient() as client:
        response = await client.post(
            f"{API_BASE}/architect/plan",
            json={"feature_spec": feature_spec}
        )
        assert response.status_code == 200
        plan = response.json()
        
        feature_id = plan["feature_id"]
        packet_id = plan["packets"][0]
        
        print(f"Created feature: {feature_id}")
        print(f"Created packet: {packet_id}")
    
    # Step 3: Wait for worker to claim and execute
    # (Worker should be running in background)
    
    # Poll packet status
    max_wait = 300  # 5 minutes
    waited = 0
    
    while waited < max_wait:
        async with httpx.AsyncClient() as client:
            response = await client.get(f"{API_BASE}/packets/{packet_id}")
            packet = response.json()
            
            print(f"Packet state: {packet['state']}")
            
            if packet['state'] in ['accepted', 'rejected', 'failed', 'merged']:
                break
        
        await asyncio.sleep(5)
        waited += 5
    
    # Step 4: Verify final state
    async with httpx.AsyncClient() as client:
        response = await client.get(f"{API_BASE}/packets/{packet_id}")
        packet = response.json()
        
        assert packet['state'] in ['accepted', 'merged'], f"Expected accepted/merged, got {packet['state']}"
    
    # Step 5: Verify artifacts
    artifacts_path = Path(f".grace/packets/{packet_id}/runs/R01")
    assert artifacts_path.exists(), "Artifacts directory not found"
    
    # Check required files
    assert (artifacts_path / "packet.json").exists()
    assert (artifacts_path / "result.json").exists()
    assert (artifacts_path / "tests/T0.json").exists()
    assert (artifacts_path / "tests/T1.json").exists()
    assert (artifacts_path / "logs.jsonl").exists()
    
    # Step 6: Verify test results
    import json
    with open(artifacts_path / "tests/T0.json") as f:
        t0_result = json.load(f)
        assert t0_result["status"] == "passed", "T0 should pass"
    
    with open(artifacts_path / "tests/T1.json") as f:
        t1_result = json.load(f)
        assert t1_result["status"] == "passed", "T1 should pass"
    
    # Step 7: Verify result
    with open(artifacts_path / "result.json") as f:
        result = json.load(f)
        assert result["accepted"] is True, "Packet should be accepted"
    
    print("✅ E2E test passed!")

@pytest.mark.e2e
@pytest.mark.asyncio
async def test_rejection_flow():
    """Test packet rejection flow."""
    
    # Create packet that will fail tests
    feature_spec = {
        "title": "Failing Feature",
        "waves": [
            {
                "title": "Test",
                "packets": [
                    {
                        "title": "Add broken code",
                        "scope": "src/broken.py",
                        "acceptance_profile": "FAST"
                    }
                ]
            }
        ]
    }
    
    # Create plan
    async with httpx.AsyncClient() as client:
        response = await client.post(
            f"{API_BASE}/architect/plan",
            json={"feature_spec": feature_spec}
        )
        plan = response.json()
        packet_id = plan["packets"][0]
    
    # Wait for execution
    max_wait = 300
    waited = 0
    
    while waited < max_wait:
        async with httpx.AsyncClient() as client:
            response = await client.get(f"{API_BASE}/packets/{packet_id}")
            packet = response.json()
            
            if packet['state'] in ['rejected', 'failed']:
                break
        
        await asyncio.sleep(5)
        waited += 5
    
    # Verify rejection
    async with httpx.AsyncClient() as client:
        response = await client.get(f"{API_BASE}/packets/{packet_id}")
        packet = response.json()
        
        assert packet['state'] in ['rejected', 'failed'], "Packet should be rejected"
    
    print("✅ Rejection flow test passed!")

@pytest.mark.e2e
@pytest.mark.asyncio
async def test_retry_flow():
    """Test packet retry flow."""
    
    # Create packet that fails first time but succeeds on retry
    # (This requires special setup)
    
    pass

@pytest.mark.e2e
@pytest.mark.asyncio
async def test_cancellation_flow():
    """Test packet cancellation."""
    
    # Create long-running packet
    feature_spec = {
        "title": "Long Running Feature",
        "waves": [
            {
                "title": "Test",
                "packets": [
                    {
                        "title": "Long task",
                        "scope": "src/long_task.py",
                        "acceptance_profile": "NORMAL"
                    }
                ]
            }
        ]
    }
    
    # Create plan
    async with httpx.AsyncClient() as client:
        response = await client.post(
            f"{API_BASE}/architect/plan",
            json={"feature_spec": feature_spec}
        )
        plan = response.json()
        packet_id = plan["packets"][0]
    
    # Wait for packet to start running
    await asyncio.sleep(10)
    
    # Cancel packet
    async with httpx.AsyncClient() as client:
        response = await client.post(
            f"{API_BASE}/packets/{packet_id}/cancel",
            json={"reason": "Test cancellation"}
        )
        assert response.status_code == 200
    
    # Wait for cancellation to complete
    await asyncio.sleep(10)
    
    # Verify cancelled
    async with httpx.AsyncClient() as client:
        response = await client.get(f"{API_BASE}/packets/{packet_id}")
        packet = response.json()
        
        assert packet['state'] == 'cancelled', "Packet should be cancelled"
    
    print("✅ Cancellation flow test passed!")
```

#### 2. Создать test runner script

**scripts/run_e2e_tests.sh:**
```bash
#!/bin/bash
set -e

echo "Starting E2E tests..."

# Start API server in background
echo "Starting API server..."
grace-api serve &
API_PID=$!
sleep 5

# Start worker in background
echo "Starting worker..."
grace-worker start &
WORKER_PID=$!
sleep 5

# Run E2E tests
echo "Running E2E tests..."
pytest tests/e2e/ -v -m e2e

# Cleanup
echo "Cleaning up..."
kill $API_PID
kill $WORKER_PID

echo "✅ E2E tests completed!"
```

#### 3. Создать test fixtures

**tests/e2e/fixtures.py:**
```python
"""
E2E test fixtures.
"""
import pytest
from pathlib import Path
import shutil

@pytest.fixture
def clean_grace_dir():
    """Clean .grace directory before test."""
    grace_dir = Path(".grace")
    if grace_dir.exists():
        shutil.rmtree(grace_dir)
    grace_dir.mkdir()
    yield
    # Cleanup after test
    if grace_dir.exists():
        shutil.rmtree(grace_dir)

@pytest.fixture
def test_repo(tmp_path):
    """Create test git repository."""
    repo_path = tmp_path / "test_repo"
    repo_path.mkdir()
    
    # Initialize git
    import subprocess
    subprocess.run(["git", "init"], cwd=repo_path, check=True)
    subprocess.run(["git", "config", "user.name", "Test"], cwd=repo_path, check=True)
    subprocess.run(["git", "config", "user.email", "test@test.com"], cwd=repo_path, check=True)
    
    # Create initial commit
    (repo_path / "README.md").write_text("# Test Repo")
    subprocess.run(["git", "add", "."], cwd=repo_path, check=True)
    subprocess.run(["git", "commit", "-m", "Initial commit"], cwd=repo_path, check=True)
    
    return repo_path
```

### Критерии готовности
- [ ] E2E test script создан
- [ ] Test runner работает
- [ ] Acceptance flow тестируется
- [ ] Rejection flow тестируется
- [ ] Retry flow тестируется
- [ ] Cancellation flow тестируется
- [ ] Все артефакты проверяются
- [ ] Все тесты проходят

---

## Documentation Tasks

### Task: Update README.md

**Время:** 1 день

#### Что делать

**README.md:**
```markdown
# GRACE Control Plane

AI-first orchestration system for autonomous software development.

## Features

- 🤖 **AI-First**: JSON primary, Markdown for debug
- 📦 **Packet-Based**: Hierarchical task decomposition (FEAT-X-W01-P01-ACTION-R01)
- ✅ **Staged Acceptance**: T0 → T1 → T2 → Canon → Reviewer (early exit)
- 🔄 **Retry & Escalation**: Automatic retry with executor escalation
- 🎯 **GRACE Canon**: File/function limits, contracts, semantic blocks
- 📊 **Structured Logging**: JSONL logs with trace_id propagation
- 🌐 **API-First**: FastAPI server + thin CLI wrapper

## Quick Start

### Installation

```bash
pip install grace-control
```

### Initialize Project

```bash
cd /path/to/your/project
grace init
```

### Start Control Plane

```bash
# Terminal 1: Start API server
grace-api serve

# Terminal 2: Start worker
grace-worker start
```

### Create Feature

```bash
grace architect plan my-feature.yaml
```

### Watch Progress

- Open http://localhost:8000 (Web UI)
- Or: `grace packet list`
- Or: Telegram notifications

## Architecture

```
┌─────────────────────────────────────────────────────────┐
│                  FastAPI Server                          │
│  - REST API (все операции)                              │
│  - WebSocket (real-time updates)                        │
└─────────────────────────────────────────────────────────┘
                         ↓
┌─────────────────────────────────────────────────────────┐
│               Core Control Plane                         │
│  - State machine (ступенчатая приёмка)                 │
│  - Executor abstraction (API + local)                   │
│  - GRACE Canon checker                                   │
└─────────────────────────────────────────────────────────┘
                         ↓
┌─────────────────────────────────────────────────────────┐
│              SQLite/Postgres DB                          │
└─────────────────────────────────────────────────────────┘
```

## Documentation

- [Quick Start](docs/QUICKSTART.md)
- [API Reference](docs/API.md)
- [Development Guide](docs/DEVELOPMENT.md)
- [Configuration](docs/CONFIGURATION.md)

## License

MIT
```

### Критерии готовности
- [ ] README.md обновлён
- [ ] Quick start написан
- [ ] Architecture diagram добавлен
- [ ] Links на документацию добавлены

---

### Task: Write QUICKSTART.md

**Время:** 1 день

#### Что делать

**docs/QUICKSTART.md:**
```markdown
# Quick Start Guide

## Installation

```bash
pip install grace-control
```

## Initialize Project

```bash
cd /path/to/your/project
grace init
```

This creates:
- `grace/project.yaml` - Project configuration
- `grace/artifacts/` - XML artifacts directory

## Configure

Edit `grace/project.yaml`:

```yaml
project:
  key: my-app
  name: My Application

logging:
  level: INFO
  components:
    worker: DEBUG
    executor: INFO

testing:
  parallel: true
  max_workers: 4
```

## Start Control Plane

### Terminal 1: API Server

```bash
grace-api serve
```

### Terminal 2: Worker

```bash
grace-worker start
```

## Create Feature

Create `my-feature.yaml`:

```yaml
title: User Authentication
description: Add JWT-based authentication

waves:
  - title: Foundation
    packets:
      - title: Add JWT utilities
        scope: src/auth/jwt.py
        acceptance_profile: NORMAL
      
      - title: Add auth middleware
        scope: src/auth/middleware.py
        acceptance_profile: STRICT
```

Submit to architect:

```bash
grace architect plan my-feature.yaml
```

## Watch Progress

### Web UI

Open http://localhost:8000

### CLI

```bash
# List packets
grace packet list

# Get packet details
grace packet get FEAT-USER-AUTH-W01-P01-ADD-JWT-UTILS

# Watch logs
grace packet logs FEAT-USER-AUTH-W01-P01-ADD-JWT-UTILS
```

### Telegram

Configure in `.env`:

```bash
TELEGRAM_BOT_TOKEN=your_token
TELEGRAM_CHAT_ID=your_chat_id
```

## Next Steps

- [Configuration Guide](CONFIGURATION.md)
- [API Reference](API.md)
- [Development Guide](DEVELOPMENT.md)
```

### Критерии готовности
- [ ] QUICKSTART.md написан
- [ ] Installation instructions
- [ ] Configuration examples
- [ ] Usage examples

---

### Task: Write API.md

**Время:** 1 день

#### Что делать

**docs/API.md:**
```markdown
# API Reference

Base URL: `http://localhost:8000/api`

## Features

### List Features

```
GET /api/features/
```

Response:
```json
[
  {
    "id": "FEAT-USER-AUTH",
    "slug": "user-auth",
    "title": "User Authentication",
    "status": "IN_PROGRESS",
    "created_at": "2026-05-31T10:00:00Z"
  }
]
```

### Get Feature

```
GET /api/features/{feature_id}
```

## Packets

### List Packets

```
GET /api/packets/?state=ready
```

### Get Packet

```
GET /api/packets/{packet_id}
```

### Cancel Packet

```
POST /api/packets/{packet_id}/cancel
```

Body:
```json
{
  "reason": "No longer needed"
}
```

## Workers

### List Workers

```
GET /api/workers/
```

### Register Worker

```
POST /api/workers/register
```

Body:
```json
{
  "worker_id": "worker-1",
  "capabilities": ["python", "typescript"]
}
```

## Architect

### Create Plan

```
POST /api/architect/plan
```

Body:
```json
{
  "feature_spec": {
    "title": "User Authentication",
    "waves": [...]
  }
}
```

## Health

### Health Check

```
GET /health
```

Response:
```json
{
  "status": "healthy",
  "workers": {
    "active": 3,
    "idle": 1,
    "dead": 0
  },
  "queue_depth": 5
}
```
```

### Критерии готовности
- [ ] API.md написан
- [ ] Все endpoints документированы
- [ ] Request/response examples

---

## Final Polish Tasks

### Task: GRACE Canon Compliance Check

**Время:** 1 день

#### Что делать

1. Запустить GRACE Canon checker на всём коде
2. Исправить все violations
3. Убедиться что все файлы < 1000 lines
4. Убедиться что все функции < 250 lines
5. Добавить contracts где нужно

### Task: Code Review

**Время:** 1 день

#### Что делать

1. Review всего кода
2. Проверить naming conventions
3. Проверить error handling
4. Проверить logging везде
5. Проверить tests coverage

### Task: Performance Testing

**Время:** 1 день

#### Что делать

1. Load testing API endpoints
2. Проверить memory leaks
3. Проверить DB query performance
4. Оптимизировать bottlenecks

---

## Phase 4 Complete Checklist

### Все задачи Phase 4
- [ ] Task #17: E2E Testing ✅
- [ ] README.md updated ✅
- [ ] QUICKSTART.md written ✅
- [ ] API.md written ✅
- [ ] GRACE Canon compliance ✅
- [ ] Code review ✅
- [ ] Performance testing ✅

### Deliverables
- ✅ E2E tests проходят
- ✅ Documentation complete
- ✅ GRACE Canon compliant
- ✅ Code reviewed
- ✅ Performance tested

### MVP Ready! 🎉

После завершения Phase 4 — **MVP готов к использованию!**
