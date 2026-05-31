# Phase 4: Testing & Polish (REVISED)

**Длительность:** 3 дня
**Цель:** Расширенное тестирование, документация, финальная полировка MVP-0

**ВАЖНО:** Это буферная фаза. MVP-0 считается готовым после Phase 3. Phase 4 — улучшения.

---

## Task #17: Advanced E2E Testing

**Приоритет:** Высокий
**Время:** 2 дня
**Зависимости:** Phase 3 complete

### Описание
Расширить E2E тестирование: retry flow, edge cases, error handling.

### Что делать

#### 1. Расширить E2E test

**tests/test_e2e_advanced.py:**
```python
"""
Advanced E2E tests for MVP-0.
"""
import pytest
import asyncio
import httpx
from pathlib import Path

API_BASE = "http://localhost:8042/api"

@pytest.mark.e2e
@pytest.mark.asyncio
async def test_retry_rejected_packet(api_server, tmp_path):
    """Test packet rejection → retry → acceptance."""
    from grace_control.db import init_db
    from grace_control.core.packet_operations import mark_ready
    
    init_db(f"sqlite:///{tmp_path}/test.db")
    
    # Create feature with packet
    async with httpx.AsyncClient(base_url=api_server) as client:
        response = await client.post("/api/architect/plan", json={
            "feature_spec": {
                "title": "Retry Test",
                "waves": [{
                    "title": "Test",
                    "packets": [{
                        "title": "Add feature",
                        "scope": "src/feature.py"
                    }]
                }]
            }
        })
        data = response.json()["data"]
        packet_id = data["packets"][0]
    
    mark_ready(packet_id)
    
    # Run worker, verify state cycle
    # READY → RUNNING → REJECTED → retry → READY → RUNNING → ACCEPTED
    pass

@pytest.mark.e2e
@pytest.mark.asyncio
async def test_packet_execution_error_handling(api_server, tmp_path):
    """Test error handling during packet execution."""
    pass

@pytest.mark.e2e
@pytest.mark.asyncio
async def test_lease_expiration(api_server, tmp_path):
    """Test lease expiration returns packet to READY."""
    pass

@pytest.mark.e2e
@pytest.mark.asyncio
async def test_worker_heartbeat_recovery(api_server, tmp_path):
    """Test worker recovery after heartbeat timeout."""
    pass

@pytest.mark.e2e
@pytest.mark.asyncio
async def test_multiple_packets_sequential(api_server, tmp_path):
    """Test sequential execution of multiple packets."""
    pass
```

#### 2. Расширить verification script

**scripts/verify_mvp0_full.sh:**
```bash
#!/bin/bash
set -e

echo "Full MVP-0 verification..."

# 1. DB schema tests
echo "1. DB schema tests..."
python -m pytest tests/test_db_schema.py -v

# 2. State machine tests
echo "2. State machine tests..."
python -m pytest tests/test_state_machine.py -v

# 3. Packet executor tests
echo "3. Packet executor tests..."
python -m pytest tests/test_packet_executor.py -v

# 4. API tests
echo "4. API tests..."
python -m pytest tests/test_api.py -v

# 5. Worker tests
echo "5. Worker tests..."
python -m pytest tests/test_worker.py -v

# 6. E2E vertical slice
echo "6. E2E vertical slice..."
python -m pytest tests/test_e2e_mvp0.py -v

# 7. Advanced E2E
echo "7. Advanced E2E..."
python -m pytest tests/test_e2e_advanced.py -v -m e2e

echo "Full MVP-0 verification complete!"
```

### Критерии готовности
- [ ] Advanced E2E тесты созданы
- [ ] Retry flow тестируется
- [ ] Error handling тестируется
- [ ] Lease expiration тестируется
- [ ] Все тесты проходят

---

## Documentation Tasks

### Task: Verify & Update README.md

**Время:** 0.5 дня

Проверить что README.md отражает актуальную архитектуру MVP-0:
- [ ] API-first архитектура описана
- [ ] Quick start с grace командами
- [ ] Ссылки на CANONICAL_DECISIONS.md и API_CONTRACT.md
- [ ] Нет упоминаний UI/Telegram/WebSocket (Post-MVP)
- [ ] Нет упоминаний Prefect как runtime (только compat layer)

### Task: Verify QUICKSTART.md

**Время:** 0.5 дня

Проверить что QUICKSTART.md рабочий:
- [ ] Команды `grace api start`, `grace worker start` работают
- [ ] `grace packet list` показывает результат
- [ ] Путь от init до первого выполненного пакета работает

---

## Final Polish Tasks

### Task: Code Review

**Время:** 0.5 дня

- [ ] Review всего нового кода (grace_control/)
- [ ] Проверить naming conventions (snake_case, префиксы grace_)
- [ ] Проверить error handling (no bare except)
- [ ] Проверить logging (GraceLogger используется везде)
- [ ] Проверить что legacy imports используют try/except prefect_compat

### Task: Performance Baseline

**Время:** 0.5 дня

- [ ] Замерить latency API endpoints
- [ ] Проверить SQLite query performance на 100+ packets
- [ ] Проверить worker throughput (packets/minute)
- [ ] Задокументировать baseline метрики в docs/METRICS.md

---

## Phase 4 Complete Checklist

- [ ] Advanced E2E tests проходят
- [ ] Документация актуальна
- [ ] Code review пройден
- [ ] Performance baseline замерен

### После Phase 4

MVP-0 полностью готов. Следующий шаг — Post-MVP waves:

1. **Wave 1:** Retry + Cancellation (3 дня)
2. **Wave 2:** UI + Telegram (1 неделя)
3. **Wave 3:** GRACE Canon + Complexity Router (1 неделя)
4. **Wave 4:** Parallel execution + Multiple workers (1 неделя)
