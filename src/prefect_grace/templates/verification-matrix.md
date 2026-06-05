# Verification Matrix
# Project: grace-control-plane
# Canonical reference: CANONICAL_DECISIONS.md, docs/openapi.json (regenerate via `make docs`)

## Overview

This document defines verification slices for the GRACE Control Plane MVP-0. Each slice maps to one feature from development-plan.xml and specifies gates, verification modules (VMs), commands, evidence, and acceptance profiles.

## Slices

### SLICE-DB-SCHEMA
- **Feature:** FEAT-GRACE-DB
- **Wave:** W01-FOUNDATION
- **Gate:** Gate 1 — All 7 tables created, CRUD works, SQLite-safe (no FOR UPDATE SKIP LOCKED)
- **Profile:** FAST
- **VMs:**
  - VM-DB-TABLES: Verify 7 tables exist with correct columns
  - VM-DB-CRUD: Verify create/read/update/delete for each entity
- **Commands:**
  - `pytest tests/test_db_schema.py -v`
- **Evidence:**
  - `test-results/db-schema.xml`

### SLICE-STATE-MACHINE
- **Feature:** FEAT-GRACE-STATE
- **Wave:** W01-FOUNDATION
- **Gate:** Gate 1 — All valid transitions work, invalid blocked, terminal states correct
- **Profile:** FAST
- **VMs:**
  - VM-STATE-TRANSITIONS: Verify DRAFT→READY, READY→RUNNING, RUNNING→ACCEPTED/REJECTED/FAILED
  - VM-STATE-TERMINAL: Verify MERGED, FAILED, CANCELLED are terminal
  - VM-STATE-INVALID: Verify REJECTED→READY (retry), DRAFT→RUNNING blocked
- **Commands:**
  - `pytest tests/test_state_machine.py -v`
- **Evidence:**
  - `test-results/state-machine.xml`

### SLICE-ADAPTER
- **Feature:** FEAT-GRACE-ADAPTER
- **Wave:** W02-EXECUTION
- **Depends on:** SLICE-DB-SCHEMA, SLICE-STATE-MACHINE
- **Gate:** Gate 2 — Adapter materializes packet → parseable by parse_packet_markdown, calls legacy runner, parses result
- **Profile:** NORMAL
- **VMs:**
  - VM-ADAPTER-MATERIALIZE: Materialized packet file is valid markdown, parseable by parse_packet_markdown
  - VM-ADAPTER-PARSE: E2EPacketRunnerResult correctly mapped to ExecutionResult
  - VM-ADAPTER-STATELESS: Adapter has no state transition calls (no mark_running/mark_accepted)
  - VM-ADAPTER-EXECUTE-AGENT: execute_agent=True and dry_run=False are passed
- **Commands:**
  - `pytest tests/test_packet_executor.py -v`
- **Evidence:**
  - `test-results/adapter.xml`

### SLICE-API
- **Feature:** FEAT-GRACE-API
- **Wave:** W02-EXECUTION
- **Depends on:** SLICE-ADAPTER
- **Gate:** Gate 2 — All 9 endpoints return correct status codes, error format, CORS configured
- **Profile:** NORMAL
- **VMs:**
  - VM-API-ENDPOINTS: GET /api/features/ (200), GET /api/features/{id} (200/404), GET /api/packets/ (200), GET /api/packets/{id} (200/404), POST /api/architect/plan (200/422), GET /api/workers/ (200), POST /api/workers/register (200), POST /api/workers/heartbeat (200/404), POST /api/packets/claim (200/404), POST /api/packets/{id}/release (200/404), GET /health (200)
  - VM-API-ERRORS: Error responses have {"error": {"code": "...", "message": "..."}} format
  - VM-API-CORS: allow_origin_regex configured, bind 127.0.0.1 (not 0.0.0.0)
  - VM-API-ARCHITECT-READY: Architect creates packets in READY state
  - VM-API-CLAIM-STATEFUL: Claim transitions READY→RUNNING, creates lease
- **Commands:**
  - `pytest tests/test_api.py -v`
- **Evidence:**
  - `test-results/api.xml`

### SLICE-WORKER
- **Feature:** FEAT-GRACE-WORKER
- **Wave:** W03-OPERATIONS
- **Depends on:** SLICE-API
- **Gate:** Gate 3 — Worker loop: register → heartbeat → claim → execute → release
- **Profile:** NORMAL
- **VMs:**
  - VM-WORKER-CLAIM: Worker claims READY packet, lease created, state → RUNNING
  - VM-WORKER-LEASE: Lease expires, packet returns to READY (lease_manager)
  - VM-WORKER-HEARTBEAT: Worker heartbeat updates last_heartbeat
  - VM-WORKER-RELEASE: Worker releases with accepted/rejected/failed result, state updates
  - VM-WORKER-INTEGRATION: Worker → adapter → legacy runner (integration test)
- **Commands:**
  - `pytest tests/test_worker.py -v`
- **Evidence:**
  - `test-results/worker.xml`

### SLICE-CLI
- **Feature:** FEAT-GRACE-CLI
- **Wave:** W03-OPERATIONS
- **Depends on:** SLICE-API
- **Gate:** Gate 2 — All CLI commands work, JSON output, Rich formatting
- **Profile:** FAST
- **VMs:**
  - VM-CLI-COMMANDS: grace architect plan, grace packet list, grace packet get, grace worker start, grace api start, grace health
  - VM-CLI-JSON: --json flag produces valid JSON envelope
- **Commands:**
  - `pytest tests/test_cli.py -v`
- **Evidence:**
  - `test-results/cli.xml`

### SLICE-E2E
- **Feature:** FEAT-GRACE-E2E
- **Wave:** W04-VERIFICATION
- **Depends on:** SLICE-WORKER, SLICE-CLI
- **Gate:** Gate 3 — Full vertical slice: architect plan → worker claim → adapter execute → release → ACCEPTED
- **Profile:** STRICT
- **VMs:**
  - VM-E2E-FLOW: Complete flow works end-to-end
  - VM-E2E-STATES: State transitions correct: READY→RUNNING→ACCEPTED
  - VM-E2E-EVIDENCE: Evidence saved to correct path
  - VM-E2E-DB-SHARING: API server and test share same DB via GRACE_DB_URL
- **Commands:**
  - `pytest tests/test_e2e_mvp0.py -v`
- **Evidence:**
  - `test-results/e2e.xml`
  - `state/grace.db` (SQLite database snapshot)

### SLICE-LEGACY
- **Feature:** FEAT-GRACE-LEGACY
- **Wave:** W04-VERIFICATION
- **Gate:** Gate 1 — Legacy code (flows/, platform/, tasks/) works with prefect_compat
- **Profile:** FAST
- **VMs:**
  - VM-LEGACY-IMPORT: No ImportError on legacy module imports
  - VM-LEGACY-RUNNER: run_e2e_packet runs in dry-run mode without errors
  - VM-LEGACY-COMPAT: try/except prefect imports in all legacy files
- **Commands:**
  - `python scripts/test_legacy.py`
- **Evidence:**
  - `test-results/legacy.xml`

## Test Tier Matrix

| Slice            | T0 (lint)        | T1 (touched)          | T2 (full)              | Profile |
|------------------|------------------|-----------------------|------------------------|---------|
| DB-SCHEMA        | ruff, mypy       | test_db_schema        | —                      | FAST    |
| STATE-MACHINE    | ruff, mypy       | test_state_machine    | —                      | FAST    |
| ADAPTER          | ruff, mypy       | test_packet_executor  | test_packet_executor   | NORMAL  |
| API              | ruff, mypy       | test_api              | test_api (all routes)  | NORMAL  |
| WORKER           | ruff, mypy       | test_worker           | test_worker (integration) | NORMAL |
| CLI              | ruff, mypy       | test_cli (smoke)      | —                      | FAST    |
| E2E              | ruff, mypy       | —                     | test_e2e_mvp0          | STRICT  |
| LEGACY           | —                | test_legacy           | —                      | FAST    |

### Acceptance Rules by Profile

- **FAST:** T0 (lint) + T1 (touched tests) must pass. No reviewer. Auto-accept.
- **NORMAL:** T0 + T1 + T2 must pass. Reviewer optional.
- **STRICT:** T0 + T1 + T2 must pass. Reviewer **required**.

## Dependency Graph

```
SLICE-LEGACY (Phase 0, independent)
SLICE-DB-SCHEMA ──→ SLICE-STATE-MACHINE ──→ SLICE-ADAPTER ──→ SLICE-API
                                                                     │
                                                              ┌──────┴──────┐
                                                              ↓              ↓
                                                       SLICE-WORKER    SLICE-CLI
                                                              │              │
                                                              └──────┬───────┘
                                                                     ↓
                                                               SLICE-E2E
```

### Wave Grouping

```
W01-FOUNDATION:    SLICE-DB-SCHEMA, SLICE-STATE-MACHINE
W02-EXECUTION:     SLICE-ADAPTER, SLICE-API
W03-OPERATIONS:    SLICE-WORKER, SLICE-CLI
W04-VERIFICATION:  SLICE-E2E, SLICE-LEGACY
```

### Execution Order

W01 → W02 → W03 → W04 (sequential). Within waves, slices may be developed in any order but must all pass before the wave gate.

## Verification Checklist

### Per-Slice Checklist
- [ ] Slice gate criteria met
- [ ] All VMs pass
- [ ] Evidence collected (XML reports)
- [ ] No regressions in dependent slices

### Integration Checklist
- [ ] All 8 slices pass sequentially
- [ ] Full W01→W02→W03→W04 pipeline passes
- [ ] Verification script (`scripts/verify_mvp0.sh`) completes with exit 0

### Quality Gates
- [ ] All ruff checks pass (no errors)
- [ ] All mypy checks pass (no errors in strict modules)
- [ ] All pytest tests pass (no failures)
- [ ] Coverage meets threshold: 80%+ for core modules

## Verification History

| Date       | Version | Verifier    | Status | Notes |
|------------|---------|-------------|--------|-------|
| 2026-05-31 | 0.1.0   | —           | planned | MVP-0 not yet implemented |

## References

- CANONICAL_DECISIONS.md — canonical architecture decisions
- docs/openapi.json — auto-generated API contract (regenerate via `make docs`)
- tasks/PHASE_1_CORE_REVISED.md — DB + state machine + adapter specs
- tasks/PHASE_2_API_WORKER_REVISED.md — API + worker specs
- tasks/PHASE_3_CLI_E2E_REVISED.md — CLI + E2E test specs
