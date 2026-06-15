---
feature_id: Feat_1
wave_id: W02
submission_attempt: 1
status: READY_FOR_REVIEW
created_at: 2026-06-15T12:30:00Z
---

# W02 Submission: Fail-closed Plan Compiler and Scope Contract

## Changed Files

| File | Change |
|------|--------|
| `src/grace_control/core/plan_compiler.py` | Added W02 fail-closed scope validation: reject empty scope for coder packets, absolute paths, parent paths (..), Python import paths, scope/frozen overlap |
| `src/grace_control/core/contracts.py` | Added `ScopeContractError`, `validate_scope_paths()`, `_has_python_import_path()`. Removed fallback `["src/grace_control/"]` from `build_packet_contract()`. Removed silent absolute path stripping. Removed silent frozen overlap removal. Added overlap check to `validate_packet_contract()`. |
| `src/grace_control/services/packet_materializer.py` | Removed `DEFAULT_SCOPE = "src/"`. Materializer now raises `ValueError` if scope is empty. Removed default frozen scope. |
| `src/grace_control/services/feature_planning_service.py` | `_fallback_plan()` no longer creates executable coder packets with empty scope — returns empty waves with `PLAN_FAILED`. Removed `pkt.setdefault("scope", [])` that hid empty scope from compiler. |
| `src/grace_control/core/gate_resolver.py` | Removed `enriched.setdefault("scope", [])` — missing scope is now an error, not a default. |
| `src/grace_control/services/scope_path_canonicalizer.py` | Added detection of absolute paths, parent paths, Python import paths — records errors instead of silently passing. |
| `src/grace_control/core/context_collector.py` | Added W02 comment clarifying default is read-only context, not write scope. |
| `src/grace_control/mod.py` | Added W02 comment clarifying default is read-only context, not write scope. |
| `tests/test_w02_scope_contract.py` | All 6 required tests + additional coverage (parent paths, Python imports, verifier empty scope OK, materializer success path) |

## Removed Defaults

1. **`PacketMaterializer.DEFAULT_SCOPE = "src/"`** — removed entirely. No silent fallback.
2. **`build_packet_contract()` fallback `scope_list or ["src/grace_control/"]`** — removed. Empty scope stays empty; compiler catches it.
3. **`build_packet_contract()` default `frozen_scope = ["docs/archived/legacy_prefect_grace/"]`** — removed. Frozen scope defaults to `[]`.
4. **Silent absolute path stripping** in `build_packet_contract()` — replaced with `ScopeContractError`.
5. **Silent frozen overlap removal** in `build_packet_contract()` — replaced with `ScopeContractError`.
6. **`pkt.setdefault("scope", [])`** in `feature_planning_service.py` — removed. Missing scope is caught by compiler.
7. **`enriched.setdefault("scope", [])`** in `gate_resolver.py` — removed.
8. **Fallback plan coder packet** — `_fallback_plan()` no longer creates `scope: []` coder packets. Returns empty waves.

## Compiler Errors Added

| Error Code | Description |
|------------|-------------|
| `E_CODER_EMPTY_SCOPE` | Coder packet has no write scope (already existed, now enforced earlier) |
| `E_SCOPE_ABSOLUTE_PATH` | Scope path starts with `/` — must be repo-relative |
| `E_SCOPE_PARENT_PATH` | Scope path contains `..` — must be within repo |
| `E_SCOPE_PYTHON_IMPORT_PATH` | Scope path looks like Python import (e.g. `grace_control.services.foo`) |
| `E_SCOPE_FROZEN_OVERLAP` | A path appears in both `scope` and `frozen_scope` |
| `E_SCOPE_PATH_NOT_STRING` | Scope entry is not a string type |
| `E_SCOPE_PATH_NOT_CANONICAL` | (existing) Non-canonical path like `app/` or `app.` |

## Tests

### Required Tests (all implemented)

- `test_plan_compiler_rejects_empty_scope` — coder packet with `scope: []` → E_CODER_EMPTY_SCOPE
- `test_build_packet_contract_does_not_default_empty_scope` — missing scope → `[]`, not `["src/grace_control/"]`
- `test_materializer_refuses_packet_without_scope` — empty scope → ValueError
- `test_absolute_scope_path_is_error_not_silently_stripped` — `/tmp/...` → E_SCOPE_ABSOLUTE_PATH + ScopeContractError
- `test_scope_frozen_overlap_is_error` — same path in both → E_SCOPE_FROZEN_OVERLAP + ScopeContractError
- `test_architect_fallback_does_not_enqueue_empty_scope_packet` — fallback plan has no coder packets

### Additional Tests

- `test_plan_compiler_rejects_missing_scope` — no scope key at all
- `test_plan_compiler_allows_verifier_empty_scope` — verifier with empty scope is OK
- `test_parent_path_is_error` — `../etc/passwd` → E_SCOPE_PARENT_PATH
- `test_python_import_path_is_error` — `grace_control.services.packet_service` → E_SCOPE_PYTHON_IMPORT_PATH
- `test_build_packet_contract_with_explicit_scope` — explicit scope works
- `test_materializer_materializes_with_scope` — materializer success path
- `test_context_collector_default_comment` — W02 comment on read-only default

## Acceptance Criteria Verification

| # | Criterion | Status |
|---|-----------|--------|
| 1 | Packet with missing/empty scope cannot be approved/materialized | PASS — compiler rejects, materializer raises ValueError |
| 2 | Absolute and parent paths are rejected with clear compiler errors | PASS — E_SCOPE_ABSOLUTE_PATH, E_SCOPE_PARENT_PATH |
| 3 | Scope/frozen overlap is rejected | PASS — E_SCOPE_FROZEN_OVERLAP, ScopeContractError |
| 4 | Architect fallback failure does not enqueue executable code work | PASS — empty waves, PLAN_FAILED summary |
| 5 | Compiler errors are persisted in feature spec diagnostics | PASS — `spec["_plan_compiler"]` already persisted (pre-existing) |

## Known Limitations

1. **`context_collector.py` and `mod.py`** still default to `["src/grace_control/"]` for *read-only* context collection scope. This is NOT write scope — it determines which files to read for context building. Changing this would break context collection for repos without `src/grace_control/` and is out of W02 scope.

2. **`rework_packet_service.py`** defaults `allowed_paths` to `["src/grace_control/"]`. Rework packets have different semantics (rework of an existing accepted packet) and should inherit scope from the original packet. This is a separate concern.

3. **No full integration test through approve_plan API** — the service-level tests prove the logic. Full API integration via `TestClient` would require the complete FastAPI app with DB setup.

4. **Scope canonicalizer records errors but does not reject** — it records errors and keeps the invalid paths, letting the plan compiler catch them. This preserves the canonicalizer's role as a transformation pass (fix what it can, flag what it can't).
