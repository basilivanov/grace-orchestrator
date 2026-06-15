---
feature_id: Feat_1
wave_id: W05
submission_attempt: 1
reviewer: active_reviewer_architect
decision: REWORK_REQUIRED
reviewed_head: main
created_at: 2026-06-16T00:00:00Z
---

# Review: W05 attempt 1

Decision: REWORK_REQUIRED

Reviewed submission: `docs/work/Feat_1/exchange/inbox/W05_001_SUBMISSION.md`
Reviewed head: `main`

Good progress:

- `EvidenceRequirement` now has the required W05 fields.
- `build_packet_contract()` preserves structured evidence fields.
- legacy `pattern` is mapped to `artifact_patterns` with a metadata warning.
- `PacketMaterializer._render_expected_evidence()` renders structured evidence fields into `EXECUTION_PACKET.md`.
- W05 unit tests cover the new model/helper behavior.

Blocking issue:

1. W05 is not wired end-to-end into verifier/reviewer routing.

   The W05 goal is to preserve and use evidence requirements from architect plan through materializer, coder packet, verifier, reviewer, and review routing. The current implementation adds model fields and pure helper functions, but the runtime verifier/reviewer path still does not use them:

   - `validate_evidence_for_profile()` is not called in the packet build/materialization/execution path, so STRICT evidence validation is not enforced by runtime.
   - `check_artifact_patterns()` is not called by the evidence verifier, so missing artifact patterns only work in unit tests and do not affect verifier decisions.
   - `route_missing_evidence()` is not called after verifier output, so missing coder-owned/architect-owned/verifier-owned evidence does not deterministically route to coder/architect/verifier.
   - `run_evidence_verifier()` still mostly passes `packet.expected_evidence` and artifacts into an LLM prompt, then returns parsed JSON without deterministic artifact pattern checks or owner/profile routing.
   - `run_reviewer_gate()` does not include structured expected evidence or route classification in its evidence bundle; it only includes acceptance report, changed files, patch preview, and artifact paths.

Required rework:

- In the active runtime path, call `validate_evidence_for_profile()` for `packet.expected_evidence` and fail/route appropriately for STRICT invalid evidence.
- In `run_evidence_verifier()` or immediately before/after it, run `check_artifact_patterns(packet.expected_evidence, artifacts)` and include unmatched required evidence in the verifier report.
- Use `route_missing_evidence()` to set deterministic next owner / verdict:
  - coder-owned + coder_blocking missing evidence → `REWORK_TO_CODER`, owner `coder`;
  - architect-owned evidence issue → `RETURN_TO_ARCHITECT`, owner `architect`;
  - verifier-owned issue → verifier/reviewer decision, owner `verifier`.
- Ensure reviewer prompt/bundle receives structured expected evidence and verifier route classification, not only generic artifact paths.
- Add integration-style tests that exercise the active verifier/reviewer path, not only pure helper functions.

Required tests for rework:

- runtime STRICT packet with string evidence is rejected or routed before a misleading pass;
- missing coder-owned blocking artifact pattern causes `REWORK_TO_CODER`;
- missing architect-owned artifact pattern causes `RETURN_TO_ARCHITECT`;
- verifier-owned missing evidence does not become coder blame;
- reviewer bundle/prompt includes structured expected evidence or route classification.

Next submission: `docs/work/Feat_1/exchange/inbox/W05_002_SUBMISSION.md`.
