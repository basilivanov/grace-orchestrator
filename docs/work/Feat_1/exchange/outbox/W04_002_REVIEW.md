---
feature_id: Feat_1
wave_id: W04
submission_attempt: 2
reviewer: active_reviewer_architect
decision: REWORK_REQUIRED
reviewed_head: main
created_at: 2026-06-15T00:00:00Z
---

# Review: W04 attempt 2

Decision: REWORK_REQUIRED

Good progress:

- scoped copy now expands config allowlist glob patterns;
- glob config copy is covered by tests;
- `.env`, `.env.local`, and `.env.production` are blocked in the covered cases;
- `.env.example` remains allowed;
- diff after `W04_001_REVIEW` is limited to W04 rework files.

Blocking issue:

1. `.env.*` denylist is still not generic.

   W04_001_REVIEW required `.env`, `.env.*`, `.env.local`, and similar secret files to never be copied. The current `_secret_patterns` enumerates only:

   - `.env`
   - `.env.local`
   - `.env.production`
   - `.env.development`

   That still allows common secret variants such as `.env.staging`, `.env.test`, `.env.prod`, `.env.localhost`, or nested equivalents if they are passed in scope/config allowlist. This violates the acceptance rule: never copy `.env` or `.env.*`, while still allowing `.env.example`.

Required rework:

- implement generic deny rule: deny `.env` and `.env.*`, except explicitly allow `.env.example`;
- apply it to both scope paths and config allowlist/glob-expanded files;
- add tests for at least `.env.staging` and `.env.test` from scope and/or config allowlist;
- ensure `.env.example` remains copied;
- submit `docs/work/Feat_1/exchange/inbox/W04_003_SUBMISSION.md`.

Non-blocking note:

The W04_002 submission says commit `13da459`, while the user reports `13da459 + d35b12e` pushed. Next submission should name the reviewed final head commit explicitly.
