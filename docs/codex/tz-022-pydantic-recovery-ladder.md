# TZ 022 — Pydantic Recovery Ladder: odd/even routing with verifier gate

Audience: Coder (literal executor).

Parent: `docs/codex/tz-017-feature-recovery-escalation-policy.md`.

Status: **implementation spec. Build exactly as written.**

---

## 0. Goal

Replace hardcoded recovery if/else logic with a **Pydantic-based recovery ladder** that routes packets deterministically based on odd/even attempt count. The ladder uses a verifier gate on even attempts and returns decisions as typed `RecoveryRoute` objects. At attempt 7, the new architect receives full context from all previous coders + verifier verdicts.

This must NOT introduce technical debt:
- No YAML rules engine (Pydantic models only)
- No complex condition parser (conditions are typed enums)
- No separate routing table (ladder is a Pydantic model)

---

## 1. Phase map

```
Phase A — recovery_rules.py (Pydantic models + evaluate_ladder)
Phase B — integration: feature_recovery, recovery_controller, packet_executor, worker
Phase C — architect context contract (ArchitectContext + collection)
Phase D — tests: unit + fixture YAMLs
Phase E — optional YAML config (grace/recovery-ladder.yaml)
```

---

## 2. Phase A — New file: `src/grace_control/core/recovery_rules.py`

### 2.1 Models (use EXACT field names)

```python
from __future__ import annotations

from enum import Enum
from pydantic import BaseModel, Field


class RouteCondition(str, Enum):
    """Condition types for ladder rule matching."""
    ODD_ATTEMPT = "odd_attempt"
    EVEN_ATTEMPT = "even_attempt"
    ATTEMPT_GTE = "attempt_gte"


class RouteAction(str, Enum):
    """What happens when a condition matches."""
    RETRY_SAME_CODER = "RETRY_SAME_CODER"
    RUN_VERIFIER = "RUN_VERIFIER"
    SWITCH_CODER = "SWITCH_CODER"
    ARCHITECT_REPACK = "ARCHITECT_REPACK"
    NEW_ARCHITECT = "NEW_ARCHITECT"
    NO_ACTION = "NO_ACTION"


class RecoveryRoute(BaseModel):
    """Result of evaluating the ladder for a given attempt."""
    rule_index: int                         # which rule matched (0-based)
    condition: RouteCondition               # condition that matched
    action: RouteAction                     # what to do
    skip_verifier: bool = False             # skip evidence verifier
    max_coders: int = 3                     # copy of ladder.max_coders
    on_verdict: dict[str, RouteAction] = Field(default_factory=lambda: {
        "REWORK_TO_CODER": RouteAction.SWITCH_CODER.value,
        "RETURN_TO_ARCHITECT": RouteAction.ARCHITECT_REPACK.value,
    })


class RecoveryRule(BaseModel):
    """One rule in the ladder."""
    condition: RouteCondition
    condition_value: int | None = None      # for ATTEMPT_GTE
    action: RouteAction
    skip_verifier: bool = False
    on_verdict: dict[str, str] = Field(default_factory=lambda: {
        "REWORK_TO_CODER": "SWITCH_CODER",
        "RETURN_TO_ARCHITECT": "ARCHITECT_REPACK",
    })


class RecoveryLadder(BaseModel):
    """Ordered list of rules. First match wins."""
    rules: list[RecoveryRule]
    max_coders: int = 3
    switch_architect_on_attempt: int = 7

    @classmethod
    def default(cls) -> "RecoveryLadder":
        """Default odd/even ladder."""
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
```

### 2.2 Function `evaluate_ladder`

```python
def evaluate_ladder(
    attempt: int,
    ladder: RecoveryLadder | None = None,
) -> RecoveryRoute:
    """
    Evaluate the ladder for a given attempt number.
    First matching rule wins. Returns RecoveryRoute with action + metadata.

    attempt: 1-based attempt number (1, 2, 3, ...)
    ladder: optional custom ladder; None = default
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

        if match:
            return RecoveryRoute(
                rule_index=idx,
                condition=rule.condition,
                action=rule.action,
                skip_verifier=rule.skip_verifier,
                max_coders=ladder.max_coders,
                on_verdict=rule.on_verdict,
            )

    # Fallback — never skip verifier
    return RecoveryRoute(
        rule_index=-1,
        condition=RouteCondition.ODD_ATTEMPT,
        action=RouteAction.RETRY_SAME_CODER,
        skip_verifier=False,
        max_coders=ladder.max_coders,
    )


def load_ladder(path: str | None = None) -> RecoveryLadder:
    """
    Load ladder from YAML file or return default.
    path: optional file path; None = try 'grace/recovery-ladder.yaml' then default.
    """
    import yaml
    from pathlib import Path

    if path:
        config_path = Path(path)
    else:
        config_path = Path("grace/recovery-ladder.yaml")

    try:
        if config_path.exists():
            data = yaml.safe_load(config_path.read_text()) or {}
            return RecoveryLadder(**data)
    except Exception:
        pass

    return RecoveryLadder.default()
```

### 2.3 MODULE_CONTRACT for recovery_rules.py

```python
# START_MODULE_CONTRACT
# purpose: Define Pydantic recovery ladder models + evaluation logic.
#          Routes packet recovery based on odd/even attempt rules.
# inputs: attempt number, optional RecoveryLadder.
# returns: RecoveryRoute with action, skip_verifier, on_verdict mapping.
# side_effects: None (pure functions except load_ladder).
# emitted_logs: None.
# error_behavior: Falls back to default ladder on load error.
# END_MODULE_CONTRACT
```

---

## 3. Phase B — Integration with existing code

### 3.1 `feature_recovery.py` changes

**3.1.1 Add `new_architect` to `RecoveryAction`:**

```python
class RecoveryAction(str, Enum):
    ...
    NEW_ARCHITECT = "new_architect"    # ← ADD THIS VALUE
```

**3.1.2 Add `architect_switch_count` to `FailureSignal`:**

```python
class FailureSignal(BaseModel):
    ...
    architect_switch_count: int = 0    # ← ADD THIS FIELD
```

**3.1.3 Change `decide_recovery()` to use ladder:**

```python
def decide_recovery(
    signal: FailureSignal,
    policy: RecoveryPolicy | None = None,
) -> RecoveryDecision:
    policy = policy or RecoveryPolicy()

    # ── Evaluate ladder for routing metadata ──
    from grace_control.core.recovery_rules import evaluate_ladder, RecoveryLadder
    ladder = RecoveryLadder.default()       # ← or load_ladder() for YAML
    route = evaluate_ladder(signal.attempt_count, ladder)

    if route.action == RouteAction.RETRY_SAME_CODER:
        return RecoveryDecision(
            action=RecoveryAction.RETRY_SAME_CODER,
            failure_class=classify_failure(signal),
            reason=f"odd attempt {signal.attempt_count} — retry same coder",
            next_executor_hint=signal.current_executor_id,
        )

    if route.action == RouteAction.RUN_VERIFIER:
        # Verifier runs externally (packet_executor.py). Here we just route.
        fc = classify_failure(signal)
        if fc == FailureClass.ARCHITECT_REPACK_NEEDED:
            # Verifier called out RETURN_TO_ARCHITECT — repack
            if signal.coder_attempt_count >= policy.max_same_coder_attempts:
                return _decide_coder_exhausted(signal, policy, route)
            return RecoveryDecision(
                action=RecoveryAction.RETURN_TO_ARCHITECT,
                failure_class=fc,
                reason=signal.reason or "verifier returned RETURN_TO_ARCHITECT",
            )
        # Verifier said REWORK_TO_CODER — switch
        return _decide_switch_or_architect(signal, policy, route)

    if route.action == RouteAction.NEW_ARCHITECT:
        return RecoveryDecision(
            action=RecoveryAction.NEW_ARCHITECT,
            failure_class=FailureClass.ARCHITECT_ESCALATION_NEEDED,
            reason=f"3 coders + max attempts reached (attempt {signal.attempt_count}), switching architect",
            max_attempts_reached=True,
        )

    # Legacy fallback — use existing logic
    return _legacy_decide(signal, policy)
```

**Do NOT remove the existing `classify_failure()`. Add ladder evaluation as an additional routing layer.**

### 3.2 `recovery_controller.py` changes

**3.2.1 Add `_apply_new_architect` method:**

```python
def _apply_new_architect(self, packet_id: str, decision: RecoveryDecision):
    from grace_control.db import get_db
    from grace_control.db.schema import Packet, PacketRun, PacketState

    with get_db() as db:
        packet = db.query(Packet).filter_by(id=packet_id).first()
        if not packet:
            return

        # Build architect context from all previous runs
        context = self._build_architect_context(packet, db)

        sm = PacketStateMachine()
        sm.transition(PacketState(packet.state), PacketState.BLOCKED)
        packet.state = PacketState.BLOCKED.value

        spec = dict(packet.spec_json or {})
        spec["recovery"]["new_architect"] = {
            "reason": decision.reason,
            "architect_context": context.model_dump(),
            "created_at": datetime.now(timezone.utc).isoformat() + "Z",
        }
        packet.spec_json = spec
        db.flush()
```

**3.2.2 Add `_build_architect_context` method:**

```python
def _build_architect_context(self, packet: Any, db) -> ArchitectContext:
    """
    Collect full context from all previous attempts:
    - Each coder's acceptance report
    - Each verifier's verdict + spec_conflicts + architect_questions
    - Changed files per attempt
    - Executor IDs
    """
    from grace_control.db.schema import PacketRun
    from grace_control.core.recovery_rules import ArchitectContext

    runs = db.query(PacketRun).filter_by(
        packet_id=packet.id
    ).order_by(PacketRun.run_number).all()

    attempts = []
    executor_ids = []
    acceptance_reports = []
    verifier_reports = []

    for run in runs:
        rj = run.result_json or {}
        acc = rj.get("acceptance_report", {})
        ev = rj.get("evidence_verifier_report", {})

        attempts.append({
            "run_number": run.run_number,
            "status": run.status,
            "reason": rj.get("reason", ""),
            "duration_ms": run.duration_ms,
        })
        if acc:
            acceptance_reports.append(acc)
        if ev:
            verifier_reports.append(ev)

        exec_id = rj.get("executor_id", "")
        if exec_id and exec_id not in executor_ids:
            executor_ids.append(exec_id)

    # Get changed files from the latest run
    changed_files = []
    if runs:
        latest = runs[-1]
        rj = latest.result_json or {}
        changed_files = rj.get("changed_files", [])

    summary = (
        f"Packet {packet.id}: {len(runs)} attempts across "
        f"{len(executor_ids)} executors ({', '.join(executor_ids[:5])}). "
        f"Final state: {packet.state}. "
        f"Acceptance rejected {len([r for r in runs if r.status == 'rejected'])}x. "
        f"Verifier returned RETURN_TO_ARCHITECT "
        f"{len([v for v in verifier_reports if v.get('verdict') == 'RETURN_TO_ARCHITECT'])}x."
    )

    return ArchitectContext(
        original_spec=packet.spec_json or {},
        attempts=attempts,
        acceptance_reports=acceptance_reports,
        verifier_reports=verifier_reports,
        executor_ids=executor_ids,
        changed_files=changed_files,
        summary=summary,
    )
```

### 3.3 `packet_executor.py` — verifier gate on acceptance rejection

**Change at line 315 (currently skips verifier):**

```python
if not accept_report.is_accepted:
    # ── Check ladder: should we skip verifier? ──
    from grace_control.core.recovery_rules import evaluate_ladder
    attempt_count = packet_data.get("attempt_count", 1)
    route = evaluate_ladder(attempt_count)

    if route.skip_verifier:
        # Even attempt → skip verifier, go directly to NORMAL profile routing
        ev_report = skipped_evidence_report(
            f"verifier skipped per ladder (attempt {attempt_count}: {route.condition.value})")
        rv_report = skipped_reviewer_report("verifier skipped per ladder")
    else:
        # Odd attempt → RUN VERIFIER for classification
        evidence_report = await run_evidence_verifier(
            packet=pkt_contract,
            acceptance_report=accept_report,
            worktree_path=wt_path,
            run_dir=run_dir,
            changed_files=changed_files,
            artifacts=artifacts,
        )
        ev_report = evidence_report
        # Verifier verdict stored in result_json for later recovery decisions
        ...
```

### 3.4 `worker.py` — move recovery before rejection

**Change at lines 124-131:**

```python
# BEFORE — recovery after handle_rejection (never runs on max_attempts)
if status == "rejected":
    self._handle_rejection(packet_id)       # ← may crash
if status == "blocked":
    self._handle_rejection(packet_id)

# AFTER — recovery BEFORE handle_rejection
if status in ("rejected", "blocked"):
    await self._maybe_apply_recovery(packet_id)  # ← always runs
self._handle_rejection(packet_id)                 # ← may crash
```

---

## 4. Phase C — ArchitectContext contract

### 4.1 New model in `recovery_rules.py`

```python
class ArchitectContext(BaseModel):
    """Formal contract passed from recovery controller to architect on NEW_ARCHITECT."""
    original_spec: dict[str, Any] = Field(default_factory=dict)
    attempts: list[dict[str, Any]] = Field(default_factory=list)
    acceptance_reports: list[dict[str, Any]] = Field(default_factory=list)
    verifier_reports: list[dict[str, Any]] = Field(default_factory=list)
    executor_ids: list[str] = Field(default_factory=list)
    changed_files: list[str] = Field(default_factory=list)
    summary: str = ""
```

### 4.2 Where it flows

```
packet_executor.py:
  → verifier runs (even attempt) → EvidenceVerifierReport
  → stored in result_json["evidence_verifier_report"]

recovery_controller.py:
  → _build_architect_context() reads all PacketRun.result_json
  → collects acceptance_reports, verifier_reports, executor_ids
  → builds ArchitectContext
  → stores in spec_json["recovery"]["new_architect"]["architect_context"]

self_evolution.py (or manual):
  → reads context from spec_json
  → passes to architect LLM as context
```

### 4.3 Verifier → Architect contract fields

| Verifier field | Architect use |
|---------------|---------------|
| `spec_conflicts` | Architect must fix scope/verification in new packet |
| `architect_questions` | Answer these in new plan |
| `missing_evidence` | Architect must add evidence requirements |
| `verdict` | `RETURN_TO_ARCHITECT` → repack, `REWORK_TO_CODER` → coder retry |

---

## 5. Phase D — Tests

### 5.1 Unit tests: `tests/grace_control/core/test_recovery_rules.py`

```text
test_odd_attempt_retry_same_coder              — attempt 1 → RETRY_SAME_CODER + skip_verifier=true
test_odd_attempt_retry_same_coder_attempt_3    — attempt 3 → same behavior
test_even_attempt_run_verifier                 — attempt 2 → RUN_VERIFIER + skip_verifier=false
test_even_attempt_on_verdict_mapping           — route.on_verdict contains correct keys
test_attempt_gte_seven_new_architect           — attempt 7 → NEW_ARCHITECT
test_attempt_eight_not_in_ladder_fallback      — attempt 8 → fallback if no rule
test_custom_ladder_overrides_default           — custom RecoveryLadder → different rules
test_default_ladder_rule_order                 — first match wins (odd before even)
test_architect_context_model_creation          — ArchitectContext with all fields
```

**No real LLMs, git, API server.**

### 5.2 Fixture YAMLs: `fixtures/golden/recovery_route_*.yaml`

```yaml
# fixtures/golden/recovery_route_odd_even.yaml
id: recovery_route_odd_even
kind: golden_fixture
start_stage: recovery
profile: NORMAL

runs:
  - attempt: 1
    status: rejected
  - attempt: 2
    status: rejected

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

## 6. Phase E — Optional YAML config

### 6.1 File: `grace/recovery-ladder.yaml`

```yaml
recovery_ladder:
  max_coders: 3
  switch_architect_on_attempt: 7
  rules:
    - condition: ODD_ATTEMPT
      action: RETRY_SAME_CODER
      skip_verifier: true

    - condition: EVEN_ATTEMPT
      action: RUN_VERIFIER
      on_verdict:
        REWORK_TO_CODER: SWITCH_CODER
        RETURN_TO_ARCHITECT: ARCHITECT_REPACK

    - condition: ATTEMPT_GTE
      condition_value: 7
      action: NEW_ARCHITECT
      skip_verifier: true
```

### 6.2 Loading

```python
ladder = load_ladder()   # tries grace/recovery-ladder.yaml, falls back to default
```

---

## 7. File map

```
NEW:
  src/grace_control/core/recovery_rules.py         ← Phase A models + evaluate + context
  tests/grace_control/core/test_recovery_rules.py  ← Phase D unit tests (9 tests)
  fixtures/golden/recovery_route_odd_even.yaml     ← Phase D fixture (odd/even)
  grace/recovery-ladder.yaml                       ← Phase E optional config

CHANGE:
  src/grace_control/core/feature_recovery.py        ← ReocveryAction.NEW_ARCHITECT, FailureSignal.architect_switch_count, ladder integration
  src/grace_control/core/recovery_controller.py      ← _apply_new_architect, _build_architect_context
  src/grace_control/adapters/packet_executor.py      ← verifier gate on rejection (skip_verifier flag)
  src/grace_control/worker/worker.py                 ← recovery BEFORE _handle_rejection
```

---

## 8. Acceptance criteria

```text
1. RecoveryRule, RecoveryRoute, RecoveryLadder models exist with EXACT field names from §2.
2. evaluate_ladder(1) → RETRY_SAME_CODER with skip_verifier=true.
3. evaluate_ladder(2) → RUN_VERIFIER with on_verdict mapping.
4. evaluate_ladder(7) → NEW_ARCHITECT.
5. ArchitectContext model exists with all fields from §4.
6. _apply_new_architect stores ArchitectContext in spec_json.
7. packet_executor.py checks skip_verifier from ladder.
8. worker.py calls _maybe_apply_recovery BEFORE _handle_rejection.
9. RecoveryLadder.default() returns default odd/even ladder.
10. load_ladder() gracefully falls back to default on missing/invalid YAML.
11. All 9+ unit tests pass without real LLMs/git/API.
12. At least 1 fixture YAML tests odd/even routing.
13. No existing recovery tests break.
```

---

## 9. Do not do

```text
- Do not create a YAML rules engine with complex conditions.
- Do not add RouteContext with duplicate counters.
- Do not remove existing classify_failure/decide_recovery.
- Do not break existing 83 recovery tests.
- Do not run real LLMs in tests.
- Do not hardcode condition values in evaluate_ladder.
```

---

## 10. Coder report format

```text
Files changed
RecoveryRule/Route/Ladder added: yes/no
Evaluate_ladder function added: yes/no
ArchitectContext model added: yes/no
_apply_new_architect added: yes/no
_build_architect_context added: yes/no
Packet_executor verifier gate changed: yes/no
Worker recovery order changed: yes/no
RecoveryLadder.default() added: yes/no
load_ladder() added: yes/no
Tests added: count
Tests run: count
Remaining blockers
```
