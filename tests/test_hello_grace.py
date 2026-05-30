"""Tests for hello_grace module."""

import sys
from pathlib import Path

# Add src to path for imports
src_path = Path(__file__).parent.parent / "src"
sys.path.insert(0, str(src_path))

from hello_grace import hello


def test_hello_returns_correct_message():
    """Test that hello() returns 'Hello GRACE!'."""
    assert hello() == "Hello GRACE!"


def test_hello_function_exists_and_callable():
    """Test that hello function exists and is callable."""
    assert callable(hello)
    assert hasattr(hello, "__call__")
