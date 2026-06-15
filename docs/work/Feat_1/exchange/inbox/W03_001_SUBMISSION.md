---
feature_id: Feat_1
wave_id: W03
submission_attempt: 1
status: READY_FOR_REVIEW
created_at: 2026-06-15T14:00:00Z
---

# W03 Submission: Canonical Architect Prompt and Profile Unification

## Changed Files

| File | Change |
|------|--------|
| `src/grace_control/core/prompts/architect_prompt.md` | Rewritten as the single canonical architect prompt source with unified schema, canonical packet field table, legacy field mapping, and all verification/scope/frozen_scope rules |
| `src/grace_control/core/prompts/__init__.py` | Added `load_architect_prompt()`, `CANONICAL_PACKET_FIELDS`, `REQUIRED_PACKET_FIELDS`, `LEGACY_FIELD_MAP`, and `canonicalize_packet_fields()` |
| `src/grace_control/services/feature_planning_service.py` | Refactored `_build_architect_prompt()` from a 250-line inline prompt to a thin renderer that calls `load_architect_prompt()` |
| `src/grace_control/config/agent_profiles.yaml` | Replaced duplicate architect prompt bodies in `deepseek-v4-pro` and `architect-premium` with canonical schema references |
| `tests/test_w03_architect_prompt_unification.py` | All 5 required tests |

## Changes in Detail

### 1. One Canonical Architect Prompt Source

**File:** `src/grace_control/core/prompts/architect_prompt.md`

This is now the single source of truth for the architect prompt. It contains:
- Role definition and operating modes (start/formalize, rework, gate/decision)
- Operating order and 25 numbered rules
- **Canonical Packet Schema** table with all 12 canonical fields, their types, required status, and descriptions
- **Legacy field mapping** documentation (allowed_files → scope, etc.)
- Task analysis guidelines
- Verification rules (quoting, timing, sanity, runtime environment)
- Evidence rules, frozen_scope rules, source split rules, scope path rules
- GRACE canon maintainer responsibility
- Output format with JSON envelopes for all three modes

### 2. `_build_architect_prompt()` is a Thin Renderer

**File:** `src/grace_control/services/feature_planning_service.py`

Before: 250-line inline prompt with embedded rules, schema, and JSON template — the "weakest" of the three prompt sources, actually used at runtime.

After: ~80-line thin renderer that:
1. Builds runtime context header (business requirement, codebase context, file listing, knowledge graph)
2. Appends `load_architect_prompt()` — the canonical prompt body

All rules, schema definitions, and JSON templates now come from the canonical file, not from inline strings.

### 3. Architect Profiles Match Canonical Schema

**File:** `src/grace_control/config/agent_profiles.yaml`

Both `deepseek-v4-pro` and `architect-premium` profiles:
- Replaced embedded prompt bodies with reference to `architect_prompt.md`
- Added canonical PACKET CONTRACT section listing all 12 canonical fields
- Added legacy field deprecation notice
- `architect-premium` no longer uses `allowed_files`, `forbidden_files` as primary field names

### 4. Legacy Field Canonicalization

**File:** `src/grace_control/core/prompts/__init__.py`

Added `canonicalize_packet_fields()` function that:
- Maps `allowed_files` → `scope`
- Maps `forbidden_files` → `frozen_scope`
- Maps `write_scope` → `scope`
- Maps `inputs` → `coder_instructions`
- Returns `(canonicalized_packet, warnings)` — every canonicalization produces a visible warning
- When both legacy and canonical fields exist, canonical wins and legacy is dropped with an "ignored" warning

### 5. Canonical Packet Fields

| Field | Type | Required |
|-------|------|----------|
| `title` | string | YES |
| `role` | string | YES |
| `scope` | list[string] | YES |
| `frozen_scope` | list[string] | YES |
| `acceptance_profile` | string | YES |
| `depends_on` | list[string] | YES |
| `description` | string | YES |
| `coder_instructions` | list[string] | YES |
| `acceptance_criteria` | list[string] | YES |
| `verification` | object | YES |
| `expected_evidence` | list | YES |
| `workspace_requirements` | object | NO |

Legacy fields that are canonicalized with warnings:
- `allowed_files` → `scope`
- `forbidden_files` → `frozen_scope`
- `write_scope` → `scope`
- `inputs` → `coder_instructions`

## Tests

### Required Tests (all implemented)

- `test_architect_prompt_file_exists_and_loads` — canonical prompt file exists, loads, has key sections
- `test_build_architect_prompt_uses_canonical_prompt` — method calls `load_architect_prompt()`, does not embed inline rules
- `test_architect_profiles_match_canonical_schema` — architect profiles reference canonical schema and prompt
- `test_legacy_allowed_files_schema_rejected_or_canonicalized` — all 4 legacy fields canonicalized with warnings
- `test_architect_output_schema_required_fields` — canonical prompt mentions all required fields, legacy fields excluded from CANONICAL_PACKET_FIELDS

## Test Results

```
tests/test_w03_architect_prompt_unification.py — 5 passed
tests/test_w02_scope_contract.py — 16 passed, 1 env-dep skipped
tests/grace_control/core/test_plan_compiler.py — 38 passed
```

## Acceptance Criteria Verification

| # | Criterion | Status |
|---|-----------|--------|
| 1 | There is one canonical architect prompt source | PASS — architect_prompt.md |
| 2 | Enabled architect profiles match the canonical schema | PASS — both profiles reference canonical schema |
| 3 | Legacy incompatible fields are rejected or canonicalized with visible warnings | PASS — canonicalize_packet_fields() with warnings |
| 4 | Tests prove prompt/profile/schema consistency | PASS — 5 tests |

## Removed Duplicates

1. **`deepseek-v4-pro` embedded prompt** (152 lines) — replaced with 30-line canonical reference
2. **`architect-premium` embedded prompt** (43 lines) — replaced with 30-line canonical reference  
3. **`_build_architect_prompt()` inline rules** (~180 lines of embedded rules/schema) — moved to canonical prompt file
