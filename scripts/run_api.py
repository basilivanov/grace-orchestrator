#!/usr/bin/env python3
"""Start GRACE Control Plane API server."""
import os
import uvicorn

# Honor either GRACE_DB_URL (set by supervisor) or GRACE_DATABASE_URL (env yaml).
# Fallback to a sane default ONLY if neither is set, so ad-hoc runs still work.
if "GRACE_DB_URL" not in os.environ and "GRACE_DATABASE_URL" in os.environ:
    os.environ["GRACE_DB_URL"] = os.environ["GRACE_DATABASE_URL"]
os.environ.setdefault("GRACE_DB_URL", "sqlite:////tmp/grace_live.db")

from grace_control.db import init_db

init_db()

from grace_control.api.main import app

if __name__ == "__main__":
    uvicorn.run(app, host="127.0.0.1", port=8042, log_level="info")
