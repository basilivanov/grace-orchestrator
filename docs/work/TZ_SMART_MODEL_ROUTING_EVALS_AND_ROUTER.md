# ТЗ: Eval-driven Smart Model Routing для Grace Orchestrator

**Статус:** implementation-ready design / routing-only TZ  
**Дата:** 2026-08-14  
**Репозиторий:** `basilivanov/grace-orchestrator`  
**Источник evidence:** versioned routing snapshot из `basilivanov/solarsage-astro`

---

## 1. Цель

Нужно реализовать в Grace Orchestrator автоматический model routing для coding work packets на основании заранее измеренных eval-данных.

Grace НЕ проводит benchmark/eval campaign, не считает leaderboard и не владеет eval harness.

Эта ответственность перенесена в SolarSage:

```text
solarsage-astro/docs/work/TZ_AGENT_EVAL_PARALLEL_CAMPAIGN_AND_ROUTING_EVIDENCE.md
```

Grace получает компактный versioned routing evidence snapshot и использует его как источник policy.

Главная цель runtime router:

> Для каждого production work packet выбирать такую последовательность coder/repair/rescue моделей, которая с высокой вероятностью минимизирует Time-to-Green и Cost-to-Green без ухудшения reliability и critical-failure rate.

---

## 2. Основной принцип

Не выбирать одну глобально «лучшую» модель.

Router должен принимать решение на основании:

- task characteristics;
- risk/classification;
- evidence snapshot;
- текущего этапа попытки (`first`, `repair`, `rescue`);
- verifier outcome;
- operator override;
- доступности provider/model.

Базовая схема:

```text
WORK PACKET
  ↓
CLASSIFY
  ↓
SELECT FIRST CODER
  ↓
RUN
  ↓
VERIFIER
  ├─ GREEN → DONE
  └─ RED
       ↓
   classify failure
       ├─ local/repairable → SAME-MODEL REPAIR (если policy разрешает)
       │                     ↓
       │                  VERIFIER
       │                     ├─ GREEN → DONE
       │                     └─ RED → RESCUE
       └─ structural/high-risk/repeated → RESCUE MODEL
                                 ↓
                              VERIFIER
                                 ├─ GREEN → DONE
                                 └─ RED → terminal/manual policy
```

---

## 3. Evidence snapshot contract

Grace не должен знать внутренний layout `.eval-runs` SolarSage.

Он читает один versioned machine-readable snapshot.

Минимальные поля snapshot:

```json
{
  "schemaVersion": 1,
  "campaignId": "...",
  "sourceCommitSha": "...",
  "createdAt": "...",
  "models": {},
  "taskClasses": {},
  "metrics": {},
  "policyCandidates": [],
  "definitions": {
    "green": {},
    "shippable": {}
  },
  "limitations": []
}
```

Grace обязан:

- валидировать schema;
- отклонять неизвестную major schema version;
- хранить активный snapshot version/id;
- сохранять snapshot id в telemetry каждого routed packet;
- поддерживать rollback на предыдущий snapshot;
- не модифицировать snapshot in-place.

---

## 4. Task classification

Перед routing каждый work packet получает multi-label classification.

Минимальные labels:

```text
backend
frontend
fullstack
cross_codebase
contract_sensitive
canon_sensitive
discovery_required
refactor
repair
high_risk
```

Классификация может быть дополнена runtime features:

- estimated files touched;
- estimated repositories touched;
- presence of explicit file list;
- acceptance criteria completeness;
- contract/schema changes;
- migrations;
- infra/security-sensitive paths;
- task size/complexity;
- prior failure count;
- failure type.

Router не должен полагаться на один label.

---

## 5. Router input

Пример внутреннего запроса:

```json
{
  "packetId": "...",
  "projectId": "...",
  "taskClass": ["backend", "contract_sensitive"],
  "risk": "normal",
  "attempt": 1,
  "stage": "first",
  "estimatedScope": {
    "files": 5,
    "repos": 1
  },
  "previousAttempts": [],
  "operatorOverride": null
}
```

Для repair/rescue добавить:

```json
{
  "verifierFailure": {
    "kind": "test_failure",
    "summary": "...",
    "failedChecks": []
  },
  "previousModel": "...",
  "previousPatchRef": "..."
}
```

---

## 6. Router output

Router должен возвращать объяснимое решение:

```json
{
  "model": "gemini-3.7-high",
  "stage": "first",
  "reason": "best TTG/reliability evidence for backend+contract_sensitive",
  "policyId": "routing-2026-08-14-v1",
  "snapshotId": "2026-08-14-v1",
  "fallback": "luna-max",
  "sameModelRepairAllowed": true,
  "confidence": "medium"
}
```

Decision reason обязателен для observability/debugging.

---

## 7. Routing policy layers

Применять policy в таком порядке:

1. explicit operator override;
2. safety/high-risk hard rules;
3. provider/model availability;
4. task-class evidence rule;
5. global evidence fallback;
6. conservative fallback.

### 7.1. Operator override

Нужны варианты:

```text
auto
force:<model>
force-rescue:<model>
disable-repair
```

Override должен попадать в audit/telemetry.

### 7.2. High-risk rules

Для неизвестных/опасных категорий router должен иметь возможность сразу выбирать conservative model/policy.

Примеры:

- security-sensitive auth/permissions;
- migrations/data loss risk;
- broad infra mutation;
- неизвестный task class;
- низкая confidence в evidence.

High-risk hard rules конфигурируемы и versioned.

---

## 8. First-attempt routing

Router должен выбирать first coder по evidence metrics, а не по статическому рейтингу модели.

Приоритет метрик:

1. critical failure / reliability constraints;
2. `Green@1` / `Shippable@1`;
3. median/p90 Time-to-Green;
4. Cost-to-Green;
5. quality score среди GREEN;
6. sample size/confidence.

Нельзя выбирать модель только потому, что она дешевле или быстрее, если её critical failure rate превышает threshold.

Нельзя строить узкое class-specific правило на маленькой выборке без fallback.

---

## 9. Failure classification после verifier

После RED verifier нужно классифицировать failure.

Минимальные kinds:

```text
local_test_failure
lint_or_type_failure
small_contract_miss
scope_violation
empty_or_no_result
architectural_miss
wrong_approach
cross_layer_inconsistency
provider_or_infra_failure
timeout
unknown
```

`provider_or_infra_failure` не считается model-quality failure и обрабатывается отдельно.

---

## 10. Same-model repair

Same-model repair разрешать только когда:

- evidence показывает приемлемый repair success для этого model/task class;
- failure выглядит локальным/repairable;
- нет critical/scope/systemic violation;
- repair budget не исчерпан.

Repair input должен включать:

- original packet;
- текущий diff;
- verifier output;
- failed checks;
- acceptance criteria;
- требование минимального исправления без ненужного rewrite.

По умолчанию максимум один same-model repair перед rescue, если snapshot/policy явно не разрешает иное.

Не делать бесконечные `model → same model → same model` циклы.

---

## 11. Rescue / escalation

Немедленно эскалировать, если:

- повторный RED после repair;
- architectural/wrong-approach failure;
- broad cross-layer inconsistency;
- scope/process discipline failure;
- high-risk task;
- snapshot рекомендует direct rescue для данного class;
- first model вернул пустой/no-result outcome несколько раз после infra filtering.

Rescue model получает:

- original packet;
- предыдущий patch/diff;
- verifier failures;
- repair attempt evidence, если был;
- acceptance criteria;
- краткую историю решений router.

Не заставлять rescue начинать exploration с нуля без необходимости.

---

## 12. Policy representation

Routing policy должна быть data-driven и versioned.

Пример:

```yaml
policy_id: routing-2026-08-14-v1
snapshot_id: 2026-08-14-v1
rules:
  - match:
      task_labels: [backend]
      risk: normal
    first: deepseek-v4-flash
    repair: same
    rescue: luna-max

  - match:
      task_labels: [discovery_required]
    first: luna-max
    repair: same
    rescue: luna-max

fallback:
  first: gemini-3.7-high
  repair: same
  rescue: luna-max
```

Конкретные значения выше — только пример формата. Реальные правила должны генерироваться/утверждаться по evidence snapshot.

---

## 13. Policy generation/import

Grace должен поддерживать два режима:

### Manual approved policy

Оператор/разработчик формирует routing policy на основе snapshot и активирует её явно.

### Generated candidate policy

Grace или отдельный offline tool может построить candidate policy из `policyCandidates` snapshot, но activation остаётся явной контролируемой операцией.

В v1 запрещено автоматическое online self-learning и мгновенное изменение policy от production outcomes.

---

## 14. Feature flags / rollout

Нужны flags:

```text
smart_model_routing_enabled
smart_model_routing_dry_run
smart_model_repair_enabled
smart_model_rescue_enabled
```

### Dry run

В `dry_run` текущая production model selection не меняется, но router параллельно вычисляет:

- какую модель выбрал бы;
- почему;
- какой policy/snapshot применил бы.

Это пишется в telemetry для сравнения до включения.

### Rollout

Рекомендуемая последовательность:

1. policy loaded + validation only;
2. dry-run;
3. ограниченный процент low-risk packets;
4. normal routing;
5. repair;
6. rescue automation;
7. high-risk routing после отдельной проверки.

---

## 15. Observability

Для каждого work packet сохранять:

```text
packet_id
project_id
routing_policy_id
routing_snapshot_id
task_labels
risk
stage
selected_model
selection_reason
selection_confidence
operator_override
attempt_number
agent_started_at
agent_finished_at
agent_wall_seconds
verifier_result
failure_kind
repair_used
rescue_used
final_green
total_time_to_green
total_cost_to_green
```

Нужно уметь ответить:

- почему выбрали эту модель;
- сколько попыток понадобилось;
- когда router эскалировал;
- какая policy работала;
- насколько production outcome соответствует eval expectation.

---

## 16. Production feedback

Production telemetry собирать для последующего offline анализа:

- Green@1;
- attempts-to-green;
- Time-to-Green;
- repair success;
- rescue rate;
- regression/rollback signals;
- model/provider failures.

Но production feedback НЕ должен сам менять активную policy.

Обновление policy:

```text
new eval/production analysis
→ new evidence snapshot
→ new candidate policy
→ review/approval
→ activate
```

---

## 17. Provider availability

Router должен отличать model quality от provider availability.

Если выбранная модель временно недоступна:

1. применить bounded infra retry policy;
2. если недоступность сохраняется — перейти на configured availability fallback;
3. записать, что fallback вызван infrastructure, а не task-quality routing.

Provider outage не должен портить статистику модели как coder.

---

## 18. Confidence и sparse evidence

Snapshot должен передавать sample size/confidence.

Grace обязан иметь minimum evidence threshold.

Если task class слишком редкий:

```text
specific class rule
→ broader class rule
→ global rule
→ conservative fallback
```

Нельзя overfit'ить routing по единичному успешному eval.

---

## 19. Backward compatibility

При отключённом `smart_model_routing_enabled` Grace должен работать как до внедрения router.

Routing layer не должен ломать:

- существующий worker execution;
- worktree lifecycle;
- verifier;
- packet state machine;
- project/user isolation;
- manual model selection.

Router — отдельный decision layer, а не rewrite execution engine.

---

## 20. Предлагаемые компоненты

Названия адаптировать к реальной архитектуре проекта, не создавать искусственную абстракцию ради ТЗ.

Логические обязанности:

```text
RoutingEvidenceLoader
  - load/validate snapshot
  - expose metrics/confidence

TaskClassifier
  - derive multi-label task features

ModelRouter
  - choose first/repair/rescue
  - apply rule precedence

FailureClassifier
  - normalize verifier/agent failures

RoutingPolicyStore
  - active policy
  - version/rollback

RoutingTelemetry
  - decision + outcome evidence
```

Если в текущем коде уже есть близкие abstraction boundaries — расширять их, а не плодить дубль.

---

## 21. API / admin surface

Минимально нужны операции:

- посмотреть active snapshot;
- посмотреть active policy;
- загрузить/валидировать новый snapshot;
- загрузить candidate policy;
- activate policy;
- rollback policy;
- включить/выключить dry-run;
- задать operator override для конкретного packet/run;
- посмотреть routing decision/explanation.

Все mutations должны соответствовать существующим security/audit правилам Grace.

---

## 22. Acceptance criteria

Работа считается завершённой, когда:

1. Grace умеет загрузить и schema-validate SolarSage routing evidence snapshot;
2. active snapshot/policy version хранится и виден оператору;
3. work packet получает task classification;
4. router возвращает explainable first-coder decision;
5. verifier RED запускает failure classification;
6. same-model repair применяется только по policy и максимум в установленном budget;
7. structural/repeated failure эскалируется в rescue model;
8. provider failure отделён от model-quality failure;
9. operator override имеет высший приоритет;
10. unknown/sparse/high-risk case имеет conservative fallback;
11. dry-run не меняет реальную execution, но пишет decision telemetry;
12. routing telemetry позволяет восстановить decision chain;
13. routing можно полностью отключить feature flag'ом;
14. существующая execution semantics остаётся backward compatible;
15. policy можно rollback'нуть;
16. production telemetry не меняет policy автоматически.

---

## 23. Тесты

Минимальный test set:

- snapshot schema/version validation;
- unknown major version rejected;
- task classification deterministic;
- operator override wins;
- high-risk hard rule wins over evidence rule;
- unavailable provider uses infra fallback;
- provider failure does not count as model failure;
- class-specific routing with sufficient confidence;
- sparse evidence falls back to broader/global rule;
- local failure permits repair when policy allows;
- structural failure skips repair and goes rescue;
- second RED escalates;
- repair budget enforced;
- dry-run does not affect selected production model;
- telemetry contains policy/snapshot/reason;
- policy rollback;
- router disabled preserves legacy behavior.

---

## 24. Что НЕ делать в Grace

- не реализовывать SolarSage eval harness;
- не запускать 105 benchmark runs из Grace;
- не хранить raw eval traces;
- не пересчитывать blind-review leaderboard;
- не изменять eval rubrics/tasks;
- не выбирать модель по публичному benchmark напрямую;
- не делать бесконечные retries;
- не менять policy online по одному production result;
- не смешивать provider outage с quality failure;
- не hardcode'ить `Gemini всегда first`, `Luna всегда best` или аналогичное предположение.

---

## 25. Итоговый runtime flow

```text
PACKET
  ↓
TaskClassifier
  ↓
ModelRouter(snapshot + active policy)
  ↓
FIRST MODEL
  ↓
EXECUTE
  ↓
VERIFY
  ├─ GREEN ─────────────→ DONE
  │
  └─ RED
      ↓
  FailureClassifier
      ├─ infra/provider → bounded infra retry / availability fallback
      ├─ local repairable + policy allows
      │      ↓
      │   SAME MODEL REPAIR
      │      ↓
      │   VERIFY
      │      ├─ GREEN → DONE
      │      └─ RED ─────┐
      │                  │
      └─ structural ─────┤
                         ↓
                     RESCUE MODEL
                         ↓
                      VERIFY
                         ├─ GREEN → DONE
                         └─ RED → terminal/manual escalation policy
```

SolarSage отвечает за доказательства того, **какие значения должны быть в routing policy**. Grace отвечает только за **корректное, объяснимое и безопасное применение этой policy в production runtime**.
