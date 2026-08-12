# Testing Strategy

## Test layers

| Layer | Location | What |
| --- | --- | --- |
| Unit | `tests/grace_control/adapters/`, `services/`, `agent/`, `config/` | Individual classes/functions, mocked DB |
| API | `tests/grace_control/api/` | FastAPI TestClient (sync), per-test SQLite |
| Integration | `tests/grace_control/core/` | Real DB, real subprocess where safe |
| Recovery | `tests/grace_control/core/test_recovery_real_db.py` | Real DB with file-based SQLite (1 pre-existing fail) |

## Fixtures

| Fixture | Type | Purpose |
| --- | --- | --- |
| `tmp_path` | pytest built-in | Per-test temp dir |
| `db` | `tests/conftest.py` | In-memory SQLite session |
| `api` | `tests/conftest.py` | AsyncClient with ASGITransport |
| `client` | per-test file | TestClient with per-test DB |

## Execution backend in tests

All tests use `MockBackend` (in-process, no subprocess) or inject a
`_FakeBackend` directly. No tests require `prefect_grace` or API keys.

## Running

```bash
make test        # deterministic suite; external/live are explicitly marked
make lint        # Ruff + GraceLint over the canonical CI scope
make docs-check  # generated documentation freshness
make hygiene     # repository hygiene
make ci          # all four canonical gates
make test-live   # explicitly live tests; requires a running environment
```

`make test` covers the deterministic project test scope across the top-level
tests and supported test families. Tests that require a running API, browser,
or external provider are marked `external`/`live` and are not counted as
deterministic CI coverage. `tests/live/` remains an explicit runtime smoke
family and is invoked only through `make test-live`.

`make lint` evaluates one explicit `CI_LINT_SCOPE` shared by Ruff and
GraceLint: `src/grace_control`, `tests`, and `scripts`. The baseline-aware
runner still executes both linters over the complete supported scope, reports
their existing diagnostics, and fails on any diagnostic drift. It does not
use a path whitelist, broad ignore, or new rule allowlist.

## Conventions

- Tests are async-safe (`asyncio_mode = auto`)
- No `db.query()` in routers — verified by `test_no_cli_business_logic.py`
- OpenAPI path presence verified by `test_openapi_paths.py`
- Every Wx wave adds a test file in the corresponding directory
