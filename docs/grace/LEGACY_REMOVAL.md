# Legacy Removal — W8

## Summary

The entire `prefect_grace` runtime package was removed from the GRACE
Control Plane in W8 of `source/codex/tz-api-first-cleanup-waves-w0-w11.md`.
This document explains what was removed, what replaced it, and how to
find the old code.

## What was removed

| Item | Status |
| --- | --- |
| `src/prefect_grace/` (246 tracked files, 2.8 MB) | Archived → `docs/archived/legacy_prefect_grace/` |
| `[project.scripts]` (`grace-dev`, `prefect-grace`, `gracectl`) | Removed in W2 |
| `[project.optional-dependencies] legacy` (`prefect>=3.0.0`) | Removed |
| `[tool.hatch.build] packages = ["src/prefect_grace", ...]` | Changed to `["src/grace_control"]` |
| `[tool.hatch.build.targets.wheel.force-include]` (templates, prompts, roles, policies) | Removed (prompts moved to `src/grace_control/core/prompts/`) |
| `src/grace_control/agent/legacy_backend.py` | Deleted |
| `src/grace_control/agent/new_backend.py` | Deleted (shim for `ApiAgentBackend`) |
| `tool.black` / `tool.ruff` / `tool.mypy` / `tool.pytest` excludes | Cleaned of prefect_grace refs |
| `select_backend("legacy")` | Raises `ValueError` with migration hint |
| `frozen_scope` defaults `["src/prefect_grace/"]` | Changed to `["docs/archived/legacy_prefect_grace/"]` |
| `src/grace_control/__init__.py` docstring | Rewritten |
| `src/grace_control/ui/templates/dashboard.html` forbidden_scope | Updated |
| `tests/` (3 P2 tests referencing legacy_backend) | Removed |

## What was moved

### Prompts

Seven prompt markdown files moved from `src/prefect_grace/prompts/` to
`src/grace_control/core/prompts/`:

- `architect_prompt.md`, `coder_prompt.md`, `verifier_prompt.md`,
  `evidence_verifier_prompt.md`, `reviewer_prompt.md`,
  `planner_prompt.md`, `canon_digest_prompt.md`

The deterministic acceptance pipeline (`evidence_verifier.py`,
`reviewer_gate.py`) reads them from the new location via
`Path(__file__).parent / "prompts" / ...`.

### Legacy worktree helpers

Two git helpers (`_legacy_branch_name`, `_legacy_prepare_worktree`) were
inlined into `src/grace_control/adapters/packet_executor.py` because they
are trivial and only used there. They were previously in
`src/grace_control/agent/legacy_backend.py`.

## Strategic execution path

| Backend | Module | When to use |
| --- | --- | --- |
| `api` | `ApiAgentBackend` | Provider-agnostic, delegates to `AgentGatewayService`. Default for new deployments. |
| `mock` | `MockBackend` | Tests, CI, local dev without LLM credentials. |

`select_backend("legacy")` now raises a clear error pointing to this doc
and the archive location.

## Archive

The full historical `prefect_grace` source tree lives at
`docs/archived/legacy_prefect_grace/`. It is **not** part of the runtime
package. It is kept for archaeology only — do not import from it.

## GraceLint rule

W10 introduces GraceLint rule GRC100, which rejects any `prefect_grace`
import in `src/grace_control/`. This enforces the architectural boundary
that the legacy removal established.
