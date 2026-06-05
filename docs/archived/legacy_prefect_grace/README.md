# Legacy Prefect — archived snapshot

This directory is a **historical snapshot** of the original
`prefect_grace` runtime package. It is no longer part of the runtime
surface and is kept here only for archaeology / reference.

## Removal

Removed in **W8** of
`source/codex/tz-api-first-cleanup-waves-w0-w11.md`. The strategic
execution path is `grace_control.agent.api_backend.ApiAgentBackend` and
`grace_control.agent.mock_backend.MockBackend`.

## How it was removed

- `pyproject.toml` no longer declares `src/prefect_grace` as a hatch
  package; `[tool.hatch.build].packages = ["src/grace_control"]` only.
- The `legacy` optional dependency (`prefect>=3.0.0`) was removed.
- The legacy `force-include` block was removed.
- `select_backend("legacy")` raises a clear `ValueError` instead of
  silently wrapping prefect_grace.
- `src/grace_control/agent/legacy_backend.py` was deleted.
- `src/grace_control/agent/new_backend.py` (a thin shim that re-exported
  `NewDirectBackend` from `api_backend.py`) was kept for one release,
  then deleted in the same commit.

## Prompts that survived

The seven prompt markdown files in `src/prefect_grace/prompts/` were
moved into `src/grace_control/core/prompts/` because the deterministic
acceptance pipeline still reads them at runtime:

- `architect_prompt.md`
- `coder_prompt.md`
- `verifier_prompt.md`
- `evidence_verifier_prompt.md`
- `reviewer_prompt.md`
- `planner_prompt.md`
- `canon_digest_prompt.md`

`evidence_verifier.py` and `reviewer_gate.py` were updated to read
prompts from the new location (`Path(__file__).parent / "prompts" / ...`).

## DO NOT

- Do not import any module from this archive in `src/grace_control/`.
  GraceLint rule GRC100 enforces this — see
  `docs/grace/LEGACY_REMOVAL.md`.
- Do not add this archive to `pyproject.toml` packages.

## Reference

- TZ: `source/codex/tz-api-first-cleanup-waves-w0-w11.md` — W8.
- Acceptance: `docs/grace/LEGACY_REMOVAL.md`.
- The active execution backends: `docs/grace/EXECUTION_BACKENDS.md`.
