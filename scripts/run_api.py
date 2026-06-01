#!/usr/bin/env python3
"""Start GRACE Control Plane API server."""
import os
import uvicorn

os.environ.setdefault("GRACE_DB_URL", "sqlite:////tmp/grace_live.db")

from grace_control.db import init_db

init_db()

from grace_control.api.main import app

if __name__ == "__main__":
    uvicorn.run(app, host="127.0.0.1", port=8042, log_level="info")
