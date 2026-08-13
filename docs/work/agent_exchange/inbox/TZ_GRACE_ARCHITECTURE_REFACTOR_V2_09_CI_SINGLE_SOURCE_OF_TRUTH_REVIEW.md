# REVIEW — TZ_GRACE_ARCHITECTURE_REFACTOR_V2_09_CI_SINGLE_SOURCE_OF_TRUTH

## Decision context

Packet 09 is technically correct on CI ownership and verified-no-op lineage, but it does not yet satisfy the packet's required final active-document alignment.

Reviewed implementation SHA:

`8b6787f1d13aa6da44734b6de084e42ffce2c995`

Submission:

`docs/work/agent_exchange/outbox/TZ_GRACE_ARCHITECTURE_REFACTOR_V2_09_CI_SINGLE_SOURCE_OF_TRUTH_SUBMISSION.md`

## Blocking finding — stale active execution-backend catalog

`docs/grace/ARCHITECTURE.md` is an active document explicitly named in Packet 09's final documentation audit. Its current **Execution backends** section says `select_backend()` returns only:

```text
api -> ApiAgentBackend
mock -> MockBackend
legacy -> removed in W8
```

That is factually stale.

Current source of truth at the reviewed SHA is `src/grace_control/agent/__init__.py`:

```text
BACKEND_CLI = "cli"
BACKEND_API = "api"
BACKEND_MOCK = "mock"
_VALID = {BACKEND_CLI, BACKEND_API, BACKEND_MOCK}
```

`select_backend()` constructs `UniversalCliAgentBackend` for `cli`, `ApiAgentBackend` for `api`, `MockBackend` for `mock`, and explicitly raises `ValueError` for `legacy`.

The neighboring active document `docs/grace/EXECUTION_BACKENDS.md` already states the correct current contract: `cli`, `mock`, `api`, with the `cli` backend retained as an internal generic subprocess/mini-swe-compatible execution adapter and **not** as the removed public/operator control CLI.

Therefore the submission statement `active-doc changes: none` is not correct, and Packet 09 acceptance criterion requiring current active documentation to reflect the final accepted architecture is not yet met.

## Required correction

Make the smallest doc-only correction in:

`docs/grace/ARCHITECTURE.md`

Update its **Execution backends** section to reflect the actual current supported selection:

- `cli` -> `UniversalCliAgentBackend`, internal generic subprocess/mini-swe-compatible packet execution;
- `api` -> `ApiAgentBackend`;
- `mock` -> `MockBackend`;
- `legacy` is removed/rejected and is **not** a selectable supported backend.

Keep the distinction explicit:

- public/user control CLI remains removed;
- internal `cli` execution backend remains supported infrastructure.

Do not modify product/runtime code, Makefile, workflow, lint baseline, API, DB, lifecycle, packet semantics, or historical `docs/work/` evidence for this correction.

Do not rewrite already-correct active docs merely for consistency. `docs/grace/EXECUTION_BACKENDS.md`, `docs/grace/CANON.md`, and `docs/grace/RUNBOOK_LOCAL_DEV.md` already express the internal-cli/public-control-CLI distinction correctly at the reviewed SHA.

## Required verification after correction

Run at minimum:

```bash
make docs-check
make lint
make hygiene
PYTHONPATH=src .venv/bin/pytest -q tests/grace_control/architecture/test_ci_single_source_of_truth.py
make ci

git diff --check
```

Also verify the corrected active docs are mutually consistent with current backend selection:

```bash
rg -n 'Execution backends|UniversalCliAgentBackend|BACKEND_CLI|legacy|control CLI|OpenCode' \
  src/grace_control/agent/__init__.py \
  docs/grace/ARCHITECTURE.md \
  docs/grace/EXECUTION_BACKENDS.md \
  docs/grace/CANON.md \
  docs/grace/RUNBOOK_LOCAL_DEV.md
```

No next packet. Resubmit only:

`docs/work/agent_exchange/outbox/TZ_GRACE_ARCHITECTURE_REFACTOR_V2_09_CI_SINGLE_SOURCE_OF_TRUTH_RESUBMISSION.md`

Machine lines must be exactly:

```text
WEB_ORCH_REPORT: RESUBMISSION TZ_GRACE_ARCHITECTURE_REFACTOR_V2_09_CI_SINGLE_SOURCE_OF_TRUTH
WEB_ORCH_STATUS: DONE
WEB_ORCH_COMMIT: <full-40-character-correction-sha>
WEB_ORCH_CHECKS: PASS
```
