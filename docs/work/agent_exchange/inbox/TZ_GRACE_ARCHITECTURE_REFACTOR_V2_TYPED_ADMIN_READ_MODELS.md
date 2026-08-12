# TZ_GRACE_ARCHITECTURE_REFACTOR_V2_TYPED_ADMIN_READ_MODELS — Packet 7: bounded typed Admin read boundaries

## Packet identity

- `TZ_NAME`: `TZ_GRACE_ARCHITECTURE_REFACTOR_V2_TYPED_ADMIN_READ_MODELS`
- Role: Coder
- Repository: `/opt/grace-orchestrator`
- Upstream: `origin/main`
- Parent programme: `docs/work/TZ_GRACE_ARCHITECTURE_REFACTOR_V2.md`
- Normative implementation detail: `docs/work/WORKER_GRACE_ARCHITECTURE_REFACTOR_V2.md`, **Wave 5 only**.
- Previous named packet `TZ_GRACE_ARCHITECTURE_REFACTOR_V2_LIFECYCLE_SERVICE_EXTRACTION` is ACCEPTED.
- Implement **only bounded typed Admin read models** in this packet.
- Do **not** start dead-code/repo hygiene, CI consolidation, mutation-service cleanup, lifecycle follow-up cleanup, API redesign, schema changes, or any later wave.

This packet is self-contained. Do not invent or start another packet. Only Architect ACCEPT authorizes the next named TZ.

## Mandatory sync before work

Before inspecting implementation files or editing anything:

```bash
cd /opt/grace-orchestrator
git switch main
git fetch origin main
git merge --ff-only origin/main
git status --short
git rev-parse HEAD
```

Record synced base SHA and initial `git status --short` in the submission.

Preserve unrelated pre-existing untracked files, including `.env.bak-mini-endpoint-20260705170600` and `parse_list.py` if still present. Do not use `git reset --hard` or `git clean`.

Do not create `state.json`, lock files, orchestration metadata, or repository-side web-orch state.

---

# Objective

Reduce the most dangerous shared `dict[str, Any]` contracts at Admin read boundaries while preserving **exactly the current external JSON shapes**.

This is deliberately **not** a full typing migration. Do not convert every local dictionary. Type only contracts that cross service/API/template boundaries or are large enough that multiple magic-key readers already depend on them.

Preferred implementation style for this repository: frozen, slotted dataclasses with explicit serialization methods, e.g.:

```python
@dataclass(frozen=True, slots=True)
class SomeReadModel:
    ...

    def to_dict(self) -> dict[str, Any]:
        ...
```

Pydantic is allowed only if current repository evidence makes it clearly smaller/safer; do not add a new dependency for this packet.

Create the bounded model module:

`src/grace_control/services/admin_read_models.py`

Do not create a generic `models.py`, `dto.py`, BaseDTO hierarchy, model registry, serialization framework, service locator, or reflection-driven mapper.

---

# Frozen compatibility invariants

1. No API route, method, status code, response key, key spelling, nesting level, or list/dict shape changes.
2. No template-facing key changes.
3. Do not rename existing keys for style (`project_key`, `fetched_at`, `duration_ms`, `current_elapsed`, `coverage`, `attention`, etc.).
4. Do not serialize dataclass reprs or objects directly through FastAPI/templates. Public boundaries still receive plain JSON-safe dictionaries/lists.
5. No DB schema or ORM changes.
6. No lifecycle API response changes from Packet 6.
7. No new mutation/control behavior.
8. No conversion of local one-function scratch dictionaries unless required to support one of the named shared models below.
9. No giant all-purpose Admin model mirroring `AdminAggregationService` or `AdminCrossProjectService`.
10. No new GRC005/GRC012 allowlist entries. Touched source files remain <=1000 physical lines; target <=800 where practical.

---

# Baseline inventory before edits

Inspect at minimum:

```text
src/grace_control/services/admin_cross_project_helpers.py
src/grace_control/services/admin_cross_project_overview_service.py
src/grace_control/services/admin_cross_project_query_service.py
src/grace_control/services/admin_overview_read_service.py
src/grace_control/services/admin_packet_read_service.py
src/grace_control/services/admin_pipeline_read_service.py
src/grace_control/services/admin_aggregation_service.py
src/grace_control/services/admin_control_center_project_service.py
src/grace_control/services/admin_control_center_packet_service.py
src/grace_control/services/worker_read_service.py
src/grace_control/services/lifecycle_service.py
src/grace_control/api/routers/admin.py
src/grace_control/api/routers/admin_controls.py
```

Also search for the exact keys/functions below before deciding each conversion:

```bash
rg -n 'projects_total|projects_responded|projects_failed|projects_disabled|projects_partial' src tests
rg -n 'severity.*project_key|detail_url|latest_attention|attention' src/grace_control/services tests
rg -n 'supervisor_alive|api_alive|workers_alive|db_ok|code_sha|version' src/grace_control/services tests
rg -n 'current_elapsed|current_packet_id|last_heartbeat|started_at' src/grace_control/services tests
rg -n 'tokens_in|tokens_out|integration_base_sha|elapsed_seconds|run_number' src/grace_control/services tests
rg -n 'target_tab|duration_ms|derive_pipeline|derive_stages' src/grace_control/services tests
```

For every selected model, first capture the current exact key set/types in characterization tests. The final implementation may be in the same commit, but the expected baseline shape must be explicit in tests rather than inferred from the new model implementation.

---

# Required models and exact boundaries

## 1. `CrossProjectCoverage`

Create a typed model for the **full overview/diagnostics coverage shape currently produced by** `admin_cross_project_helpers._coverage()`:

```text
projects_total
projects_responded
projects_failed
projects_disabled
projects_partial
partial
```

Requirements:

- field types should match current semantics (`int` counts, `bool` partial);
- explicit `to_dict()` must emit exactly those six keys;
- use it in `_coverage()` / overview + diagnostics paths that already return this six-key shape;
- do **not** silently widen the smaller `_coverage_from_results()` three-key shape by adding disabled/partial keys. That is a distinct existing JSON contract unless characterization proves otherwise;
- do not rename `projects_partial` to something “cleaner”.

## 2. `AttentionItem`

Create a typed model for the normalized attention row currently built by `_attention_item()` and also manually duplicated for disabled projects:

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

Requirements:

- preserve nullable values exactly where the current code allows them (`entity_type`, `entity_id`, `timestamp`);
- `_attention_item()` should construct/serialize the model rather than hand-building a dict;
- remove the disabled-project duplicate dictionary by constructing the same model there;
- `_sort_attention()` and public overview/diagnostics results must continue to receive/emit plain mappings with identical keys/values;
- do not introduce severity enums or validation that rejects currently tolerated values in this wave.

## 3. `ProjectHealthSnapshot`

Type the local Admin system-health contract produced by `AdminOverviewReadService.get_system_health()`:

```text
supervisor_alive
api_alive
workers_alive
db_ok
code_sha
version
```

Requirements:

- preserve exact current defaults and final JSON values;
- public `get_system_health()` still returns a plain dictionary unless changing the internal return type can be proven not to leak through current facade/API call sites; safest default is typed construction + `.to_dict()` at the service boundary;
- do not merge this with the different lifecycle `/health/full` DTO from Packet 6;
- do not use this packet to refactor the existing AdminOverviewReadService infrastructure reads (env/state/git). Wave 5 is typing only; architecture cleanup there would be scope creep.

## 4. `WorkerSnapshot` — Admin worker shape only

Type the worker row currently emitted by `AdminOverviewReadService._worker_to_dict()`:

```text
id
status
current_packet_id
last_heartbeat
started_at
current_elapsed
```

Requirements:

- preserve exact timestamp and elapsed semantics;
- use the model for `get_overview()` workers and `get_workers()` rows;
- **do not unify it with Packet 6 `WorkerReadService` lifecycle rows**, whose external shape intentionally uses `worker_id` and omits `current_elapsed`;
- do not change `/api/admin/lifecycle/status` worker JSON.

This distinction is mandatory: two similar contracts with different keys are not permission to “standardize” the public API in this packet.

## 5. `PacketRunSummary`

Type the rich run-summary row currently produced by `AdminPacketReadService.get_packet_runs()`.

Characterize and preserve the current exact fields, including at least the existing identifiers/status/timing/model/token/cost/base SHA fields such as:

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

Requirements:

- derive the exact baseline key set from the synced source and lock it in a characterization test;
- introduce one small serializer/helper so `get_packet_runs()` no longer assembles that large row ad hoc;
- preserve numeric/null behavior for cost/tokens/timestamps exactly;
- do not automatically replace the smaller `runs_summary` shape inside `get_packet_detail()` unless it is proven to have the exact same public contract. If it is intentionally a subset, leave it a subset rather than adding keys.

## 6. `PipelineStageView` — convert only the canonical shared stage shape

Inspect all stage dictionaries produced by `AdminPipelineReadService` before editing.

Create `PipelineStageView` only for the canonical repeated stage-card shape if characterization proves those rows share a stable key contract (for example keys such as `key`, `label`, `status`, `started_at`, `finished_at`, `duration_ms`, `meta`, `target_tab`).

Rules:

- if all operator pipeline stage rows share the same baseline keys, convert their repeated construction to `PipelineStageView` and serialize to the exact old dict shape;
- if there are legitimately different stage families with different key presence, do **not** force one model to add absent keys. Either:
  - model only the genuinely shared canonical family; or
  - leave heterogeneous local dictionaries alone and document the evidence in submission.
- no inheritance hierarchy of stage DTOs;
- no enum migration for status in this wave;
- no behavior changes to pipeline derivation.

`PipelineStageView` is therefore evidence-gated rather than an excuse to normalize externally visible JSON.

---

# Explicit non-goals / avoid over-conversion

Leave these alone unless directly necessary for the models above:

- event row dictionaries;
- log row dictionaries;
- raw OpenAPI/explorer payloads;
- error DTOs;
- feature/wave tree local dictionaries;
- maintenance DTOs;
- lifecycle status/version/health DTOs;
- mutation/control DTOs;
- ORM models;
- `_RemoteResult` transport model (already typed and not part of this wave).

Do not convert `_coverage_from_results()` merely for symmetry if that changes its smaller key set.

---

# Serialization rules

Every read model must have an explicit, boring serialization boundary. Preferred:

```python
model.to_dict()
```

Do not use:

```python
model.__dict__
asdict(model)  # unless nested behavior is proven and deliberately wanted
jsonable_encoder(model) as an implicit contract
reflection over dataclass fields
```

The goal is to make JSON shape visible in code review.

Nested `dict[str, Any]` fields are allowed where the existing contract genuinely contains opaque nested data, but do not annotate every field as `Any` if a scalar/null type is obvious.

Models should be immutable (`frozen=True`) and slotted unless repository constraints make that impossible.

---

# Characterization tests

Add focused tests, preferred path:

`tests/grace_control/services/test_admin_read_models.py`

At minimum lock:

1. `CrossProjectCoverage.to_dict()` exact six-key set and values.
2. `AttentionItem.to_dict()` exact ten-key set, including nullable fields.
3. `ProjectHealthSnapshot.to_dict()` exact six-key set.
4. `WorkerSnapshot.to_dict()` exact Admin worker key set (`id`, not `worker_id`).
5. `PacketRunSummary.to_dict()` exact baseline rich-run key set.
6. `PipelineStageView` exact key set only if implemented after characterization.

Also add integration/characterization assertions in existing service tests so the model serializer and service output cannot drift independently.

---

# Architecture guard

Add:

`tests/grace_control/architecture/test_admin_read_models_boundary.py`

At minimum assert:

- `admin_read_models.py` exists and defines the required non-gated models above;
- models are dataclasses/frozen or the chosen equivalent immutable project style;
- `admin_read_models.py` imports no FastAPI, SQLAlchemy ORM entities, filesystem/process infrastructure, project registry/service facades, or router modules;
- model module contains no service locator/base DTO/model registry;
- `AttentionItem` is used by `_attention_item()` and disabled-project attention instead of two separate hand-written ten-key dict literals;
- `CrossProjectCoverage` is used only where the six-key shape is already expected and does not cause `_coverage_from_results()` to gain keys;
- Admin worker typing does not change lifecycle `worker_id` JSON contract;
- no public boundary returns raw dataclass/model objects where current callers expect dictionaries.

Keep the guard structural and focused; do not create a fragile repository-wide ban on `dict[str, Any]`.

---

# Required regression proof

Run at minimum the currently active tests covering these boundaries. Discover exact names if paths moved, but expected set includes:

```bash
PYTHONPATH=src .venv/bin/pytest -q \
  tests/grace_control/services/test_admin_read_models.py \
  tests/grace_control/services/test_admin_aggregation_service.py \
  tests/grace_control/api/test_admin_router.py \
  tests/grace_control/api/test_admin_pipeline_contract.py \
  tests/grace_control/api/test_admin_cross_project_observability.py \
  tests/grace_control/architecture/test_admin_read_models_boundary.py
```

Also run current Control Center tests that consume project cards/coverage/attention/packet runs, including the active Stage07 service/matrix tests if present. Do not require an unrelated slow subprocess topology fixture to become a code-cleanup task; if such a fixture has a pre-existing environment readiness timeout, document it separately and prove the in-process/service contracts pass.

Because `WorkerSnapshot` is explicitly **not** the lifecycle worker shape, also rerun:

```bash
PYTHONPATH=src .venv/bin/pytest -q tests/supervisor/test_lifecycle_api.py
```

Then:

```bash
python3 scripts/grace_lint.py <all-changed-python-files-and-tests>
ruff check <all-changed-python-files-and-tests>
python3 -m py_compile <all-changed-python-files>
git diff --check
```

Touched files must pass focused lint. Do not broaden into repository-wide legacy lint cleanup.

---

# Acceptance criteria

PASS only if all are true:

1. `admin_read_models.py` is bounded and contains no infrastructure/business-service logic.
2. `CrossProjectCoverage`, `AttentionItem`, `ProjectHealthSnapshot`, `WorkerSnapshot`, and `PacketRunSummary` are typed and serialized explicitly.
3. `PipelineStageView` is implemented only if characterization proves a stable repeated stage shape; otherwise submission documents why it was correctly left unconverted.
4. Public JSON keys/nesting/types are unchanged.
5. Full six-key cross-project coverage does not accidentally widen the existing smaller three-key coverage contract.
6. Disabled-project attention uses the same `AttentionItem` model as normal attention construction.
7. Admin `WorkerSnapshot` does not alter lifecycle worker JSON (`worker_id` remains `worker_id`).
8. Rich packet run summary remains exact; smaller packet-detail run subsets are not widened merely for reuse.
9. No DTO hierarchy/registry/generic serializer/service locator is introduced.
10. No local one-off dict conversion campaign occurs outside named boundaries.
11. Characterization + architecture guard tests pass.
12. Relevant Admin/Hub/Control Center/lifecycle regression tests pass or any unrelated known environment-only topology timeout is explicitly separated with equivalent in-process proof.
13. No schema, route, mutation, lifecycle, or later-wave behavior changes are included.
14. No new lint/size allowlist exceptions are added.

---

# Required submission

After implementation, commit and push the implementation to `origin/main`.

Create only:

`docs/work/agent_exchange/outbox/TZ_GRACE_ARCHITECTURE_REFACTOR_V2_TYPED_ADMIN_READ_MODELS_SUBMISSION.md`

It must begin with exactly:

```text
WEB_ORCH_REPORT: SUBMISSION TZ_GRACE_ARCHITECTURE_REFACTOR_V2_TYPED_ADMIN_READ_MODELS
WEB_ORCH_STATUS: DONE
WEB_ORCH_COMMIT: <full-implementation-commit-sha>
WEB_ORCH_CHECKS: PASS
```

`WEB_ORCH_COMMIT` must be the full 40-character actual implementation commit, not the submission-document commit.

Submission body must include:

- synced base SHA;
- initial status/untracked preservation;
- exact changed files;
- exact models added and each serialized key set;
- explicit statement that Admin WorkerSnapshot and lifecycle worker shape remain distinct;
- PipelineStageView evidence and whether it was converted or intentionally left local;
- characterization evidence for JSON-shape preservation;
- exact tests/check counts;
- any unrelated pre-existing environment-only failure separately identified;
- confirmation that no Wave 6+ work was started.

Do not invent or start the next packet. Only Architect ACCEPT authorizes it.
