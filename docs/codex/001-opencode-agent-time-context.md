# ТЗ: управляемая передача текущего времени в OpenCode agent system context

## Цель

Добавить в GRACE Orchestrator управляемую возможность передавать **текущее время** в системный контекст OpenCode-агентов.

Важно: нужна только информация о времени. Дату добавлять нельзя.

Фича должна:

- легко включаться и выключаться;
- работать для всех пользователей системы, а не только для одного локального профиля;
- попадать именно в agent/system context OpenCode, а не только в пользовательские сообщения;
- работать для coder-агента и для дочерних/делегированных agent runs, если они запускаются через GRACE Orchestrator;
- не загрязнять git diff пользовательского worktree runtime-файлами.

## Контекст проблемы

OpenCode уже умеет добавлять дату в общий environment/system prompt, но этого недостаточно для GRACE:

- дата не нужна;
- нужно именно текущее время;
- время должно быть доступно агенту при принятии решений, логировании, планировании и интерпретации относительных формулировок;
- включение должно контролироваться централизованно оркестратором.

Нельзя решать задачу добавлением времени только в текст user prompt, потому что тогда оно будет зависеть от конкретного сообщения пользователя и может не попадать в subagent/task context.

## Требуемое поведение

Когда фича включена, каждый OpenCode-запуск, созданный GRACE Orchestrator, должен получать дополнительный system context примерно такого вида:

```text
<grace-runtime-time>
Current local time: 14:37:22
Timezone: Europe/Berlin
Instruction: Treat this as the current local time for this GRACE run. Do not infer the current date from this block.
</grace-runtime-time>
```

Точный формат можно менять, но обязательно:

- присутствует время;
- присутствует timezone;
- дата отсутствует;
- блок явно помечен как GRACE runtime context;
- агенту явно сказано не выводить дату из этого блока.

Когда фича выключена, GRACE Orchestrator не должен добавлять этот block ни в system prompt, ни в user prompt, ни в synthetic messages.

## Конфигурация

Нужно добавить централизованный флаг.

Минимально допустимый вариант через ENV:

```bash
GRACE_OPENCODE_AGENT_TIME_ENABLED=true
GRACE_OPENCODE_AGENT_TIMEZONE=Europe/Berlin
GRACE_OPENCODE_AGENT_TIME_FORMAT=HH:mm:ss
```

Требования:

- `GRACE_OPENCODE_AGENT_TIME_ENABLED=false` полностью отключает фичу;
- значение по умолчанию: `false`, если в проекте нет уже принятой политики включать GRACE runtime context по умолчанию;
- timezone по умолчанию берётся из системной timezone процесса;
- если задан `GRACE_OPENCODE_AGENT_TIMEZONE`, использовать его;
- формат по умолчанию: `HH:mm:ss`;
- дата не должна появляться даже при альтернативном формате, если это не будет явно разрешено отдельной будущей фичей.

Если в проекте уже есть централизованная конфигурация, нужно также поддержать config-level настройку, например:

```yaml
opencode:
  agent_time_context:
    enabled: true
    timezone: Europe/Berlin
    format: HH:mm:ss
```

Приоритет:

1. ENV override;
2. project/system config;
3. default values.

## Архитектурное решение

Предпочтительный вариант: реализовать через управляемый OpenCode plugin или equivalent system-transform layer, который GRACE Orchestrator автоматически подключает ко всем OpenCode runs.

Не нужно патчить пользовательский prompt вручную в каждом control packet.

Ожидаемый flow:

1. GRACE Orchestrator готовит OpenCode run context.
2. Проверяет `agent_time_context.enabled`.
3. Если включено:
   - вычисляет текущее локальное время;
   - формирует runtime time block без даты;
   - подключает его к OpenCode system context.
4. Запускает OpenCode.
5. Все agents/subagents, созданные через этот OpenCode run, получают одинаковый runtime time context.

## Где лучше реализовать

Нужно найти существующую точку запуска OpenCode, предположительно рядом с `run_e2e_packet()` или аналогичным runner-кодом.

Реализация должна быть на уровне GRACE Orchestrator launch wrapper, а не внутри конкретного пакета.

Запрещено:

- просить пользователя вручную настраивать локальный OpenCode профиль;
- требовать ручной установки plugin для каждого пользователя;
- писать `.opencode/plugins/...` в пользовательский worktree так, чтобы это попадало в git diff;
- добавлять время в обычный user message как основной механизм;
- добавлять дату.

Разрешено:

- генерировать временный OpenCode config/plugin в runtime temp directory;
- передавать его через `OPENCODE_CONFIG` или другой поддерживаемый OpenCode mechanism;
- хранить managed plugin внутри репозитория GRACE Orchestrator, если он не зависит от пользовательского worktree;
- использовать fallback wrapper, если plugin hook недоступен в установленной версии OpenCode.

## Формат runtime block

Сделать функцию, условно:

```python
def build_opencode_agent_time_context(now: datetime, timezone_name: str, time_format: str) -> str:
    ...
```

Функция должна возвращать только system-context block.

Пример результата:

```text
<grace-runtime-time>
Current local time: 09:05:17
Timezone: Europe/Berlin
Instruction: Treat this as the current local time for this GRACE run. Do not infer or expose any current date from this block.
</grace-runtime-time>
```

## Поведение при ошибках

Если timezone некорректна:

- не падать в середине OpenCode run;
- записать warning в лог;
- использовать системную timezone процесса;
- если системную timezone определить нельзя, использовать UTC;
- в runtime block всё равно не добавлять дату.

Если OpenCode plugin/config injection не сработал:

- runner должен явно логировать это как warning или error;
- acceptance не должна молча считать фичу работающей;
- тесты должны покрывать этот сценарий.

## Логи и аудит

В run manifest или audit log нужно фиксировать:

```json
{
  "opencode_agent_time_context_enabled": true,
  "timezone": "Europe/Berlin",
  "time_format": "HH:mm:ss",
  "injection_target": "system_context"
}
```

Запрещено логировать полный system prompt целиком, если в проекте это не принято.

Можно логировать сам time block только в debug/test режиме.

## Тесты

Нужно добавить тесты без live OpenCode, через fake runner / fake clock.

Обязательные unit tests:

1. `enabled=false` не создаёт runtime time block.
2. `enabled=true` создаёт block с временем.
3. Block не содержит дату.
4. Block содержит timezone.
5. Некорректная timezone даёт fallback и warning.
6. ENV override имеет приоритет над config.
7. Формат по умолчанию `HH:mm:ss`.

Обязательные integration/runner tests:

1. OpenCode launch получает managed config/plugin при включённой фиче.
2. OpenCode launch не получает managed config/plugin при выключенной фиче.
3. Runtime files/config не попадают в git diff worktree.
4. Manifest/audit содержит факт включения/выключения.
5. Subagent/task launch получает тот же system time context, если он идёт через GRACE-managed OpenCode run.

Обязательные regression tests:

1. В system context не появляется текущая дата.
2. User prompt не модифицируется ради добавления времени.
3. Фича работает одинаково для разных пользователей системы, если они запускают пакеты через общий GRACE Orchestrator.

## Acceptance criteria

Фича считается готовой, если:

- есть централизованный флаг включения/выключения;
- включение не требует ручной настройки локального OpenCode профиля пользователя;
- все GRACE-managed OpenCode runs получают time context при включённой фиче;
- при выключенной фиче time context нигде не появляется;
- в prompt/context добавляется время, но не дата;
- git status/diff пользовательского worktree не загрязняется runtime plugin/config файлами;
- есть unit и runner tests;
- есть manifest/audit запись;
- документация описывает ENV/config флаги и expected behavior.

## Предпочтительный план реализации

1. Найти единую точку запуска OpenCode в GRACE Orchestrator.
2. Добавить config model для `opencode.agent_time_context`.
3. Добавить resolver ENV/config/defaults.
4. Добавить builder для runtime time block.
5. Реализовать managed injection в OpenCode system context через plugin/config/wrapper.
6. Добавить fake-clock tests.
7. Добавить runner tests на включение/выключение.
8. Добавить audit/manifest запись.
9. Проверить, что root worktree остаётся чистым после запуска.

## Не входит в задачу

- Добавление даты.
- Изменение UI OpenCode.
- Изменение истории сообщений пользователя.
- Глобальная модификация пользовательского `~/.config/opencode`.
- Патч OpenCode core, если задачу можно решить на стороне GRACE Orchestrator.
- Решение проблемы `plan.json`; это отдельная runtime-scratch задача.
