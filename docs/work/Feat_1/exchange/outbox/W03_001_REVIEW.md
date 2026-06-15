---
feature_id: Feat_1
wave_id: W03
submission_attempt: 1
reviewer: active_reviewer_architect
decision: REWORK_REQUIRED
reviewed_commit: 76787c2
created_at: 2026-06-15T00:00:00Z
---

# Review: W03

Decision: REWORK_REQUIRED

Good progress:

- canonical prompt file exists and includes the canonical packet schema;
- `_build_architect_prompt()` is now a thin renderer that appends `load_architect_prompt()`;
- architect profile prompt bodies were reduced and aligned with the canonical schema;
- tests cover prompt loading, profile schema text, required fields, and the standalone legacy-field canonicalizer.

Blocking issue:

1. `canonicalize_packet_fields()` is not wired into the active architect plan parsing path. W03 requires legacy fields to be rejected or canonicalized with visible warnings in active runtime contracts. The function exists, but `run_architect()` parses JSON, normalizes `waves`, sets only `acceptance_profile` and `depends_on`, then persists the plan. It does not call `canonicalize_packet_fields()` for packets, and no warnings are persisted.

Required rework:

- call `canonicalize_packet_fields()` for every packet in the parsed architect plan before persisting `parsed_plan.json`;
- persist warnings, for example under `spec['_architect_schema_warnings']` or a plan compiler/canonicalization artifact;
- add an integration-style test proving a parsed packet with `allowed_files` becomes `scope` before compiler/materializer;
- add a test proving the warning is visible/persisted.

Non-blocking note:

The profile consistency test only selects profile ids containing `architect`, so it misses `deepseek-v4-pro`, even though that profile is used as architect executor. Add coverage later or in the rework if easy.

Next submission: `docs/work/Feat_1/exchange/inbox/W03_002_SUBMISSION.md`.
