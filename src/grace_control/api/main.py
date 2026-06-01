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
from pathlib import Path

import uvicorn
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from grace_control.api.routers import architect, features, packets, workers
from grace_control.db import init_db

_lease_task = None
_UI_DIR = Path(__file__).parent.parent / "ui"

#START_BLOCK_LIFESPAN
@asynccontextmanager
async def lifespan(app: FastAPI):
    global _lease_task
    db_url = os.environ.get("GRACE_DB_URL")
    init_db(db_url)
    from grace_control.core.lease_manager import lease_expiration_loop
    _lease_task = asyncio.create_task(lease_expiration_loop())
    from grace_control.core.wave_gate import check_wave_gates as _gate_loop
    async def _gate_task():
        while True:
            try: check_wave_gates()
            except Exception: pass
            await asyncio.sleep(30)
    asyncio.create_task(_gate_task())
    from grace_control.core.feature_gate import check_feature_completion
    async def _feature_task():
        while True:
            try: check_feature_completion()
            except Exception: pass
            await asyncio.sleep(60)
    asyncio.create_task(_feature_task())
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

# Global exception handler — API survives any runtime error
from fastapi import Request
from fastapi.responses import JSONResponse as _JSONResponse

@app.exception_handler(Exception)
async def global_exception_handler(request: Request, exc: Exception):
    return _JSONResponse(
        status_code=500,
        content={"error": {"code": "INTERNAL_ERROR", "message": str(exc)[:200]}},
    )

app.include_router(features.router, prefix="/api/features", tags=["features"])
app.include_router(packets.router, prefix="/api/packets", tags=["packets"])
app.include_router(workers.router, prefix="/api/workers", tags=["workers"])
app.include_router(architect.router, prefix="/api/architect", tags=["architect"])

#END_BLOCK_APP

#START_BLOCK_UI
@app.get("/", response_class=HTMLResponse)
async def dashboard():
    template = _UI_DIR / "templates" / "dashboard.html"
    if template.exists():
        return HTMLResponse(template.read_text())
    return HTMLResponse("<h1>GRACE Control Plane</h1><p>Dashboard template not found.</p>")


@app.get("/test")
async def test_page():
    """Minimal test page to verify basic rendering."""
    from grace_control.db import get_db as _gdb
    from grace_control.db.schema import Feature, Packet
    with _gdb() as db:
        fcount = db.query(Feature).count()
        pcount = db.query(Packet).count()
    return HTMLResponse(f"""<!doctype html><html><head><meta charset=UTF-8><title>GRACE Test</title></head>
<body style="font-family:sans-serif;background:#0d1117;color:#c9d1d9;padding:20px">
<h1 style=color:#58a6ff>GRACE Control Plane</h1>
<p>Server is running. API is healthy.</p>
<ul>
<li>Features: {fcount}</li>
<li>Packets: {pcount}</li>
<li>API: <a href=/api/dashboard style=color:#58a6ff>/api/dashboard</a></li>
<li>Health: <a href=/health style=color:#58a6ff>/health</a></li>
</ul>
<p style=color:#8b949e;font-size:12px>If you can see this, the problem is in dashboard.html JavaScript.</p>
<p style=color:#8b949e;font-size:12px>If you CANNOT see this, the problem is network/browser.</p>
</body></html>""")


@app.get("/api/dashboard")
async def dashboard_data():
    """Aggregated view: features → waves → packets + workers + stats."""
    from grace_control.db import get_db as _gdb
    from grace_control.db.schema import Feature, Wave, Packet, Worker

    with _gdb() as db:
        features = db.query(Feature).all()
        workers = db.query(Worker).all()

        result_features = []
        for f in features:
            waves = db.query(Wave).filter_by(feature_id=f.id).order_by(Wave.order).all()
            fw = []
            for w in waves:
                packets = db.query(Packet).filter_by(feature_id=f.id, wave_id=w.id).all()
                fw.append({
                    "id": w.id, "title": w.title, "order": w.order, "status": w.status,
                    "packets": [
                        {"id": p.id, "title": p.title, "state": p.state,
                         "acceptance_profile": p.acceptance_profile,
                         "attempt_count": p.attempt_count, "max_attempts": p.max_attempts,
                         "feature_id": p.feature_id, "wave_id": p.wave_id}
                        for p in packets
                    ]
                })
            result_features.append({
                "id": f.id, "title": f.title, "status": f.status, "waves": fw,
            })

        # Stats
        all_pkts = db.query(Packet).all()
        stats = {}
        for p in all_pkts:
            stats[p.state] = stats.get(p.state, 0) + 1
        active_workers = len([w for w in workers if w.status == "active"])

        return {
            "features": result_features,
            "workers": [{"id": w.id, "status": w.status, "current_packet_id": w.current_packet_id,
                         "last_heartbeat": w.last_heartbeat.isoformat() + "Z" if w.last_heartbeat else None}
                        for w in workers],
            "stats": {**stats, "workers": active_workers},
        }


@app.get("/api/events")
async def list_events(entity_type: str = "", entity_id: str = "", limit: int = 100):
    from grace_control.db import get_db as _gdb
    from grace_control.db.schema import Event

    with _gdb() as db:
        q = db.query(Event).order_by(Event.timestamp.desc())
        if entity_type:
            q = q.filter_by(entity_type=entity_type)
        if entity_id:
            q = q.filter_by(entity_id=entity_id)
        events = q.limit(limit).all()
        return {
            "data": [
                {"timestamp": e.timestamp.isoformat() + "Z", "event_type": e.event_type,
                 "entity_type": e.entity_type, "entity_id": e.entity_id,
                 "payload": e.payload_json, "trace_id": e.trace_id}
                for e in reversed(events)
            ]
        }


@app.get("/api/packets/{packet_id}/runs/{run_id}")
async def get_packet_run(packet_id: str, run_id: str):
    from grace_control.db import get_db as _gdb
    from grace_control.db.schema import PacketRun
    with _gdb() as db:
        run = db.query(PacketRun).filter_by(id=f"{packet_id}-{run_id}").first()
        if not run:
            return JSONResponse({"error": "not found"}, status_code=404)
        return {
            "data": {
                "id": run.id, "packet_id": run.packet_id, "run_number": run.run_number,
                "status": run.status, "result_json": run.result_json,
                "evidence_path": run.evidence_path, "executor_id": run.executor_id,
                "started_at": run.started_at.isoformat() + "Z" if run.started_at else None,
                "finished_at": run.finished_at.isoformat() + "Z" if run.finished_at else None,
                "duration_ms": run.duration_ms,
            }
        }


@app.get("/api/packets/{packet_id}/runs/{run_id}/artifacts")
async def list_artifacts(packet_id: str, run_id: str):
    from grace_control.db import get_db as _gdb
    from grace_control.db.schema import PacketRun
    from pathlib import Path as _P

    with _gdb() as db:
        run = db.query(PacketRun).filter_by(id=f"{packet_id}-{run_id}").first()
        if not run or not run.evidence_path:
            return {"data": []}

        ep = _P(run.evidence_path)
        files = []
        if ep.exists():
            for f in sorted(ep.rglob("*")):
                if f.is_file():
                    rel = str(f.relative_to(ep))
                    ext = f.suffix.lower()
                    ftype = "image" if ext in (".png", ".jpg", ".gif", ".svg") else \
                            "log" if ext in (".log", ".txt") else \
                            "json" if ext == ".json" else "file"
                    files.append({"name": rel, "type": ftype, "size": f.stat().st_size})

        return {"data": files}


@app.get("/api/packets/{packet_id}/runs/{run_id}/artifacts/file")
async def get_artifact_file(packet_id: str, run_id: str, path: str = "", tail: int = 0):
    from grace_control.db import get_db as _gdb
    from grace_control.db.schema import PacketRun
    from pathlib import Path as _P
    from fastapi.responses import PlainTextResponse

    with _gdb() as db:
        run = db.query(PacketRun).filter_by(id=f"{packet_id}-{run_id}").first()
        if not run or not run.evidence_path:
            return JSONResponse({"error": "not found"}, status_code=404)

        fp = _P(run.evidence_path) / path
        if not fp.exists() or not fp.is_file():
            return JSONResponse({"error": "file not found"}, status_code=404)

        content = fp.read_text()
        if tail > 0:
            lines = content.splitlines()
            content = "\n".join(lines[-tail:])
        return PlainTextResponse(content)

#START_BLOCK_WS
from fastapi import WebSocket
from grace_control.api.ws_broadcast import handle_websocket

@app.websocket("/ws")
async def websocket_endpoint(ws: WebSocket):
    await handle_websocket(ws)

#END_BLOCK_WS


@app.get("/api/artifacts/{packet_id}/{run_id:path}")
async def get_artifact(packet_id: str, run_id: str):
    from grace_control.db import get_db as _get_db
    from grace_control.db.schema import PacketRun
    with _get_db() as db:
        run = db.query(PacketRun).filter_by(id=f"{packet_id}-{run_id}").first()
        if not run or not run.result_json:
            return JSONResponse({"error": "not found"}, status_code=404)
        return {"data": run.result_json, "evidence_path": run.evidence_path}


@app.get("/health", include_in_schema=False)
async def health():
    from grace_control.core.health import check_health
    return await check_health()

#END_BLOCK_UI

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
