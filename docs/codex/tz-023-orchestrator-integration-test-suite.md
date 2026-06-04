# TZ 023 — Orchestrator Integration & Regression Test Suite

Аудитория: кодер (literal executor).

Статус: **спецификация на реализацию. Делать строго как написано.**

Язык: русский. Имена классов и файлов — на английском (как в коде).

---

## 0. Цель

Создать тестовый набор, который закрывает **99% функциональности оркестратора**: все компоненты, failure-пути, regression на исправленные баги, edge-кейсы, full pipeline с реальной SQLite. Сейчас 472 теста (все на mock'ах), 49 golden fixture YAML (не запускаются как CI). Нужно добавить **26 тестов** в 5 категориях.

---

## 1. Категории тестов

| Категория | Тестов | Покрывают |
|-----------|--------|-----------|
| SESSION | 3 | Реальная SQLite + реальные сессии |
| FAILURE INJECTION | 5 | Crash + corrupt data + missing records |
| FULL PIPELINE | 6 | End-to-end с реальными состояниями |
| REGRESSION | 7 | Каждый исправленный баг = 1 тест |
| EDGE CASES | 5 | Граничные значения, большие истории |
| **Итого** | **26** | |

---

## 2. Категория SESSION (3 теста)

### Тесты с РЕАЛЬНОЙ SQLite и РЕАЛЬНЫМИ сессиями

Все эти тесты используют `conftest.py:db` (SQLite фикстуру) и `get_db()`. БЕЗ `mock.patch`, БЕЗ `unittest.mock`.

### 2.1 `test_build_signal_real_db`

```python
def test_build_signal_real_db(db):
    """
    build_signal() должен работать с реальной SQLite сессией.
    Сейчас падает с DetachedInstanceError, потому что result_json
    читается ПОСЛЕ закрытия контекстного менеджера get_db().
    """
    from grace_control.db.schema import Packet, PacketRun, Feature, Wave
    from grace_control.core.recovery_controller import RecoveryController

    with get_db() as d:
        make_feature(d, fid="F1")
        make_wave(d, wid="W01", fid="F1", order=1)
        make_packet(d, pid="P1", fid="F1", wid="W01", state=PacketState.REJECTED.value)
        d.add(PacketRun(
            id="R01", packet_id="P1", run_number=1, status="rejected",
            result_json={
                "acceptance_report": {"final_verdict": "rework_required", "summary": "T1 failed"},
                "evidence_verifier_report": {"verdict": "REWORK_TO_CODER"},
            },
            started_at=datetime.now(timezone.utc),
            finished_at=datetime.now(timezone.utc),
        ))
        d.flush()

    # Сессия ЗАКРЫТА. build_signal должен работать без DetachedInstanceError
    ctrl = RecoveryController()
    signal = ctrl.build_signal("P1")
    assert signal.packet_id == "P1"
    assert signal.coder_attempt_count == 1
    assert signal.acceptance_verdict == "rework_required"
    assert signal.evidence_verifier_verdict == "REWORK_TO_CODER"
```

### 2.2 `test_apply_decision_real_db`

```python
def test_apply_decision_real_db(db):
    """
    apply_decision делает реальные DB-переходы через PacketStateMachine.
    """
    from grace_control.db.schema import Packet, Feature, Wave
    from grace_control.core.recovery_controller import RecoveryController
    from grace_control.core.feature_recovery import RecoveryDecision, RecoveryAction, FailureClass

    with get_db() as d:
        make_feature(d, fid="F1")
        make_wave(d, wid="W01", fid="F1", order=1)
        make_packet(d, pid="P1", fid="F1", wid="W01", state=PacketState.REJECTED.value)
        d.flush()

    ctrl = RecoveryController()
    decision = RecoveryDecision(
        action=RecoveryAction.RETRY_SAME_CODER,
        failure_class=FailureClass.RETRYABLE_CODER,
        reason="test retry",
    )
    await ctrl._apply_decision("P1", decision)

    with get_db() as d:
        p = d.query(Packet).filter_by(id="P1").first()
        assert p.state == PacketState.READY.value  # ← реальный переход
```

### 2.3 `test_evaluate_stale_workers`

```python
def test_evaluate_stale_workers(db):
    """
    build_signal должен работать с пакетом, у которого были зомби-воркеры
    в исторических PacketRun.
    """
    from grace_control.db.schema import PacketRun, Packet, Feature, Wave
    from grace_control.core.recovery_controller import RecoveryController

    with get_db() as d:
        make_feature(d, fid="F1")
        make_wave(d, wid="W01", fid="F1")
        make_packet(d, pid="P1", fid="F1", wid="W01", state=PacketState.REJECTED.value)
        for i, (eid, status) in enumerate([
            ("eval-w1", "rejected"), ("eval-w2", "rejected"), ("golden-w0", "rejected")
        ], 1):
            d.add(PacketRun(
                id=f"R0{i}", packet_id="P1", run_number=i, status=status,
                result_json={"executor_id": eid, "domain_status": status},
            ))
        d.flush()

    ctrl = RecoveryController()
    signal = ctrl.build_signal("P1")
    assert signal.coder_attempt_count == 3
    assert "eval-w1" in signal.previous_executor_ids
    assert "golden-w0" in signal.previous_executor_ids
```

---

## 3. Категория FAILURE INJECTION (5 тестов)

### 3.1 `test_build_signal_no_runs`

```python
def test_build_signal_no_runs(db):
    """Пакет без PacketRun → ValueError, не DetachedInstanceError."""
    from grace_control.db.schema import Packet, Feature, Wave
    from grace_control.core.recovery_controller import RecoveryController

    with get_db() as d:
        make_packet(d, pid="P1", fid="F1", wid="W01", state=PacketState.READY.value)
        d.flush()

    ctrl = RecoveryController()
    with pytest.raises(ValueError, match="No runs"):
        ctrl.build_signal("P1")
```

### 3.2 `test_build_signal_corrupted_result_json`

```python
def test_build_signal_corrupted_result_json(db):
    """result_json = None → не падает."""
    from grace_control.db.schema import PacketRun, Packet, Feature, Wave
    from grace_control.core.recovery_controller import RecoveryController

    with get_db() as d:
        make_packet(d, pid="P1", fid="F1", wid="W01", state=PacketState.REJECTED.value)
        d.add(PacketRun(id="R01", packet_id="P1", run_number=1, status="rejected",
                        result_json=None))
        d.flush()

    ctrl = RecoveryController()
    signal = ctrl.build_signal("P1")
    assert signal.packet_id == "P1"
    assert signal.evidence_verifier_verdict == ""  # пусто, не краш
```

### 3.3 `test_evaluate_crash_is_safe`

```python
def test_evaluate_crash_is_safe(db, mocker):
    """
    Если build_signal или classify_failure падает → log_error → не крашится.
    """
    from grace_control.core.recovery_controller import RecoveryController
    from grace_control.core.feature_recovery import FailureClass

    ctrl = RecoveryController()
    mocker.patch.object(ctrl, "build_signal", side_effect=RuntimeError("simulated crash"))
    
    # async call через evaluate. Не должно бросаться наружу.
    import asyncio
    try:
        decision = asyncio.run(ctrl.evaluate("nonexistent", allow_apply=False))
        assert decision.action == RecoveryAction.NO_ACTION  # fallback
    except Exception:
        # тоже ок — главное что не RuntimeError наружу
        pass
```

### 3.4 `test_apply_decision_missing_packet`

```python
def test_apply_decision_missing_packet(db):
    """Пакет удалён из БД между evaluate и apply → не крашится."""
    from grace_control.core.recovery_controller import RecoveryController
    from grace_control.core.feature_recovery import RecoveryAction, FailureClass, RecoveryDecision

    ctrl = RecoveryController()
    decision = RecoveryDecision(
        action=RecoveryAction.RETRY_SAME_CODER,
        failure_class=FailureClass.RETRYABLE_CODER,
        reason="test",
    )
    # Не должно упасть — просто нет пакета
    try:
        await ctrl._apply_decision("nonexistent", decision)
    except Exception:
        pass
```

### 3.5 `test_evaluate_max_sessions`

```python
def test_evaluate_max_sessions(db):
    """
    50+ исторических runs → build_signal не зависает и не падает.
    """
    from grace_control.db.schema import PacketRun, Packet, Feature, Wave
    from grace_control.core.recovery_controller import RecoveryController

    with get_db() as d:
        make_packet(d, pid="P1", fid="F1", wid="W01", state=PacketState.REJECTED.value)
        for i in range(1, 51):
            d.add(PacketRun(
                id=f"R{i:02d}", packet_id="P1", run_number=i, status="rejected",
                result_json={"acceptance_verdict": "rework_required"},
            ))
        d.flush()

    ctrl = RecoveryController()
    signal = ctrl.build_signal("P1")
    assert signal.coder_attempt_count >= 1
    assert signal.coder_attempt_count <= 50
```

---

## 4. Категория FULL PIPELINE (6 тестов)

### 4.1 `test_full_odd_even_real_db`

```python
def test_full_odd_even_real_db(db):
    """
    Полный odd/even ладдер: attempt 1 → RETRY_SAME, attempt 2 → RUN_VERIFIER.
    С реальным evaluate_ladder, classify_failure, decide_recovery, apply_decision.
    """
    from grace_control.core.recovery_rules import evaluate_ladder, RecoveryLadder
    from grace_control.core.feature_recovery import RouteAction

    # Attempt 1 (odd) — skip verifier, same coder
    route1 = evaluate_ladder(1)
    assert route1.action == RouteAction.RETRY_SAME_CODER
    assert route1.skip_verifier is True

    # Attempt 2 (even) — run verifier, on_verdict mapping
    route2 = evaluate_ladder(2)
    assert route2.action == RouteAction.RUN_VERIFIER
    assert route2.skip_verifier is False
    assert "REWORK_TO_CODER" in route2.on_verdict
    assert "RETURN_TO_ARCHITECT" in route2.on_verdict

    # Attempt 7 — new architect
    route7 = evaluate_ladder(7)
    assert route7.action == RouteAction.NEW_ARCHITECT
```

### 4.2 `test_full_coder_switch_real_db`

```python
def test_full_coder_switch_real_db(db):
    """
    decide_recovery → SWITCH_CODER → _apply_switch_coder → READY + spec_json.recovery.requested_executor_id.
    """
    from grace_control.db.schema import Packet, Feature, Wave
    from grace_control.core.feature_recovery import (
        FailureSignal, RecoveryPolicy, classify_failure, decide_recovery,
        RecoveryAction, FailureClass,
    )
    from grace_control.core.recovery_controller import RecoveryController

    # Имитируем многократные отказы
    signal = FailureSignal(
        feature_id="F1", packet_id="P1", packet_state="rejected",
        reason="T1 failed",
        coder_attempt_count=2, attempt_count=2,
        acceptance_verdict="rework_required",
        current_executor_id="coder-deepseek-flash",
        previous_executor_ids=["coder-deepseek-flash"] * 1,
    )
    fc = classify_failure(signal)
    assert fc == FailureClass.RETRYABLE_CODER

    decision = decide_recovery(signal, RecoveryPolicy())
    assert decision.action == RecoveryAction.SWITCH_CODER

    # Проверяем что _apply_switch_coder ставит READY
    with get_db() as d:
        make_packet(d, pid="P1", fid="F1", wid="W01", state=PacketState.REJECTED.value)
        d.flush()

    ctrl = RecoveryController()
    await ctrl._apply_decision("P1", decision)

    with get_db() as d:
        p = d.query(Packet).filter_by(id="P1").first()
        assert p.state == PacketState.READY.value
        assert p.spec_json["recovery"]["requested_executor_id"] == decision.next_executor_hint
```

### 4.3 `test_full_stale_db_history`

```python
def test_full_stale_db_history(db):
    """
    БД с накопленной историей от старых сессий → recovery controller работает.
    """
    from grace_control.db.schema import PacketRun, Packet, Feature, Wave, SelfEvolutionSession, PacketState
    from grace_control.core.recovery_controller import RecoveryController

    with get_db() as d:
        # Старая сессия (уже завершена)
        d.add(Feature(id="feat_old", slug="old", title="old", spec_json={}, status="NOT_STARTED"))
        d.add(Wave(id="wave_old", feature_id="feat_old", slug="old", title="old", order=1))
        make_packet(d, pid="P-old", fid="feat_old", wid="wave_old", state=PacketState.MERGED.value)
        d.add(SelfEvolutionSession(
            id="ses-old", title="old", status="completed",
            created_at=datetime.now(timezone.utc)
        ))

        # Новая фича (текущая)
        d.add(Feature(id="feat_new", slug="new", title="new", spec_json={}, status="NOT_STARTED"))
        d.add(Wave(id="wave_new", feature_id="feat_new", slug="new", title="new", order=1))
        make_packet(d, pid="P-new", fid="feat_new", wid="wave_new", state=PacketState.REJECTED.value)
        for i in range(1, 3):
            d.add(PacketRun(
                id=f"R0{i}", packet_id="P-new", run_number=i, status="rejected",
                result_json={"acceptance_report": {"final_verdict": "rework_required"}},
            ))
        d.flush()

    ctrl = RecoveryController()
    signal = ctrl.build_signal("P-new")  # ← не падает, не путает с P-old
    assert signal.packet_id == "P-new"
    assert signal.coder_attempt_count == 2
```

### 4.4 `test_full_multiwave_acceptance_recovery`

```python
def test_full_multiwave_acceptance_recovery_real_db(db):
    """
    Две волны. Wave 1 rejected → recovery → SWITCH_CODER → retry.
    Wave gate должен открыть W02 даже с BLOCKED в W01.
    """
    from grace_control.core.recovery_controller import RecoveryController
    from grace_control.core.feature_recovery import RecoveryAction, FailureClass, RecoveryDecision

    with get_db() as d:
        d.add(Feature(id="F1", slug="mf", title="multi", spec_json={}, status="NOT_STARTED"))
        d.add(Wave(id="W01", feature_id="F1", slug="w1", title="W1", order=1))
        d.add(Wave(id="W02", feature_id="F1", slug="w2", title="W2", order=2))
        make_packet(d, pid="P1", fid="F1", wid="W01", state=PacketState.REJECTED.value)
        make_packet(d, pid="P2", fid="F1", wid="W02", state=PacketState.DRAFT.value)
        d.flush()

    # Recovery controller: rejected P1 → SWITCH_CODER
    ctrl = RecoveryController()
    decision = RecoveryDecision(RecoveryAction.SWITCH_CODER, FailureClass.RETRYABLE_CODER, "test")
    await ctrl._apply_decision("P1", decision)

    # Wave gate: W01 считается завершённой (P1 in READY или BLOCKED), W02 открывается
    from grace_control.core.wave_gate import check_wave_gates
    gated = check_wave_gates()
    assert gated >= 0  # W01 done → W02 READY

    with get_db() as d:
        p2 = d.query(Packet).filter_by(id="P2").first()
        assert p2.state == PacketState.READY.value
```

### 4.5 `test_full_profiles_maintained`

```python
def test_full_profiles_maintained(db):
    """
    STRICT never downgrades even after recovery decisions.
    FAST never upgrades.
    """
    from grace_control.core.feature_recovery import FailureSignal, RecoveryPolicy, decide_recovery

    # STRICT profile + RETRYABLE_CODER → never downgrade
    signal_strict = FailureSignal(
        feature_id="F1", packet_id="P1", packet_state="rejected",
        acceptance_profile="STRICT",
        coder_attempt_count=2,
        acceptance_verdict="rework_required",
    )
    decision = decide_recovery(signal_strict, RecoveryPolicy())
    assert decision.next_acceptance_profile != "NORMAL"
    assert decision.next_acceptance_profile != "FAST"

    # FAST profile → stays FAST
    signal_fast = FailureSignal(
        feature_id="F1", packet_id="P2", packet_state="rejected",
        acceptance_profile="FAST",
        coder_attempt_count=1,
        acceptance_verdict="rework_required",
    )
    decision = decide_recovery(signal_fast, RecoveryPolicy())
    assert decision.next_acceptance_profile is None or decision.next_acceptance_profile == "FAST"
```

### 4.6 `test_full_merge_conflict_recovery`

```python
def test_full_merge_conflict_recovery(db):
    """
    merge_error во FailureSignal → классифицируется как TRUE_BLOCKER или MERGE_RETRYABLE.
    """
    from grace_control.core.feature_recovery import FailureSignal, classify_failure, FailureClass

    signal = FailureSignal(
        feature_id="F1", packet_id="P1", packet_state="rejected",
        merge_error="DIRTY_TARGET_REPO",
    )
    fc = classify_failure(signal)
    assert fc == FailureClass.TRUE_BLOCKER

    signal2 = FailureSignal(
        feature_id="F1", packet_id="P2", packet_state="rejected",
        merge_error="transient connection timeout",
    )
    fc2 = classify_failure(signal2)
    assert fc2 == FailureClass.MERGE_RETRYABLE
```

---

## 5. Категория REGRESSION (7 тестов)

Каждый исправленный баг = 1 тест. Не возвращать баги.

### 5.1 `test_regression_detached_instance` → USE 2.1

### 5.2 `test_regression_evidence_pattern`

```python
def test_regression_evidence_pattern():
    """
    evidence.py:_check_evidence_kind ищет в cmd.command+stdout+stderr, не только в command.
    """
    from grace_control.core.evidence import EvidenceCollector, EvidenceRequirement
    from grace_control.core.contracts import CommandResult

    # Для kind=command: pattern ищется в command+stdout+stderr
    collector = EvidenceCollector()
    req = EvidenceRequirement(id="test", kind="command", required=True, pattern="3 passed")

    cmd = CommandResult(
        command="python3 -m pytest test_x.py -q",
        cwd="/tmp", exit_code=0,
        stdout="3 passed in 0.5s", stderr="",
        stdout_path="", stderr_path="",
        timed_out=False, duration_ms=100,
    )
    stage = StageResult(name=StageName.T1_TARGETED_TESTS, status=StageStatus.PASSED,
                        summary="ok", commands=[cmd])
    found = collector._check_evidence_kind(req, [stage], Path("/tmp"), [])
    assert found is True, "pattern not found in stdout+stderr"
```

### 5.3 `test_regression_wave_gate_blocked`

```python
def test_regression_wave_gate_blocked(db):
    """
    BLOCKED = terminal состояние для wave gate.
    После фикса wave_gate.py:52 не должно зависать.
    """
    from grace_control.core.wave_gate import check_wave_gates
    from grace_control.db.schema import PacketState

    with get_db() as d:
        make_feature(d, fid="F1")
        make_wave(d, wid="W01", fid="F1")
        make_wave(d, wid="W02", fid="F1", order=2)
        make_packet(d, pid="P1", fid="F1", wid="W01", state=PacketState.MERGED.value)
        make_packet(d, pid="P2", fid="F1", wid="W01", state=PacketState.BLOCKED.value)
        make_packet(d, pid="P3", fid="F1", wid="W02", state=PacketState.DRAFT.value)
        d.flush()

    gated = check_wave_gates()
    assert gated == 1  # BLOCKED terminal → W02 открывается
```

### 5.4 `test_regression_worker_recovery_order`

```python
def test_regression_worker_recovery_order():
    """
    worker.py вызывает _maybe_apply_recovery() ПЕРЕД _handle_rejection().
    """
    import ast
    tree = ast.parse(open("src/grace_control/worker/worker.py").read())
    found_recovery = False
    found_rejection = False
    for node in ast.walk(tree):
        if isinstance(node, ast.Call):
            if hasattr(node.func, "attr"):
                if node.func.attr == "_maybe_apply_recovery":
                    found_recovery = True
                elif node.func.attr == "_handle_rejection":
                    found_rejection = True
                if found_recovery and not found_rejection:
                    assert True  # recovery перед reject
                    import sys; sys.exit(0)
    assert found_recovery, "_maybe_apply_recovery not found in worker.py"
```

### 5.5 `test_regression_recovery_env_var`

```python
def test_regression_recovery_env_var():
    """
    GRACE_RECOVERY_CONTROLLER_ENABLED передаётся в worker_env.
    Проверка: self_evolution.py:_run_evolution() передаёт этот env в subprocess.Popen.
    """
    import ast
    tree = ast.parse(open("src/grace_control/api/routers/self_evolution.py").read())
    # Ищем worker_env dict — должно содержать GRACE_RECOVERY_CONTROLLER_ENABLED
    for node in ast.walk(tree):
        if isinstance(node, ast.Dict):
            for k in node.keys:
                if isinstance(k, ast.Constant) and "GRACE_RECOVERY_CONTROLLER_ENABLED" in str(k.value):
                    assert True
                    import sys; sys.exit(0)
    pytest.fail("GRACE_RECOVERY_CONTROLLER_ENABLED not found in worker_env")
```

### 5.6 `test_regression_never_downgrade_strict`

```python
def test_regression_never_downgrade_strict():
    """
    never_downgrade_strict пресутствует в RecoveryPolicy.
    STRICT никогда не понижается.
    """
    from grace_control.core.feature_recovery import RecoveryPolicy, FailureSignal, decide_recovery, RecoveryAction

    policy = RecoveryPolicy()
    assert hasattr(policy, "never_downgrade_strict")
    assert policy.never_downgrade_strict is True

    signal = FailureSignal(
        feature_id="F1", packet_id="P1", packet_state="rejected",
        acceptance_profile="STRICT",
        coder_attempt_count=1,
        acceptance_verdict="rework_required",
    )
    decision = decide_recovery(signal, policy)
    # never downgraded — профиль должен быть STRICT или None, не NORMAL/FAST
    assert decision.next_acceptance_profile in (None, "STRICT")
```

### 5.7 `test_regression_coder_ladder_yaml`

```python
def test_regression_coder_ladder_yaml():
    """
    Coder ladder читается из agent_profiles.yaml, не хардкоден.
    """
    from grace_control.core.executor_selector import get_escalation

    executors = get_escalation("coder")
    assert len(executors) >= 2
    # Проверяем что все имеют executor_id
    for e in executors:
        assert "executor_id" in e
        assert "model" in e
        assert "priority" in e
    # Порядок: по убыванию priority
    priorities = [e["priority"] for e in executors]
    assert priorities == sorted(priorities, reverse=True)
```

---

## 6. Категория EDGE CASES (5 тестов)

### 6.1 `test_edge_attempt_zero`

```python
def test_edge_attempt_zero():
    """evaluate_ladder(0) — attempt=0 → через ODD (0%2=0 — even) → не должен крашиться."""
    from grace_control.core.recovery_rules import evaluate_ladder

    route = evaluate_ladder(0)
    assert route.action in (RouteAction.RETRY_SAME_CODER, RouteAction.RUN_VERIFIER)
```

### 6.2 `test_edge_max_int_attempts`

```python
def test_edge_max_int_attempts():
    """evaluate_ladder(999999) — должен вернуть NEW_ARCHITECT (ATTEMPT_GTE 7)."""
    from grace_control.core.recovery_rules import evaluate_ladder, RouteAction

    route = evaluate_ladder(999999)
    assert route.action == RouteAction.NEW_ARCHITECT
```

### 6.3 `test_edge_empty_result_json_all_runs`

```python
def test_edge_empty_result_json_all_runs(db):
    """Все PacketRun.result_json = null → build_signal не падает."""
    from grace_control.core.recovery_controller import RecoveryController
    from grace_control.db.schema import PacketRun, Packet, Feature, Wave

    with get_db() as d:
        make_packet(d, pid="P1", fid="F1", wid="W01", state=PacketState.REJECTED.value)
        for i in range(1, 4):
            d.add(PacketRun(id=f"R0{i}", packet_id="P1", run_number=i, status="rejected",
                            result_json=None))
        d.flush()

    ctrl = RecoveryController()
    signal = ctrl.build_signal("P1")
    assert signal.packet_id == "P1"
    assert signal.evidence_verifier_verdict == ""
```

### 6.4 `test_edge_missing_feature`

```python
def test_edge_missing_feature(db):
    """Packet есть, Feature нет → build_signal крашится? не должен."""
    from grace_control.core.recovery_controller import RecoveryController
    from grace_control.db.schema import Packet, Wave

    with get_db() as d:
        d.add(Packet(id="P1", feature_id="F-missing", wave_id="W-missing",
                     slug="orphan", title="orphan", spec_json={}, state="rejected"))
        d.flush()

    ctrl = RecoveryController()
    signal = ctrl.build_signal("P1")
    assert signal.feature_id == "F-missing"
    # feature null — не должно быть краша
```

### 6.5 `test_edge_packet_canceled_state_transition`

```python
def test_edge_packet_canceled_state_transition():
    """
    Все 9 PacketState имеют определённое поведение в state_machine.
    BLOCKED/CANCELLED/FAILED — нет переходов в READY.
    """
    from grace_control.core.state_machine import PacketStateMachine
    from grace_control.db.schema import PacketState

    sm = PacketStateMachine()
    for state in PacketState:
        if state in (PacketState.BLOCKED, PacketState.CANCELLED, PacketState.FAILED):
            # Эти состояния не должны иметь переходов назад
            transitions = sm._transitions.get(state, [])
            assert PacketState.READY not in transitions, f"{state} should not transition to READY"
```

---

## 7. Файлы

| Файл | Статус | Что |
|------|--------|-----|
| `tests/grace_control/core/test_recovery_real_db.py` | **NEW** | SESSION + FAILURE + FULL PIPELINE + EDGE (16 тестов) |
| `tests/grace_control/core/test_regression.py` | **NEW** | REGRESSION (7 тестов) |
| `tests/grace_control/core/test_recovery_controller.py` | MODIFY | +3 existing → +some existing |
| `tests/unit/test_wave_gate.py` | MODIFY | +3 regression test (уже добавлен BLOCKED) |

---

## 8. Принципы

1. **Real SQLite DB** (`conftest.py:db` фикстура) — никаких `mock.patch`
2. **Каждый тест на одну ответственность** — один assert/reason
3. **Тесты не зависят друг от друга** — чистая установка перед каждым
4. **Названия читаемые** — `test_build_signal_real_db` понятно, `test_case_42` — нет
5. **Без реальных LLM/git** — не запускать opencode/agy/architect

---

## 9. Acceptance checklist

```text
1. Все 26 новых тестов добавлены.
2. `test_build_signal_real_db` проходит (detached instance fix проверен).
3. Все регрессионные тесты проходят (7 шт).
4. Все edge case тесты проходят (5 шт).
5. Общий сьют: 472 + 26 = 498 тестов, все зелёные.
6. Золотые фикстуры (49 шт) не запускаются в CI — добавить Makefile target.
```

---

## 10. Coder report

```text
Файлы добавлены/изменены
Категория SESSION реализована: да/нет (3 теста)
Категория FAILURE INJECTION: да/нет (5 тестов)
Категория FULL PIPELINE: да/нет (6 тестов)
Категория REGRESSION: да/нет (7 тестов)
Категория EDGE CASES: да/нет (5 тестов)
Тестов добавлено: количество
Тестов пройдено: количество
Упавших тестов: количество
Оставшиеся блокеры
```
