---
feature_id: Feat_1
wave_id: W04
kind: SUBMISSION
status: SUBMITTED
task: docs/work/Feat_1/exchange/outbox/W04_001_REVIEW.md
---

# Submission: W04 — Execution Packet Context Bundle for Coder (Attempt 2)

Addresses all 3 blocking issues from W04_001_REVIEW.md.

## Changes vs W04_001

### 1. `.env` denylist in `AgentWorkspaceBuilder.build_scoped_copy()`
- Added `_is_secret()` helper that matches against known secret patterns:
  `.env`, `.env.local`, `.env.production`, `.env.development`
- `.env.example` is **not** blocked — it is a safe template explicitly in CONFIG_ALLOWLIST
- Both scope paths and config allowlist entries are checked; blocked files
  are recorded with reason `secret_file_denied:<path>` in `omitted_files`
- **Files changed:**
  - `src/grace_control/services/agent_workspace_builder.py` (+34 lines)

### 2. Config glob patterns now copied into scoped workspaces
- `build_scoped_copy()` detects entries with `*`, `?`, `[` and expands them
  via `Path.glob()` against `resolved_target` before copying
- `CONFIG_ALLOWLIST` in `packet_materializer.py` extended with 4 glob patterns:
  `tsconfig.*.json`, `vite.config.*`, `vitest.config.*`, `playwright.config.*`
- `_render_config_available()` unified to resolve globs inline (removed
  redundant glob-only section), displaying `<name> (available)` for matches
  and `<pattern> (no match)` for unmapped globs (previously always `(not found)`)
- **Files changed:**
  - `src/grace_control/services/packet_materializer.py` (+8 / -10 lines)
  - `src/grace_control/services/agent_workspace_builder.py` (glob expansion logic)

### 3. Stale commit SHA fixed
- Previous submission referenced `b295530` (stale); actual reviewed commit
  is `9c804fe`. This submission references the correct fix commit below.

### 4. Tests (4 new)
- `test_env_files_never_copied_from_scope` — `.env` + `.env.local` in scope
  are omitted with `secret_file_denied`
- `test_env_files_never_copied_from_config` — `.env.production` blocked,
  `.env.example` allowed
- `test_glob_config_patterns_resolved_and_copied` — `tsconfig.*.json` and
  `vite.config.*` globs match and copy actual files
- `test_glob_config_pattern_no_match_omitted` — unmapped globs recorded as
  `config_glob_no_match`
- **File:** `tests/grace_control/services/test_agent_workspace_builder.py`

## Commit SHA

`13da459`

## Test Commands and Output

```bash
python3 -m pytest tests/grace_control/services/test_agent_workspace_builder.py tests/test_w04_execution_packet_context_bundle.py -v
```
23 passed — 16 builder tests (12 existing + 4 new) + 7 W04 tests.

## Evidence

- `.env` files in scope paths → `secret_file_denied:.env` in omitted_files,
  file not present in workspace
- Glob patterns (`tsconfig.*.json`, `vite.config.*`) → files physically
  present in scoped workspace, listed in `copied_files`
- `.env.example` still copied as expected
