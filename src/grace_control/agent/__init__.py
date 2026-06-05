# AI_HEADER: agent — select_backend() factory (BACKEND_CLI | BACKEND_API | BACKEND_MOCK)
# START_MODULE_CONTRACT
# purpose: Public entry point for picking an ExecutionBackend implementation.
#          Reads grace_control.config.settings.execution_backend (env:
#          GRACE_EXECUTION_BACKEND) when called with empty name.
# inputs: backend_name (str) — "cli", "api", or "mock".
# returns: ExecutionBackend instance.
# side_effects: Lazy-imports the chosen backend module.
# emitted_logs: backend_selected.
# error_behavior: Raises ValueError for "legacy" or unknown names.
# END_MODULE_CONTRACT
# START_MODULE_MAP
# mapping:   - function: select_backend
#           - constants: BACKEND_CLI, BACKEND_API, BACKEND_MOCK
# END_MODULE_MAP

from __future__ import annotations
from grace_control.agent.backend import ExecutionBackend
from grace_control.core.structured_logger import GraceLogger
_log = GraceLogger("agent")

BACKEND_CLI = "cli"
BACKEND_API = "api"
BACKEND_MOCK = "mock"
BACKEND_NEW = BACKEND_CLI  # back-compat alias for existing test code

_VALID = {BACKEND_CLI, BACKEND_API, BACKEND_MOCK}


def select_backend(backend_name: str = "") -> ExecutionBackend:
    if not backend_name:
        from grace_control.config.settings import settings as _settings
        backend_name = _settings.execution_backend
    if backend_name == "legacy":
        raise ValueError("execution_backend='legacy' was removed in W8. Use 'cli', 'api', or 'mock'.")
    if backend_name not in _VALID:
        raise ValueError(f"Unknown execution backend: {backend_name!r}. Expected one of {sorted(_VALID)}.")
    if backend_name == BACKEND_CLI:
        from grace_control.agent.universal_cli_backend import UniversalCliAgentBackend
        backend: ExecutionBackend = UniversalCliAgentBackend()
    elif backend_name == BACKEND_API:
        from grace_control.agent.api_backend import ApiAgentBackend
        backend = ApiAgentBackend()
    else:
        from grace_control.agent.mock_backend import MockBackend
        backend = MockBackend()
    _log.info("backend_selected", backend=backend_name)
    return backend
