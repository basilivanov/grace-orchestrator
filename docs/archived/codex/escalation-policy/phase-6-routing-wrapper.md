# Escalation Policy — Phase 6: Routing Policy Wrapper

Audience: Coder (literal executor).

Depends on: Phase 3 (classify + decide stable), Phase 5 (admin display of metadata).

---

## Goal

Add a thin metadata wrapper around `classify_failure()` / `decide_recovery()`. Not a routing engine. Not a YAML rules engine. Just structured metadata decoration for admin/UI observability and future session context routing.

---

## 1. New model: `RouteDecision` in `src/grace_control/core/feature_recovery.py`

```python
class RouteDecision(BaseModel):
    """Wraps RecoveryDecision with routing metadata for admin UI and future session routing."""
    decision: RecoveryDecision                                      # The actual decision
    matched_rule_id: str = ""                                       # Human-readable rule name
    display_reason: str = ""                                        # UI-friendly reason
    session_context_mode: str = "none"                              # none|summary_only|summary_plus_artifacts|full_structured_context
    stop_condition_hit: str = ""                                    # Which stop guard triggered, if any
    safety_notes: list[str] = Field(default_factory=list)           # Warnings/notes for admin
```

---

## 2. New function in `src/grace_control/core/feature_recovery.py`

### `decorate_route(decision, signal=None, context=None) -> RouteDecision`

```python
def decorate_route(
    decision: RecoveryDecision,
    signal: FailureSignal | None = None,
    context: dict[str, Any] | None = None,
) -> RouteDecision:
    """
    Wrap RecoveryDecision with routing metadata.
    No LLM calls. No API calls. Pure function.
    
    Does NOT replace classify_failure or decide_recovery.
    Does NOT add a rules engine or YAML config.
    """
    # Determine rule ID from decision characteristics
    rule_id = _resolve_rule_id(decision, signal)
    
    # Build human-friendly display reason
    display_reason = _build_display_reason(decision, signal)
    
    # Determine session context mode based on action
    session_mode = _resolve_session_mode(decision.action)
    
    return RouteDecision(
        decision=decision,
        matched_rule_id=rule_id,
        display_reason=display_reason,
        session_context_mode=session_mode,
        stop_condition_hit=_stop_guard_if_hit(signal, decision),
        safety_notes=_collect_safety_notes(decision, signal),
    )


def _resolve_rule_id(decision: RecoveryDecision, signal: FailureSignal | None) -> str:
    """Map RecoveryAction → human-readable rule ID."""
    mapping = {
        RecoveryAction.RETRY_SAME_CODER:    "coder-retry-same",
        RecoveryAction.SWITCH_CODER:        "coder-switch-model",
        RecoveryAction.RETURN_TO_ARCHITECT: "architect-repack-needed",
        RecoveryAction.ESCALATE_ARCHITECT:  "architect-escalation",
        RecoveryAction.RETRY_VERIFIER:      "verifier-retry",
        RecoveryAction.RETRY_REVIEWER:      "reviewer-retry",
        RecoveryAction.RETRY_MERGE:         "merge-retry",
        RecoveryAction.BLOCK_FEATURE:       "feature-blocked",
        RecoveryAction.NO_ACTION:           "no-action",
    }
    return mapping.get(decision.action, "unknown-rule")


def _build_display_reason(decision: RecoveryDecision, signal: FailureSignal | None) -> str:
    """Build human-friendly display reason."""
    parts = []
    if signal:
        parts.append(f"Packet {signal.packet_id}: {signal.packet_state}")
        if signal.coder_attempt_count:
            parts.append(f"coder attempt {signal.coder_attempt_count}")
    parts.append(decision.reason[:200])
    return " — ".join(parts)


def _resolve_session_mode(action: RecoveryAction) -> str:
    """Resolve session_context_mode for future Phase 4 session resume."""
    modes = {
        RecoveryAction.RETRY_SAME_CODER:    "summary_plus_artifacts",
        RecoveryAction.SWITCH_CODER:        "full_structured_context",
        RecoveryAction.RETURN_TO_ARCHITECT: "full_structured_context",
        RecoveryAction.ESCALATE_ARCHITECT:  "full_structured_context",
        RecoveryAction.RETRY_VERIFIER:      "summary_only",
        RecoveryAction.RETRY_REVIEWER:      "summary_only",
        RecoveryAction.RETRY_MERGE:         "summary_only",
        RecoveryAction.BLOCK_FEATURE:       "summary_only",
        RecoveryAction.NO_ACTION:           "none",
    }
    return modes.get(action, "none")


def _stop_guard_if_hit(signal: FailureSignal | None, decision: RecoveryDecision) -> str:
    """Check if any stop guard triggered."""
    if not signal:
        return ""
    policy = RecoveryPolicy()
    if signal.coder_attempt_count >= policy.max_total_coder_attempts:
        return f"max_total_coder_attempts ({policy.max_total_coder_attempts}) reached"
    if signal.architect_repair_count >= policy.max_architect_repairs:
        return f"max_architect_repairs ({policy.max_architect_repairs}) reached"
    if signal.verifier_reject_count >= policy.max_verifier_retries:
        return f"max_verifier_retries ({policy.max_verifier_retries}) reached"
    if signal.reviewer_reject_count >= policy.max_reviewer_retries:
        return f"max_reviewer_retries ({policy.max_reviewer_retries}) reached"
    if signal.merge_attempt_count >= policy.max_merge_retries:
        return f"max_merge_retries ({policy.max_merge_retries}) reached"
    return ""


def _collect_safety_notes(decision: RecoveryDecision, signal: FailureSignal | None) -> list[str]:
    """Collect safety warnings for admin display."""
    notes = []
    if signal and signal.acceptance_profile == "STRICT":
        notes.append("STRICT profile — acceptance profile will not be downgraded")
    if decision.action == RecoveryAction.BLOCK_FEATURE:
        notes.append("Feature blocked — manual review required")
    if decision.action == RecoveryAction.ESCALATE_ARCHITECT:
        notes.append("Escalation — architect review required before retry")
    return notes
```

---

## 3. Integration with Phase 3 RecoveryController

In `recovery_controller.py:evaluate()`, after `decide_recovery()`:

```python
decision = decide_recovery(signal, policy)
route = decorate_route(decision, signal)   # ← add this line
# decision.audit_payload.update(route.model_dump(exclude={"decision"}))
```

---

## 4. Admin UI metadata

`RouteDecision` fields visible in dashboard:

```
matched_rule_id:    "coder-switch-model"
display_reason:     "Packet pkt_xxx: rejected — coder attempt 3"
session_context_mode: "full_structured_context"
stop_condition_hit: "max_total_coder_attempts (4) reached"
safety_notes:       ["STRICT profile — acceptance profile will not be downgraded"]
```

---

## 5. Required tests

Add to `tests/grace_control/core/test_feature_recovery.py`:

```text
test_decorate_route_retry_same_coder         — RETRY_SAME_CODER → summary_plus_artifacts
test_decorate_route_switch_coder             — SWITCH_CODER → full_structured_context
test_decorate_route_block_feature            — BLOCK_FEATURE → safety note about manual review
test_decorate_route_strict_profile_note      — STRICT profile → never downgraded note
test_stop_guard_max_coder_detected           — 4+ coder attempts → stop_condition_hit populated
test_stop_guard_max_architect_repairs        — 2+ architect repairs → stop_condition_hit
test_decorate_route_does_not_change_decision — RouteDecision wraps, never alters action
test_session_mode_per_action_mapped          — all 9 actions have valid session mode
```

**No real LLMs, agents, or API calls.**

---

## 6. What this phase does NOT include

- Do NOT create a YAML rules engine
- Do NOT implement `RecoveryRoutingPolicy` separate from `RecoveryPolicy`
- Do NOT add `RouteContext` with duplicate counters
- Do NOT add `RouteRule` matching engine
- Do NOT make decisions driven by the wrapper — decisions remain with `classify`/`decide`
- Do NOT implement live session resume

---

## 7. Acceptance criteria

```text
1. RouteDecision model exists as a wrapper around RecoveryDecision.
2. decorate_route() returns RouteDecision with matched_rule_id + display_reason.
3. session_context_mode correctly mapped for all 9 RecoveryAction values.
4. stop_condition_hit reflects RecoveryPolicy limits.
5. safety_notes include STRICT never-downgrade, block, and escalation warnings.
6. decorate_route() does NOT alter the underlying RecoveryDecision.
7. RecoveryController optionally calls decorate_route() after decide_recovery().
8. Admin dashboard can show matched_rule_id, display_reason, session_context_mode.
9. All 7+ tests pass without real LLMs.
```
