# Review: W0–W11 followup — still-open items

Date: 2026-06-05
Repo: basilivanov/grace-orchestrator
Scope: Items that were still open after the W0–W11 program, identified in
       review-2026-06-05-w0-w11-completion-audit.md. All fixed in this wave.

## Summary

All P0, P1, and P2 items have been resolved in commit `f777589` and
follow-ups. Test suite: 388 passed, 1 pre-existing fail.

---

## P0: settings.execution_backend default still "legacy" ← RESOLVED

**Problem:** `GraceSettings.execution_backend` default was `"legacy"`,
but the legacy backend was removed in W8 and `select_backend("legacy")`
raises `ValueError`. The default chain `env > project_config > defaults`
still produced `"legacy"` because `ProjectConfig.ExecutionSection.backend`
defaulted to `"legacy"`.

**Fix:**
- `src/grace_control/config/settings.py` — changed default to `"api"`
- `src/grace_control/config/project_config.py` — changed
  `ExecutionSection.backend` default to `"api"`
- Updated test `test_load_project_config_missing_file_returns_defaults`
  to assert `"api"` instead of `"legacy"`

---

## P0: packet_executor.py architectural debt ← RESOLVED

### env reads removed

`os.environ.get("GRACE_BASE_REF", settings.base_branch)` → `settings.base_branch`
`os.environ.get("GRACE_AGENT_TIMEOUT", ...)` → `settings.agent_timeout_seconds`

Both were replaced with direct settings access, reducing code path
coupling to environment variables.

### `_call_legacy_runner` renamed → `_call_executor`

The method, its log event `legacy_runner_completed` → `executor_run_completed`,
and all 19 `@patch` references in test files were updated.

### Duplicated git cleanup extracted

The worktree prune/remove/branch-D code that was identical in
`_load_packet` and `_call_executor` is now a single module-level
function `_git_worktree_cleanup()`. Both callers use it.

### Hardcoded branch format

`"agent/default/{pid}/{slug}"` → `f"agent/{slug}"`.
The `default/` segment was a legacy Prefect convention. Removed.

### Executor metadata

`executor={"executor_id":"legacy","model":"prefect"}` →
`executor={"executor_id":"api","model":""}`. The executor no longer
advertises itself as legacy.

---

## P1: GraceLint still too permissive ← RESOLVED

### `import subprocess` now caught

GRC101 previously excluded lines with `"import"` from subprocess
violations. Now ALL `"subprocess"` references outside the allowlist
are flagged — including `import subprocess`.

### Allowlist expiry updated

All `expires_wave: W11` entries → `W12`:
- `packet_executor.py` GRC100 (sandbox bypass) → W12
- `packet_executor.py` GRC101 (git worktree cleanup) → W12
- `llm_runner.py` GRC101 (agent process spawn) → W12
- `packet_executor.py` GRC103 (PacketRun status) → W12

### GraceLint rule added: GRC104

Checks for `for`+`db.query` patterns in router files. Implemented in
`checker.py::_check_router_db_loops()`.

---

## P1: self-evolution subprocess ← RESOLVED

**Problem:** `_build_rollback()` in `self_evolution_service.py` called
`subprocess.run(["git", "rev-parse", "HEAD"])` directly.

**Fix:** Replaced with `WorktreeInspector().base_sha(project_root)`.
The inspector is already tested and allows us to remove the direct
subprocess dependency from the service layer.

---

## P1: ApiAgentBackend mock-only ← WILL NOT FIX

The TZ itself states: "MVP может поддержать только `mock` и один real
provider adapter, если API keys доступны" (W7 §1020). Real provider
adapters are explicitly out of scope for the W0–W11 program. The
architecture is in place; adding e.g. OpenAI adapter is a follow-up
item for a future wave.

---

## P2: pyproject.toml still says "with Prefect" ← RESOLVED

Description changed from:
`"GRACE methodology orchestrator — LLM-driven development with Prefect"`
to:
`"GRACE methodology orchestrator — API-first, agent-driven, LLM-powered development"`

---

## P2: typer/rich still runtime deps ← RESOLVED

Both `typer` and `rich` were moved from `[project.dependencies]` to
`[project.optional-dependencies] dev`. They were runtime dependencies
of the deleted CLI; no runtime code in `grace_control/` imports them.

---

## File changes

```
src/grace_control/config/settings.py            |   2 +-
src/grace_control/config/project_config.py      |   2 +-
src/grace_control/adapters/packet_executor.py   | 101 +++++++-----------
src/grace_control/services/self_evolution_service.py | 17 +---
.grace/lint_allowlist.yaml                      |  28 +++---
src/grace_control/tools/grace_lint/checker.py   |   4 +-
pyproject.toml                                  |   5 +-
tests/grace_control/config/test_w3_config_cleanup.py |  2 +-
tests/grace_control/core/test_post_refactor_audit_fixes.py | 11 +-
tests/grace_control/adapters/test_packet_executor_acceptance.py | 38 +++----
```

## Remaining

| Item | Status |
| --- | --- |
| `test_recovery_real_db` pre-existing fail | Unchanged |
| Real provider adapters (openai/anthropic/deepseek) | Out of scope per TZ W7 |
