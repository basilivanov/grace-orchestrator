# GraceLint Rules

GraceLint is a set of source-level rules enforced via `make lint` (ruff +
black + mypy) and custom checks in `Makefile`.

| Rule | Check | Enforced by |
| --- | --- | --- |
| `GRC100` | No `prefect_grace` import in `src/grace_control/` | ruff / grep |
| `GRC101` | No `db.query()` in router files | `tests/grace_control/api/test_no_cli_business_logic.py` |
| `GRC102` | No inline `subprocess.run(["git", ...])` in adapter class | Source audit |
| `GRC103` | No env-reads in `app_factory.py` | `test_post_refactor_audit_fixes.py` |
| `GRC104` | `api/main.py` < 150 lines | File budget check |
| `GRC105` | Router files do not contain business logic from deleted CLI commands | `test_no_cli_business_logic.py` |

## W10 expansion

W10 will expand this to [14 rules](/source/codex/tz-api-first-cleanup-waves-w0-w11.md#w10).
