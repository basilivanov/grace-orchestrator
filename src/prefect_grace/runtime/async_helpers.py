# ############################################################################
# AI_HEADER: async_helpers
# ROLE: Safe async/sync interop utilities with event loop detection.
# ############################################################################

# START_MODULE_CONTRACT
# purpose: Provide safe utilities for running async code from sync contexts.
# inputs: Coroutines to execute.
# returns: Results from async execution.
# side_effects: May create new event loops when safe to do so.
# emitted_logs: None.
# error_behavior: Raises RuntimeError if called from within existing event loop.
# END_MODULE_CONTRACT

import asyncio
from typing import Any, Coroutine, TypeVar

T = TypeVar('T')


def is_in_event_loop() -> bool:
    """
    Detect if currently running inside an event loop.

    Returns:
        True if inside an event loop, False otherwise.
    """
    try:
        asyncio.get_running_loop()
        return True
    except RuntimeError:
        return False


def run_async_safe(coro: Coroutine[Any, Any, T]) -> T:
    """
    Safely run an async coroutine from a sync context.

    This function checks if we're already in an event loop and raises
    a clear error if so. Use this instead of asyncio.run() in sync methods
    that might be called from async contexts.

    Args:
        coro: The coroutine to execute.

    Returns:
        The result of the coroutine execution.

    Raises:
        RuntimeError: If called from within an existing event loop.
                     The error message guides users to use the async version.

    Example:
        # In a sync method:
        def read_status(self):
            async def _fetch():
                return await some_async_call()
            return run_async_safe(_fetch())

        # In an async method:
        async def read_status_async(self):
            return await some_async_call()
    """
    if is_in_event_loop():
        raise RuntimeError(
            "Cannot use run_async_safe() from within an event loop. "
            "You are calling a sync method from an async context. "
            "Please use the async version of this method instead (e.g., read_run_status_async())."
        )

    return asyncio.run(coro)
