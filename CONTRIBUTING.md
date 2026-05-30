# Contributing to grace-orchestrator

Thank you for your interest in contributing to grace-orchestrator! This document provides guidelines and instructions for contributing.

## Code of Conduct

This project adheres to a code of conduct that all contributors are expected to follow. Please be respectful and constructive in all interactions.

## Getting Started

### Development Setup

1. Fork the repository on GitHub
2. Clone your fork locally:

```bash
git clone https://github.com/yourusername/grace-orchestrator.git
cd grace-orchestrator
```

3. Create a virtual environment:

```bash
python -m venv venv
source venv/bin/activate  # On Windows: venv\Scripts\activate
```

4. Install development dependencies:

```bash
pip install -e ".[dev,prefect]"
```

5. Install pre-commit hooks:

```bash
pre-commit install
```

### Running Tests

```bash
# Run all tests
pytest

# Run with coverage
pytest --cov=grace_orchestrator --cov-report=html

# Run specific test file
pytest tests/test_flows.py

# Run with verbose output
pytest -v
```

### Code Style

We use the following tools to maintain code quality:

- **black**: Code formatting
- **isort**: Import sorting
- **flake8**: Linting
- **mypy**: Type checking

Run all checks:

```bash
# Format code
black src/ tests/
isort src/ tests/

# Lint
flake8 src/ tests/

# Type check
mypy src/
```

## How to Contribute

### Reporting Bugs

Before creating a bug report:

1. Check the [existing issues](https://github.com/yourusername/grace-orchestrator/issues)
2. Verify you're using the latest version
3. Collect relevant information (version, OS, error messages, logs)

Create a bug report with:

- Clear, descriptive title
- Steps to reproduce
- Expected vs. actual behavior
- Environment details
- Relevant logs or screenshots

### Suggesting Features

Feature requests are welcome! Please:

1. Check if the feature has already been requested
2. Explain the use case and benefits
3. Provide examples of how it would work
4. Consider implementation complexity

### Pull Requests

1. Create a new branch from `main`:

```bash
git checkout -b feature/your-feature-name
```

2. Make your changes following our code style
3. Add or update tests as needed
4. Update documentation if applicable
5. Commit with clear, descriptive messages:

```bash
git commit -m "feat: add support for custom agent profiles"
```

6. Push to your fork:

```bash
git push origin feature/your-feature-name
```

7. Open a pull request with:
   - Clear description of changes
   - Link to related issues
   - Screenshots/examples if applicable
   - Test results

### Commit Message Format

We follow [Conventional Commits](https://www.conventionalcommits.org/):

```
<type>(<scope>): <subject>

<body>

<footer>
```

Types:
- `feat`: New feature
- `fix`: Bug fix
- `docs`: Documentation changes
- `style`: Code style changes (formatting, etc.)
- `refactor`: Code refactoring
- `test`: Adding or updating tests
- `chore`: Maintenance tasks

Examples:

```
feat(cli): add gracectl evidence export command

Add new command to export evidence to JSON format.
Includes tests and documentation.

Closes #123
```

```
fix(flows): handle missing project.yaml gracefully

Previously crashed with unclear error. Now provides
helpful message and exits cleanly.
```

## Development Guidelines

### Project Structure

```
grace-orchestrator/
├── src/grace_orchestrator/
│   ├── __init__.py
│   ├── cli/              # CLI commands
│   ├── core/             # Core logic
│   ├── agents/           # Agent implementations
│   ├── flows/            # Prefect flows
│   ├── templates/        # Project templates
│   └── utils/            # Utilities
├── tests/
│   ├── unit/
│   ├── integration/
│   └── fixtures/
├── docs/
└── docker/
```

### Adding New Features

1. **CLI Commands**: Add to `src/grace_orchestrator/cli/`
2. **Flows**: Add to `src/grace_orchestrator/flows/`
3. **Agents**: Add to `src/grace_orchestrator/agents/`
4. **Tests**: Mirror structure in `tests/`

### Testing Guidelines

- Write tests for all new features
- Maintain or improve code coverage
- Use fixtures for common test data
- Mock external dependencies (Prefect, API calls)
- Test both success and failure cases

Example test:

```python
import pytest
from grace_orchestrator.config import load_project_config

def test_load_project_config_success(tmp_path):
    """Test loading valid project configuration."""
    config_file = tmp_path / "project.yaml"
    config_file.write_text("""
    defaults:
      repo_root: .
    slices:
      TEST-SLICE:
        title: "Test Slice"
    """)
    
    config = load_project_config(config_file)
    assert config.defaults.repo_root == "."
    assert "TEST-SLICE" in config.slices

def test_load_project_config_missing_file():
    """Test handling of missing configuration file."""
    with pytest.raises(FileNotFoundError):
        load_project_config("nonexistent.yaml")
```

### Documentation

- Update README.md for user-facing changes
- Add docstrings to all public functions/classes
- Update API documentation in `docs/`
- Include examples for new features

Docstring format:

```python
def create_verification_flow(slice_id: str, config_path: str) -> Flow:
    """Create a Prefect flow for slice verification.
    
    Args:
        slice_id: Unique identifier for the verification slice
        config_path: Path to grace/project.yaml configuration
        
    Returns:
        Configured Prefect Flow instance
        
    Raises:
        ValueError: If slice_id not found in configuration
        FileNotFoundError: If config_path does not exist
        
    Example:
        >>> flow = create_verification_flow("AUTH-FLOW", "grace/project.yaml")
        >>> flow.deploy(name="auth-verification")
    """
```

## Release Process

Maintainers handle releases:

1. Update version in `pyproject.toml`
2. Update CHANGELOG.md
3. Create release tag: `git tag v0.2.0`
4. Push tag: `git push origin v0.2.0`
5. GitHub Actions builds and publishes to PyPI

## Questions?

- Open a [Discussion](https://github.com/yourusername/grace-orchestrator/discussions)
- Join our community chat (link TBD)
- Email maintainers (see README.md)

## License

By contributing, you agree that your contributions will be licensed under the MIT License.
