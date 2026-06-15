---
feature_id: Feat_1
wave_id: W04
submission_attempt: 1
reviewer: active_reviewer_architect
decision: REWORK_REQUIRED
reviewed_commit: 9c804fe
created_at: 2026-06-15T00:00:00Z
---

# Review: W04

Decision: REWORK_REQUIRED

Good progress:

- `EXECUTION_PACKET.md` now renders the 17 requested sections.
- The materializer includes file tree, previews, nearby tests, config availability, import hints, evidence details, workspace limitations, target diagnostics, and full spec dump.
- The executor passes `target_root` into the materializer.
- NORMAL/STRICT packets are blocked when `skip_context_builder=true` and `context_not_required` is not set.
- Missing cwd now raises instead of being silently created.
- The diff is clean and limited to W04 files.

Blocking issues:

1. `.env` can still be copied when it is part of packet scope.

   W04 acceptance says `.env` must never be copied. `AgentWorkspaceBuilder.build_scoped_copy()` copies every existing scope path before config allowlist handling. There is no denylist check for `.env`, `.env.local`, `.env.*`, or similar secret files. The current test only checks `.env` is not in the allowlist, but does not prove scoped copy refuses `.env` from `scope_paths`.

   Required rework:
   - add an explicit secret/env denylist in scoped copy;
   - never copy `.env` or `.env.*` from either scope or config allowlist;
   - record omitted reason such as `secret_file_denied:.env`;
   - add a test where `.env` is present in scope and is not copied.

2. Config glob patterns are rendered but not copied into scoped workspaces.

   `PacketMaterializer._render_config_available()` checks glob-style patterns for `tsconfig.*.json`, `vite.config.*`, `vitest.config.*`, and `playwright.config.*`, but `AgentWorkspaceBuilder.build_scoped_copy()` only iterates literal entries from `CONFIG_ALLOWLIST`. Therefore files such as `vite.config.ts`, `vitest.config.ts`, `playwright.config.ts`, or `tsconfig.app.json` are reported/expected but not included in scoped copy.

   Required rework:
   - support allowlist glob patterns during scoped copy, or expand matched config files before calling the builder;
   - include required config families from W04 spec: tsconfig variants, vite/vitest/playwright configs, package locks, pytest/ruff/mypy/tox config;
   - add tests proving glob configs are copied.

3. Submission metadata has stale commit SHA.

   The submission says commit `b295530`, while the reviewed clean commit is `9c804fe`. This is not the functional blocker, but the next submission must report the actual commit SHA.

Next submission: `docs/work/Feat_1/exchange/inbox/W04_002_SUBMISSION.md`.
