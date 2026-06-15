---
feature_id: Feat_1
wave_id: W02
submission_attempt: 3
status: READY_FOR_REVIEW
created_at: 2026-06-15T13:35:00Z
rework_for: W02_002_REVIEW
---

# W02 Submission (Attempt 3): Fail-closed Plan Compiler and Scope Contract

## Rework for W02_002_REVIEW

The reviewer identified two remaining fail-closed gaps:

1. **PlanCompiler does not reject non-list scope before iterating** — a string scope is truthy and iterates as characters instead of producing a compiler error.
2. **Root constraints frozen_scope overlap not validated** — root-level `constraints.frozen_scope` is applied during materialization after compiler validation, so a packet with scope overlapping root frozen_scope could silently become READY.

## Changes in This Rework

### 1. Reject non-list scope (E_SCOPE_NOT_LIST)

**File:** `src/grace_control/core/plan_compiler.py`

Added explicit type validation BEFORE scope iteration. When `scope` is not a `list` (e.g. string, dict, int), the compiler emits `E_SCOPE_NOT_LIST` and resets scope to `[]` to prevent character-by-character iteration.

```python
# Before (bug): "src/foo/" → iterates as ["s", "r", "c", "/", "f", "o", "o", "/"]
scope = packet.get("scope", [])
# No type check — non-list scope silently iterated

# After (fix): "src/foo/" → E_SCOPE_NOT_LIST error, scope reset to []
if scope is not None and not isinstance(scope, list):
    _add_error(result, "E_SCOPE_NOT_LIST", ...)
    scope = []
```

This covers: missing, empty, string, dict, int, or any other non-list scope type.

### 2. Reject root constraints.frozen_scope overlap (E_ROOT_FROZEN_SCOPE_OVERLAP)

**File:** `src/grace_control/core/plan_compiler.py`

Added overlap check between each packet's scope and root-level `plan.constraints.frozen_scope`. Previously, root frozen_scope was only applied during materialization (`feature_planning_service.py` line 1043), after compiler validation — so overlapping scope/frozen was never caught.

```python
# Before (bug): compiler validates, then materializer adds root frozen → overlap undetected
# After (fix): compiler checks root constraints.frozen_scope overlap before materialization
root_constraints = plan.get("constraints", {})
root_frozen = root_constraints.get("frozen_scope", []) or []
if scope and root_frozen:
    root_overlap = set(scope) & set(root_frozen)
    if root_overlap:
        _add_error(result, "E_ROOT_FROZEN_SCOPE_OVERLAP", ...)
```

### 3. Fix Python import path false positive for filenames

**File:** `src/grace_control/core/plan_compiler.py`

Fixed `E_SCOPE_PYTHON_IMPORT_PATH` false positive for filenames with extensions like `file.py`, `config.yaml`. These are valid filesystem paths but were rejected because they contain `.` without `/`. Added common file extension exclusion.

### 4. New Tests

**File:** `tests/test_w02_scope_contract.py`

Required tests from review:
- `test_plan_compiler_rejects_scope_string` — string scope → E_SCOPE_NOT_LIST, no per-character errors
- `test_plan_compiler_rejects_root_constraints_scope_overlap` — scope overlaps root constraints.frozen_scope → E_ROOT_FROZEN_SCOPE_OVERLAP

Additional coverage:
- `test_plan_compiler_rejects_scope_dict` — dict scope → E_SCOPE_NOT_LIST
- `test_plan_compiler_rejects_scope_int` — int scope → E_SCOPE_NOT_LIST
- `test_plan_compiler_allows_non_overlapping_root_frozen` — non-overlapping root frozen + packet scope is OK

## Compiler Errors Added in This Rework

| Error Code | Description |
|------------|-------------|
| `E_SCOPE_NOT_LIST` | Scope must be a list of strings — string, dict, int, or other non-list types are rejected |
| `E_ROOT_FROZEN_SCOPE_OVERLAP` | Packet scope overlaps root `constraints.frozen_scope` — root frozen paths are applied during materialization and cannot be writable |

## Test Results

```
tests/test_w02_scope_contract.py — 16 passed, 1 skipped (sqlalchemy env)
tests/grace_control/core/test_plan_compiler.py — 38 passed

New tests:
  test_plan_compiler_rejects_scope_string ................ PASSED
  test_plan_compiler_rejects_scope_dict .................. PASSED
  test_plan_compiler_rejects_scope_int ................... PASSED
  test_plan_compiler_rejects_root_constraints_scope_overlap PASSED
  test_plan_compiler_allows_non_overlapping_root_frozen .. PASSED
```

## Acceptance Criteria Verification

| # | Criterion | Status |
|---|-----------|--------|
| 1 | PlanCompiler rejects non-list scope (string, dict, int) with clear compiler error | PASS — E_SCOPE_NOT_LIST |
| 2 | String scope does NOT iterate as characters | PASS — scope reset to [] after type error, no per-character errors |
| 3 | Root constraints.frozen_scope overlap is validated before materialization | PASS — E_ROOT_FROZEN_SCOPE_OVERLAP |
| 4 | test_plan_compiler_rejects_scope_string passes | PASS |
| 5 | test_plan_compiler_rejects_root_constraints_scope_overlap passes | PASS |

## All W02 Compiler Errors (Complete List)

| Error Code | Description |
|------------|-------------|
| `E_CODER_EMPTY_SCOPE` | Coder packet has no write scope |
| `E_SCOPE_NOT_LIST` | Scope is not a list type (string, dict, int, etc.) |
| `E_SCOPE_PATH_NOT_STRING` | Scope entry is not a string type |
| `E_SCOPE_ABSOLUTE_PATH` | Scope path starts with `/` |
| `E_SCOPE_PARENT_PATH` | Scope path contains `..` |
| `E_SCOPE_PYTHON_IMPORT_PATH` | Scope path looks like Python import |
| `E_SCOPE_PATH_NOT_CANONICAL` | Non-canonical scope path |
| `E_SCOPE_FROZEN_OVERLAP` | Scope and frozen_scope overlap at packet level |
| `E_ROOT_FROZEN_SCOPE_OVERLAP` | Scope overlaps root constraints.frozen_scope |
