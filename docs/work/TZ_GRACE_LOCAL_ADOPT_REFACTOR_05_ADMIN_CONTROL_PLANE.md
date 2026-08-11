# TZ — Grace Local Adopt refactor / 05 Admin control plane

Status: READY FOR CODER
Parent: `TZ_GRACE_LOCAL_ADOPT_REFACTOR_MASTER.md`
Priority: P0
Dependency: block 01

Hard-limit targets:

- `src/grace_control/services/admin_aggregation_service.py`
- `src/grace_control/services/admin_control_center.py`

Near-limit admin files are handled in block 06 after these boundaries settle.

## 1. Problem

The admin/control-plane area has grown by adding surfaces to a small number of broad modules. Two service modules now exceed the 1000-line hard limit and multiple neighbouring router/service files are close to it.

This block establishes clear read/control ownership without changing the public admin API.

## 2. Global admin constraints

This is a structural refactor only.

Preserve:

- every current HTTP path and method;
- request schemas;
- response DTO keys/shapes;
- HTTP status behaviour;
- auth/security dependencies;
- project selection / multi-project semantics;
- read-only vs mutation boundaries;
- log/event/result field names consumed by the UI;
- filesystem safety checks;
- existing template/UI expectations;
- OpenAPI surface.

Do not perform a UI redesign in this block.

---

# Part A — `admin_aggregation_service.py`

## A1. Current responsibility problem

`AdminAggregationService` is nominally an admin-friendly read-side aggregator but the module now contains multiple independent surfaces such as:

- overview/stats;
- packet detail/run summaries;
- evidence/artifact tree/preview metadata;
- sessions/logs;
- blocking/recommendation data;
- search;
- system health;
- filesystem/artifact classification helpers.

This should become a thin read facade backed by focused read-side components.

## A2. Goal

After refactor:

- `admin_aggregation_service.py` <=1000 lines, preferred <=500-700;
- public `AdminAggregationService` remains compatible;
- endpoint DTOs are byte-for-byte/shape-compatible where deterministic;
- no new mutation responsibility enters the read-side service.

## A3. Preferred extraction boundaries

Exact names can follow repository conventions.

### Overview/system read service

Candidate ownership:

- packet-state counts;
- feature/wave/packet counts;
- worker summary;
- recent events;
- blocked packet summary;
- system health composition.

Suggested module:

- `admin_overview_read_service.py`.

### Packet/run read service

Candidate ownership:

- packet detail DTO;
- run summaries;
- run size breakdown composition;
- blocking/recommendation read model;
- dev replay read model where packet/run-specific.

Suggested module:

- `admin_packet_read_service.py`.

### Artifact/evidence read service

Candidate ownership:

- bounded artifact tree construction;
- artifact classification;
- preview metadata/content policy;
- evidence/artifact DTO composition.

Suggested module:

- `admin_artifact_read_service.py`.

Preserve truncation limits, MIME/kind mapping, path safety and preview semantics.

### Logs/sessions/search read service

If large enough, extract one or more focused components for:

- packet sessions;
- aggregated/read logs;
- search/read-only lookup surfaces.

Do not create tiny one-function modules unless they form a real responsibility boundary.

## A4. Keep facade compatibility

Routers/callers should still be able to instantiate/use `AdminAggregationService` through the old module path.

The facade may compose extracted read services.

Do not force route changes merely because internals moved.

## A5. Tests — do we change them?

**Yes, internal unit coverage may be added; API/DTO expectations do not change.**

Keep tests asserting:

- overview counts/states;
- packet detail keys;
- run summaries;
- artifacts/evidence;
- sessions/logs;
- blocked/recommendation data;
- health/search data;
- not-found behaviour.

Allowed:

- add focused unit tests for artifact tree/read components;
- update monkeypatch targets after extraction;
- add facade compatibility tests.

Forbidden:

- deleting expected DTO fields;
- renaming fields;
- changing `None`/empty-list/empty-dict fallback behaviour just to simplify code;
- turning read-only aggregation into mutation.

## A6. Acceptance

- original file <=1000 lines, preferred <=700;
- no function >4000 estimated tokens;
- public facade preserved;
- admin read DTO shapes unchanged;
- tests pass.

---

# Part B — `services/admin_control_center.py`

## B1. Problem

The service-level admin control center exceeds the hard file limit and centralises too many control/read use cases for the multi-project admin surface.

This module should become a bounded facade over coherent control-center capabilities rather than another all-admin module.

## B2. Goal

After refactor:

- `services/admin_control_center.py` <=1000 lines, preferred <=600-800;
- control-center responsibilities are grouped by use case;
- security/path safety and project isolation remain unchanged;
- routers retain their existing service contract.

## B3. Preferred extraction boundaries

Inspect existing helpers before adding new ones:

- `admin_control_center_helpers.py`;
- `admin_control_center_explorer_helpers.py`;
- `admin_control_local_helpers.py`;
- `admin_control_security.py`;
- cross-project/admin Git/filesystem services.

Do not create duplicate helper layers when existing modules already own a responsibility.

Potential coherent ownership groups:

### Project/read surface composition

- resolve project context;
- compose project-level overview/read DTOs;
- delegate cross-project reads to existing cross-project service.

### Explorer surface

- filesystem/log/artifact/explorer orchestration;
- reuse explorer helpers and safe filesystem services.

### Control actions

- route control-center commands to the existing mutation/maintenance/control owner;
- preserve security checks and operation audit data.

### Cached/schema/static read helpers

If OpenAPI/cache/read helper code is sizeable and independent, extract it without changing public API generation.

## B4. Security rule

Security checks must not become optional because code moved.

Preserve:

- project/root containment;
- allowed filesystem roots;
- mutation authorization/guard logic;
- maintenance/control restrictions;
- cross-project isolation;
- user/project identity semantics.

A new helper must accept already-resolved secure context or perform the same mandatory check itself; do not create an unguarded internal backdoor.

## B5. Tests — do we change them?

**Yes, only for internal wiring plus new focused security/delegation coverage.**

Keep existing API/service tests as behavioural contract.

Required regression areas:

1. project selection and project isolation;
2. filesystem/path rejection outside allowed roots;
3. read endpoints remain read-only;
4. mutation/control requests still pass through security/maintenance owners;
5. explorer responses preserve keys/shapes;
6. OpenAPI/admin route surface remains unchanged;
7. not-found/error mapping remains unchanged.

Allowed:

- update internal patch targets;
- add tests for newly extracted service boundaries;
- add facade compatibility tests.

Do not relax security assertions to simplify extraction.

## B6. Interaction with existing helpers

Before coding, produce a small ownership map:

- what `admin_control_center.py` currently owns;
- what `admin_control_center_helpers.py` already owns;
- what `admin_control_center_explorer_helpers.py` owns;
- what `admin_control_local_helpers.py` owns;
- what `admin_control_security.py` owns.

Then extract only responsibilities with a clear owner.

If an existing helper is itself large but below the programme target, do not automatically rewrite it in this packet unless moving a responsibility there would push it near/over 1000 lines.

## B7. Acceptance

- original service <=1000 lines, preferred <=800;
- no touched function >4000 estimated tokens;
- no duplicated security/path logic;
- public service/router behaviour unchanged;
- admin tests pass.

---

# 3. API contract verification for both parts

Because admin code feeds the UI directly, verify public API stability.

Required:

```bash
make docs-check
```

If `docs/openapi.json` changes, inspect the semantic diff.

A pure internal refactor should not remove/add/change admin routes or schemas. Unexpected OpenAPI drift is a blocker, not a generated-file update to accept blindly.

## 4. Size acceptance — block 05

Required:

- `admin_aggregation_service.py` <=1000 lines;
- `services/admin_control_center.py` <=1000 lines;
- all new modules <=1000 lines;
- all touched functions <=4000 estimated tokens;
- no oversized logic is merely moved into one new 1000+ line helper.

## 5. Verification

Run dedicated admin service/API tests first, then:

```bash
make lint
make test
make docs-check
```

Final programme gate:

```bash
make ci
```

## 6. Coder submission

For each Part A/B packet report:

- before/after line count;
- responsibility extraction map;
- new modules and owners;
- tests changed/added and why;
- OpenAPI semantic diff result;
- confirmation that security and read/mutation boundaries are unchanged;
- verification commands/results.
