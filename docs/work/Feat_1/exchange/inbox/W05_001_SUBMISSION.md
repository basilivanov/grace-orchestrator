---
feature_id: Feat_1
wave_id: W05
submission_attempt: 1
status: READY_FOR_REVIEW
created_at: 2026-06-16T12:00:00Z
---

# W05 Submission: Evidence Contract End-to-End

## Changed Files

| File | Change |
|------|--------|
| `src/grace_control/core/contracts.py` | Extended `EvidenceRequirement` with 7 new fields (stage, owner, producer, profile, coder_blocking, artifact_patterns, description, validation_hint); added legacy `pattern` → `artifact_patterns` mapping with warning; added `validate_evidence_for_profile()`, `route_missing_evidence()`, `check_artifact_patterns()`; updated `build_packet_contract()` to preserve all evidence fields and persist `_evidence_schema_warnings` in contract metadata |
| `src/grace_control/services/packet_materializer.py` | Updated `_render_expected_evidence()` to render all structured fields (kind, stage, owner, producer, profile, required, coder_blocking, artifact_patterns, description, validation_hint) in EXECUTION_PACKET.md, not only IDs |
| `tests/test_w05_evidence_contract.py` | All 6 required tests + 3 additional tests (9 total) |

## Changes in Detail

### 1. Extended EvidenceRequirement dataclass

Added 7 new fields to `EvidenceRequirement`:

| Field | Type | Default | Purpose |
|-------|------|---------|---------|
| `stage` | `str` | `""` | Which verification stage produces this evidence (t0/t1/t2/t3/post_merge) |
| `owner` | `str` | `"coder"` | Who is responsible (coder/architect/verifier) |
| `producer` | `str` | `""` | Agent that produces this evidence |
| `profile` | `str` | `""` | Acceptance profile this applies to |
| `coder_blocking` | `bool` | `True` | Whether missing evidence blocks coder rework loop |
| `artifact_patterns` | `list[str]` | `[]` | Glob patterns for artifact files (canonical field) |
| `description` | `str` | `""` | Human-readable description |
| `validation_hint` | `str` | `""` | Hint for verifier on how to validate |

Legacy `pattern` field is retained for transition compatibility but marked as deprecated.

### 2. Legacy pattern → artifact_patterns mapping

In `build_packet_contract()`, the legacy `pattern` field is now mapped to `artifact_patterns` with a visible warning persisted in `contract.metadata["_evidence_schema_warnings"]`.

### 3. String evidence handling

- **NORMAL/FAST (transition mode)**: String evidence items (bare IDs) are accepted but get a warning in `_evidence_schema_warnings`
- **STRICT**: String evidence items that lack structured fields are rejected by `validate_evidence_for_profile()`

### 4. Evidence routing by owner/profile

`route_missing_evidence()` routes missing evidence based on the `owner` field:
- **architect-owned** → returns `"architect"` (prevents architect issues from becoming coder blame)
- **coder-owned + coder_blocking** → returns `"coder"`
- **verifier-owned only** → returns `"verifier"`
- **default** → returns `"coder"`

### 5. Artifact pattern checks by evidence kind

`check_artifact_patterns()` verifies that each evidence requirement's `artifact_patterns` match against available artifacts using fnmatch glob matching. Unmatched patterns produce warnings that include the evidence kind.

### 6. Materializer renders structured evidence

`_render_expected_evidence()` in PacketMaterializer now renders all 11 fields per evidence item in EXECUTION_PACKET.md, not just the ID.

## Test Results

- **W05 tests**: 9 passed
- **W02 tests**: 17 passed (no regression)
- **W03 tests**: 11 passed (no regression)

## Required Tests Mapping

| Required Test | Implemented As |
|---------------|----------------|
| `test_evidence_requirement_preserves_all_fields` | ✅ Tests all 11 fields round-trip |
| `test_materializer_renders_structured_evidence` | ✅ Verifies EXECUTION_PACKET.md contains all fields |
| `test_string_evidence_gets_warning_or_rejected_for_strict` | ✅ NORMAL warns, STRICT rejects |
| `test_missing_coder_blocking_evidence_rework_to_coder` | ✅ Routes correctly including non-blocking edge cases |
| `test_architect_owned_evidence_issue_returns_to_architect` | ✅ Architect priority over coder |
| `test_artifact_patterns_replace_legacy_pattern` | ✅ Pattern mapped, STRICT rejects bare legacy |

## Acceptance Criteria

| Criterion | Status |
|-----------|--------|
| Evidence fields survive plan → packet → verifier/reviewer | PASS |
| Missing coder-blocking evidence routes to coder rework | PASS |
| Architect-owned evidence issue does not become coder blame | PASS |
| Legacy evidence shape is visible as warning or rejected in STRICT | PASS |
