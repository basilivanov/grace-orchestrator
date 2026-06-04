# Escalation Policy — Phase 5: Admin/Event Integration

Audience: Coder (literal executor).

Depends on: Phase 3 (recovery events, API), Phase 4 (session resume stubs).

---

## Goal

Expose recovery data in the admin dashboard and event stream. Do NOT build a new UI from scratch — extend the existing `dashboard.html` and event API.

---

## 1. Dashboard HTML additions (`src/grace_control/ui/templates/dashboard.html`)

### 1.1 Recovery summary per packet

In packet detail view, show:

```html
<div class="recovery-section" id="recovery-${packetId}">
  <h3>Recovery</h3>
  <div class="recovery-status">
    <span class="badge">${recovery.failureClass || 'none'}</span>
    <span>${recovery.action || '-'}</span>
  </div>
  <div class="recovery-reason">${recovery.reason || ''}</div>
  <div class="recovery-executors">
    ${recovery.currentExecutorId || '?'} → ${recovery.nextExecutorHint || '?'}
  </div>
</div>
```

### 1.2 Recovery events stream

Add recovery events to the existing event stream panel with distinct styling:

```javascript
const recoveryEvents = events.filter(e => e.event_type.startsWith('recovery_'));
if (recoveryEvents.length > 0) {
  // Show recovery timeline
  recoveryEvents.forEach(ev => {
    renderEventCard(ev, 'recovery');
  });
}
```

### 1.3 Session resume indicator

```html
<div class="session-resume" id="session-${packetId}">
  ${sessionResumeAvailable ? '🔄 Session resume available' : '⏳ No resume session'}
</div>
```

---

## 2. Dashboard API additions (`src/grace_control/api/main.py: dashboard_data()`)

### 2.1 Per-packet recovery data

Add to the existing packet response:

```python
# In dashboard_data(), for each packet:
recovery_runs = db.query(PacketRun).filter_by(
    packet_id=p.id
).filter(
    PacketRun.result_json.contains({"recovery": {}})
).order_by(PacketRun.run_number.desc()).limit(1).all()

recovery_data = None
if recovery_runs:
    rj = recovery_runs[0].result_json or {}
    rec = rj.get("recovery", {})
    recovery_data = {
        "failure_class": rec.get("failure_class", ""),
        "action": rec.get("action", ""),
        "reason": rec.get("reason", ""),
        "current_executor_id": rec.get("current_executor_id", ""),
        "next_executor_hint": rec.get("next_executor_hint", ""),
        "decision_id": rec.get("decision_id", ""),
    }

# Add to packet dict:
packet_dict["recovery"] = recovery_data
```

### 2.2 Per-feature recovery summary

```python
# For feature-level summary in dashboard_data():
feature["blocked_recovery_count"] = sum(
    1 for p in packets
    if p.state == "blocked"
    and p.spec_json
    and isinstance(p.spec_json, dict)
    and p.spec_json.get("recovery", {}).get("blocked_reason")
)
```

---

## 3. Event API additions

### 3.1 Recovery event types in event stream

Ensure the existing event API (`GET /api/events`) returns recovery events:

Recovery event types:
```
recovery_classified
recovery_decision_made
recovery_retry_same_coder
recovery_switch_coder
recovery_return_to_architect
recovery_escalate_architect
recovery_retry_verifier
recovery_retry_reviewer
recovery_retry_merge
recovery_block_feature
recovery_no_action
recovery_apply_failed
```

### 3.2 Filter by recovery events

```python
@router.get("/api/events")
async def list_events(
    entity_type: str = None,
    entity_id: str = None,
    event_type: str = None,  # Supports "recovery_*" prefix
    limit: int = 20,
):
    ...
    if event_type and event_type.startswith("recovery_"):
        query = query.filter(Event.event_type.like("recovery_%"))
    ...
```

---

## 4. Dashboard WebSocket updates

Add recovery events to the existing WebSocket broadcast:

```python
# In ws_broadcast.py, add recovery event types to the broadcast filter
RECOVERY_EVENTS = frozenset([
    "recovery_classified",
    "recovery_decision_made",
    "recovery_retry_same_coder",
    "recovery_switch_coder",
    "recovery_return_to_architect",
    "recovery_block_feature",
    "recovery_no_action",
])

async def broadcast_event(event_type: str, data: dict):
    ...
    # Include recovery events
    if event_type.startswith("recovery_"):
        await ws_manager.broadcast(json.dumps({
            "type": "recovery_update",
            "data": data,
            "timestamp": datetime.now(timezone.utc).isoformat() + "Z",
        }))
    ...
```

---

## 5. No new files

All changes go into existing files:
- `src/grace_control/ui/templates/dashboard.html` — HTML/CSS additions
- `src/grace_control/api/main.py` — dashboard_data() additions
- `src/grace_control/api/ws_broadcast.py` — recovery event types
- `src/grace_control/api/routers/events.py` or equivalent — event filtering

**Do NOT create new UI files, pages, or frontend frameworks.**

---

## 6. Required tests

Add to existing test files (no new test file needed):

```text
test_dashboard_recovery_data_in_packet      — dashboard response includes recovery field
test_dashboard_blocked_count_for_feature    — blocked_recovery_count computed
test_events_filter_recovery_prefix          — event_type=recovery_* works
test_ws_broadcast_recovery_events           — recovery events trigger ws broadcast
test_recovery_section_renders_in_html       — dashboard HTML contains recovery div
```

---

## 7. Acceptance criteria

```text
1. Dashboard HTML shows recovery data per packet (failure_class, action, reason, executors).
2. Dashboard API returns recovery field in packet data.
3. Dashboard API returns blocked_recovery_count per feature.
4. Event stream API supports filtering by recovery_* event types.
5. WebSocket broadcasts recovery_update for all recovery event types.
6. Session resume indicator shows "available" or "pending" based on Phase 4 stubs.
7. All 5+ tests pass without breaking existing dashboard/events tests.
```
