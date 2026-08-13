WEB_ORCH_REPORT: RESUBMISSION TZ_GRACE_ARCHITECTURE_REFACTOR_V2_09_CI_SINGLE_SOURCE_OF_TRUTH
WEB_ORCH_STATUS: DONE
WEB_ORCH_COMMIT: 5284e4919e884ede65f32997e6733c50519f6270
WEB_ORCH_CHECKS: PASS

# Packet 09 resubmission

## Correction lineage

- Original reviewed implementation SHA: `8b6787f1d13aa6da44734b6de084e42ffce2c995`.
- Review commit: `b2170b4704fbac077a63084ac88d0af2df490f37`.
- Correction SHA: `5284e4919e884ede65f32997e6733c50519f6270`.
- Correction pushed successfully to `origin/main`.

## Review correction

Changed exactly one path:

- `docs/grace/ARCHITECTURE.md`

The active **Execution backends** catalog now matches `src/grace_control/agent/__init__.py` and the neighboring backend catalog:

- `cli` → `UniversalCliAgentBackend`, internal generic subprocess packet execution with mini-swe-compatible declarative profiles;
- `api` → `ApiAgentBackend`;
- `mock` → `MockBackend`;
- `legacy` is removed in W8, explicitly rejected, and not selectable.

The document explicitly distinguishes the supported internal `cli` execution backend from the removed public/operator control CLI. No runtime, API, DB, lifecycle, packet, Makefile, workflow, lint baseline, or historical `docs/work/` files were changed.

## Verification

- `make docs-check` — PASS: `docs freshness OK — 3 files in sync`.
- `make lint` — PASS: baseline-aware full scope, `ruff=1020`, `gracelint=3249`.
- `make hygiene` — PASS: `OK: repo-hygiene passed`.
- `PYTHONPATH=src .venv/bin/pytest -q tests/grace_control/architecture/test_ci_single_source_of_truth.py` — PASS, 7 passed.
- `make ci` — PASS: `2018 passed, 3 skipped, 62 deselected`, followed by lint, docs-check, and hygiene PASS.
- Backend consistency scan over `src/grace_control/agent/__init__.py`, `docs/grace/ARCHITECTURE.md`, `docs/grace/EXECUTION_BACKENDS.md`, `docs/grace/CANON.md`, and `docs/grace/RUNBOOK_LOCAL_DEV.md` — PASS; current `cli/api/mock` selection, rejected `legacy`, OpenCode removal, and public control-CLI distinction are consistent.
- `git diff --check` — PASS.

No next packet was started.
