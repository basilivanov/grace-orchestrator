# TZ 022 — Pydantic Recovery Ladder: универсальный routing по правилам

Аудитория: кодер (literal executor).

Родитель: `docs/codex/tz-017-feature-recovery-escalation-policy.md`.

Статус: **спецификация на реализацию. Делать строго как написано.**

Язык: русский. Поля и имена классов — на английском (как в коде).

---

## 0. Цель

Заменить хардкодные if/else в recovery-логике на **Pydantic-лэддер** — универсальную систему правил, которая по текущему состоянию (attempt, coder, failure_class, error) определяет что делать дальше.

Идея: берём стейт → прогоняем через Pydantic-схему правил → получаем сухой контракт `RecoveryRoute`.

```text
Стейт (attempt=3, coder=deepseek, reason=T1 failed)
  ↓
evaluate_ladder(attempt, ladder)   ← Pydantic, чистая функция
  ↓
RecoveryRoute(action=SWITCH_CODER, skip_verifier=true, ...)
```

Любые будущие правила добавляются так: **+1 enum + 1 if в evaluate_ladder() + 1 тест**. Без изменения структуры кода, без YAML-движков, без техдолга.

---

## 1. Файловая карта

```
NEW:
  src/grace_control/core/recovery_rules.py         ← модели + evaluate_ladder
  tests/grace_control/core/test_recovery_rules.py  ← unit-тесты (9+ штук)
  fixtures/golden/recovery_route_odd_even.yaml     ← fixture на odd/even правила

CHANGE:
  src/grace_control/core/feature_recovery.py        ← RecoveryAction.NEW_ARCHITECT, FailureSignal.architect_switch_count, интеграция с лэддером
  src/grace_control/core/recovery_controller.py      ← _apply_new_architect, _build_architect_context
  src/grace_control/adapters/packet_executor.py      ← проверка skip_verifier из лэддера
  src/grace_control/worker/worker.py                 ← recovery ДО _handle_rejection
```

---

## 2. Новый файл: `src/grace_control/core/recovery_rules.py`

### 2.1 Модели (использовать ТОЧНО эти имена полей)

```python
# ############################################################################
# AI_HEADER: recovery_rules
# ROLE: Pydantic recovery ladder — evaluate state → route decision.
# ############################################################################

# START_MODULE_CONTRACT
# purpose: Define Pydantic recovery ladder models + evaluate_ladder().
#          Routes packet recovery decisions based on attempt number and state.
# inputs: attempt number, optional RecoveryLadder.
# returns: RecoveryRoute with action, skip_verifier, on_verdict mapping.
# side_effects: None (pure functions).
# emitted_logs: None.
# error_behavior: Falls back to default ladder on missing config.
# END_MODULE_CONTRACT

# START_MODULE_MAP
# mapping:
#   - enum: RouteCondition
#   - enum: RouteAction
#   - class: RecoveryRule
#   - class: RecoveryLadder
#   - class: RecoveryRoute
#   - class: ArchitectContext
#   - function: evaluate_ladder
# END_MODULE_MAP

from __future__ import annotations

from enum import Enum
from typing import Any

from pydantic import BaseModel, Field


class RouteCondition(str, Enum):
    """Типы условий срабатывания правил в лэддере."""
    ODD_ATTEMPT = "odd_attempt"
    EVEN_ATTEMPT = "even_attempt"
    ATTEMPT_GTE = "attempt_gte"
    # ← будущие условия добавлять сюда


class RouteAction(str, Enum):
    """Что делает лэддер при совпадении условия."""
    RETRY_SAME_CODER = "RETRY_SAME_CODER"
    RUN_VERIFIER = "RUN_VERIFIER"
    SWITCH_CODER = "SWITCH_CODER"
    ARCHITECT_REPACK = "ARCHITECT_REPACK"
    NEW_ARCHITECT = "NEW_ARCHITECT"
    BLOCK_FEATURE = "BLOCK_FEATURE"
    NO_ACTION = "NO_ACTION"


class RecoveryRule(BaseModel):
    """Одно правило лэддера: условие → действие."""
    condition: RouteCondition
    condition_value: int | None = None      # для ATTEMPT_GTE: 7
    action: RouteAction
    skip_verifier: bool = False             # пропустить evidence verifier
    on_verdict: dict[str, str] = Field(default_factory=lambda: {
        "REWORK_TO_CODER": RouteAction.SWITCH_CODER.value,
        "RETURN_TO_ARCHITECT": RouteAction.ARCHITECT_REPACK.value,
    })


class RecoveryLadder(BaseModel):
    """Упорядоченный список правил. Первое совпадение — победитель."""
    rules: list[RecoveryRule]
    max_coders: int = 3
    switch_architect_on_attempt: int = 7

    @classmethod
    def default(cls) -> "RecoveryLadder":
        """Дефолтный odd/even лэддер. Не требует внешнего конфига."""
        return cls(
            max_coders=3,
            switch_architect_on_attempt=7,
            rules=[
                RecoveryRule(
                    condition=RouteCondition.ODD_ATTEMPT,
                    action=RouteAction.RETRY_SAME_CODER,
                    skip_verifier=True,
                ),
                RecoveryRule(
                    condition=RouteCondition.EVEN_ATTEMPT,
                    action=RouteAction.RUN_VERIFIER,
                    skip_verifier=False,
                    on_verdict={
                        "REWORK_TO_CODER": RouteAction.SWITCH_CODER.value,
                        "RETURN_TO_ARCHITECT": RouteAction.ARCHITECT_REPACK.value,
                    },
                ),
                RecoveryRule(
                    condition=RouteCondition.ATTEMPT_GTE,
                    condition_value=7,
                    action=RouteAction.NEW_ARCHITECT,
                    skip_verifier=True,
                ),
            ],
        )


class RecoveryRoute(BaseModel):
    """Результат evaluate_ladder(): что делать."""
    rule_index: int                         # индекс правила (0-based)
    condition: RouteCondition               # сработавшее условие
    action: RouteAction                     # что делать
    skip_verifier: bool = False
    max_coders: int = 3
    on_verdict: dict[str, str] = Field(default_factory=dict)


class ArchitectContext(BaseModel):
    """Контракт между recovery controller и новым архитектором (попытка 7+)."""
    original_spec: dict[str, Any] = Field(default_factory=dict)
    attempts: list[dict[str, Any]] = Field(default_factory=list)
    acceptance_reports: list[dict[str, Any]] = Field(default_factory=list)
    verifier_reports: list[dict[str, Any]] = Field(default_factory=list)
    executor_ids: list[str] = Field(default_factory=list)
    changed_files: list[str] = Field(default_factory=list)
    summary: str = ""
```

### 2.2 Функция `evaluate_ladder`

```python
def evaluate_ladder(
    attempt: int,
    ladder: RecoveryLadder | None = None,
) -> RecoveryRoute:
    """
    Пропустить стейт через лэддер, найти первое правило.

    attempt: 1-based номер попытки.
    ladder:  кастомный лэддер; None = дефолтный.

    Returns RecoveryRoute с action + skip_verifier + on_verdict.
    """
    ladder = ladder or RecoveryLadder.default()

    for idx, rule in enumerate(ladder.rules):
        match = False
        if rule.condition == RouteCondition.ODD_ATTEMPT and attempt % 2 == 1:
            match = True
        elif rule.condition == RouteCondition.EVEN_ATTEMPT and attempt % 2 == 0:
            match = True
        elif rule.condition == RouteCondition.ATTEMPT_GTE and attempt >= (rule.condition_value or 7):
            match = True
        # ← будущие условия добавлять сюда

        if match:
            return RecoveryRoute(
                rule_index=idx,
                condition=rule.condition,
                action=rule.action,
                skip_verifier=rule.skip_verifier,
                max_coders=ladder.max_coders,
                on_verdict=rule.on_verdict,
            )

    # Фолбек — на всякий случай
    return RecoveryRoute(
        rule_index=-1,
        condition=RouteCondition.ODD_ATTEMPT,
        action=RouteAction.RETRY_SAME_CODER,
        skip_verifier=False,
        max_coders=ladder.max_coders,
    )
```

---

## 3. Как профили (FAST/NORMAL/STRICT) уживаются с лэддером

`skip_verifier` из лэддера — **ортогонален** профилю:

```text
odd попытка (skip_verifier=true)  → VERIFIER SKIP для ВСЕХ профилей
even попытка (skip_verifier=false) → FAST: SKIP, NORMAL: RUN, STRICT: RUN

Reviewer gate = как раньше по профилю:
  FAST → SKIP, NORMAL → SKIP, STRICT → RUN
```

| | FAST | NORMAL | STRICT |
|--|------|--------|--------|
| T0/T1/T2 | ✅ | ✅ | ✅ (T2 required) |
| Verifier (odd) | ⚪ skip | ⚪ skip | ⚪ skip |
| Verifier (even) | ⚪ skip (FAST) | ✅ run | ✅ run |
| Reviewer | ⚪ skip | ⚪ skip | ✅ run |
| `never_downgrade_strict` | — | — | ✅ enforced |

STRICT никогда не даунгрейдится в NORMAL/FAST — `RecoveryPolicy.never_downgrade_strict` ловит.

---

## 4. Интеграция с существующим кодом

### 4.1 `feature_recovery.py`

**4.1.1 Добавить NEW_ARCHITECT в RecoveryAction (строка ~30):**

```python
class RecoveryAction(str, Enum):
    ...
    NEW_ARCHITECT = "new_architect"        # ← ДОБАВИТЬ
```

**4.1.2 Добавить architect_switch_count в FailureSignal (строка ~70):**

```python
class FailureSignal(BaseModel):
    ...
    architect_switch_count: int = 0        # ← ДОБАВИТЬ
```

**4.1.3 decide_recovery() использует лэддер:**

Вызывать `evaluate_ladder()` для routing-метаданных. Не заменять существующий classify/decide, а дополнять их через `RecoveryRoute`.

### 4.2 `recovery_controller.py`

**4.2.1 Добавить _apply_new_architect:**

```python
def _apply_new_architect(self, packet_id: str, decision: RecoveryDecision):
    # 1. Собрать ArchitectContext из всех PacketRun
    # 2. packet → BLOCKED
    # 3. Сохранить architect_context в spec_json["recovery"]["new_architect"]
```

**4.2.2 Добавить _build_architect_context:**

```python
def _build_architect_context(self, packet, db) -> ArchitectContext:
    # Читает все PacketRun.result_json
    # Собирает: acceptance_reports, verifier_reports, executor_ids, changed_files
    # Возвращает ArchitectContext с summary
```

### 4.3 `packet_executor.py` — verifier gate на rejection

На строке ~315 (где `if not accept_report.is_accepted → skip verifier`):

```python
if not accept_report.is_accepted:
    from grace_control.core.recovery_rules import evaluate_ladder
    route = evaluate_ladder(packet_data.get("attempt_count", 1))

    if route.skip_verifier:
        # Нечётная попытка → skip verifier, быстрое возвращение кодеру
        ev_report = skipped_evidence_report(...)
        rv_report = skipped_reviewer_report(...)
    else:
        # Чётная попытка → verifier классифицирует для recovery controller
        ev_report = await run_evidence_verifier(...)

    # Дальше — профиль решает про reviewer gate
```

### 4.4 `worker.py` — recovery перед rejection

На строках ~124-131:

```python
# БЫЛО: recovery после handle_rejection (никогда не вызывается на max_attempts)
if status == "rejected":
    self._handle_rejection(packet_id)

# СТАЛО: recovery ДО handle_rejection
if status in ("rejected", "blocked"):
    await self._maybe_apply_recovery(packet_id)
self._handle_rejection(packet_id)
```

---

## 5. Как добавлять новые условия (будущим кодерам)

```python
# Шаг 1: +1 enum
class RouteCondition(str, Enum):
    CODER_COUNT_GTE = "coder_count_gte"    # ← новое условие

# Шаг 2: +1 if в evaluate_ladder
elif rule.condition == RouteCondition.CODER_COUNT_GTE and coder_count >= rule.condition_value:
    match = True

# Шаг 3: +1 тест
def test_coder_count_gte_switches_architect(self):
    route = evaluate_ladder(5, custom_ladder_with_coder_count_rule)
    assert route.action == RouteAction.NEW_ARCHITECT
```

Без изменения других файлов. Без YAML. Без парсера условий.

---

## 6. Тесты

### 6.1 Unit: `tests/grace_control/core/test_recovery_rules.py`

```text
test_odd_attempt_retry_same_coder              — попытка 1 → RETRY_SAME_CODER + skip_verifier=true
test_odd_attempt_3_same_behavior               — попытка 3 → то же поведение
test_even_attempt_run_verifier                 — попытка 2 → RUN_VERIFIER + skip_verifier=false
test_even_attempt_on_verdict_mapping           — route.on_verdict содержит правильные ключи
test_attempt_gte_seven_new_architect           — попытка 7 → NEW_ARCHITECT
test_attempt_eight_fallback                    — попытка 8 → fallback
test_custom_ladder_overrides_default           — кастомный лэддер меняет default
test_default_ladder_rule_order                 — первое условие → победитель
test_architect_context_model_creation          — ArchitectContext со всеми полями
```

**Без реальных LLM, git, API.**

### 6.2 Fixture YAML: `fixtures/golden/recovery_route_odd_even.yaml`

```yaml
id: recovery_route_odd_even
kind: golden_fixture
start_stage: recovery
profile: NORMAL

runs:
  - attempt: 1
    status: rejected
    acceptance_report:
      final_verdict: rework_required
      summary: T1 failed
  - attempt: 2
    status: rejected
    acceptance_report:
      final_verdict: rework_required
      summary: T1 failed again

expected:
  recovery_route:
    attempt_1:
      action: RETRY_SAME_CODER
      skip_verifier: true
    attempt_2:
      action: RUN_VERIFIER
      skip_verifier: false
```

---

## 7. ЧТО НЕ ДЕЛАТЬ

```text
- Не создавать YAML-файл с правилами для лэддера. Pydantic-дефолтов достаточно.
- Не создавать YAML-парсер условий. Условия — enum, строго типизированы.
- Не заменять существующий classify_failure/decide_recovery. evaluate_ladder — дополнительный слой.
- Не ломать 83 существующих recovery-теста.
- Не запускать реальные LLM в тестах.
- Не добавлять eval() или произвольные expression'ы.
- Не хардкодить значения условий за enum'ом.
```

---

## 8. Acceptance criteria

```text
1. RecoveryRule, RecoveryRoute, RecoveryLadder модели существуют с ПОЛЯМИ КАК В §2.
2. evaluate_ladder(1) → RETRY_SAME_CODER с skip_verifier=true.
3. evaluate_ladder(2) → RUN_VERIFIER с on_verdict mapping.
4. evaluate_ladder(7) → NEW_ARCHITECT.
5. ArchitectContext модель существует со всеми полями из §2.
6. _apply_new_architect сохраняет ArchitectContext в spec_json.
7. packet_executor.py проверяет skip_verifier из лэддера на rejection.
8. worker.py вызывает _maybe_apply_recovery ДО _handle_rejection.
9. RecoveryLadder.default() возвращает дефолтный odd/even лэддер.
10. Все 9+ unit-тестов проходят без реальных LLM/git/API.
11. 1 fixture YAML тестирует odd/even routing.
12. Профили (FAST/NORMAL/STRICT) работают без изменений.
13. STRICT never downgraded — never_downgrade_strict не сломан.
14. Существующие recovery-тесты не сломаны.
```

---

## 9. Кодер: форма отчёта

```text
Файлы изменены
RecoveryRule/Route/Ladder модели добавлены: да/нет
evaluate_ladder функция добавлена: да/нет
ArchitectContext модель добавлена: да/нет
_apply_new_architect добавлен: да/нет
_build_architect_context добавлен: да/нет
packet_executor.py verifier gate изменён: да/нет
worker.py recovery порядок изменён: да/нет
RecoveryLadder.default() добавлен: да/нет
Тестов добавлено: количество
Тестов пройдено: количество
Оставшиеся блокеры
```
