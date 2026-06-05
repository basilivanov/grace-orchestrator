# ############################################################################
# AI_HEADER: api_routers_artifacts
# ROLE: Artifacts router — evidence directory access. Extracted from
#       api/main.py in W5. All artifact file reading is path-safe.
# ############################################################################

# START_MODULE_CONTRACT
# purpose: Serve per-run PacketRun / evidence files. The /file route enforces
#          path-traversal safety (target must be inside the evidence dir).
# inputs: HTTP requests with packet_id / run_id / path params.
# returns: JSON or PlainText.
# side_effects: None (reads evidence files only).
# emitted_logs: None.
# error_behavior: 404 when run/evidence is missing; 403 on path traversal.
# END_MODULE_CONTRACT

# START_MODULE_MAP
# mapping:
#   - router: APIRouter
#     routes:
#       - GET /api/packets/{packet_id}/runs/{run_id}
#       - GET /api/packets/{packet_id}/runs/{run_id}/artifacts
#       - GET /api/packets/{packet_id}/runs/{run_id}/artifacts/file
#       - GET /api/artifacts/{packet_id}/{run_id:path}
# END_MODULE_MAP

from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter, HTTPException
from fastapi.responses import JSONResponse, PlainTextResponse

from grace_control.db import get_db
from grace_control.db.schema import PacketRun

router = APIRouter(tags=["artifacts"])


# START_BLOCK_DTO_HELPERS
def _resolve_run(db, packet_id: str, run_id: str) -> PacketRun | None:
    return db.query(PacketRun).filter_by(id=f"{packet_id}-{run_id}").first()
# END_BLOCK_DTO_HELPERS


# START_FUNCTION_CONTRACT
# name: get_packet_run
# purpose: Return one PacketRun with the full result_json.
# inputs: packet_id, run_id (path params).
# returns: dict {"data": <run>}.
# side_effects: None.
# emitted_logs: None.
# error_behavior: 404 when the run is not found.
# END_FUNCTION_CONTRACT
@router.get("/api/packets/{packet_id}/runs/{run_id}")
def get_packet_run(packet_id: str, run_id: str) -> dict:
    with get_db() as db:
        run = _resolve_run(db, packet_id, run_id)
        if not run:
            raise HTTPException(status_code=404, detail="run not found")
        return {
            "data": {
                "id": run.id,
                "packet_id": run.packet_id,
                "run_number": run.run_number,
                "status": run.status,
                "result_json": run.result_json,
                "evidence_path": run.evidence_path,
                "executor_id": run.executor_id,
                "started_at": run.started_at.isoformat() + "Z" if run.started_at else None,
                "finished_at": run.finished_at.isoformat() + "Z" if run.finished_at else None,
                "duration_ms": run.duration_ms,
            }
        }


# START_FUNCTION_CONTRACT
# name: list_artifacts
# purpose: List files under the run's evidence directory.
# inputs: packet_id, run_id (path params).
# returns: dict {"data": [{"name", "type", "size"}, ...]}.
# side_effects: Reads filesystem.
# emitted_logs: None.
# error_behavior: Empty data on missing evidence dir.
# END_FUNCTION_CONTRACT
@router.get("/api/packets/{packet_id}/runs/{run_id}/artifacts")
def list_artifacts(packet_id: str, run_id: str) -> dict:
    with get_db() as db:
        run = _resolve_run(db, packet_id, run_id)
        if not run or not run.evidence_path:
            return {"data": []}
        ep = Path(run.evidence_path)
        files = []
        if ep.exists():
            for f in sorted(ep.rglob("*")):
                if f.is_file():
                    rel = str(f.relative_to(ep))
                    ext = f.suffix.lower()
                    ftype = (
                        "image" if ext in (".png", ".jpg", ".gif", ".svg")
                        else "log" if ext in (".log", ".txt")
                        else "json" if ext == ".json"
                        else "file"
                    )
                    files.append({"name": rel, "type": ftype, "size": f.stat().st_size})
        return {"data": files}


# START_FUNCTION_CONTRACT
# name: get_artifact_file
# purpose: Stream a file under the run's evidence directory. Path-traversal
#          safe: target must be inside evidence_dir.
# inputs: packet_id, run_id, path (relative), tail (optional int, last N lines).
# returns: PlainTextResponse or JSONResponse.
# side_effects: Reads evidence files.
# emitted_logs: None.
# error_behavior: 404 on missing run/evidence; 403 on path traversal.
# END_FUNCTION_CONTRACT
@router.get("/api/packets/{packet_id}/runs/{run_id}/artifacts/file")
def get_artifact_file(packet_id: str, run_id: str, path: str = "", tail: int = 0):
    with get_db() as db:
        run = _resolve_run(db, packet_id, run_id)
        if not run or not run.evidence_path:
            return JSONResponse({"error": "not found"}, status_code=404)
        evidence_dir = Path(run.evidence_path).resolve()
        fp = (evidence_dir / path).resolve()
        # Path-traversal guard: target must be inside evidence_dir.
        if not fp.is_file() or evidence_dir not in fp.parents:
            return JSONResponse({"error": "forbidden"}, status_code=403)
        content = fp.read_text()
        if tail > 0:
            content = "\n".join(content.splitlines()[-tail:])
        return PlainTextResponse(content)


# START_FUNCTION_CONTRACT
# name: get_artifact
# purpose: Return the run's full result_json + evidence path.
# inputs: packet_id, run_id (path params; run_id may contain slashes).
# returns: dict {"data": <result_json>, "evidence_path": str}.
# side_effects: None.
# emitted_logs: None.
# error_behavior: 404 on missing run/result.
# END_FUNCTION_CONTRACT
@router.get("/api/artifacts/{packet_id}/{run_id:path}")
def get_artifact(packet_id: str, run_id: str):
    with get_db() as db:
        run = _resolve_run(db, packet_id, run_id)
        if not run or not run.result_json:
            return JSONResponse({"error": "not found"}, status_code=404)
        return {"data": run.result_json, "evidence_path": run.evidence_path}
