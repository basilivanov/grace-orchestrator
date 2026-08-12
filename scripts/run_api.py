#!/usr/bin/env python3
"""Start GRACE Control Plane API server."""
import os
from pathlib import Path
import uvicorn

# Honor either GRACE_DB_URL (set by supervisor) or GRACE_DATABASE_URL (env yaml).
# Fallback to a sane default ONLY if neither is set, so ad-hoc runs still work.
if "GRACE_DB_URL" not in os.environ and "GRACE_DATABASE_URL" in os.environ:
    os.environ["GRACE_DB_URL"] = os.environ["GRACE_DATABASE_URL"]
os.environ.setdefault("GRACE_DB_URL", f"sqlite:///{Path.cwd() / 'grace.db'}")

# Protect API from OOM killer: set oom_score_adj to OOM_SCORE_ADJ_MIN (-1000).
# When an agent run consumes 4+ GB RSS and system runs out of memory,
# the OOM killer must kill the big subprocess, NOT the API.
try:
    with open("/proc/self/oom_score_adj", "w") as _f:
        _f.write("-1000\n")
except OSError:
    pass

from grace_control.db import init_db

init_db()

from grace_control.api.main import app

if __name__ == "__main__":
    host = os.environ.get("GRACE_API_HOST", "127.0.0.1")
    port = int(os.environ.get("GRACE_API_PORT", "8042"))
    uvicorn.run(app, host=host, port=port, log_level="info")
