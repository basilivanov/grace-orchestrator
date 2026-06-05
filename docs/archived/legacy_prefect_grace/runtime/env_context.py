"""Context manager for safe Prefect API URL environment variable management.

This module provides a context manager pattern for temporarily setting the
PREFECT_API_URL environment variable in a stack-safe, exception-safe manner.
It prevents global state pollution and ensures proper cleanup even when
exceptions occur.
"""

import atexit
import logging
import os
from typing import Optional

logger = logging.getLogger(__name__)


class PrefectAPIContext:
    """Context manager for temporarily setting PREFECT_API_URL.

    This class provides stack-based tracking for nested contexts and automatic
    restoration of the previous value on exit, even when exceptions occur.

    Example:
        >>> with PrefectAPIContext("https://api.prefect.cloud/api/accounts/..."):
        ...     # PREFECT_API_URL is set for this block
        ...     deployment.apply()
        ... # PREFECT_API_URL is restored to previous value

    Features:
        - Stack-based nesting support
        - Exception-safe restoration
        - Leak detection at process exit
        - Input validation
    """

    _stack: list[tuple[str, Optional[str]]] = []

    def __init__(self, api_url: str):
        """Initialize context with target API URL.

        Args:
            api_url: The Prefect API URL to set temporarily.

        Raises:
            ValueError: If api_url is empty or None.
        """
        if not api_url:
            raise ValueError("api_url cannot be empty or None")
        self.api_url = api_url
        self.previous_value: Optional[str] = None

    def __enter__(self) -> "PrefectAPIContext":
        """Enter the context and set PREFECT_API_URL."""
        self.previous_value = os.environ.get("PREFECT_API_URL")
        os.environ["PREFECT_API_URL"] = self.api_url

        # Track on stack for leak detection
        PrefectAPIContext._stack.append((self.api_url, self.previous_value))

        logger.debug(
            f"PrefectAPIContext entered: set PREFECT_API_URL to {self.api_url} "
            f"(previous: {self.previous_value}, depth: {len(PrefectAPIContext._stack)})"
        )

        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        """Exit the context and restore previous PREFECT_API_URL value."""
        # Remove from stack
        if PrefectAPIContext._stack:
            PrefectAPIContext._stack.pop()

        # Restore previous value
        if self.previous_value is not None:
            os.environ["PREFECT_API_URL"] = self.previous_value
        else:
            os.environ.pop("PREFECT_API_URL", None)

        logger.debug(
            f"PrefectAPIContext exited: restored PREFECT_API_URL to {self.previous_value} "
            f"(depth: {len(PrefectAPIContext._stack)})"
        )

        # Don't suppress exceptions
        return False

    @classmethod
    def current_depth(cls) -> int:
        """Return the current nesting depth of contexts.

        Returns:
            Number of active PrefectAPIContext instances.
        """
        return len(cls._stack)

    @classmethod
    def check_for_leaks(cls) -> None:
        """Check for leaked contexts at process exit.

        This is registered with atexit to detect programming errors where
        contexts were not properly exited.
        """
        if cls._stack:
            logger.warning(
                f"PrefectAPIContext leak detected: {len(cls._stack)} context(s) "
                f"not properly exited at process termination. Stack: {cls._stack}"
            )


def prefect_api_context(api_url: str) -> PrefectAPIContext:
    """Convenience function to create a PrefectAPIContext.

    Args:
        api_url: The Prefect API URL to set temporarily.

    Returns:
        A PrefectAPIContext instance ready to use as a context manager.

    Example:
        >>> with prefect_api_context("https://api.prefect.cloud/..."):
        ...     deployment.apply()
    """
    return PrefectAPIContext(api_url)


# Register leak detection at process exit
atexit.register(PrefectAPIContext.check_for_leaks)
