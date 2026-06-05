# TZ 024 — Orchestrator Observability: structured logging + trace audit tool

Аудитория: кодер (literal executor).

Статус: **спецификация на реализацию. Делать строго как написано.**

Язык: русский. Имена полей и классов — на английском (как в коде).

---

## 0. Цель

Каждое решение, каждый вызов, каждая причина отказа должны быть залогированы в структурированном формате с `trace_id`. Итоговый тул `grace trace` должен по одному packet/feature/wave ID показать хронологическую цепочку: что произошло, почему, кто принял решение, с какими данными. Причина должна прокидываться через весь pipeline — от T1 failure до recovery decision.

---

## 1. Текущее состояние

| Компонент | Логов | Проблема |
|-----------|-------|----------|
| `feature_recovery.py` | **0** | classify/decide решения не видны |
| `recovery_controller.py` | 3 | build_signal, apply_* не логируются |
| `worker.py` | 0 | recovery flow не отслеживается |
| `packet_executor.py` | 24 (DEBUG) | acceptance reject — только вердикт, без причины |
| `acceptance_pipeline.py` | 0 | T1 fail — нет stderr, exit_code, failed tests |
| `Event` table | 12 event types | recovery decisions хранятся, но без детального context |
| `trace_id` | только в worker | recovery controller не наследует |
| Аудит-тул | нет | Нельзя запросить историю пакета |

---

## 2. Реализация

### 2.1 Добавить GraceLogger в каждый файл

```python
from grace_control.core.structured_logger import GraceLogger, get_trace_id
_log = GraceLogger("component_name")
```

Каждый лог ВСЕГДА включает `trace_id` (из `get_trace_id()`), `packet_id`, `reason`.

### 2.2 `acceptance_pipeline.py` — причина T1/T0/T2 rejection

На строке ~263 где `if not c.passed`:

```python
if not c.passed:
    _log.info("t1_command_failed",
        packet_id=packet.packet_id,
        command=c.command[:200],
        exit_code=c.exit_code,
        stderr=c.stderr[:500],
        stdout=c.stdout[:500],
    )
```

На строке ~297 где строится `StageResult.FAILED` с `blocking_issues`:

```python
blocking_issues = [
    f"command failed: {c.command} (exit={c.exit_code}) stderr={c.stderr[:200]} stdout={c.stdout[:200]}"
    for c in failed
]
```

Аналогично для T0 и T2.

### 2.3 `feature_recovery.py` — логировать classify и decide

```python
# classify_failure() — на КАЖДЫЙ return
_log.info("classify_failure",
    packet_id=signal.packet_id,
    failure_class=fc.value,
    reason=signal.reason or "",
    packet_state=signal.packet_state,
    ev_verdict=signal.evidence_verifier_verdict or "",
    rv_verdict=signal.reviewer_verdict or "",
    merge_error=signal.merge_error or "",
)

# decide_recovery() — на КАЖДЫЙ return
_log.info("decide_recovery",
    packet_id=signal.packet_id,
    action=decision.action.value,
    failure_class=decision.failure_class.value,
    reason=decision.reason or "",
    next_executor_hint=decision.next_executor_hint or "",
    coder_attempt_count=signal.coder_attempt_count,
    max_attempts_reached=decision.max_attempts_reached,
)
```

### 2.4 `recovery_controller.py` — логировать build_signal, evaluate, apply_*

```python
# build_signal() — после сборки сигнала
_log.info("build_signal",
    packet_id=packet_id,
    runs_count=len(runs),
    coder_attempt_count=coder_count,
    executor_ids=executor_ids,
    verifier_rejects=verifier_reject,
    acceptance_verdict=acc.get("final_verdict", ""),
)

# evaluate() — после принятия решения
_log.info("recovery_decision_applied",
    packet_id=packet_id,
    action=decision.action.value,
    failure_class=decision.failure_class.value,
    reason=decision.reason or "",
    next_executor_hint=decision.next_executor_hint or "",
    allow_apply=allow_apply,
)

# Каждый apply_* метод — логировать ПЕРЕД и ПОСЛЕ
def _apply_switch_coder(self, packet_id: str, decision: RecoveryDecision):
    _log.info("apply_switch_coder_start", packet_id=packet_id,
        requested_executor=decision.next_executor_hint)
    # ... apply logic ...
    _log.info("apply_switch_coder_done", packet_id=packet_id,
        new_state=packet.state, requested_executor=decision.next_executor_hint)
```

### 2.5 `worker.py` — логировать recovery flow

```python
async def _maybe_apply_recovery(self, packet_id: str):
    controller_enabled = os.environ.get("GRACE_RECOVERY_CONTROLLER_ENABLED", "false") == "true"
    _log.info("recovery_check",
        packet_id=packet_id,
        controller_enabled=controller_enabled,
    )
    if not controller_enabled:
        return
    try:
        decision = await asyncio.wait_for(
            ctrl.evaluate(packet_id, allow_apply=True),
            timeout=30,
        )
        _log.info("recovery_applied",
            packet_id=packet_id,
            action=decision.action.value,
            reason=decision.reason,
        )
    except Exception as e:
        _log.error("recovery_apply_failed",
            packet_id=packet_id,
            error=str(e)[:500],
        )
```

### 2.6 `packet_executor.py` — причина rejection

На строчках где `ExecutionResult(accepted=False, ...)`:

```python
acceptance_summary = accept_report.summary
acceptance_verdict = accept_report.final_verdict.value
_log.info("execution_rejected",
    packet_id=packet_id,
    verdict=acceptance_verdict,
    summary=acceptance_summary,
    stages=[s.name.value for s in accept_report.stages],
    evidence_issues=accept_report.evidence_issues,
    scope_violations=accept_report.scope_violations,
)
```

### 2.8 `packets.py` — merge endpoint logging

Уже есть (дополнить причиной):

```python
# _log.info("packet_merged") + record_event("packet_merged") — уже есть
# Добавить: reason propagation при merge_failed

_log.info("merge_failed",
    packet_id=packet.id,
    branch=branch_name,
    worktree=worktree_path,
    stderr=merge_stderr[:500],
    target_repo=str(repo),
    dirty_repo=(not allow_dirty),
)
```

И при git push failure (я добавил `git push` в packets.py):

```python
_log.warn("merge_push_failed",
    packet_id=packet.id,
    stderr=pr.stderr[:200],
    target_repo=str(repo),
)
```

Добавить в `_maybe_apply_recovery`:

```python
from grace_control.core.structured_logger import get_trace_id
trace_id = get_trace_id()
# прокинуть через evaluate → build_signal → classify → decide → apply
```

И в `recovery_controller.evaluate()`:

```python
async def evaluate(self, packet_id, allow_apply=False, trace_id=None):
    _log.info("evaluate_start",
        packet_id=packet_id,
        allow_apply=allow_apply,
        trace_id=trace_id,
    )
    ...
```

---

## 3. Audit-тул: `grace trace`

### 3.1 CLI

```bash
# По пакету
grace trace --packet pkt_xxx
# → timeline всех событий + решений

# По фиче
grace trace --feature feat_yyy
# → timeline всех пакетов в фиче

# По желе
grace trace --wave wave_zzz
# → пакеты в этой волне

# JSON output
grace trace --packet pkt_xxx --json
# → машинно-читаемый формат

# Полный context (recovery solution, verifier output)
grace trace --packet pkt_xxx --full
# → + acceptance_reports, verifier_verdicts, changed_files
```

### 3.2 Реализация

**Новый файл:** `src/grace_control/cli/trace.py`

```python
@cli.command("trace")
@click.option("--packet", "packet_id", default=None)
@click.option("--feature", "feature_id", default=None)
@click.option("--wave", "wave_id", default=None)
@click.option("--json", "json_out", is_flag=True)
@click.option("--full", "full_context", is_flag=True)
def trace(packet_id, feature_id, wave_id, json_out, full_context):
    """Show detailed execution timeline for a packet/feature/wave."""
    # 1. Query Event table by entity_id
    # 2. For each event, read PacketRun.result_json for context
    # 3. Sort chronologically
    # 4. Format: [timestamp] ROUND — stage — action — reason
    # 5. If --full: add acceptance_reports, verifier_outputs
```

**Функция в `trace.py`:**

```python
def collect_events(entity_id: str, db) -> list[dict]:
    """Collect all events for an entity from Event table."""
    events = db.query(Event).filter_by(
        entity_id=entity_id
    ).order_by(Event.timestamp).all()
    return [{
        "ts": e.timestamp.isoformat() + "Z" if e.timestamp else "",
        "event_type": e.event_type,
        "payload": e.payload_json or {},
        "trace_id": e.trace_id,
    } for e in events]


def collect_packet_runs(packet_id: str, db) -> list[dict]:
    """Collect PacketRun history for a packet."""
    from grace_control.db.schema import PacketRun
    runs = db.query(PacketRun).filter_by(
        packet_id=packet_id
    ).order_by(PacketRun.run_number).all()
    return [{
        "run_number": r.run_number,
        "status": r.status,
        "duration_ms": r.duration_ms,
        "result": r.result_json or {},
    } for r in runs]


def format_timeline(entity_id: str, db, full=False) -> str:
    """Build human-readable timeline."""
    events = collect_events(entity_id, db)
    runs = collect_packet_runs(entity_id, db)
    
    lines = [f"Timeline for: {entity_id}", "=" * 60]
    for ev in events:
        ts = ev["ts"][:19]
        etype = ev["event_type"]
        payload = ev["payload"]
        action = payload.get("action", "")
        reason = payload.get("reason", "")[:100]
        lines.append(f"{ts}  {etype:30s}  {action:25s}  {reason}")
    
    for run in runs:
        rj = run["result"]
        acc = rj.get("acceptance_report", {})
        ev = rj.get("evidence_verifier_report", {})
        lines.append(f"  Run {run['run_number']}: {run['status']} ({run['duration_ms']}ms)")
        if acc:
            lines.append(f"    acceptance: {acc.get('final_verdict', '?')}")
            for s in acc.get("stages", []):
                lines.append(f"      {s['name']}: {s['status']}")
                for bi in s.get("blocking_issues", []):
                    lines.append(f"        BLOCKER: {bi[:150]}")
            if acc.get("evidence_issues"):
                for ei in acc["evidence_issues"]:
                    lines.append(f"        EVIDENCE: {ei}")
        if ev:
            lines.append(f"    verifier: {ev.get('verdict', '?')} — {ev.get('summary', '')[:100]}")
        if rj.get("recovery"):
            rec = rj["recovery"]
            lines.append(f"    recovery: {rec.get('action', '?')} — {rec.get('reason', '')[:100]}")
    
    return "\n".join(lines)
```

### 3.3 CLI integration

В `src/grace_control/cli/main.py`:

```python
import trace as _trace

@cli.group()
def trace_cmd():
    """Trace commands."""

@trace_cmd.command("pkt")
@click.argument("packet_id")
@click.option("--full", is_flag=True)
def trace_packet(packet_id, full):
    ...
```

**Или проще:** `grace trace` как отдельный CLI без подкоманды.

### 3.4 Пример вывода

```text
$ grace trace --packet pkt_PWgwT5Y3I5

Timeline for: pkt_PWgwT5Y3I5
============================================================
2026-06-04T14:22:09  packet_claimed                  (worker: self-w0)
2026-06-04T14:22:09  execution_started               (coder: deepseek-flash, timeout: 600s)
2026-06-04T14:22:09  adapter_execute_start           (acceptance_profile: NORMAL)
2026-06-04T14:22:40  acceptance_completed            accepted=false verdict=rework_required
2026-06-04T14:22:40  ladder_evaluated                condition=ODD_ATTEMPT action=RETRY_SAME_CODER skip_verifier=true
2026-06-04T14:22:40  packet_released                 state=rejected
2026-06-04T14:22:40  recovery_classified             failure_class=RETRYABLE_CODER reason="T1 failed: test_tz019_acceptance.py exit=4"
2026-06-04T14:22:40  recovery_retry_same_coder       next_executor=coder-deepseek-flash

  Run 1: rejected (30600ms)
    acceptance: rework_required
      T0_SCOPE_AND_LINT: passed
      T1_TARGETED_TESTS: failed
        BLOCKER: command failed: python3 -m pytest tests/test_tz019_acceptance.py -q (exit=4)
    verifier: REWORK_TO_CODER — odd attempt skips verifier per ladder
    recovery: RETRY_SAME_CODER — odd attempt, retry same coder

2026-06-04T14:22:40  packet_claimed                  (worker: self-w0, attempt=2)
2026-06-04T14:22:40  execution_started               (coder: deepseek-flash, timeout: 600s)
2026-06-04T14:23:10  acceptance_completed            accepted=false verdict=rework_required
2026-06-04T14:23:10  ladder_evaluated                condition=EVEN_ATTEMPT action=RUN_VERIFIER skip_verifier=false
2026-06-04T14:23:25  evidence_verifier_completed     verdict=REWORK_TO_CODER
2026-06-04T14:23:25  packet_released                 state=blocked
2026-06-04T14:23:25  recovery_classified             failure_class=RETRYABLE_CODER reason="T1 failed: test_tz019_acceptance.py exit=4"
2026-06-04T14:23:25  recovery_switch_coder           from=coder-deepseek-flash to=coder-gemini-flash

  Run 2: blocked (24000ms)
    acceptance: rework_required
      T1_TARGETED_TESTS: failed
        BLOCKER: command failed: python3 -m pytest tests/test_tz019_acceptance.py -q (exit=4)
    verifier: REWORK_TO_CODER — deterministic acceptance failed
    recovery: SWITCH_CODER — coder failed 2x, switching from deepseek-flash to gemini-flash
```

---

## 4. Файлы

| Файл | Статус | Что |
|------|--------|-----|
| `src/grace_control/core/feature_recovery.py` | MODIFY | +2 _log.info в classify/decide |
| `src/grace_control/core/recovery_controller.py` | MODIFY | +1 _log в build_signal, +1 в evaluate, +7 в apply_* |
| `src/grace_control/adapters/packet_executor.py` | MODIFY | +1 _log.info с подробной причиной |
| `src/grace_control/core/acceptance_pipeline.py` | MODIFY | +1 _log.info с exit_code, stderr, failed tests |
| `src/grace_control/worker/worker.py` | MODIFY | +3 _log в _maybe_apply_recovery |
| `src/grace_control/cli/trace.py` | **NEW** | Аудит-тул |
| `src/grace_control/cli/main.py` | MODIFY | Интеграция trace команды |

---

## 5. Формат лога (GRACE Canon)

Каждый лог ВСЕГДА содержит:

```json
{
  "ts": "ISO-8601 UTC",
  "level": "INFO|WARN|ERROR|DEBUG",
  "component": "feature_recovery",
  "msg": "classify_failure",
  "trace_id": "pkt_xxx",
  "ctx": {
    "packet_id": "pkt_xxx",
    "reason": "..."      // ← ОБЯЗАТЕЛЬНО, детально
    // ... специфичные поля
  }
}
```

---

## 6. Acceptance criteria

```text
1. feature_recovery.py: classify_failure() логирует каждое решение (packet_id + failure_class + reason).
2. feature_recovery.py: decide_recovery() логирует каждое решение (action + reason + next_executor_hint).
3. recovery_controller.py: build_signal() логирует (runs_count + executor_ids + counters).
4. recovery_controller.py: evaluate() логирует (action + failure_class + trace_id).
5. recovery_controller.py: каждый apply_* логирует +-.
6. packet_executor.py: rejection логирует (verdict + summary + stages + evidence_issues).
7. acceptance_pipeline.py: T1/T0/T2 fail логирует (command + exit_code + stderr + stdout).
8. worker.py: _maybe_apply_recovery логирует (controller_enabled + action + reason).
9. trace_id propagates через recovery controller.
10. CLI: grace trace --packet pkt_xxx возвращает timeline + runs + acceptance + verifier.
11. CLI: grace trace --feature feat_yyy возвращает timeline всех пакетов фичи.
12. CLI: grace trace --json возвращает машинно-читаемый JSON.
13. Все существующие тесты проходят (логи — side effect, не ломают бизнес-логику).
```

---

## 7. What NOT to do

```text
- Не менять существующую бизнес-логику.
- Не добавлять логгирование в циклы (<10 итераций можно, >10 — только суммарный).
- Не делать логирование синхронным блокирующим — GraceLogger._emit уже async-safe.
- Не менять существующий Event table schema.
```
