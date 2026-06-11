# Worker handoff: GRACE single-feature FIFO queue discipline

**Status:** READY_FOR_WORKER
**Date:** 2026-06-12

## Goal

Implement deterministic queue discipline for GRACE Control Plane.

Desired behavior:

1. Features are processed in FIFO order by creation time.
2. Only one feature is active at a time when `GRACE_MAX_CONCURRENCY=1`.
3. Inside the active feature, packets are processed wave by wave.
4. Inside a wave, packets are processed in deterministic order.
5. Next feature starts only after the current feature is fully completed, cancelled, or manually skipped.
6. Failed/rejected/blocked packets stop the feature from advancing until retry, cancel, or operator action.

This is queue discipline, not a rewrite of packet execution.

## Current state

Existing code already has the base objects:

- `Feature`
- `Wave`
- `Packet`
- `PacketRun`
- `Worker`
- `Lease`
- `Event`

Existing `PacketService.claim()` creates a packet lease and moves a packet to `RUNNING`.

Existing `wave_gate.check_wave_gates()` promotes next-wave packets when the previous wave is done.

Problem:

- `/packets/claim` currently queries all `READY` packets without deterministic feature/wave/packet ordering.
- READY packets from multiple features can be mixed.
- There is no explicit single-active-feature policy.
- Concurrency=1 is mostly an operational assumption, not a queue invariant.

## Target repo

- Repository: `basilivanov/grace-orchestrator`
- Suggested branch: `grace/queue-discipline-single-feature-fifo`

## Required queue policy

### Feature order

Features are processed FIFO by:

1. `Feature.created_at ASC`
2. `Feature.id ASC` as a deterministic tie-breaker

Do not add `queue_order` in this packet unless the existing timestamps are proven insufficient. The current schema already has `created_at`.

### Feature status policy

Use existing `Feature.status` string column. Normalize these statuses:

- `queued` — feature exists but has not started
- `active` — this is the only feature claimable under single-feature mode
- `done` — all packets in all waves are terminal successful/accepted by policy
- `degraded` — feature has failed/rejected/blocked packets and must not advance automatically
- `cancelled` — operator skipped/cancelled the feature

For backward compatibility, treat missing/old statuses like `NOT_STARTED` as `queued`.

### Wave order

Within the active feature, waves are processed by:

1. `Wave.order ASC`
2. `Wave.created_at ASC`
3. `Wave.id ASC`

Only packets from the earliest claimable wave are eligible.

A later wave must not be claimed while an earlier wave has non-terminal or degraded packets.

### Packet order inside a wave

Within the active wave, packets are processed by:

1. `Packet.created_at ASC`
2. `Packet.id ASC`

Do not add a packet order column in this packet unless tests prove timestamps are insufficient.

### Concurrency policy

For MVP, support:

```bash
GRACE_MAX_CONCURRENCY=1
```

When this value is `1`:

- only one packet may be `RUNNING` globally;
- only one feature may be `active`;
- claim must not return packets from another feature while the active feature is incomplete.

Future concurrency >1 may allow multiple packets inside the same wave, but that is out of scope.

## Claim algorithm

Replace the current broad `READY` scan with deterministic queue selection.

Pseudo-policy:

```text
claim_next(worker_id):
  expire stale leases if existing policy supports it, or skip leased packets
  if GRACE_MAX_CONCURRENCY == 1 and any packet is RUNNING:
      return 404/no packet available

  active_feature = oldest feature with status active
  if active_feature is None:
      active_feature = oldest queued/NOT_STARTED feature that is not degraded/done/cancelled
      mark active_feature.status = active

  if active_feature is None:
      return 404/no packet available

  run wave_gate/check progression for active_feature only

  if active_feature has degraded packets:
      active_feature.status = degraded
      return 404/no packet available

  wave = earliest wave in active_feature with claimable packets
  packet = earliest READY packet in wave by created_at/id

  if no packet:
      if all packets in feature are complete/merged/cancelled by policy:
          active_feature.status = done
          return 404/no packet available
      return 404/no packet available

  claim packet via PacketService.claim(packet.id, worker_id)
```

Keep final state semantics aligned with existing `PacketState` and `wave_gate`.

## Completion policy

A feature is `done` when all its packets are in terminal accepted-success states.

For this packet, use the existing wave gate meaning:

- successful terminal: `MERGED`
- intentionally skipped: `CANCELLED`

Do not treat `FAILED`, `REJECTED`, `BLOCKED_RECOVERABLE`, or `BLOCKED_FINAL` as done.

If a feature has any degraded packets, mark `Feature.status = degraded` and do not start the next feature automatically.

## Required implementation areas

Likely files:

- `src/grace_control/api/routers/packets.py`
- `src/grace_control/services/packet_service.py`
- `src/grace_control/core/wave_gate.py`
- new small service if useful: `src/grace_control/services/queue_service.py`
- tests under `tests/`

Prefer creating `QueueService` so `/packets/claim` stays thin.

## Required tests

Add or update tests to cover:

### FIFO feature order

Given Feature A then Feature B, both with READY packets:

- first claim returns A's first packet;
- B is not claimed until A is done.

### Wave order

Given active Feature A with Wave 1 and Wave 2:

- packets from Wave 1 are claimed first;
- Wave 2 packets are not claimed until Wave 1 packets are `MERGED` or `CANCELLED`.

### Packet order inside wave

Given multiple READY packets in one wave:

- claim order is `Packet.created_at ASC`, then `Packet.id ASC`.

### Failed/rejected/blocked stops feature

Given Feature A has a packet in `FAILED`, `REJECTED`, `BLOCKED_RECOVERABLE`, or `BLOCKED_FINAL`:

- Feature A becomes `degraded`;
- Feature B does not start automatically.

### Single concurrency

Given `GRACE_MAX_CONCURRENCY=1` and any packet is `RUNNING`:

- claim returns no packet;
- no second packet enters `RUNNING`.

### Backward compatibility

Given existing feature status is `NOT_STARTED`:

- it is treated as queued;
- queue can activate it.

### Lease behavior

Given a packet already has a non-expired lease:

- it is not claimed by another worker.

If stale lease cleanup is not implemented, document current behavior and do not expand scope.

## API behavior

`POST /packets/claim` should keep the same response shape when a packet is claimed.

When no packet is claimable, keep current `404 No packets available`, but include a useful reason if possible:

- `running_packet_exists`
- `feature_degraded`
- `no_queued_features`
- `waiting_for_wave_completion`

Do not break existing clients if reason is absent.

## Admin/UI visibility

Minimal requirement:

- queue state is inferable from Feature.status, Wave.status, Packet.state.

Optional, if cheap:

- admin API/list view shows active feature and next queued feature.

No large admin UI redesign in this packet.

## Required report

Create:

`docs/work/REPORT_GRACE_QUEUE_DISCIPLINE_SINGLE_FEATURE_FIFO.md`

Report must include:

- base SHA / final SHA
- files changed
- implemented queue ordering rules
- tests added/updated
- manual smoke command if any
- known limitations
- confirmation that existing claim response shape remains compatible

## Required gates

Run the relevant test suite. At minimum:

```bash
pytest tests -q
```

If the project has narrower queue/API tests, run them explicitly too.

Also run any existing lint/contract checks if practical:

```bash
python3 scripts/check_orchestrator_contracts.py
```

Report pre-existing failures separately.

## Acceptance criteria

PASS only if:

1. Feature FIFO by `created_at, id` is deterministic.
2. Only one feature is active under `GRACE_MAX_CONCURRENCY=1`.
3. Packets are claimed wave-by-wave by `Wave.order`.
4. Packets inside wave are claimed by `Packet.created_at, Packet.id`.
5. A degraded feature blocks the queue and does not allow later features to start automatically.
6. Existing claim/release API shape is compatible.
7. Tests prove feature order, wave order, packet order, degraded stop, backward status compatibility, and single concurrency.
8. Report exists.

## Out of scope

- Parallel execution inside one wave.
- Priority queue beyond FIFO.
- Manual drag-and-drop queue UI.
- DB schema migration unless absolutely necessary.
- Product feature planning.
- Agent execution logic rewrite.
- Session resume/fork logic.

## Suggested commit message

`feat: enforce single-feature FIFO queue discipline`
