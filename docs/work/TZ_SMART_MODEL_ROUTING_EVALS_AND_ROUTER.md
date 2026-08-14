# ТЗ: Eval-driven Smart Model Routing для Grace Orchestrator

**Статус:** implementation-ready design / master TZ  
**Дата:** 2026-08-14  
**Целевой репозиторий:** `basilivanov/grace-orchestrator`  
**Источник эталонных eval-данных:** `basilivanov/solarsage-astro`  

---

## 1. Зачем это делаем

Нужно перестать выбирать coder-модель в Grace Orchestrator вручную по общим публичным benchmark'ам и перейти к автоматическому routing на основании реальных результатов моделей на задачах, максимально похожих на production work packets.

Основной вопрос не «какая модель умнее», а:

> Какая routing policy быстрее, дешевле и надёжнее доводит реальный work packet до принятого GREEN-результата с минимальным количеством retry/escalation и без роста critical failures?

Кандидаты первого цикла:

- `luna-max` — `gpt-5.6-luna`, reasoning/effort `max`;
- `gemini-3.7-high` — новый Gemini 3.7 Flash в high reasoning/profile;
- `deepseek-v4-flash` — уже присутствует в SolarSage eval harness и должен остаться полноценным кандидатом, а не контрольной моделью.

Важно: текущие SolarSage-прогоны уже показали, что DeepSeek 4 Flash способен быть близок к Luna Max по качеству, но существенно быстрее/дешевле, а на тяжёлой cross-codebase задаче был лучше. Поэтому нельзя строить router как бинарный выбор «Gemini vs Luna».

---

## 2. Главный принцип

Не оптимизировать single-run score и не выбирать «победителя модели».

Оптимизировать **pipeline outcome**:

- вероятность получить приемлемый патч с первой попытки;
- время до первого GREEN;
- время до принятого результата;
- стоимость до GREEN;
- количество repair/retry;
- вероятность critical failure / scope violation / regression;
- p90, а не только среднее время;
- необходимость эскалации на более дорогую/медленную модель.

Основная operational-метрика: **Time To Green (TTG)**.

Дополнительно считать **Cost To Green (CTG)** и **Shippable/Accepted rate**.

---

## 3. Разделение ответственности между репозиториями

### 3.1. `solarsage-astro`

Использовать как эталонный model-eval harness и источник сравнительных данных.

Там должны жить:

- immutable eval tasks;
- immutable rubrics;
- pinned base SHA/tree;
- model/pricing snapshots;
- isolated worktrees;
- raw run evidence;
- reviewed scorecards;
- агрегированные pipeline metrics;
- два новых eval task;
- итоговый routing evidence snapshot.

Существующие старые task/rubric/result-файлы **не переписывать**.

### 3.2. `grace-orchestrator`

Здесь должен жить production router:

- классификация work packet;
- выбор coder-модели;
- repair policy;
- escalation policy;
- operator override;
- feature flag / dry-run;
- audit trail routing-решений;
- runtime telemetry;
- загрузка/versioning routing policy, полученной из eval evidence.

Router не должен напрямую читать сырые eval runs из SolarSage во время production execution. Он работает по компактному versioned policy snapshot.

---

## 4. Что уже есть и что сохраняем

В `solarsage-astro/evals` уже есть правильная база:

1. `checkin-mood-trend-v1` — full-stack API + UI + contracts;
2. `day-momentum-v1` — deterministic backend algorithm;
3. `grace-event-registry-v1` — canon/process/registry discipline;
4. `ui-contract-disclosure-v1` — UI semantic/test contract;
5. `sidecar-planet-house-v1` — cross-codebase change + backward compatibility.

Harness уже использует:

- pinned base SHA и tree hash;
- detached isolated worktree;
- одинаковую исходную базу для кандидатов;
- controller verification;
- scope checks;
- token/time/cost accounting;
- blind human review;
- immutable task/rubric после scored run.

Эти свойства являются обязательными и не должны быть упрощены.

---

# PHASE A — MODEL EVAL CAMPAIGN

## 5. Добавить Gemini 3.7 в eval harness

В `solarsage-astro/evals/models.toml` добавить отдельную модель:

- logical id: `gemini-3.7-high`;
- runner/provider — тот production-совместимый путь, который реально планируется использовать;
- reasoning/profile — high;
- отдельный immutable pricing snapshot;
- usage parser — фактический для выбранного runner;
- никаких API keys в Git.

Цена должна фиксироваться snapshot'ом так же, как у существующих моделей.

Если production Grace Orchestrator будет вызывать Gemini не через тот же runner, что eval harness, отдельно зафиксировать это в manifest. Нельзя смешивать model-quality и runner-reliability в одну метрику.

---

## 6. Матрица прогонов

### 6.1. Модели

Каждый task прогонять на:

1. `luna-max`;
2. `gemini-3.7-high`;
3. `deepseek-v4-flash`.

### 6.2. Повторы

**Пять независимых прогонов каждой комбинации `task × model`.**

Не один прогон и не best-of-5.

Все пять являются наблюдениями и входят в статистику.

### 6.3. Существующие eval tasks

5 задач × 3 модели × 5 повторов = **75 scored model runs**.

### 6.4. Новые eval tasks

2 задачи × 3 модели × 5 повторов = **30 scored model runs**.

### 6.5. Полный первый corpus

Итого после добавления двух задач:

> **7 tasks × 3 models × 5 runs = 105 scored model runs.**

Infra rerun не считать дополнительным «шестым результатом модели». Он должен маркироваться отдельно как повтор вследствие подтверждённого harness/runner failure.

---

## 7. Правила честного A/B/C

Для каждой реплики task:

- одинаковый pinned base SHA;
- одинаковое состояние зависимостей;
- одинаковый host/runtime по возможности;
- одинаковый prompt/task packet;
- одинаковые allowed tools;
- одинаковая политика subagents;
- одинаковые verification gates;
- fresh isolated worktree;
- отсутствие доступа к патчам других кандидатов;
- human quality review до раскрытия identity/cost;
- latency кандидатов сравнивать только при сопоставимом runner/host контексте.

Если модель упала из-за provider/runner/CLI transport error, это не превращать автоматически в model-quality failure.

Обязательно хранить две отдельные категории:

- `model_failure` — модель завершила работу некорректно, пустым/невалидным патчем либо не выполнила task при исправном runner;
- `infra_failure` — доказанный сбой runner/provider/controller.

При сомнении не переписывать историю: оставить incident и пометить classification confidence.

---

# PHASE B — ДВА НОВЫХ EVAL

## 8. `repair-after-verifier-v1`

### 8.1. Цель

Измерить главное, чего не измеряют обычные one-pass feature evals:

> Насколько быстро и надёжно модель чинит уже существующую неудачную попытку после controller/verifier feedback.

Этот eval нужен для ответа на вопрос: выгоднее ли `fast model → repair` по сравнению с `Luna Max one-pass` или `fast model → Luna rescue`.

### 8.2. Исходное состояние

Создать deterministic frozen broken patch на pinned repo snapshot.

Патч должен выглядеть реалистично: feature почти сделана, но содержит несколько разных типов дефектов.

Минимально заложить:

- один реальный failing test или typecheck failure;
- одну contract/behavior ошибку, которую видно из требований или verifier evidence;
- одну process/scope/hygiene проблему, которую нельзя исправить случайным «make tests green»;
- при этом задача должна быть repairable без полного переписывания feature.

### 8.3. На вход модели

Дать:

- исходный work packet;
- существующий broken diff/worktree state;
- точный вывод verifier;
- failing test/typecheck logs;
- acceptance criteria;
- обычные repo instructions.

Не подсказывать конкретный fix.

### 8.4. Требуемое поведение

Модель должна:

1. диагностировать root cause;
2. исправить существующую реализацию;
3. не разрушить уже корректные части;
4. не выйти за scope;
5. запустить нужные проверки;
6. довести task до GREEN.

### 8.5. Метрики именно этого eval

- `repair_green_rate`;
- `repair_accepted_rate`;
- `repair_seconds`;
- `repair_cost_usd`;
- `additional_input_tokens`;
- `additional_output_tokens`;
- `additional_reasoning_tokens`;
- `new_regressions_count`;
- `scope_violation`;
- `critical_failure`;
- размер repair diff;
- доля unnecessary rewrite / scope expansion по human review.

---

## 9. `discovery-refactor-v1`

### 9.1. Цель

Проверить класс задач, где coder не получает почти готовую карту файлов и должен сам:

- исследовать repo;
- найти источник дублирования/legacy;
- понять архитектурные границы;
- выбрать минимальный правильный scope;
- реализовать изменение;
- сохранить compatibility;
- определить адекватные tests.

Именно здесь Luna Max может иметь реальное преимущество за счёт глубокого reasoning. Это нужно измерить, а не предполагать.

### 9.2. Формат prompt

Task должен задавать problem/desired invariant, а не implementation recipe.

Пример класса постановки:

> В системе X вычисление/контракт Y дублируется в двух местах. Уберите дублирование, сохранив текущее публичное поведение и backward compatibility. Найдите правильный canonical layer самостоятельно. Добавьте/обновите проверки. Не создавайте новую абстракцию без необходимости.

Не указывать модели заранее полный exact file list, который фактически решает discovery за неё.

При этом safety boundary harness должен остаться: разрешённый repository/module scope задаётся контроллером, но не превращается в пошаговую подсказку.

### 9.3. Что оценивать

- правильность repo exploration;
- корректность выбранной architectural boundary;
- минимальность scope;
- отсутствие duplicate/parallel abstraction;
- backward compatibility;
- качество tests;
- completeness;
- verifier result;
- TTG;
- cost;
- unnecessary churn.

---

# PHASE C — МЕТРИКИ И PIPELINE LEADERBOARD

## 10. Не менять старые human rubrics

Существующие task rubrics immutable.

Не встраивать в них новые speed/cost правила задним числом.

Вместо этого добавить **отдельный pipeline leaderboard**, который агрегирует результаты поверх task-level scorecards.

---

## 11. Run-level поля

Для каждого model run сохранять минимум:

- task id/version;
- model logical id;
- exact provider/model id;
- runner id/version;
- reasoning/effort;
- base SHA/tree hash;
- repetition index `1..5`;
- start/end/duration model time;
- controller verification result;
- `control_valid`;
- scope status;
- critical failure boolean + class;
- completion score;
- accuracy score/cases;
- human accepted/verdict;
- patch bytes / changed file count;
- input/cached/output/reasoning tokens;
- normalized cost;
- reported cost separately;
- infra failure boolean/class;
- model no-result/empty-result boolean;
- repair/escalation metadata, если применимо.

---

## 12. Определения outcome

Не смешивать разные уровни «успеха».

### `VerifierGreen`

Все обязательные deterministic controller gates зелёные.

### `ControlValid`

Нет scope/head/worktree/control violation.

### `Accepted`

Патч принят по immutable human rubric данного task; нет rubric critical failure.

### `Shippable`

Для pipeline aggregation:

`VerifierGreen && ControlValid && Accepted`

Если task/rubric имеет специальное правило acceptance — использовать его, а не придумывать универсальный completion threshold задним числом.

---

## 13. Главные агрегированные метрики

Считать по модели, task и task-family:

### Надёжность

- `Green@1` — доля first attempts с `VerifierGreen`;
- `Shippable@1`;
- `Green@2` — с учётом одного repair/retry по заданной policy;
- `Shippable@2`;
- `critical_failure_rate`;
- `scope_violation_rate`;
- `model_no_result_rate`;
- `infra_failure_rate` — отдельно, не смешивать с model failure;
- regression rate.

### Скорость

- `TTG_p50`;
- `TTG_p90`;
- `TimeToAccepted_p50`;
- `TimeToAccepted_p90`;
- first-attempt duration p50/p90;
- repair duration p50/p90.

### Стоимость

- `CostToGreen_p50`;
- `CostToGreen_p90`;
- `CostToAccepted_p50/p90`;
- tokens-to-green;
- reasoning-tokens-to-green.

### Качество

- median human completion among shippable runs;
- median accuracy among shippable runs;
- unnecessary-churn/scope-expansion notes;
- test quality score, если rubric его содержит.

### Retry burden

- attempts-to-green p50/p90;
- attempts-to-accepted p50/p90;
- escalation rate;
- same-model repair success rate;
- rescue success rate.

---

## 14. Time To Green

TTG — основная operational metric.

Для policy из нескольких шагов TTG считается как суммарное model execution time всех попыток до первого GREEN, включая repair/escalation.

Например:

`Gemini first attempt + Gemini repair + Luna rescue`

должен сравниваться с:

`Luna first attempt`

как две **pipeline policies**, а не как две независимые single-run модели.

Не включать подготовку dependencies/controller bootstrap, если старый harness уже исключает их; правило должно быть одинаковым для всех кандидатов.

---

# PHASE D — POLICY SIMULATOR

## 15. Сравнивать policies, а не только модели

На собранном corpus автоматически посчитать минимум следующие стратегии:

1. `luna-only`;
2. `gemini-only`;
3. `deepseek-only`;
4. `gemini -> gemini-repair`;
5. `deepseek -> deepseek-repair`;
6. `gemini -> luna-rescue`;
7. `deepseek -> luna-rescue`;
8. `gemini -> gemini-repair -> luna-rescue`;
9. `deepseek -> deepseek-repair -> luna-rescue`;
10. direct `luna-max` для discovery/refactor family.

Не делать вывод, что один global winner обязан обслуживать все task families.

---

## 16. Как выбирать policy

Не использовать один непрозрачный weighted score как единственный источник истины.

Сначала применить quality/safety constraints, затем сравнивать Pareto frontier.

Рекомендуемый порядок:

1. исключить policy с неприемлемым critical failure / scope violation / no-result rate;
2. сравнить `Shippable@1/@2`;
3. сравнить `TTG_p50` и особенно `TTG_p90`;
4. сравнить `CostToGreen`;
5. при близких значениях использовать human quality как tie-breaker;
6. если качество статистически/практически неразличимо — предпочитать более быструю и дешёвую policy.

Поскольку на первом цикле всего 5 повторов, не изображать ложную статистическую точность. Показывать raw counts (`4/5`, `5/5`), bootstrap/interval только как ориентир и требовать material margin для агрессивного routing.

---

# PHASE E — ROUTING EVIDENCE SNAPSHOT

## 17. Отдельный versioned artifact

Из eval corpus генерировать компактный immutable/versioned snapshot, например:

`model-routing-evidence-vYYYYMMDD-N.json`

Он должен содержать:

- eval suite version;
- task versions/base SHAs;
- model/provider/runner versions;
- pricing snapshot ids;
- число runs;
- per-family metrics;
- candidate policies;
- выбранную policy по family;
- confidence/data-quality flags;
- generation timestamp;
- generator version/hash.

Production router не должен сам интерпретировать сырые scorecards.

---

# PHASE F — SMART MODEL ROUTER В GRACE ORCHESTRATOR

## 18. Scope v1

В первой версии router управляет **только coder role**.

Не распространять автоматически выводы coder eval на planner/reviewer/tester/architect roles. Для них нужны отдельные eval evidence позднее.

---

## 19. Классификация work packet

Router должен извлекать deterministic features из уже существующего packet/context, без отдельного дорогого LLM-call там, где это возможно.

Минимальные признаки:

- task kind: feature / bugfix / refactor / repair;
- backend / frontend / full-stack;
- cross-module / cross-codebase;
- наличие explicit exact write scope;
- ambiguity/discovery requirement;
- contract/schema/API change;
- generated artifacts/canon involvement;
- backward compatibility risk;
- UI semantic contract;
- estimated scope/touched modules;
- наличие existing failing verifier evidence;
- retry attempt number;
- previous failure class;
- risk tier.

Если packet metadata сейчас этого не содержит, добавить компактный `routing_profile`, формируемый из уже известной orchestrator информации.

Не заставлять пользователя вручную выбирать все эти признаки.

---

## 20. Task families v1

Минимум:

- `backend_algorithm`;
- `fullstack_contract`;
- `ui_contract`;
- `canon_process`;
- `cross_codebase_compat`;
- `discovery_refactor`;
- `repair_after_verifier`;
- `unknown/high_risk`.

Маппинг должен быть declarative/testable, а не размазан по executor if/else.

---

## 21. Routing state machine

Базовый production flow:

```text
WORK PACKET
    |
    v
routing profile / task family
    |
    v
select first coder from evidence policy
    |
    v
execute
    |
    v
controller/verifier
    |
    +---- GREEN + accepted-by-automation-contract ---> DONE
    |
    v
failure classification
    |
    +---- infra failure ---------------------------> infra retry; модель не штрафуется
    |
    +---- local/repairable failure ----------------> same-model repair (max 1 в v1)
    |
    +---- repeated / architectural / scope / stuck -> Luna Max rescue
    |
    +---- unknown/high-risk -----------------------> conservative escalation
```

Конкретная first-model и необходимость same-model repair должны браться из routing policy snapshot, а не быть навечно hardcoded как Gemini/DeepSeek.

---

## 22. Failure classifier

После verifier failure router должен различать хотя бы:

- `infra`;
- `test_local`;
- `typecheck_local`;
- `contract_mismatch`;
- `scope_violation`;
- `incomplete_task`;
- `architectural_mismatch`;
- `model_no_result/stuck`;
- `unknown`.

Для `test_local/typecheck_local` разрешить same-model repair, если evidence показывает выгоду.

Для repeated failure, scope violation, architectural mismatch или stuck/no-result — эскалация на rescue policy без бесконечных retry.

В v1 максимум retry/escalation должен быть ограничен конфигом.

---

## 23. Rescue context

При escalation новая модель должна получить не только исходный task.

Передавать:

- original work packet;
- текущий patch/worktree state;
- previous model id;
- verifier failures;
- commands/results;
- concise attempt history;
- failure classification;
- acceptance criteria.

Не передавать ненужный сырой chain-of-thought предыдущей модели.

---

## 24. Conservative fallback

Если:

- task family неизвестна;
- evidence snapshot отсутствует/несовместим;
- policy confidence ниже допустимого;
- task помечен high-risk;

использовать conservative fallback.

На первом rollout fallback может быть `luna-max`, пока новые evals не докажут более выгодную безопасную стратегию.

Fallback должен быть configurable.

---

## 25. Operator override

Всегда оставить возможность принудительно задать:

- model;
- effort/reasoning;
- disable smart routing;
- disable same-model repair;
- force direct rescue/high-reasoning path.

Override должен попадать в audit log и не считаться ошибкой router.

---

# PHASE G — OBSERVABILITY И FEEDBACK LOOP

## 26. Каждое routing decision логировать

Минимум:

- work packet id;
- routing policy snapshot version;
- task family;
- extracted routing features;
- selected model;
- selection reason;
- attempt number;
- verifier result;
- failure class;
- repair/escalation decision;
- TTG;
- cost/tokens, если доступны;
- final outcome;
- operator override.

Нужен понятный ответ на вопрос:

> Почему конкретный packet ушёл именно этой модели и почему потом был/не был эскалирован?

---

## 27. Не делать online self-learning в v1

Router v1 **не должен сам менять policy в production на лету**.

Production telemetry собирается, затем периодически анализируется offline и выпускается новый versioned routing snapshot.

Это предотвращает drift, feedback loops и необъяснимое поведение.

Будущая v2 может использовать production data для recalibration, но только через reviewable policy update.

---

# PHASE H — DRY RUN И ROLLOUT

## 28. Feature flags

Добавить минимум:

- `smart_model_routing_enabled`;
- `smart_model_routing_dry_run`.

### Dry-run

В dry-run router вычисляет:

- какую модель выбрал бы;
- repair/escalation policy;
- причину;

но фактическую модель не меняет.

Это позволит сравнить старый routing с новым до включения автоматики.

---

## 29. Rollout

Порядок:

1. закончить 105-run corpus;
2. сгенерировать pipeline leaderboard;
3. выпустить evidence snapshot;
4. реализовать router behind flag;
5. unit/integration tests;
6. включить dry-run;
7. собрать реальные production observations;
8. проверить, что predicted family/policy адекватны;
9. включить smart routing для low/medium-risk coder packets;
10. high-risk/unknown оставить conservative до дополнительной выборки.

---

# PHASE I — ТЕСТЫ ROUTER

## 30. Unit tests

Обязательно покрыть:

- deterministic task-family classification;
- policy snapshot loading/version validation;
- missing/invalid snapshot fallback;
- operator override precedence;
- first coder selection;
- local failure -> same-model repair;
- second failure -> rescue;
- architectural/scope failure -> immediate rescue;
- infra failure не штрафует model route;
- max retry limit;
- unknown family fallback;
- audit reason serialization.

---

## 31. Integration tests

Сделать synthetic executor/verifier fixtures:

### Scenario A
Fast model green с первой попытки -> rescue не вызывается.

### Scenario B
Fast model падает локальным test failure -> same-model repair green.

### Scenario C
Fast model repair снова падает -> Luna rescue -> green.

### Scenario D
Первая попытка даёт scope/architectural failure -> immediate rescue без бессмысленного retry.

### Scenario E
Runner infra error -> infrastructure retry/path, routing quality statistics не портятся.

### Scenario F
Evidence snapshot отсутствует -> conservative fallback.

### Scenario G
Operator force-model -> router не переопределяет выбор.

---

# PHASE J — REPORTING

## 32. Pipeline leaderboard output

Сгенерировать machine-readable JSON и человекочитаемый Markdown/HTML.

Для каждой модели и policy показывать минимум:

| Metric | Meaning |
|---|---|
| Green@1 | verifier green с первой попытки |
| Shippable@1 | реально принимаемый first pass |
| Green@2 | green после одного repair |
| TTG p50/p90 | время до green |
| CostToGreen p50/p90 | цена до green |
| Critical failure rate | опасные/неприемлемые результаты |
| Scope violation rate | дисциплина scope |
| No-result rate | пустые/stuck model outcomes |
| Repair success | способность чинить verifier failure |
| Escalation rate | как часто нужен rescue |
| Human quality | качество уже shippable patches |

Отдельно показывать runner/provider infra reliability.

---

# PHASE K — DELIVERABLES

## 33. SolarSage deliverables

В `solarsage-astro` должны появиться:

1. `gemini-3.7-high` model config;
2. immutable Gemini pricing snapshot;
3. `repair-after-verifier-v1` task + rubric + frozen base;
4. `discovery-refactor-v1` task + rubric + frozen base;
5. repeat index/run metadata support, если его ещё нет;
6. агрегатор pipeline metrics;
7. policy simulator;
8. pipeline leaderboard JSON + human report;
9. versioned routing evidence snapshot;
10. reviewed results всех 105 model runs либо явно документированные infra incidents.

---

## 34. Grace Orchestrator deliverables

В `grace-orchestrator` должны появиться:

1. typed routing policy schema;
2. evidence snapshot loader;
3. work-packet routing profiler/classifier;
4. declarative task-family route table;
5. coder selection service;
6. verifier failure classifier;
7. bounded same-model repair flow;
8. rescue/escalation flow;
9. operator overrides;
10. dry-run + feature flags;
11. routing audit telemetry;
12. unit/integration tests;
13. documentation по обновлению routing evidence snapshot.

---

# PHASE L — ACCEPTANCE CRITERIA

Работа считается выполненной только если выполняются все условия:

### Eval layer

- [ ] старые immutable tasks/rubrics/results не изменены задним числом;
- [ ] Gemini 3.7 добавлен отдельным versioned model id;
- [ ] DeepSeek 4 Flash остаётся полноправным кандидатом;
- [ ] создано два новых eval task;
- [ ] каждый из 7 task прогнан по 5 раз на каждой из 3 моделей;
- [ ] получено 105 scored runs либо каждый отсутствующий run имеет подтверждённый infra incident;
- [ ] infra failures и model failures разделены;
- [ ] рассчитаны Green@1/Green@2, TTG p50/p90, CTG, critical/scope/no-result rates;
- [ ] рассчитаны repair и escalation metrics;
- [ ] построен pipeline policy leaderboard;
- [ ] выпущен versioned evidence snapshot.

### Router layer

- [ ] smart routing не hardcode'ит «Gemini всегда первый» или «Luna всегда лучший»;
- [ ] выбор зависит от task family + versioned evidence policy;
- [ ] есть bounded same-model repair;
- [ ] есть rescue/escalation;
- [ ] unknown/high-risk имеет conservative fallback;
- [ ] operator override всегда сильнее auto-router;
- [ ] есть dry-run;
- [ ] каждое решение объяснимо из audit record;
- [ ] retry loop ограничен и не может уйти в бесконечный цикл;
- [ ] router tests покрывают основные state transitions;
- [ ] production router не читает raw SolarSage eval runs напрямую.

---

# 35. Что НЕ делать

Не делать в рамках этого ТЗ:

- online RL/self-learning router;
- автоматическую смену planner/reviewer моделей без отдельных evals;
- weighted «магический score», скрывающий реальные TTG/quality показатели;
- best-of-5 вместо пяти независимых наблюдений;
- изменение старых rubric ради нового победителя;
- смешивание runner crash и model failure;
- бесконечные retry одной быстрой модели;
- routing только по цене токена;
- routing только по публичному benchmark;
- hardcoded правило, которое невозможно пересчитать после выхода следующей модели.

---

# 36. Практический ожидаемый результат

После первого полного цикла система должна уметь ответить данными, например:

- backend algorithm -> DeepSeek first, repair same-model, Luna rescue;
- full-stack contract -> Gemini first, Luna rescue;
- discovery/refactor -> Luna direct;
- UI contract -> fast model first;
- unknown/high-risk -> Luna fallback;

**Это только пример формы policy, не заранее заданный результат.** Реальные назначения формируются исключительно из 105-run evidence corpus.

Главный итог ТЗ:

> Grace Orchestrator выбирает не «самую сильную модель вообще», а эмпирически лучшую pipeline policy для конкретного класса work packet и умеет автоматически перейти от быстрого coder к repair/rescue path, если verifier показывает, что первая стратегия не сработала.
