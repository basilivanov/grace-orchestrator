# ############################################################################
# AI_HEADER: api_main
# ROLE: FastAPI application entry point for GRACE Control Plane.
# ############################################################################

# START_MODULE_CONTRACT
# purpose: Create FastAPI app with lifespan, CORS, routers, and uvicorn runner.
# inputs: None (reads GRACE_DB_URL from env).
# returns: FastAPI app instance.
# side_effects: Initializes DB on startup.
# emitted_logs: None.
# error_behavior: None at module level.
# END_MODULE_CONTRACT

# START_MODULE_MAP
# mapping:
#   - app: FastAPI instance
#   - function: lifespan
#   - function: health
#   - function: main
# END_MODULE_MAP

from __future__ import annotations

import asyncio
import os
from contextlib import asynccontextmanager
from datetime import datetime

import uvicorn
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from grace_control.api.routers import architect, features, packets, workers
from grace_control.db import init_db

_lease_task = None

#START_BLOCK_LIFESPAN
@asynccontextmanager
async def lifespan(app: FastAPI):
    global _lease_task
    db_url = os.environ.get("GRACE_DB_URL")
    init_db(db_url)
    from grace_control.core.lease_manager import lease_expiration_loop
    _lease_task = asyncio.create_task(lease_expiration_loop())
    yield
    if _lease_task:
        _lease_task.cancel()

#END_BLOCK_LIFESPAN

#START_BLOCK_APP
app = FastAPI(
    title="GRACE Control Plane",
    version="0.1.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origin_regex=r"http://localhost:\d+",
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(features.router, prefix="/api/features", tags=["features"])
app.include_router(packets.router, prefix="/api/packets", tags=["packets"])
app.include_router(workers.router, prefix="/api/workers", tags=["workers"])
app.include_router(architect.router, prefix="/api/architect", tags=["architect"])

#END_BLOCK_APP

#START_BLOCK_HEALTH
@app.get("/health")
async def health():
    from grace_control.core.health import check_health
    return await check_health()

#END_BLOCK_HEALTH

#START_BLOCK_MAIN
def main():
    port = int(os.environ.get("GRACE_API_PORT", "8042"))
    uvicorn.run(
        "grace_control.api.main:app",
        host="127.0.0.1",
        port=port,
        reload=False,
    )

if __name__ == "__main__":
    main()

#END_BLOCK_MAIN
