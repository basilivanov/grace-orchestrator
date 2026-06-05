"""Tests for async_helpers module."""

import asyncio
import pytest

from prefect_grace.runtime.async_helpers import is_in_event_loop, run_async_safe


def test_is_in_event_loop_from_sync_context():
    """Test that is_in_event_loop returns False from sync context."""
    assert is_in_event_loop() is False


@pytest.mark.asyncio
async def test_is_in_event_loop_from_async_context():
    """Test that is_in_event_loop returns True from async context."""
    assert is_in_event_loop() is True


def test_run_async_safe_from_sync_context():
    """Test that run_async_safe works from sync context."""
    async def _sample_coro():
        await asyncio.sleep(0.01)
        return "success"

    result = run_async_safe(_sample_coro())
    assert result == "success"


@pytest.mark.asyncio
async def test_run_async_safe_raises_from_async_context():
    """Test that run_async_safe raises clear error from async context."""
    async def _sample_coro():
        return "should not reach here"

    with pytest.raises(RuntimeError) as exc_info:
        run_async_safe(_sample_coro())

    error_msg = str(exc_info.value)
    assert "event loop" in error_msg.lower()
    assert "async version" in error_msg.lower()


def test_run_async_safe_propagates_exceptions():
    """Test that exceptions from coroutines are propagated correctly."""
    async def _failing_coro():
        raise ValueError("test error")

    with pytest.raises(ValueError) as exc_info:
        run_async_safe(_failing_coro())

    assert str(exc_info.value) == "test error"


def test_run_async_safe_with_return_value():
    """Test that run_async_safe returns coroutine results correctly."""
    async def _compute():
        await asyncio.sleep(0.01)
        return {"status": "ok", "value": 42}

    result = run_async_safe(_compute())
    assert result == {"status": "ok", "value": 42}


def test_run_async_safe_with_nested_async_calls():
    """Test that run_async_safe works with nested async calls."""
    async def _inner():
        await asyncio.sleep(0.01)
        return "inner"

    async def _outer():
        result = await _inner()
        return f"outer-{result}"

    result = run_async_safe(_outer())
    assert result == "outer-inner"
