# Review 009 — Admin Control Center Stage 03

Status: CHANGES REQUIRED

Original implementation reviewed: `635da6421a6aff71ef577bfe99996aa24fd706a8`.
Resubmission implementation reviewed: `7d4262ac4b6f18919f79ff62c5e1e955322a14f8`.

The resubmission correctly closes the previous continuation, health-only aggregate, project-metadata search fallback, and disabled-overview issues. Two acceptance/protocol gaps remain.

## Required fixes

### 1. Structurally malformed diagnostics are still counted as zero-valued overview data

`get_diagnostics()` now detects whether the diagnostics payload contains known diagnostic fields and excludes health-only/unavailable snapshots from count aggregates. That fix is correct.

However `get_projects_overview()` still follows the old path through `_overview_for_context()`:

```python
snapshot = _safe_json(_data_mapping(diagnostics.payload)) if diagnostics.ok else None
...
snapshots = [row["diagnostics"] for row in rows if row["diagnostics"] is not None]
aggregate = _aggregate_snapshots(snapshots)
```

Therefore a project can return HTTP/transport success with a JSON object that is structurally malformed for diagnostics (for example `{"data": {"unexpected": true}}`). The project is treated as non-partial, the malformed mapping is added to the overview aggregate, and `_aggregate_snapshots()` silently contributes zero packet/worker/run/lease counts while increasing `projects_in_aggregate`.

This is the same mathematical-validity requirement from the previous review: unavailable **or malformed/incomplete** diagnostics must not become healthy zero-valued aggregate data.

Required:

- apply the same diagnostics-availability/schema-validity concept to overview normalization;
- keep the project card/health visible, but mark the project partial and expose a per-project malformed/partial diagnostics error when the diagnostics response is structurally unusable;
- exclude that diagnostics payload from overview count aggregates;
- `projects_in_aggregate` must count only projects whose diagnostic counters actually contributed;
- add an acceptance test where project A has valid diagnostics and project B returns a successful but structurally invalid diagnostics object while health remains healthy. Overview aggregate must include only A's counters and coverage must mark B partial.

Do not require every optional diagnostics field; validate only enough canonical Stage 02 diagnostic structure to distinguish a usable snapshot from an unrelated/malformed object.

### 2. `009_RESUBMISSION.md` is not present in the repository

The reviewer can fetch implementation commit `7d4262ac4b6f18919f79ff62c5e1e955322a14f8`, but on the repository default branch:

`docs/work/agent_exchange/outbox/009_RESUBMISSION.md`

returns 404, and repository code search finds no `009_RESUBMISSION` file.

The coder report text supplied externally is not a substitute for the protocol artifact. Create and commit/push the required outbox file with the implementation/fix commit SHA and concise checks.

## Scope

Do not start Task 010 / Stage 04. Fix only the overview malformed-diagnostics aggregate/coverage issue and commit the required resubmission artifact.

Re-run the focused Task 009 acceptance tests plus the directly relevant Task 007–008/Admin diagnostics regressions and required Ruff / `py_compile` / GRACE lint / `git diff --check` checks.

Then create/update:

`docs/work/agent_exchange/outbox/009_RESUBMISSION.md`

Do not start Task 010 until reviewer returns `ACCEPT 009`.
