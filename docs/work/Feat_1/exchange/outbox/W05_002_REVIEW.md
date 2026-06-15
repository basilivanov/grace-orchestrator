---
feature_id: Feat_1
wave_id: W05
submission_attempt: 2
reviewer: active_reviewer_architect
decision: APPROVED
reviewed_commit: 7aa0087
created_at: 2026-06-16T00:00:00Z
---

# Review: W05 attempt 2

Decision: APPROVED

Reviewed submission: `docs/work/Feat_1/exchange/inbox/W05_002_SUBMISSION.md`
Reviewed commit: `7aa0087`

The W05 rework addresses the previous blocker.

Verified:

- `validate_evidence_for_profile()` is now called in the contract build path, and invalid STRICT evidence raises `ScopeContractError` before materializer/verifier runtime can produce a misleading pass.
- `run_evidence_verifier()` now calls `validate_evidence_for_profile()`, `check_artifact_patterns()`, and `route_missing_evidence()` in the active verifier path.
- deterministic missing evidence can return `RETURN_TO_ARCHITECT` for architect-owned evidence and `REWORK_TO_CODER` with the appropriate `suggested_next_owner` for coder/verifier routes.
- verifier prompt now includes structured expected evidence rather than only raw repr output.
- reviewer evidence bundle now includes structured expected evidence and verifier route classification.
- W05 test coverage was expanded to cover the new behavior and claimed regression suites remain green.

Non-blocking note:

Some W05 tests named as verifier integration still test the deterministic helper/routing layer directly rather than executing the full async `run_evidence_verifier()` path. The runtime wiring itself is present, so this does not block W05. A later hardening wave should add true async verifier-path tests around mocked `run_llm`.

W05 is approved. Proceed to W06.
