from __future__ import annotations

import logging
from typing import Any, Callable

try:
    from prefect import flow, get_run_logger, tags, task
except ModuleNotFoundError:
    def task(fn: Callable[..., Any] | None = None, **_: Any):
        def decorator(inner: Callable[..., Any]) -> Callable[..., Any]:
            return inner

        if fn is not None:
            return decorator(fn)
        return decorator

    def flow(fn: Callable[..., Any] | None = None, **_: Any):
        def decorator(inner: Callable[..., Any]) -> Callable[..., Any]:
            return inner

        if fn is not None:
            return decorator(fn)
        return decorator

    class _NoopTags:
        def __init__(self, *_: Any):
            pass

        def __enter__(self) -> None:
            return None

        def __exit__(self, *_: Any) -> bool:
            return False

    def tags(*_: Any):
        return _NoopTags()

    def get_run_logger() -> logging.Logger:
        return logging.getLogger("prefect_grace")
