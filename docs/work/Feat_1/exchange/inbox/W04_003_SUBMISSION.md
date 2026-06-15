---
feature_id: Feat_1
wave_id: W04
kind: SUBMISSION
status: SUBMITTED
task: docs/work/Feat_1/exchange/outbox/W04_001_REVIEW.md
---

# Submission: W04 — Execution Packet Context Bundle for Coder (Attempt 3)

Addresses all reviewer blocking issues.

## Changes since W04_001

### 1. `.env` / `.env.*` denylist in scoped copy
- `_is_secret()` blocks `.env` and any `.env.*` file (via fnmatch glob)
- `.env.example` is exempted via `_secret_exceptions` set
- Both scope paths and config allowlist entries are checked
- Blocked files recorded with reason `secret_file_denied:<path>`
- **File:** `src/grace_control/services/agent_workspace_builder.py`

### 2. Config glob patterns now physically copied
- `build_scoped_copy()` expands entries with `*`, `?`, `[` via `Path.glob()`
- `CONFIG_ALLOWLIST` extended: `tsconfig.*.json`, `vite.config.*`,
  `vitest.config.*`, `playwright.config.*`
- `_render_config_available()` unified to resolve globs inline
- **File:** `src/grace_control/services/packet_materializer.py`

### 3. Tests (4 new)
- `test_env_files_never_copied_from_scope`
- `test_env_files_never_copied_from_config` — `.env.example` allowed,
  `.env.production` blocked by `.env.*`
- `test_glob_config_patterns_resolved_and_copied`
- `test_glob_config_pattern_no_match_omitted`
- **File:** `tests/grace_control/services/test_agent_workspace_builder.py`

## Commit

`13da459` (rework) + `d35b12e` (submission v2) + `THIS_COMMIT` (fix: `.env.*` glob + v3)

## Test Results

```bash
python3 -m pytest tests/grace_control/services/test_agent_workspace_builder.py tests/test_w04_execution_packet_context_bundle.py -v
```
23 passed.
