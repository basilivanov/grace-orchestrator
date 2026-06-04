# Review: TZ-024 — Orchestrator Observability & Logging (commit f71f43a)

Review of commit `f71f43a` against `docs/codex/tz-024-orchestrator-observability-logging.md`.

Date: 2026-06-04

---

## Summary

| Metric | Value |
|--------|-------|
| Files changed | 7 (280 lines) |
| New files | `cli/trace.py` (128 lines) |
| Components logged | 5/5 |
| Test regressions | 0 |
| New CLI tool | `grace trace` |

---

## Section-by-section check

### §2.2 acceptance_pipeline — ✅

| Log | Location | Fields |
|-----|----------|--------|
| `t0_command_failed` | `acceptance_pipeline.py:245` | command, exit_code, stderr[:500] |
| `t1_command_failed` | `acceptance_pipeline.py:286` | command, exit_code, stderr[:500] |
| `t2_command_failed` | `acceptance_pipeline.py:317` | command, exit_code, stderr[:500] |

Все три записывают `blocking_issues` с `exit_code + stderr[:200] + stdout[:200]`.

### §2.3 feature_recovery — ✅

| Log | Location | Fields |
|-----|----------|--------|
| `classify_failure` | `feature_recovery.py:113` | failure_class, reason, packet_state, ev_verdict, rv_verdict, merge_error |
| `decide_recovery` | `feature_recovery.py:338` | action, failure_class, reason, next_executor_hint, coder_attempt_count, max_attempts_reached |

Оба лога записывают полный контекст решения: что было на входе + что на выходе.

### §2.4 recovery_controller — ✅

| Log | Type | Покрытие |
|-----|------|----------|
| `evaluate_start` | начало evaluate | packet_id, allow_apply, trace_id |
| `build_signal` | сбор сигнала | runs_count, coder_attempts, executor_ids |
| `recovery_decision_applied` | решение применено | action, failure_class, reason, next_executor_hint |
| 5 × `apply_*_start` | до аппли | packet_id |
| 5 × `apply_*_done` | после аппли | packet_id, new_state |
| 5 × `apply_*_skip` | пропуск (пакет не найден) | packet_id, reason |

**15 лог-записей для 5 recovery-действий.**

### §2.5 worker — ✅

| Log | Location | Fields |
|-----|----------|--------|
| `recovery_check` | `worker.py:167` | packet_id, controller_enabled |
| `recovery_applied` | `worker.py:180` | packet_id, action, reason |

### §2.6 packet_executor — ✅

| Log | Location | Fields |
|-----|----------|--------|
| `execution_rejected` | `packet_executor.py:1011` | verdict, summary, stages, evidence_issues, scope_violations |

### §2.7 trace_id propagation — ✅

- `get_trace_id()` импортирован в `recovery_controller.py:26`
- `evaluate()` принимает параметр `trace_id` (строка 37)
- `evaluate_start` лог включает `trace_id` (строка 41)

### §3 CLI trace tool — ✅

| Флаг | Код | TZ-024 match |
|------|-----|-------------|
| `--packet` | `collect_events()` + `collect_packet_runs()` | ✅ |
| `--feature` | `collect_events()` | ✅ |
| `--wave` | `collect_events()` | ✅ |
| `--json` | `json.dumps(timeline)` | ✅ |
| `--full` | включает acceptance + verifier reports | ✅ |

---

## Пример вывода `grace trace`

```text
$ grace trace --packet pkt_xxx

Timeline for: pkt_xxx
============================================================
2026-06-04T14:22:09  packet_claimed
2026-06-04T14:22:09  execution_started
2026-06-04T14:22:40  execution_rejected     verdict=rework_required  summary=T1 failed
2026-06-04T14:22:40  classify_failure       RETRYABLE_CODER  reason="T1 failed: exit=4"
2026-06-04T14:22:40  decide_recovery        RETRY_SAME_CODER  reason="odd attempt, retry same coder"
2026-06-04T14:22:40  recovery_check         controller_enabled=true
2026-06-04T14:22:40  recovery_applied       RETRY_SAME_CODER  reason="odd attempt, retry same coder"
2026-06-04T14:23:10  execution_rejected     verdict=rework_required  summary=T1 failed
2026-06-04T14:23:10  classify_failure       RETRYABLE_CODER  reason="T1 failed: exit=4"
2026-06-04T14:23:10  decide_recovery        SWITCH_CODER  reason="coder failed 2x, switching"
2026-06-04T14:23:10  recovery_check         controller_enabled=true
2026-06-04T14:23:10  recovery_applied       SWITCH_CODER  next=coder-gemini-flash

  Run 1: rejected (30600ms)
    acceptance: rework_required
      T0_SCOPE_AND_LINT: passed
      T1_TARGETED_TESTS: failed
        BLOCKER: command failed: python3 -m pytest test_tz019_acceptance.py -q (exit=4)
    verifier: REWORK_TO_CODER — odd attempt skips verifier per ladder
    recovery: RETRY_SAME_CODER — odd attempt, retry same coder

  Run 2: blocked (24000ms)
    acceptance: rework_required
      T1: failed
        BLOCKER: command failed: python3 -m pytest test_tz019_acceptance.py -q (exit=4)
    verifier: REWORK_TO_CODER — deterministic acceptance failed
    recovery: SWITCH_CODER — from deepseek-flash to gemini-flash
```

---

## Issues

| # | Severity | Issue |
|---|----------|-------|
| 1 | 🟢 Low | Merge git push success — `_log.debug` вместо `INFO` + `record_event` |
| 2 | 🟢 Low | `test_evaluate_crash_is_safe` — pre-existing `mocker` bug, не от TZ-024 |
| 3 | 🟢 Low | Не все `record_event` пишут `trace_id` в DB колонку (пишут в JSON payload) |

---

## File inventory

| Файл | Строк | Что |
|------|-------|-----|
| `acceptance_pipeline.py` | +28 | t0/t1/t2 command_failed | 
| `feature_recovery.py` | +30 | classify_failure + decide_recovery | 
| `recovery_controller.py` | +58 | build_signal + evaluate + 7 × apply_* |
| `packet_executor.py` | +12 | execution_rejected |
| `worker.py` | +36/-18 | recovery_check + recovery_applied |
| `cli/trace.py` | +128 | **NEW** — audit CLI tool |
| `cli/main.py` | +6 | trace command integration |
| **Total** | **280** | **7 files** |

---

## Verdict

**95/100 — Все 5 компонентов + CLI trace tool + trace_id propagation. Полное соответствие TZ-024 §§2-3.**

Logging covers:
- classify/decide decisions with reason ✅
- T0/T1/T2 failures with exit_code + stderr ✅
- Recovery flow with action + reason ✅
- build_signal with counters + executor_ids ✅
- 7 apply_* methods (start/skip/done) ✅
- execution_rejected with verdict + stages ✅
- worker recovery check + applied ✅
- trace_id propagation through evaluate() ✅
- `grace trace` CLI with --packet/--feature/--wave/--json/--full ✅
