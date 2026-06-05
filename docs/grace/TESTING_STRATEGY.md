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
pytest tests/ -q                  # quick
pytest tests/grace_control/ -q    # core tests only
make test                         # full suite with coverage
make lint                         # ruff + black + mypy
```

## Conventions

- Tests are async-safe (`asyncio_mode = auto`)
- No `db.query()` in routers — verified by `test_no_cli_business_logic.py`
- OpenAPI path presence verified by `test_openapi_paths.py`
- Every Wx wave adds a test file in the corresponding directory
