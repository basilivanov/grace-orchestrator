# State Machine

Packet states and transitions:

```
  DRAFT ──→ READY ──→ RUNNING ──→ ACCEPTED ──→ MERGED ──→ [done]
   ↑           │           │                        ↓
   │           │           └──→ REJECTED            CANCELLED
   │           │                    ↓
   │           │               PENDING
   └───────────┴──────────────────┘  (retry loop, max_attempts)
```

| State | Meaning |
| --- | --- |
| `DRAFT` | Not yet ready for execution |
| `READY` | Approved by architect, available for claim |
| `RUNNING` | Claimed by a worker |
| `ACCEPTED` | Acceptance pipeline passed, ready for merge |
| `MERGED` | Changes merged to target branch, final terminal state |
| `REJECTED` | Acceptance pipeline or verifier rejected — attempt exhausted |
| `CANCELLED` | Explicitly aborted (user or policy) |
| `PENDING` | Rejected, will be retried on next wave gate |
| `BLOCKED` | Returned to architect (re-plan required) |

Transitions are enforced by `services/packet_service.py:PacketService.transition()`
via `core/state_machine.py:StateMachine`.

Waves progress when all packets in the wave reach `MERGED` or `CANCELLED`.
