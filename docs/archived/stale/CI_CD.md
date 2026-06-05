# CI/CD Pipeline

## GitHub Actions Workflows

### CI Workflow (.github/workflows/ci.yml)

Runs on every push and PR to main/develop.

**Jobs:**
1. **test** - Run pytest with coverage (Python 3.11, 3.12)
2. **lint** - Run ruff, black, isort
3. **type-check** - Run mypy
4. **verification** - Run health checks and verification tools
5. **security** - Run bandit and safety

**Quality Gates:**
- Coverage ≥60%
- All tests pass
- No linting errors
- No type errors
- No security issues

### Pre-commit Hooks

Run automatically on git commit:
- Trailing whitespace removal
- End-of-file fixer
- YAML/JSON/TOML validation
- Large file detection
- Private key detection
- Black formatting
- isort import sorting
- Ruff linting
- Mypy type checking

**Setup:**
```bash
./scripts/setup_precommit.sh
```

## Local Development

**Run tests:**
```bash
pytest tests/ -v --cov
```

**Run linting:**
```bash
ruff check src/grace_control
black src/grace_control
isort src/grace_control
```

**Run type checking:**
```bash
mypy src/grace_control --ignore-missing-imports
```

**Run all checks:**
```bash
pre-commit run --all-files
```

## CI/CD Best Practices

### Before Committing

1. Run tests locally: `pytest tests/ -v`
2. Check coverage: `pytest --cov=src/grace_control --cov-report=term tests/`
3. Run linters: `ruff check src/grace_control`
4. Format code: `black src/grace_control && isort src/grace_control`
5. Type check: `mypy src/grace_control --ignore-missing-imports`

Or simply run: `pre-commit run --all-files`

### Before Creating PR

1. Ensure all tests pass locally
2. Verify coverage meets 60% threshold
3. Fix all linting and type errors
4. Update documentation if needed
5. Write clear commit messages

### PR Review Process

1. CI checks must pass (all jobs green)
2. Code review from at least 1 reviewer
3. All conversations resolved
4. Branch up to date with base

## Troubleshooting

### Coverage Below Threshold

Add tests for uncovered code or adjust threshold in `.github/workflows/ci.yml`:
```yaml
- name: Check coverage threshold
  run: |
    coverage report --fail-under=60  # Adjust this value
```

### Linting Errors

Auto-fix most issues:
```bash
ruff check --fix src/grace_control
black src/grace_control
isort src/grace_control
```

### Type Errors

Add type hints or use `# type: ignore` comments for unavoidable issues:
```python
result = some_untyped_function()  # type: ignore
```

### Pre-commit Hook Failures

Skip hooks temporarily (not recommended):
```bash
git commit --no-verify
```

Better: Fix the issues or update `.pre-commit-config.yaml`

## Security Scanning

### Bandit

Scans for common security issues in Python code.

**Run locally:**
```bash
bandit -r src/grace_control -ll
```

**Ignore false positives:**
Add `# nosec` comment:
```python
password = os.getenv("PASSWORD")  # nosec B105
```

### Safety

Checks dependencies for known security vulnerabilities.

**Run locally:**
```bash
safety check
```

**Update vulnerable packages:**
```bash
pip install --upgrade <package-name>
```

## Continuous Improvement

### Adding New Checks

Edit `.github/workflows/ci.yml` to add new jobs or steps.

### Updating Dependencies

Keep CI dependencies current:
- Update versions in `pyproject.toml`
- Update pre-commit hook versions in `.pre-commit-config.yaml`
- Update GitHub Actions versions in `.github/workflows/ci.yml`

### Monitoring CI Performance

- Check job execution times in GitHub Actions
- Optimize slow tests
- Use caching for dependencies
- Run expensive checks only on main/develop branches
