---
feature_id: Feat_1
wave_id: W03
submission_attempt: 2
status: READY_FOR_REVIEW
created_at: 2026-06-15T18:00:00Z
---

# W03 Rework Submission: Canonical Architect Prompt and Profile Unification

## Review Blocker Addressed

**Blocker:** `canonicalize_packet_fields()` is not wired into the active architect plan parsing path. The function existed but `run_architect()` did not call it, and no warnings were persisted.

## Changes in This Rework

### 1. Extracted `normalize_architect_plan()` — standalone normalization function

**File:** `src/grace_control/services/feature_planning_service.py`

Extracted the plan normalization logic from `run_architect()` into a module-level function `normalize_architect_plan(plan: dict) -> dict`. This function:

- Unwraps nested `plan.waves` if the LLM wrapped its output
- Wraps bare `packets` into a single wave
- Ensures every wave has a `packets` list
- Sets `acceptance_profile` / `depends_on` defaults
- **W03 rework**: Calls `canonicalize_packet_fields()` for every packet, replacing legacy fields (`allowed_files`, `forbidden_files`, `write_scope`, `inputs`) with canonical equivalents (`scope`, `frozen_scope`, `coder_instructions`)
- **W03 rework**: Collects all canonicalization warnings and persists them under `plan["_architect_schema_warnings"]`

`run_architect()` now calls `normalize_architect_plan(plan)` instead of inline normalization, ensuring the canonicalization path is always active in the runtime contract.

### 2. Warning persistence

Warnings are stored under `plan["_architect_schema_warnings"]` as a list of strings, each prefixed with the packet location (e.g., `waves[0].packets[0]: Legacy field 'allowed_files' canonicalized to 'scope'`). This key is:

- Persisted in `parsed_plan.json` via `artifact_store.write_json()`
- Visible to downstream stages (compiler, materializer, reviewer)
- Only present when legacy fields were actually canonicalized (absent when all fields are canonical)

### 3. Integration tests added

**File:** `tests/test_w03_architect_prompt_unification.py`

| Test | Purpose |
|------|---------|
| `test_normalize_architect_plan_canonicalizes_allowed_files_to_scope` | Integration: packet with `allowed_files` becomes `scope` before compiler; verifies plan passes `PlanCompiler.compile_plan()` without `E_CODER_EMPTY_SCOPE` |
| `test_normalize_architect_plan_canonicalizes_forbidden_files_to_frozen_scope` | Integration: `forbidden_files` → `frozen_scope` |
| `test_normalize_architect_plan_canonicalizes_write_scope_and_inputs` | Integration: `write_scope` → `scope`, `inputs` → `coder_instructions` |
| `test_normalize_architect_plan_persists_schema_warnings` | Warning persistence: `_architect_schema_warnings` key exists, contains location-prefixed warnings mentioning both legacy and canonical field names |
| `test_normalize_architect_plan_no_warnings_when_canonical` | No false positives: plans with only canonical fields have no `_architect_schema_warnings` |

### 4. Non-blocking: deepseek-v4-pro profile coverage

Added `test_deepseek_v4_pro_architect_profile_matches_canonical_schema()` — verifies the `deepseek-v4-pro` profile (used as architect executor in `run_architect()`) references the canonical schema and prompt source, even though its profile id does not contain "architect".

## Test Results

- **W03 tests**: 11 passed
- **W02 tests**: 17 passed (no regression)

## Acceptance Criteria

| Criterion | Status |
|-----------|--------|
| One canonical architect prompt source | PASS (unchanged) |
| Enabled architect profiles match canonical schema | PASS (unchanged) |
| Legacy fields rejected or canonicalized with visible warnings | PASS (now wired into runtime path) |
| Tests prove prompt/profile/schema consistency | PASS (11 tests) |
