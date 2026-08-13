# TZ_GRACE_ARCHITECTURE_REFACTOR_V2_07_TYPED_ADMIN_READ_MODELS — Packet 07: bounded typed Admin read boundaries

## Packet identity

- `TZ_NAME`: `TZ_GRACE_ARCHITECTURE_REFACTOR_V2_07_TYPED_ADMIN_READ_MODELS`
- Role: Coder
- Repository: `/opt/grace-orchestrator`
- Upstream: `origin/main`
- Parent source: `docs/work/TZ_GRACE_ARCHITECTURE_REFACTOR_V2.md`
- Normative detail: Architecture Refactor V2 Wave 5 — bounded typed Admin read models only.
- Previous new-cycle packet `TZ_GRACE_ARCHITECTURE_REFACTOR_V2_06_LIFECYCLE_SERVICE_EXTRACTION` is ACCEPTED.
- Historical agent-exchange packets from earlier cycles are evidence only. Do not edit/reuse their submission/review files.

Implement only this named packet. Do not start dead-code/repo hygiene, CI consolidation, mutation refactoring, lifecycle follow-up cleanup, API redesign, schema changes, or any later wave.

## Mandatory fast-forward sync

Before inspecting implementation files or editing anything:

```bash
cd /opt/grace-orchestrator
git switch main
git fetch origin --prune
git pull --ff-only origin main
git status --short --branch
git rev-parse HEAD
```

Record synced base SHA and initial status. Preserve unrelated untracked files. Do not use `git reset --hard`, `git clean`, destructive checkout, repo-side `state.json`, lock files, or orchestration metadata.

## Current-state rule

This new cycle verifies/refines a repository that may already contain the earlier accepted Wave 5 implementation.

1. Current synced `main` is authoritative.
2. Audit actual current code first; do not recreate old `dict[str, Any]` implementations merely because historical TZs describe the pre-refactor state.
3. If every acceptance criterion is already satisfied, run the required verification and submit a **verified no-op** using synced `HEAD` as `WEB_ORCH_COMMIT`.
4. Do not manufacture source edits merely to produce an implementation commit.
5. If a gap exists, make only the smallest in-scope correction, commit/push it, and report the actual implementation SHA.

## Objective

Keep the most important shared Admin read boundaries typed internally while preserving **exactly** the accepted external JSON dictionaries/lists.

Preferred bounded model module:

`src/grace_control/services/admin_read_models.py`

Preferred style:

```python
@dataclass(frozen=True, slots=True)
class SomeReadModel:
    ...

    def to_dict(self) -> dict[str, Any]:
        ...
```

This is not a broad typing campaign. Do not replace every local dictionary, introduce a DTO hierarchy/registry, generic serializer, `BaseDTO`, service locator, reflection mapper, or new dependency.

## Frozen compatibility invariants

Preserve:

- all API routes, status codes, response keys, key spelling, nesting and list/dict shapes;
- all template-facing keys;
- DB schema/ORM models/Alembic;
- Packet 06 lifecycle status/version/health JSON contracts;
- mutation/control behavior;
- packet lifecycle/execution/reviewer/recovery/merge semantics;
- existing smaller-vs-larger DTO distinctions where key sets differ.

Public service/API/template boundaries must continue to receive plain JSON-safe dictionaries/lists, not raw dataclass objects.

Do not add GRC005/GRC012 allowlist entries. No touched source file may exceed 1000 physical lines; target <=800 where practical.

## Audit before edits

Inspect current versions of at least:

```text
src/grace_control/services/admin_read_models.py
src/grace_control/services/admin_cross_project_helpers.py
src/grace_control/services/admin_cross_project_overview_service.py
src/grace_control/services/admin_cross_project_query_service.py
src/grace_control/services/admin_overview_read_service.py
src/grace_control/services/admin_packet_read_service.py
src/grace_control/services/admin_pipeline_read_service.py
src/grace_control/services/admin_aggregation_service.py
src/grace_control/services/worker_read_service.py
src/grace_control/services/lifecycle_service.py

tests/grace_control/services/test_admin_read_models.py
tests/grace_control/architecture/test_admin_read_models_boundary.py
```

Some preferred files may already exist. Treat current code as authoritative and verify responsibilities/key sets rather than recreating historical work.

Run targeted key/model inventory:

```bash
rg -n 'CrossProjectCoverage|AttentionItem|ProjectHealthSnapshot|WorkerSnapshot|PacketRunSummary|PipelineStageView' \
  src/grace_control/services tests/grace_control || true

rg -n 'projects_total|projects_responded|projects_failed|projects_disabled|projects_partial' \
  src/grace_control/services tests/grace_control || true

rg -n 'severity|project_key|project_name|detail_url|latest_attention' \
  src/grace_control/services/admin_cross_project_* tests/grace_control || true

rg -n 'tokens_in|tokens_out|integration_base_sha|elapsed_seconds|run_number' \
  src/grace_control/services/admin_* tests/grace_control || true
```

## Required target state

### 1. `admin_read_models.py` stays bounded and infrastructure-free

It must define the accepted bounded immutable read models and explicit serializers without importing FastAPI, SQLAlchemy ORM entities, routers, project service facades, filesystem/process infrastructure, service locators or generic serialization frameworks.

Expected non-gated models:

- `CrossProjectCoverage`
- `AttentionItem`
- `ProjectHealthSnapshot`
- `WorkerSnapshot`
- `PacketRunSummary`

Expected canonical pipeline model when the accepted source has the stable repeated stage shape:

- `PipelineStageView`

All must serialize through explicit `to_dict()` or an equivalently explicit boring method. Do not expose `__dict__`, reflection or implicit framework serialization as the contract.

### 2. `CrossProjectCoverage` preserves the full six-key contract only

The full coverage shape remains exactly:

```text
projects_total
projects_responded
projects_failed
projects_disabled
projects_partial
partial
```

The smaller `_coverage_from_results()` contract must **not** be widened merely for symmetry if its accepted external shape is smaller.

### 3. `AttentionItem` is the single normalized attention-row constructor

Preserve exactly the accepted attention keys:

```text
severity
project_key
project_name
kind
entity_type
entity_id
title
reason
timestamp
detail_url
```

Normal attention construction and disabled-project attention must use the same typed model/serializer rather than duplicate handwritten ten-key dictionaries.

Do not add severity enums or validation that rejects currently accepted values.

### 4. `ProjectHealthSnapshot` remains distinct from lifecycle health

The local Admin system-health shape remains exactly the accepted six-key contract:

```text
supervisor_alive
api_alive
workers_alive
db_ok
code_sha
version
```

Do not merge it with Packet 06 `/api/admin/lifecycle/health/full`.

### 5. `WorkerSnapshot` is the Admin worker shape, not lifecycle worker shape

Admin worker rows remain the accepted shape:

```text
id
status
current_packet_id
last_heartbeat
started_at
current_elapsed
```

Packet 06 `WorkerReadService` lifecycle rows intentionally use `worker_id` and a different key set. Do not “standardize” one into the other.

### 6. `PacketRunSummary` preserves the rich packet-runs row exactly

The rich shared run summary must retain the accepted baseline keys and null/numeric semantics, including at least:

```text
run_id
run_number
worker_id
executor_id
model
status
duration_ms
started_at
finished_at
elapsed_seconds
is_running
tokens_in
tokens_out
cost_usd
base_sha
integration_base_sha
```

Do not widen the smaller run subset inside packet-detail merely to reuse this model if that subset intentionally has fewer keys.

### 7. `PipelineStageView` only models the canonical repeated stage shape

If current accepted code already uses `PipelineStageView`, verify its explicit serializer preserves the exact repeated stage-card keys and values.

Do not force heterogeneous stage families into one model and do not alter pipeline behavior/status semantics.

### 8. No raw model leakage

Every current public service/router/template consumer that historically receives dict/list JSON must still receive dict/list JSON. Typed models are internal construction boundaries, not new API return objects.

## Architecture guard

A durable guard, preferred path:

`tests/grace_control/architecture/test_admin_read_models_boundary.py`

must prove directly or equivalently:

1. bounded required models exist;
2. model module is infrastructure/router/service-facade free;
3. serializers are explicit and public boundaries emit dictionaries;
4. full six-key coverage typing does not widen the smaller coverage contract;
5. disabled-project and normal attention use `AttentionItem` rather than duplicate full literals;
6. Admin `WorkerSnapshot` does not change lifecycle `worker_id` JSON;
7. rich `PacketRunSummary` does not silently widen smaller packet-detail run rows;
8. no DTO registry/base hierarchy/service locator/generic serializer is introduced.

Keep the guard focused; do not add a repository-wide ban on `dict[str, Any]`.

## Required verification

Run at minimum current equivalents of:

```bash
PYTHONPATH=src .venv/bin/pytest -q tests/grace_control/services/test_admin_read_models.py
PYTHONPATH=src .venv/bin/pytest -q tests/grace_control/architecture/test_admin_read_models_boundary.py
PYTHONPATH=src .venv/bin/pytest -q tests/grace_control/services/test_admin_aggregation_service.py
PYTHONPATH=src .venv/bin/pytest -q tests/grace_control/api/test_admin_router.py
PYTHONPATH=src .venv/bin/pytest -q tests/grace_control/api/test_admin_pipeline_contract.py
PYTHONPATH=src .venv/bin/pytest -q tests/grace_control/api/test_admin_cross_project_observability.py
PYTHONPATH=src .venv/bin/pytest -q tests/supervisor/test_lifecycle_api.py
```

Also run current Control Center regressions that consume project cards/coverage/attention/packet runs when present.

Then run:

```bash
make lint
make docs-check
make hygiene
python3 -m py_compile <changed-python-files-if-any>
git diff --check
```

For baseline-aware lint, report canonical `make lint` success separately from raw Ruff/GraceLint debt.

If the packet is verified no-op, still run the characterization/architecture/regression checks and report exact counts; historical submissions are not proof for this cycle.

## Submission protocol

If corrections are required, commit/push them and use the full 40-character implementation SHA. If current `main` already satisfies the packet, use synced `HEAD` and explicitly state `verified no-op`.

Create only:

`docs/work/agent_exchange/outbox/TZ_GRACE_ARCHITECTURE_REFACTOR_V2_07_TYPED_ADMIN_READ_MODELS_SUBMISSION.md`

It MUST begin exactly:

```text
WEB_ORCH_REPORT: SUBMISSION TZ_GRACE_ARCHITECTURE_REFACTOR_V2_07_TYPED_ADMIN_READ_MODELS
WEB_ORCH_STATUS: DONE
WEB_ORCH_COMMIT: <full-40-character-implementation-sha>
WEB_ORCH_CHECKS: PASS
```

Then include:

- synced base SHA and initial status;
- implementation SHA or verified-no-op statement;
- exact models/serializer ownership evidence;
- external JSON compatibility evidence for each typed boundary;
- proof that Admin vs lifecycle worker contracts remain distinct;
- coverage/attention/run-summary/stage characterization evidence;
- exact targeted test counts/check results;
- changed paths, or `none` for verified no-op.

Do not create/start the next packet. Wait for Architect ACCEPT/REVIEW.

## Acceptance criteria

Architect ACCEPT requires all of:

1. bounded immutable Admin read models exist and remain infrastructure-free;
2. explicit serialization preserves exact external JSON keys/types/nesting;
3. `CrossProjectCoverage`, `AttentionItem`, `ProjectHealthSnapshot`, `WorkerSnapshot`, and `PacketRunSummary` are correctly used at their accepted shared boundaries;
4. `PipelineStageView` is used only for the canonical repeated stage shape when present;
5. smaller coverage and packet-detail run contracts are not widened;
6. Admin worker typing does not alter lifecycle worker JSON;
7. no raw dataclass/model objects leak to existing public boundaries;
8. no DTO hierarchy/registry/generic serializer/service locator is introduced;
9. no API/DB/lifecycle/control/packet semantic drift or later-wave work is mixed in;
10. architecture/characterization/regression checks pass and are truthfully reported;
11. no lint/size allowlist expansion is introduced;
12. submission follows the exact named-file protocol with a full SHA.
