"""Admin pipeline router — new read endpoints for pipeline observability v2."""
from __future__ import annotations

from datetime import datetime, timezone
from fastapi import APIRouter, HTTPException, Query

from grace_control.core.structured_logger import GraceLogger
from grace_control.db import get_db
from grace_control.db.schema import StageRun, Packet, Feature, Wave
from grace_control.services.admin_aggregation_service import AdminAggregationService
from grace_control.services.aggregated_logs_service import get_aggregated_logs
from grace_control.services.stage_metrics_service import (
    get_stage_metrics,
    get_all_stages_reference,
    recompute_metrics,
)
from grace_control.services.packet_control_service import (
    retry_packet,
    cancel_packet,
    delete_packet,
    rerun_stage,
    stop_worker,
    dev_replay,
)

router = APIRouter()
_log = GraceLogger("admin_pipeline")
_svc = AdminAggregationService()


def _add_bar_geometry(bars: list[dict], time_min: datetime | None, time_max: datetime | None) -> list[dict]:
    """Добавляет left_pct/width_pct каждому bar относительно временной оси."""
    if not bars or not time_min or not time_max:
        return bars
    total_ms = (time_max - time_min).total_seconds() * 1000
    if total_ms <= 0:
        total_ms = 3600000  # 1h fallback

    for b in bars:
        s = _parse_dt(b.get("started_at"))
        e = _parse_dt(b.get("finished_at")) or s or time_max
        if not s:
            b["left_pct"] = 0
            b["width_pct"] = 0
            continue
        left_ms = (s - time_min).total_seconds() * 1000
        dur_ms = (e - s).total_seconds() * 1000 if e else total_ms - left_ms
        b["left_pct"] = round(left_ms / total_ms * 100, 2)
        b["width_pct"] = max(round(dur_ms / total_ms * 100, 2), 0.5)
    return bars


def _parse_dt(iso: str | None) -> datetime | None:
    if not iso:
        return None
    try:
        return datetime.fromisoformat(iso.replace("Z", "+00:00"))
    except (ValueError, TypeError):
        return None


@router.get("/api/admin/packet/{packet_id}/pipeline")
def packet_pipeline(packet_id: str, include_skipped: bool = Query(False)):
    with get_db() as db:
        stages = db.query(StageRun).filter_by(packet_id=packet_id).order_by(StageRun.started_at).all()
        pkt = db.query(Packet).filter_by(id=packet_id).first()
        if not pkt:
            raise HTTPException(status_code=404, detail="Packet not found")
        recovery_chain: list[dict] = []
        totals = {"duration_ms": 0, "tokens_in": 0, "tokens_out": 0, "cost_usd": 0.0, "loop_count": 0}
        result_stages = []
        seen_loops: set[str] = set()
        for s in stages:
            if s.status == "skipped" and not include_skipped:
                continue
            result_stages.append({
                "id": s.id,
                "stage_key": s.stage_key,
                "status": s.status,
                "started_at": s.started_at.isoformat() + "Z" if s.started_at else None,
                "finished_at": s.finished_at.isoformat() + "Z" if s.finished_at else None,
                "duration_ms": s.duration_ms,
                "loop_round": s.loop_round,
                "attempt_number": s.attempt_number,
                "parent_stage_run_id": s.parent_stage_run_id,
                "error": s.error,
                "executor_id": s.executor_id,
                "worker_id": s.worker_id,
                "model": s.model,
                "tokens_in": s.tokens_in,
                "tokens_out": s.tokens_out,
                "cost_usd": float(s.cost_usd) if s.cost_usd else None,
                "stdout_path": s.stdout_path,
                "stderr_path": s.stderr_path,
                "artifacts_dir": s.artifacts_dir,
                "result_path": s.result_path,
                "trace_id": s.trace_id,
                "recovery_reason": s.recovery_reason,
            })
            if s.duration_ms:
                totals["duration_ms"] += s.duration_ms
            if s.tokens_in:
                totals["tokens_in"] += s.tokens_in
            if s.tokens_out:
                totals["tokens_out"] += s.tokens_out
            if s.cost_usd:
                totals["cost_usd"] += float(s.cost_usd)
            if s.parent_stage_run_id and s.parent_stage_run_id not in seen_loops:
                seen_loops.add(s.parent_stage_run_id)
                parent = db.query(StageRun).filter_by(id=s.parent_stage_run_id).first()
                if parent:
                    recovery_chain.append({
                        "from": parent.stage_key,
                        "to": s.stage_key,
                        "reason": s.recovery_reason or "",
                        "decision": f"recovery_return_to_{s.stage_key}",
                        "at": s.created_at.isoformat() + "Z" if s.created_at else None,
                        "loop_round": s.loop_round,
                    })

        totals["loop_count"] = len(recovery_chain)

        return {
            "packet_id": packet_id,
            "totals": totals,
            "stages": result_stages,
            "recovery_chain": recovery_chain,
        }


@router.get("/api/admin/packet/{packet_id}/pipeline/gantt")
def packet_pipeline_gantt(packet_id: str, zoom: str = Query("24h")):
    with get_db() as db:
        stages = db.query(StageRun).filter_by(packet_id=packet_id).order_by(StageRun.started_at).all()
        if not stages:
            return {"zoom": zoom, "time_min": None, "time_max": None, "lanes": []}

        times = [s.started_at for s in stages if s.started_at] + [s.finished_at for s in stages if s.finished_at]
        time_min = min(times) if times else None
        time_max = max(times) if times else None

        color_map = {
            "pending": "#CCC", "running": "#0B5E87", "done": "#1E7E34",
            "failed": "#B02A2A", "skipped": "#B8860B", "cancelled": "#6C3483",
        }
        bars = []
        for s in stages:
            if not s.started_at:
                continue
            bars.append({
                "stage_key": s.stage_key,
                "started_at": s.started_at.isoformat() + "Z",
                "finished_at": s.finished_at.isoformat() + "Z" if s.finished_at else None,
                "status": s.status,
                "duration_ms": s.duration_ms,
                "loop_round": s.loop_round,
                "color": color_map.get(s.status, "#CCC"),
            })

        bars = _add_bar_geometry(bars, time_min, time_max)

        return {
            "zoom": zoom,
            "time_min": time_min.isoformat() + "Z" if time_min else None,
            "time_max": time_max.isoformat() + "Z" if time_max else None,
            "lanes": [{"packet_id": packet_id, "label": packet_id, "bars": bars}],
        }


@router.get("/api/admin/feature/{feature_id}/gantt")
def feature_gantt(feature_id: str, zoom: str = Query("24h"), wave_id: str = Query("all")):
    with get_db() as db:
        feature = db.query(Feature).filter_by(id=feature_id).first()
        if not feature:
            raise HTTPException(status_code=404, detail="Feature not found")
        waves = db.query(Wave).filter_by(feature_id=feature_id).order_by(Wave.order).all()
        if wave_id != "all":
            waves = [w for w in waves if w.id == wave_id]

        lanes = []
        all_times: list[datetime] = []
        color_map = {
            "pending": "#CCC", "running": "#0B5E87", "done": "#1E7E34",
            "failed": "#B02A2A", "skipped": "#B8860B", "cancelled": "#6C3483",
        }
        for wave in waves:
            packets = db.query(Packet).filter_by(feature_id=feature_id, wave_id=wave.id).all()
            for pkt in packets:
                stages = db.query(StageRun).filter_by(packet_id=pkt.id).order_by(StageRun.started_at).all()
                bars = []
                for s in stages:
                    if not s.started_at:
                        continue
                    all_times.append(s.started_at)
                    if s.finished_at:
                        all_times.append(s.finished_at)
                    bars.append({
                        "stage_key": s.stage_key,
                        "started_at": s.started_at.isoformat() + "Z",
                        "finished_at": s.finished_at.isoformat() + "Z" if s.finished_at else None,
                        "status": s.status,
                        "duration_ms": s.duration_ms,
                        "loop_round": s.loop_round,
                        "color": color_map.get(s.status, "#CCC"),
                    })
                lanes.append({
                    "packet_id": pkt.id,
                    "wave": wave.slug,
                    "label": pkt.slug or pkt.id,
                    "bars": bars,
                })

        time_min = min(all_times) if all_times else None
        time_max = max(all_times) if all_times else None

        for lane in lanes:
            lane["bars"] = _add_bar_geometry(lane["bars"], time_min, time_max)

        return {
            "zoom": zoom,
            "time_min": time_min.isoformat() + "Z" if time_min else None,
            "time_max": time_max.isoformat() + "Z" if time_max else None,
            "lanes": lanes,
        }


@router.get("/api/admin/packet/{packet_id}/logs/aggregated")
def aggregated_logs(
    packet_id: str,
    sources: str = Query("all"),
    tail: int = Query(500, ge=1, le=5000),
    level: str = Query("all"),
    trace_id: str = Query(None),
    regex: str = Query(None),
    since: str = Query(None),
    until: str = Query(None),
):
    return get_aggregated_logs(
        packet_id=packet_id,
        sources=sources.split(",") if sources != "all" else None,
        tail=tail,
        level=level,
        trace_id=trace_id,
        regex=regex,
        since=since,
        until=until,
    )


@router.get("/api/admin/packet/{packet_id}/stages/{stage_key}/artifacts")
def stage_artifacts(packet_id: str, stage_key: str, loop_round: int = Query(1)):
    with get_db() as db:
        srun = db.query(StageRun).filter_by(
            packet_id=packet_id, stage_key=stage_key, loop_round=loop_round
        ).order_by(StageRun.created_at.desc()).first()
        if not srun:
            raise HTTPException(status_code=404, detail="Stage run not found")

        artifacts = []
        total_size = 0
        if srun.artifacts_dir:
            from pathlib import Path
            base = Path(srun.artifacts_dir)
            if base.exists():
                for f in base.rglob("*"):
                    if f.is_file():
                        ext = f.suffix.lower()
                        if ext in (".png", ".jpg", ".jpeg", ".gif", ".svg", ".webp"):
                            ftype = "image"
                        elif ext in (".log", ".txt", ".md"):
                            ftype = "log"
                        elif ext in (".json", ".jsonl", ".har"):
                            ftype = "json"
                        elif ext in (".patch", ".diff"):
                            ftype = "patch"
                        else:
                            ftype = "file"
                        rel = str(f.relative_to(base))
                        size = f.stat().st_size
                        artifacts.append({
                            "name": f.name,
                            "path": f"{stage_key}/{rel}",
                            "size": size,
                            "type": ftype,
                        })
                        total_size += size

        return {
            "stage_key": stage_key,
            "stage_run_id": srun.id,
            "loop_round": srun.loop_round,
            "artifacts": artifacts,
            "total_size": total_size,
        }


@router.get("/api/admin/packet/{packet_id}/stages/{stage_key}/logs")
def stage_logs(packet_id: str, stage_key: str, stream: str = Query("all"), tail: int = Query(200)):
    with get_db() as db:
        srun = db.query(StageRun).filter_by(
            packet_id=packet_id, stage_key=stage_key
        ).order_by(StageRun.created_at.desc()).first()
        if not srun:
            raise HTTPException(status_code=404, detail="Stage run not found")

        from pathlib import Path
        lines = []
        source_file = None

        if srun.stdout_path and stream in ("all", "stdout"):
            try:
                stdout_lines = Path(srun.stdout_path).read_text(errors="replace").split("\n")[-tail:]
                for line in stdout_lines:
                    if line.strip():
                        lines.append({"ts": "", "source": "stdout", "level": "info", "msg": line.strip()})
                source_file = srun.stdout_path
            except (OSError, IOError):
                pass

        if srun.stderr_path and stream in ("all", "stderr"):
            try:
                stderr_lines = Path(srun.stderr_path).read_text(errors="replace").split("\n")[-tail:]
                for line in stderr_lines:
                    if line.strip():
                        lines.append({"ts": "", "source": "stderr", "level": "error" if "error" in line.lower() else "warn", "msg": line.strip()})
                source_file = source_file or srun.stderr_path
            except (OSError, IOError):
                pass

        return {"lines": lines, "source_file": source_file, "truncated": len(lines) > tail}


@router.get("/api/admin/stages/{stage_key}/metrics")
def stage_metrics_endpoint(stage_key: str, period: str = Query("24h")):
    return get_stage_metrics(stage_key=stage_key, period=period)


@router.get("/api/admin/stages/metrics/heatmap")
def stage_metrics_heatmap(period: str = Query("7d")):
    from collections import defaultdict
    from datetime import timedelta

    now = datetime.utcnow()
    if period == "24h":
        period_start = now - timedelta(hours=24)
    elif period == "30d":
        period_start = now - timedelta(days=30)
    else:
        period_start = now - timedelta(days=7)
    period_end = now

    with get_db() as db:
        runs = db.query(StageRun).filter(
            StageRun.finished_at.isnot(None),
            StageRun.finished_at >= period_start,
            StageRun.finished_at < period_end,
        ).all()

    matrix: dict[str, dict[int, list[int]]] = defaultdict(lambda: defaultdict(list))
    all_stages: set[str] = set()
    for r in runs:
        if not r.finished_at:
            continue
        hour = r.finished_at.hour
        matrix[r.stage_key][hour].append(r.duration_ms or 0)
        all_stages.add(r.stage_key)

    rows = []
    for stage_key in sorted(all_stages):
        hour_data: list[dict] = []
        for h in range(24):
            vals = matrix[stage_key].get(h, [])
            if vals:
                avg_ms = round(sum(vals) / len(vals))
                count = len(vals)
            else:
                avg_ms = 0
                count = 0
            hour_data.append({"hour": h, "count": count, "avg_ms": avg_ms})
        rows.append({"stage_key": stage_key, "hours": hour_data})

    return {"matrix": rows, "stages": sorted(all_stages), "hours": list(range(24))}


@router.get("/api/admin/stages")
def stages_reference():
    return get_all_stages_reference()


@router.post("/api/admin/packet/{packet_id}/retry")
def retry_packet_endpoint(packet_id: str, body: dict):
    actor = body.get("actor")
    reason = body.get("reason", "manual_retry")
    try:
        return retry_packet(packet_id, actor=actor, reason=reason)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.post("/api/admin/packet/{packet_id}/cancel")
def cancel_packet_endpoint(packet_id: str, body: dict):
    actor = body.get("actor")
    reason = body.get("reason", "manual_cancel")
    try:
        return cancel_packet(packet_id, actor=actor, reason=reason)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.post("/api/admin/packet/{packet_id}/delete")
def delete_packet_endpoint(packet_id: str, body: dict):
    confirm = body.get("confirm", "")
    actor = body.get("actor")
    try:
        return delete_packet(packet_id, confirm=confirm, actor=actor)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.post("/api/admin/packet/{packet_id}/stages/{stage_key}/rerun")
def rerun_stage_endpoint(packet_id: str, stage_key: str, body: dict):
    if stage_key not in ("verifier", "reviewer"):
        raise HTTPException(status_code=400, detail="Rerun only allowed for verifier/reviewer")
    actor = body.get("actor")
    try:
        return rerun_stage(packet_id, stage_key, actor=actor)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.post("/api/admin/workers/{worker_id}/stop")
def stop_worker_endpoint(worker_id: str, body: dict):
    actor = body.get("actor")
    try:
        return stop_worker(worker_id, actor=actor)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.post("/api/admin/packet/{packet_id}/dev-replay")
async def dev_replay_endpoint(packet_id: str, body: dict):
    stage_key = body.get("stage_key")
    actor = body.get("actor")
    try:
        return await dev_replay(packet_id, stage_key=stage_key, actor=actor)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.post("/api/admin/stages/metrics/recompute")
def recompute_metrics_endpoint(body: dict):
    period = body.get("period", "24h")
    import asyncio as _asyncio
    _asyncio.ensure_future(recompute_metrics(period_kind=period))
    return {"ok": True, "message": f"Metrics recompute for {period} started"}
