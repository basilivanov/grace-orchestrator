---
feature_id: Feat_1
wave_id: W05
submission_attempt: 2
status: READY_FOR_REVIEW
created_at: 2026-06-16T14:00:00Z
---

# W05 Rework Submission: Evidence Contract End-to-End

## Review Blocker Addressed

**Blocker:** W05 is not wired end-to-end into verifier/reviewer routing. The pure helper functions exist but are not called in the active runtime path.

## Changes in This Rework

### 1. `validate_evidence_for_profile()` wired into `build_packet_contract()`

**File:** `src/grace_control/core/contracts.py`

STRICT packets with string evidence are now rejected at `build_packet_contract()` time with `ScopeContractError`, preventing misleading passes later in the pipeline. The validation runs before the contract is returned, so invalid evidence never reaches the materializer or verifier.

### 2. `check_artifact_patterns()` wired into `run_evidence_verifier()`

**File:** `src/grace_control/core/evidence_verifier.py`

Before the LLM call, `run_evidence_verifier()` now runs deterministic artifact pattern checks:

1. Calls `validate_evidence_for_profile()` — STRICT validation failures return immediately with `REWORK_TO_CODER`, no LLM needed.
2. Calls `check_artifact_patterns()` against available artifacts — unmatched patterns are collected as missing evidence IDs.
3. When acceptance is OK and patterns are missing, returns a deterministic report directly (no LLM call needed).
4. When acceptance also has issues, continues to LLM for richer context but merges deterministic findings into the LLM report.

The verifier prompt now includes structured expected evidence (id, kind, owner, stage, coder_blocking, artifact_patterns, description) instead of the raw `expected_evidence` repr.

### 3. `route_missing_evidence()` wired into verifier report routing

**File:** `src/grace_control/core/evidence_verifier.py`

When deterministic or LLM-identified missing evidence is found, `route_missing_evidence()` determines:

- **architect-owned missing** → `RETURN_TO_ARCHITECT` verdict, `suggested_next_owner="architect"`
- **coder-owned + coder_blocking** → `REWORK_TO_CODER`, `suggested_next_owner="coder"`
- **verifier-owned only** → `REWORK_TO_CODER`, `suggested_next_owner="verifier"`

The LLM cannot override the deterministic routing for missing evidence, but it can add context (spec_conflicts, coder_instructions, architect_questions).

### 4. Reviewer bundle enhanced with structured evidence and route classification

**File:** `src/grace_control/core/reviewer_gate.py`

- `_build_reviewer_evidence_bundle()` now accepts `expected_evidence` and `verifier_route_classification` parameters.
- Structured expected evidence (id, kind, stage, owner, coder_blocking, artifact_patterns, description) is serialized and included in the bundle.
- Verifier route classification (the `suggested_next_owner` from evidence verifier) is included.
- `_render_reviewer_evidence_bundle()` renders "Expected evidence (structured):" and "Evidence route classification:" sections.
- `run_reviewer_gate()` passes `packet.expected_evidence` and `evidence_verifier_report.suggested_next_owner` to the bundle builder.

### 5. Integration tests

**File:** `tests/test_w05_evidence_contract.py` (14 tests total, 5 new integration tests)

| Test | Purpose |
|------|---------|
| `test_strict_packet_with_string_evidence_rejected_at_build` | STRICT + string evidence → `ScopeContractError` at build time, not misleading pass |
| `test_missing_coder_blocking_artifact_causes_rework_to_coder_in_verifier` | Missing coder-owned blocking artifact → `REWORK_TO_CODER` |
| `test_missing_architect_owned_artifact_causes_return_to_architect` | Missing architect-owned artifact → `RETURN_TO_ARCHITECT` |
| `test_verifier_owned_missing_evidence_not_coder_blame` | Missing verifier-owned evidence → routes to verifier, not coder |
| `test_reviewer_bundle_includes_structured_evidence_and_route` | Reviewer bundle includes structured evidence and route classification |

## Test Results

- **W05 tests**: 14 passed
- **W02 tests**: 17 passed (no regression)
- **W03 tests**: 11 passed (no regression)

## Acceptance Criteria

| Criterion | Status |
|-----------|--------|
| Evidence fields survive plan → packet → verifier/reviewer | PASS |
| Missing coder-blocking evidence routes to coder rework | PASS (wired into verifier) |
| Architect-owned evidence issue does not become coder blame | PASS (wired into verifier) |
| Legacy evidence shape is visible as warning or rejected in STRICT | PASS (rejected at build time) |
