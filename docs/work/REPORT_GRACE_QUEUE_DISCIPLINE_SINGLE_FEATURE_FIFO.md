# Report: GRACE single-feature FIFO queue discipline

**Status:** PASS
**Date:** 2026-06-12

## Commits
- Base: `c04f8ce`
- Final SHA: (current HEAD)

## Files changed

| File | Change |
|---|---|
| `src/grace_control/services/queue_service.py` | New — `claim_next()` implements FIFO queue discipline |
| `src/grace_control/api/routers/packets.py` | `/packets/claim` uses `claim_next` instead of broad READY scan |
| `tests/grace_control/services/test_queue_service.py` | New — 13 tests for queue behavior |

## Queue ordering rules

- **Feature FIFO**: `Feature.created_at ASC, Feature.id ASC`
- **Wave order**: `Wave.order ASC, Wave.created_at ASC, Wave.id ASC`
- **Single active feature**: `GRACE_MAX_CONCURRENCY=1` — one active feature at a time
- **Wave gating**: later waves not claimable until earlier wave packets are terminal
- **Packet order**: `Packet.created_at ASC, Packet.id ASC` inside the same wave
- **Degraded stop**: `FAILED`/`REJECTED`/`BLOCKED*` packets → `Feature.status = degraded` → queue blocked
- **Feature done**: all packets `MERGED`/`CANCELLED` → `Feature.status = done`
- **Backward compat**: `NOT_STARTED` treated as `queued`

## Claim algorithm

1. If `GRACE_MAX_CONCURRENCY=1` and any `RUNNING` → return `running_packet_exists`
2. Find `active` feature, or promote oldest `queued`/`NOT_STARTED` → `active`
3. Run wave gate for the feature
4. If feature has degraded packets → `feature_degraded`
5. Find earliest wave with READY packets
6. Find earliest READY packet in that wave
7. Return packet_id or descriptive reason

## Tests (13)

| Test | What |
|---|---|
| `test_oldest_feature_activated_first` | Older feature gets activated first |
| `test_feature_order_by_id_tiebreaker` | Same timestamp → id ASC tiebreak |
| `test_wave_order` | Wave 1 before Wave 2 |
| `test_packet_order_inside_wave` | Older packet first |
| `test_packet_order_by_id_tiebreaker` | Same timestamp → id ASC |
| `test_degraded_packet_blocks_feature` | REJECTED → degraded |
| `test_degraded_feature_does_not_block_activation` | Degraded stops queue |
| `test_single_concurrency_blocks_second_claim` | RUNNING blocks claim |
| `test_second_feature_not_claimable_while_first_active` | FIFO with actual PacketService.claim |
| `test_no_running_packet_allows_claim` | READY → claimable |
| `test_not_started_treated_as_queued` | Legacy NOT_STARTED works |
| `test_feature_marked_active_after_claim` | Status → active |
| `test_all_merged_makes_feature_done` | All merged → done |
| `test_wave1_draft_wave2_ready_no_claim` | Wave 1 DRAFT blocks Wave 2 |
| `test_wave1_accepted_wave2_ready_no_claim` | Wave 1 ACCEPTED blocks Wave 2 (only MERGED counts) |
| `test_wave1_merged_wave2_ready_claim_wave2` | Wave 1 MERGED → Wave 2 claimable |
| `test_all_accepted_feature_not_done` | ACCEPTED packets don't trigger feature_done |

## Known limitations
- `check_wave_gates` runs for ALL features, not just the active one (minor, not a correctness issue)
- Stale lease cleanup not implemented (existing behavior unchanged)
- Claim response shape unchanged — backward compatible
- 10 packet API test failures are pre-existing (`ImportError: enrich_packet`)
