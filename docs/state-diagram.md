```mermaid
stateDiagram-v2
    draft --> ready
    ready --> running
    ready --> cancelled
    running --> accepted
    running --> rejected
    running --> blocked_recoverable
    running --> blocked_final
    running --> failed
    running --> cancelled
    rejected --> ready
    rejected --> blocked_recoverable
    rejected --> blocked_final
    rejected --> cancelled
    blocked --> ready
    blocked_recoverable --> ready
    blocked_recoverable --> blocked_final
    blocked_recoverable --> cancelled
    accepted --> merged

    classDef terminal fill:#fdd,stroke:#900,stroke-width:2px
    class blocked_final terminal
    class cancelled terminal
    class failed terminal
    class merged terminal
```
