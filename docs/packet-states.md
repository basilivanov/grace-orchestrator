# Packet States

Auto-generated from grace_control.core.state_machine.

| State | Terminal? | Allowed transitions |
|-------|-----------|---------------------|
| `draft` | no | ready |
| `ready` | no | running, cancelled |
| `running` | no | accepted, rejected, blocked_recoverable, blocked_final, failed, cancelled |
| `rejected` | no | ready, blocked_recoverable, blocked_final, cancelled |
| `blocked` | no | ready |
| `blocked_recoverable` | no | ready, blocked_final, cancelled |
| `blocked_final` | yes | (none) |
| `accepted` | no | merged |
| `merged` | yes | (none) |
| `failed` | yes | (none) |
| `cancelled` | yes | (none) |
