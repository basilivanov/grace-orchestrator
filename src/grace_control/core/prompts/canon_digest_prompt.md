# GRACE Canon Digest — Control Packet Reference

Встраивается в секцию `## Source Of Truth` или `## Must Preserve` каждого EXECUTION_PACKET.md.
Цель: дёшевый агент (Gemini Flash) пишет код, проходящий T0 (lint+canon) с первого раза.

---

## 1. AI_HEADER (первая строка файла)

```python
# ############################################################################
# AI_HEADER: <имя_модуля>
# ROLE: <одно предложение — что делает модуль>
# ############################################################################
```

Пример:
```python
# AI_HEADER: db_schema
# ROLE: SQLAlchemy models for GRACE Control Plane (7 tables).
```

---

## 2. MODULE_CONTRACT (сразу после AI_HEADER)

```python
# START_MODULE_CONTRACT
# purpose: <что делает модуль>
# inputs: <что принимает на вход>
# returns: <что возвращает>
# side_effects: <побочные эффекты или None>
# emitted_logs: <какие логи пишет или None>
# error_behavior: <как обрабатывает ошибки>
# END_MODULE_CONTRACT
```

---

## 3. MODULE_MAP (перечень экспортов)

```python
# START_MODULE_MAP
# mapping:
#   - class: <ClassName>
#   - function: <function_name>
# END_MODULE_MAP
```

---

## 4. START_BLOCK / END_BLOCK (логические секции)

Каждая функция/класс/группа внутри `#START_BLOCK_<NAME>` / `#END_BLOCK_<NAME>`.

```python
#START_BLOCK_MODELS
@dataclass
class Packet:
    ...
#END_BLOCK_MODELS

#START_BLOCK_OPERATIONS
def claim_packet(...):
    ...
#END_BLOCK_OPERATIONS
```

Правила:
- Имена блоков — UPPER_SNAKE_CASE
- Каждый START должен иметь парный END
- Имена должны совпадать (START_BLOCK_FOO → END_BLOCK_FOO)
- Блоки не вкладываются

---

## 5. FUNCTION_CONTRACT (перед каждой функцией)

```python
# START_FUNCTION_CONTRACT
# name: <function_name>
# purpose: <одно предложение>
# inputs:
#   param1: <описание>
#   param2: <описание>
# returns: <описание возврата>
# side_effects: <побочные эффекты или None>
# emitted_logs: <какие логи или None>
# error_behavior: <как обрабатывает ошибки>
# END_FUNCTION_CONTRACT
def function_name(param1: str, param2: int) -> bool:
    ...
```

---

## 6. Лимиты (нарушение → REJECT на T0)

| Правило | Лимит |
|---------|-------|
| Строк в файле | ≤ 1000 |
| Токенов в функции | ≤ 4000 |
| Изменений в пакете | ≤ 300 LOC |

---

## 7. Структурированное логирование (GraceLogger)

```python
from grace_control.core.structured_logger import GraceLogger, trace_context

_log = GraceLogger("worker")

# Логирование с контекстом
_log.info("packet_claimed", packet_id="PKT-001", worker_id="w1")
_log.error("execution_failed", packet_id="PKT-001", error=str(e))

# Trace-контекст для сквозного trace_id
with trace_context(packet_id):
    _log.info("execution_started")
    # все логи внутри блока получают этот trace_id
```

Формат вывода — JSONL (одна строка JSON на событие):
```json
{"ts":"2026-05-31T10:00:00+00:00Z","level":"INFO","component":"worker","msg":"packet_claimed","trace_id":"PKT-001","ctx":{"packet_id":"PKT-001","worker_id":"w1"}}
```

Правила:
- НЕ использовать `print()` — только `GraceLogger`
- НЕ использовать `logging.getLogger()` напрямую
- `_log = GraceLogger("component_name")` объявляется один раз на уровне модуля
- Имена сообщений должны быть статическими строками: `_log.info("msg_name", ctx_key=value)`
- Всегда указывать `packet_id` в параметрах лога, когда операция относится к пакету
- `trace_context(packet_id)` для всех операций внутри одного пакета
- НЕ импортировать `prefect_grace`

---

## 8. Контракты в новом коде (grace_control/)

Новый модуль обязан иметь: AI_HEADER, MODULE_CONTRACT, MODULE_MAP.
Новая функция обязана иметь: FUNCTION_CONTRACT, START_BLOCK/END_BLOCK.
Новый файл: все функции внутри блоков, все блоки закрыты.

---

## 9. Проверка перед коммитом (T0)

```bash
python3 scripts/grace_lint.py
python3 -m ruff check src/
```

T0 жестко прописан в пайплайне — запускается всегда, не переопределяется архитектором.
Если любая команда падает → пакет не проходит T0 → REJECT.

---

## 10. Чеклист для кодера (перед handoff)

- [ ] AI_HEADER с ROLE в каждом новом файле
- [ ] START_MODULE_CONTRACT / END_MODULE_CONTRACT в каждом новом файле
- [ ] MODULE_MAP со всеми публичными именами
- [ ] START_FUNCTION_CONTRACT / END_FUNCTION_CONTRACT у каждой новой функции
- [ ] START_BLOCK_*/END_BLOCK_* — все пары сходятся
- [ ] Файл ≤ 1000 строк
- [ ] Функция ≤ 4000 токенов
- [ ] `python3 scripts/grace_lint.py` чисто (Канон)
- [ ] `python3 -m ruff check src/` чисто
- [ ] `GraceLogger` вместо `print()`/`logging.getLogger()`
- [ ] `_log = GraceLogger("component_name")` объявлен один раз на уровне модуля
- [ ] `trace_context(packet_id)` обёрнут вокруг основного вызова
- [ ] `packet_id` во всех пакетных `_log.*(...)` вызовах
- [ ] `prefect_grace` не импортируется
