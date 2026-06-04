# Escalation Policy — Phase 3: RecoveryController

Audience: Coder (literal executor).

Depends on: `phase-1-2-baseline.md` (must not break existing code).

---

## Goal

Wire the recovery policy into the orchestrator. When a packet is `rejected`, `blocked`, or `failed`, the controller:
1. Builds `FailureSignal` from the latest packet run
2. Calls `classify_failure()` / `decide_recovery()`
3. Persists `RecoveryDecision`
4. Emits recovery events
5. Applies safe actions (retry, switch coder, block, return to architect)
6. All behind `GRACE_RECOVERY_CONTROLLER_ENABLED=true` flag

---

## 1. New file: `src/grace_control/core/recovery_controller.py`

### 1.1 Class signature

```python
class RecoveryController:

    def __init__(self, project_root: Path | None = None):
        """Project root for DB access."""
        self._root = project_root or Path.cwd()
        self._enabled = os.environ.get("GRACE_RECOVERY_CONTROLLER_ENABLED", "false").lower() == "true"

    async def evaluate(self, packet_id: str, allow_apply: bool = False) -> RecoveryDecision:
        """Build FailureSignal → classify → decide → persist → apply."""
        ...
    
    def build_signal(self, packet_id: str) -> FailureSignal:
        """Build FailureSignal from latest PacketRun in DB."""
        ...
```

### 1.2 `build_signal(packet_id)` — exact implementation

```python
def build_signal(self, packet_id: str) -> FailureSignal:
    from grace_control.db import get_db
    from grace_control.db.schema import Packet, PacketRun

    with get_db() as db:
        packet = db.query(Packet).filter_by(id=packet_id).first()
        if not packet:
            raise ValueError(f"Packet not found: {packet_id}")

        runs = db.query(PacketRun).filter_by(packet_id=packet_id).order_by(
            PacketRun.run_number.desc()
        ).limit(10).all()

        if not runs:
            raise ValueError(f"No runs for packet: {packet_id}")

        latest = runs[0]
        result = latest.result_json or {}

    # Extract from result_json
    legacy = result.get("legacy_result", {})
    acc = result.get("acceptance_report", {})
    ev = result.get("evidence_verifier_report", {})
    rv = result.get("reviewer_report", {})

    # Count previous executor attempts
    executor_ids = []
    prev_ids = []
    coder_count = 0
    verifier_reject = 0
    reviewer_reject = 0
    merge_count = 0
    architect_repairs = 0

    for run in runs:
        r = run.result_json or {}
        exec_id = r.get("executor_id", "")
        if exec_id and exec_id not in executor_ids:
            executor_ids.append(exec_id)
        prev_ids.append(exec_id)
        if run.status in ("rejected", "failed"):
            coder_count += 1
        if "verifier" in (r.get("domain_status") or ""):
            verifier_reject += 1
        if "reviewer" in (r.get("domain_status") or ""):
            reviewer_reject += 1
        if "merge" in (r.get("domain_status") or ""):
            merge_count += 1
        if "architect" in (r.get("domain_status") or ""):
            architect_repairs += 1

    return FailureSignal(
        feature_id=packet.feature_id,
        packet_id=packet.id,
        packet_state=packet.state,
        domain_status=legacy.get("domain_status", ""),
        reason=result.get("reason", ""),
        acceptance_verdict=acc.get("final_verdict", ""),
        evidence_verifier_verdict=ev.get("verdict", ""),
        reviewer_verdict=rv.get("verdict", ""),
        merge_error=result.get("merge_error", ""),
        acceptance_profile=packet.acceptance_profile,
        attempt_count=packet.attempt_count,
        coder_attempt_count=coder_count,
        architect_repair_count=architect_repairs,
        verifier_reject_count=verifier_reject,
        reviewer_reject_count=reviewer_reject,
        merge_attempt_count=merge_count,
        current_executor_id=prev_ids[-1] if prev_ids else None,
        previous_executor_ids=prev_ids,
    )
```

### 1.3 `evaluate(packet_id, allow_apply)`

```python
async def evaluate(self, packet_id: str, allow_apply: bool = False) -> RecoveryDecision:
    signal = self.build_signal(packet_id)
    policy = RecoveryPolicy()
    fc = classify_failure(signal)
    decision = decide_recovery(signal, policy)

    # Persist decision
    db_decision_id = self._persist_decision(packet_id, decision, signal)

    # Emit events
    self._emit_recovery_events(packet_id, signal, decision)

    # Apply safe actions if enabled
    if allow_apply and self._enabled:
        await self._apply_decision(packet_id, decision)

    # Attach decision ID to response
    decision.audit_payload["decision_id"] = db_decision_id
    return decision
```

---

## 2. Apply actions: `_apply_decision(packet_id, decision)`

### 2.1 RETRY_SAME_CODER

```python
async def _apply_retry_same_coder(self, packet_id: str):
    from grace_control.db import get_db
    from grace_control.db.schema import Packet, PacketState

    with get_db() as db:
        packet = db.query(Packet).filter_by(id=packet_id).first()
        if not packet:
            return
        from grace_control.core.state_machine import StateMachine
        sm = StateMachine()
        sm.transition(PacketState(packet.state), PacketState.READY)
        packet.state = PacketState.READY.value
        # Keep same executor — do not set requested_executor
        db.flush()
```

### 2.2 SWITCH_CODER

```python
async def _apply_switch_coder(self, packet_id: str, decision: RecoveryDecision):
    from grace_control.db import get_db
    from grace_control.db.schema import Packet, PacketState

    with get_db() as db:
        packet = db.query(Packet).filter_by(id=packet_id).first()
        if not packet:
            return
        from grace_control.core.state_machine import StateMachine
        sm = StateMachine()
        sm.transition(PacketState(packet.state), PacketState.READY)
        packet.state = PacketState.READY.value

        # Store requested_executor for next worker claim
        spec = packet.spec_json or {}
        spec["recovery"] = {"requested_executor_id": decision.next_executor_hint}
        packet.spec_json = spec
        db.flush()
```

### 2.3 RETURN_TO_ARCHITECT

```python
async def _apply_return_to_architect(self, packet_id: str, decision: RecoveryDecision):
    from grace_control.db import get_db
    from grace_control.db.schema import Packet, PacketState

    with get_db() as db:
        packet = db.query(Packet).filter_by(id=packet_id).first()
        if not packet:
            return
        from grace_control.core.state_machine import StateMachine
        sm = StateMachine()
        sm.transition(PacketState(packet.state), PacketState.BLOCKED)
        packet.state = PacketState.BLOCKED.value

        # Store architect repair request
        spec = packet.spec_json or {}
        spec["architect_repair"] = {
            "reason": decision.reason,
            "failure_class": decision.failure_class.value,
            "instruction": decision.architect_instruction,
        }
        packet.spec_json = spec
        db.flush()
```

### 2.4 BLOCK_FEATURE / ESCALATE_ARCHITECT

```python
async def _apply_block_feature(self, packet_id: str, decision: RecoveryDecision):
    from grace_control.db import get_db
    from grace_control.db.schema import Packet, PacketState, Feature

    with get_db() as db:
        packet = db.query(Packet).filter_by(id=packet_id).first()
        if not packet:
            return
        from grace_control.core.state_machine import StateMachine
        sm = StateMachine()
        sm.transition(PacketState(packet.state), PacketState.BLOCKED)
        packet.state = PacketState.BLOCKED.value

        # Also mark feature as blocked for recovery
        feature = db.query(Feature).filter_by(id=packet.feature_id).first()
        if feature:
            spec = packet.spec_json or {}
            spec["recovery"] = {"blocked_reason": decision.reason}
            packet.spec_json = spec
        db.flush()
```

### 2.5 RETRY_VERIFIER / RETRY_REVIEWER / RETRY_MERGE

```python
async def _apply_retry_verifier(self, packet_id: str):
    with get_db() as db:
        packet = db.query(Packet).filter_by(id=packet_id).first()
        if not packet:
            return
        spec = packet.spec_json or {}
        spec["recovery"] = {"retry_verifier": True}
        packet.spec_json = spec
        db.flush()

async def _apply_retry_reviewer(self, packet_id: str):
    with get_db() as db:
        packet = db.query(Packet).filter_by(id=packet_id).first()
        if not packet:
            return
        spec = packet.spec_json or {}
        spec["recovery"] = {"retry_reviewer": True}
        packet.spec_json = spec
        db.flush()

async def _apply_retry_merge(self, packet_id: str):
    with get_db() as db:
        packet = db.query(Packet).filter_by(id=packet_id).first()
        if not packet:
            return
        from grace_control.core.state_machine import StateMachine
        sm = StateMachine()
        sm.transition(PacketState(packet.state), PacketState.ACCEPTED)
        packet.state = PacketState.ACCEPTED.value
        db.flush()
```

---

## 3. New file: `src/grace_control/api/routers/recovery.py`

### 3.1 Endpoints

```python
@router.post("/evaluate/{packet_id}")
async def evaluate_packet(packet_id: str, request: dict) -> dict:
    """
    POST /api/recovery/evaluate/{packet_id}
    Body: {"apply": false}
    
    Builds FailureSignal → classify → decide → persist → optionally apply.
    Returns RecoveryDecision with decision_id, action, reason, next_executor_hint.
    """
    allow_apply = request.get("apply", False)
    controller = RecoveryController()
    decision = await controller.evaluate(packet_id, allow_apply=allow_apply)
    
    return {
        "data": {
            "packet_id": packet_id,
            "decision_id": decision.audit_payload.get("decision_id", ""),
            "failure_class": decision.failure_class.value,
            "action": decision.action.value,
            "reason": decision.reason,
            "next_executor_hint": decision.next_executor_hint,
            "max_attempts_reached": decision.max_attempts_reached,
            "status": "applied" if allow_apply else "proposed",
        },
        "timestamp": datetime.now(timezone.utc).isoformat() + "Z",
    }


@router.get("/packets/{packet_id}")
async def get_packet_recovery(packet_id: str) -> dict:
    """
    GET /api/recovery/packets/{packet_id}
    Returns recovery history for a packet.
    """
    from grace_control.db import get_db
    from grace_control.db.schema import PacketRun

    with get_db() as db:
        runs = db.query(PacketRun).filter_by(packet_id=packet_id).order_by(
            PacketRun.run_number.desc()
        ).limit(20).all()
        
        decisions = []
        for r in runs:
            rj = r.result_json or {}
            rec = rj.get("recovery", {})
            if rec:
                decisions.append(rec)

    return {
        "data": {
            "packet_id": packet_id,
            "decisions": decisions,
            "total": len(decisions),
        },
        "timestamp": datetime.now(timezone.utc).isoformat() + "Z",
    }


@router.get("/features/{feature_id}")
async def get_feature_recovery(feature_id: str) -> dict:
    """
    GET /api/recovery/features/{feature_id}
    Returns recovery summary for all packets in a feature.
    """
    from grace_control.db import get_db
    from grace_control.db.schema import Packet, PacketRun

    with get_db() as db:
        packets = db.query(Packet).filter_by(feature_id=feature_id).all()
        summary = []
        for p in packets:
            runs = db.query(PacketRun).filter_by(packet_id=p.id).order_by(
                PacketRun.run_number.desc()
            ).limit(5).all()
            for r in runs:
                rj = r.result_json or {}
                rec = rj.get("recovery", {})
                if rec:
                    summary.append({
                        "packet_id": p.id,
                        "run_id": r.id,
                        "decision": rec,
                    })
                    break  # only latest per packet

    return {
        "data": {
            "feature_id": feature_id,
            "packets_with_recovery": len(summary),
            "decisions": summary,
        },
        "timestamp": datetime.now(timezone.utc).isoformat() + "Z",
    }
```

---

## 4. Worker integration

In `src/grace_control/worker/worker.py`, after packet rejection, call the controller:

```python
# In _main_loop, after packet_rejected:
if status == "rejected" or status == "blocked":
    controller_enabled = os.environ.get("GRACE_RECOVERY_CONTROLLER_ENABLED", "false") == "true"
    if controller_enabled:
        from grace_control.core.recovery_controller import RecoveryController
        ctrl = RecoveryController()
        try:
            decision = await asyncio.wait_for(
                ctrl.evaluate(packet_id, allow_apply=True),
                timeout=30,
            )
            self.log.info("recovery_applied",
                packet_id=packet_id, action=decision.action.value)
        except Exception as e:
            self.log.error("recovery_apply_failed",
                packet_id=packet_id, error=str(e)[:200])
```

### Worker executor selection for SWITCH_CODER

In `src/grace_control/adapters/packet_executor.py`, when selecting executor:

```python
# Line ~177 — after packet_data["spec_json"] is available
spec_json = packet_data.get("spec_json") or {}
recovery = spec_json.get("recovery", {})
requested_executor_id = recovery.get("requested_executor_id")

if isinstance(spec_json, dict) and requested_executor_id:
    # Honor recovery controller's executor choice
    from grace_control.core.executor_selector import load_profiles
    profiles = load_profiles()
    executors = profiles.get("codex", {}).get("executors", [])
    matching = [e for e in executors if e.get("executor_id") == requested_executor_id]
    if matching:
        executor = matching[0]
    else:
        executor = select_executor("coder", attempt=packet_data.get("attempt_count", 1) + 1)
else:
    executor = select_executor("coder", attempt=packet_data.get("attempt_count", 1) + 1)
```

---

## 5. Recovery events (`src/grace_control/core/event_recorder.py` additions)

Add recovery-specific event types:

```python
def record_recovery_event(event_type: str, packet_id: str, payload: dict, db=None):
    """
    Emit structured recovery events.
    event_type: recovery_signal_built, recovery_classified, recovery_decision_made,
                recovery_retry_same_coder, recovery_switch_coder,
                recovery_return_to_architect, recovery_escalate_architect,
                recovery_block_feature, recovery_no_action, recovery_apply_failed
    """
    if db is None:
        from grace_control.db import get_db
        db = next(get_db())
    
    event = Event(
        entity_type="packet",
        entity_id=packet_id,
        event_type=event_type,
        payload=payload,
        timestamp=datetime.now(timezone.utc),
    )
    db.add(event)
    db.flush()
```

**Do NOT create a separate events table or module.** Extend the existing event system.

---

## 6. Required tests

Create `tests/grace_control/core/test_recovery_controller.py`:

```text
test_build_signal_from_latest_run              — builds FailureSignal with correct fields
test_build_signal_counts_previous_attempts     — coder_attempt_count = rejected + failed
test_evaluate_retry_same_coder                 — coder failed once → RETRY_SAME_CODER
test_evaluate_switch_coder                     — coder failed twice → SWITCH_CODER
test_evaluate_return_architect                 — coder failed 4x → RETURN_TO_ARCHITECT
test_evaluate_true_blocker                     — dirty target → BLOCK_FEATURE
test_apply_retry_same_coder_sets_READY          — packet.transition → READY
test_apply_switch_coder_stores_requested_executor  — spec_json.recovery.requested_executor_id
test_apply_return_architect_sets_BLOCKED        — packet → BLOCKED
test_apply_block_feature_blocks_packet          — packet → BLOCKED
test_controller_disabled_by_default             — _enabled=False → no apply
test_controller_honors_feature_flag             — GRACE_RECOVERY_CONTROLLER_ENABLED=true → apply
test_evaluate_persists_decision                 — RecoveryDecision stored in result_json
test_evaluate_emits_events                      — recovery events visible in event stream
test_strict_never_downgraded                    — STRICT profile + recovery → still STRICT
test_custom_recovery_policy_changes_decision    — different max_attempts → different action
```

**Do not run real LLMs, git, opencode, agy, or API server in these tests.**

---

## 7. Event emission

RecoveryController must emit events at each step:

```python
def _emit_recovery_events(self, packet_id: str, signal: FailureSignal, decision: RecoveryDecision):
    from grace_control.core.event_recorder import record_recovery_event

    record_recovery_event("recovery_classified", packet_id, {
        "failure_class": decision.failure_class.value,
        "signal": signal.model_dump(),
    })

    action_event_map = {
        RecoveryAction.RETRY_SAME_CODER: "recovery_retry_same_coder",
        RecoveryAction.SWITCH_CODER: "recovery_switch_coder",
        RecoveryAction.RETURN_TO_ARCHITECT: "recovery_return_to_architect",
        RecoveryAction.ESCALATE_ARCHITECT: "recovery_escalate_architect",
        RecoveryAction.RETRY_VERIFIER: "recovery_retry_verifier",
        RecoveryAction.RETRY_REVIEWER: "recovery_retry_reviewer",
        RecoveryAction.RETRY_MERGE: "recovery_retry_merge",
        RecoveryAction.BLOCK_FEATURE: "recovery_block_feature",
        RecoveryAction.NO_ACTION: "recovery_no_action",
    }
    event_type = action_event_map.get(decision.action, "recovery_no_action")
    record_recovery_event(event_type, packet_id, {
        "action": decision.action.value,
        "reason": decision.reason,
        "next_executor_hint": decision.next_executor_hint,
    })
```

---

## 8. Router integration — mount in `src/grace_control/api/main.py`

```python
from grace_control.api.routers import recovery
app.include_router(recovery.router, prefix="/api/recovery", tags=["recovery"])
```

---

## 9. Acceptance criteria

```text
1. RecoveryController.build_signal() builds FailureSignal from DB data.
2. RecoveryController.evaluate() runs classify + decide + persist.
3. RecoveryController applies safe actions behind feature flag.
4. SWITCH_CODER sets packet.spec_json["recovery"]["requested_executor_id"].
5. PacketExecutor honors requested_executor_id when present.
6. RETRY_SAME_CODER transitions packet to READY.
7. RETURN_TO_ARCHITECT / BLOCK_FEATURE transitions to BLOCKED.
8. POST /api/recovery/evaluate/{packet_id} returns decision.
9. GET /api/recovery/packets/{packet_id} returns history.
10. GET /api/recovery/features/{feature_id} returns summary.
11. Recovery events are emitted for all actions.
12. GRACE_RECOVERY_CONTROLLER_ENABLED=false disables all application.
13. All 16+ tests pass without real LLMs/git/API.
14. Existing 25 recovery tests still pass.
15. Existing 14 recovery fixture YAMLs still pass.
```
