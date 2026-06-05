# ############################################################################
# AI_HEADER: api_main
# ROLE: FastAPI application entry point for GRACE Control Plane — wiring-only.
#       All configuration lives in `app_factory.create_app` and the routers
#       under `api/routers/`. This file is intentionally small.
# ############################################################################

# START_MODULE_CONTRACT
# purpose: Provide `app` (FastAPI instance) and `main()` (uvicorn runner).
#          All real work is in `app_factory.py`.
# inputs: None at module load. `main()` reads settings.api_host/api_port.
# returns: FastAPI app instance + uvicorn runner.
# side_effects: Imports the app; main() binds a socket.
# emitted_logs: None.
# error_behavior: None.
# END_MODULE_CONTRACT

# START_MODULE_MAP
# mapping:
#   - app: FastAPI instance (from app_factory)
#   - function: main
# END_MODULE_MAP

from __future__ import annotations

import uvicorn

from grace_control.api.app_factory import create_app
from grace_control.config.settings import settings

app = create_app()


def main() -> None:
    """Run the API under uvicorn. Used by deployment / dev scripts."""
    uvicorn.run(
        "grace_control.api.main:app",
        host=settings.api_host,
        port=settings.api_port,
        reload=False,
    )


if __name__ == "__main__":
    main()
