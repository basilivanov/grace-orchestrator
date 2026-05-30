#!/bin/bash
# Setup pre-commit hooks

set -euo pipefail

echo "Installing pre-commit..."
pip install pre-commit

echo "Installing pre-commit hooks..."
pre-commit install

echo "Running pre-commit on all files..."
pre-commit run --all-files || true

echo "✓ Pre-commit hooks installed"
echo ""
echo "Hooks will run automatically on git commit"
echo "To run manually: pre-commit run --all-files"
