# Development Setup

## Pre-commit Hooks

Install pre-commit hooks:

```bash
pip install pre-commit
pre-commit install
```

Run manually:

```bash
pre-commit run --all-files
```

## Quality Checks

### Type Checking

```bash
mypy src/prefect_grace
```

Core modules have strict typing enabled:
- `prefect_grace.runtime_config`
- `prefect_grace.platform.*` (selected modules)

### Code Formatting

```bash
black src/prefect_grace
```

### Linting

```bash
ruff check src/prefect_grace
```

### Coverage

```bash
pytest --cov=prefect_grace --cov-report=html
open htmlcov/index.html
```

**Minimum coverage: 75%**

## CI Pipeline

All checks run in CI:
- pytest (75% coverage required)
- mypy (strict for core modules)
- black (formatting)
- ruff (linting)

## Running Tests

```bash
# Run all tests
pytest

# Run with coverage
pytest --cov=prefect_grace --cov-report=term

# Run specific test file
pytest src/prefect_grace/tests/test_executor_integration.py

# Run with verbose output
pytest -v
```

## Pre-commit Hook Details

The pre-commit configuration runs:
1. **black**: Code formatting (line length 120)
2. **ruff**: Linting with auto-fix
3. **mypy**: Type checking for core modules

Hooks run automatically on `git commit`. To skip (not recommended):
```bash
git commit --no-verify
```
