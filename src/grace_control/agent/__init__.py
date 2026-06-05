# ############################################################################
# AI_HEADER: agent
# ROLE: Public API for execution backends — select_backend() factory.
# ############################################################################

# START_MODULE_CONTRACT
# purpose: Public entry point for picking an ExecutionBackend implementation.
#          Single owner of the "which backend is active" decision; consumed by
#          adapters.packet_executor.PacketExecutionAdapter. The choice is driven
#          by grace_control.config.settings.execution_backend (env:
#          GRACE_EXECUTION_BACKEND).
# inputs: backend_name (str) — "legacy", "api", or "mock".
# returns: ExecutionBackend instance.
# side_effects: Lazy-imports the chosen backend module on first call.
# emitted_logs: backend_selected.
# error_behavior: Raises ValueError for unknown backend names.
# END_MODULE_CONTRACT

# START_MODULE_MAP
# mapping:
#   - function: select_backend
#   - constant: BACKEND_LEGACY
#   - constant: BACKEND_API
#   - constant: BACKEND_MOCK
# END_MODULE_MAP

from __future__ import annotations

from grace_control.agent.backend import ExecutionBackend
from grace_control.core.structured_logger import GraceLogger

_log = GraceLogger("agent")

BACKEND_LEGACY = "legacy"
BACKEND_API = "api"
BACKEND_MOCK = "mock"
# Back-compat alias kept for tests + downstream code.
BACKEND_NEW = BACKEND_API

_VALID = {BACKEND_LEGACY, BACKEND_API, BACKEND_MOCK}


def select_backend(backend_name: str = "") -> ExecutionBackend:
    """Return an ExecutionBackend instance for the given name.

    Args:
        backend_name: One of "legacy" (wraps prefect_grace), "api"
                      (delegates to AgentGatewayService), or "mock"
                      (in-process, no subprocess). When backend_name is
                      empty, reads
                      grace_control.config.settings.execution_backend
                      (env: GRACE_EXECUTION_BACKEND).

    Raises:
        ValueError: if backend_name is not in {"legacy", "api", "mock"}.
    """
    if not backend_name:
        from grace_control.config.settings import settings as _settings
        backend_name = _settings.execution_backend

    if backend_name not in _VALID:
        raise ValueError(
            f"Unknown execution backend: {backend_name!r}. "
            f"Expected one of {sorted(_VALID)}."
        )

    if backend_name == BACKEND_LEGACY:
        # Lazy import keeps the legacy boundary isolated — no prefect_grace at
        # module import time. Only the legacy_backend module imports it.
        from grace_control.agent.legacy_backend import LegacyPrefectBackend
        backend: ExecutionBackend = LegacyPrefectBackend()
    elif backend_name == BACKEND_API:
        from grace_control.agent.api_backend import ApiAgentBackend
        backend = ApiAgentBackend()
    else:  # mock
        from grace_control.agent.mock_backend import MockBackend
        backend = MockBackend()

    _log.info("backend_selected", backend=backend_name)
    return backend
