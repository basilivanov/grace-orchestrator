# Packet States

Auto-generated from grace_control.core.state_machine.

| State | Terminal? | Allowed transitions |
|-------|-----------|---------------------|
| `accepted` | no | merged, blocked_recoverable |
| `blocked` | no | ready |
| `blocked_final` | yes | cancelled |
| `blocked_recoverable` | no | ready, blocked_final, cancelled |
| `cancelled` | yes | (none) |
| `draft` | no | ready |
| `failed` | yes | cancelled |
| `merged` | yes | (none) |
| `ready` | no | running, cancelled |
| `rejected` | no | ready, failed, blocked_recoverable, blocked_final, cancelled |
| `running` | no | accepted, rejected, blocked_recoverable, blocked_final, failed, cancelled |
