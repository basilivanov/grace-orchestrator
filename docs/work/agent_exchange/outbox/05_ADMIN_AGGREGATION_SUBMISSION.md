# TZ05 — Admin Aggregation decomposition

WEB_ORCH_REPORT: SUBMISSION 05_ADMIN_AGGREGATION
WEB_ORCH_STATUS: DONE
WEB_ORCH_COMMIT: ff8b5fd93dfd4dcf8acfd1850dba5c6bb974790d
WEB_ORCH_CHECKS: PASS

## Scope

Implemented only Part A of `05_ADMIN_AGGREGATION.md`. No router, schema,
migration, DTO contract, UI, state-machine or Admin Control Center Part B
files were changed. Existing public facade and route patch points remain in
place.

## Responsibility map and size

Before: `admin_aggregation_service.py` was 1909 lines (`wc -l`). After: the
facade is 388 lines; the extracted read owners are all below 1000 lines.

| File | Responsibility | Lines |
| --- | --- | ---: |
| `admin_aggregation_service.py` | Stable compatibility facade and delegation | 388 |
| `admin_overview_read_service.py` | Overview, workers and system health | 272 |
| `admin_pipeline_read_service.py` | Pipeline stages, lifecycle, recovery and totals | 765 |
| `admin_packet_read_service.py` | Packet detail, runs, timeline and blocking decisions | 460 |
| `admin_artifact_read_service.py` | Run/evidence DTOs, artifact tree and safe previews | 401 |
| `admin_feature_read_service.py` | Feature tree, feature summary, wave detail and search | 397 |
| `admin_logs_read_service.py` | Bounded packet logs and session reads | 140 |

Largest Grace-estimated functions (characters//4):

- `derive_simple_pipeline`: ~1708
- `derive_pipeline`: ~1460
- `derive_state_machine`: ~1220
- `get_features_tree`: ~1155
- `get_packet_detail`: ~1034
- `get_wave_detail`: ~781
- `get_overview`: ~729
- `get_packet_evidence`: ~670
- `get_packet_run`: ~653
- `get_packet_logs`: ~635

No GRC005/GRC012 allowlist entries were added.

## Compatibility and reused boundaries

- `AdminAggregationService(state_root=None, worktree_root=None)` and all
  existing public method signatures/results are preserved.
- Existing module helper imports are re-exported from the facade, including
  `_iso`, `_now`, `_elapsed_seconds`, `_is_running`, `_classify_artifact`,
  `_build_artifact_tree`, `_packet_spec_value` and the state constants.
- Existing private selector/derivation patch points remain as facade wrappers.
- `SizeCalculator` remains the source of packet/run sizes.
- `SafeFilesystemService` remains the only artifact content read boundary;
  traversal, symlink containment, binary/text handling and preview limits are
  unchanged.
- `SessionStore` remains the session read boundary and preserves the
  `table_missing` fallback.
- Canonical `GitService` is reused for the read-only code SHA lookup.
- Existing ORM/event/stage read data and `AdminRawReadService` callers remain
  compatible; no raw DTO or route was rewritten.

DTO shapes, status/fallback behavior, read-only semantics, artifact path
safety, ordering and public router imports were preserved. No assertions were
weakened and no tests were changed; the existing direct coverage exercises the
facade through service, API and UI callers.

## Verification

- `python3 -m py_compile` for all seven touched/new modules: PASS.
- System `ruff check` for all seven touched/new modules: PASS.
- Targeted `python3 scripts/grace_lint.py` for all seven touched/new modules:
  PASS; no violations and no allowlist changes.
- `git diff --check`: PASS.
- Direct admin/API/UI set: **76 passed, 3 skipped**.
- `make test`: **1584 passed, 2 skipped, 33 failed**. The clean parent at
  `6a309c94afeeb6aa3048268172fc64e5317e55ff`, run with the same Python and
  command, produced the identical 33 failures and identical test list; all
  failures are pre-existing config/core/runtime/planning/session failures
  outside this change.
- `make lint`: blocked before GraceLint because the repository `.venv`
  Python has no `ruff` module. Clean parent has the same environment failure.
  The available system `ruff` and targeted GraceLint both pass.
- `make docs-check`: reports the same pre-existing drift in the three
  generated files (`docs/openapi.json`, `docs/state-diagram.md`,
  `docs/packet-states.md`) on current and clean parent. The semantic OpenAPI
  hash is unchanged on both: `7d847ff6a70c6ea300f4366ef1cb757dca180dce47ade83c2d7b8bc8c890e2c8`.
- Full `python3 scripts/grace_lint.py src/` remains non-zero only for existing
  legacy violations outside TZ05; the touched/new modules pass targeted
  GraceLint.

Implementation commit is pushed to `origin/main`.
