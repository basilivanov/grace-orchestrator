"""Pipeline stage instrumentation decorator and helpers."""
from __future__ import annotations

import asyncio
import hashlib
import traceback
from datetime import datetime
from functools import wraps

from grace_control.db import get_db
from grace_control.db.schema import StageRun, Packet
from grace_control.core.uid import new_stage_run_uid
from grace_control.config.model_pricing import compute_cost
from grace_control.api.ws_broadcast import broadcast_event


def stage(stage_key: str, llm: bool = False):
    """Decorator to instrument a pipeline stage."""
    def decorator(fn):
        is_async = asyncio.iscoroutinefunction(fn)

        def get_args_dict(args, kwargs):
            import inspect
            sig = inspect.signature(fn)
            bound = sig.bind_partial(*args, **kwargs)
            bound.apply_defaults()
            return bound.arguments

        def _setup_stage_run(args, kwargs) -> StageRun:
            args_dict = get_args_dict(args, kwargs)
            packet_id = args_dict.get("packet_id")
            if not packet_id and isinstance(args_dict.get("packet_data"), dict):
                packet_id = args_dict.get("packet_data").get("id")
            if not packet_id and args_dict.get("packet"):
                packet_obj = args_dict.get("packet")
                packet_id = getattr(packet_obj, "packet_id", None) or getattr(packet_obj, "id", None)
            if not packet_id and args:
                self_obj = args[0]
                run_dir = getattr(self_obj, "_run_dir", None) or getattr(self_obj, "run_dir", None)
                if run_dir:
                    import re
                    match = re.search(r'(pkt_[A-Za-z0-9]+)', str(run_dir))
                    if match:
                        packet_id = match.group(1)
            feature_id = args_dict.get("feature_id")
            
            if not packet_id and feature_id:
                packet_id = f"plan_{feature_id}"
                wave_id = f"plan_{feature_id}"
                attempt_number = 1
            elif packet_id:
                with get_db() as db:
                    packet = db.query(Packet).filter_by(id=packet_id).first()
                    if packet:
                        feature_id = packet.feature_id
                        wave_id = packet.wave_id
                        attempt_number = packet.attempt_count
                    else:
                        feature_id = args_dict.get("feature_id") or "unknown"
                        wave_id = "unknown"
                        attempt_number = 1
            else:
                packet_id = "unknown"
                feature_id = "unknown"
                wave_id = "unknown"
                attempt_number = 1

            loop_round = 1
            with get_db() as db:
                prev_runs = db.query(StageRun).filter_by(
                    packet_id=packet_id, stage_key=stage_key
                ).all()
                if prev_runs:
                    loop_round = max(r.loop_round for r in prev_runs) + 1

            srun = StageRun(
                id=new_stage_run_uid(),
                packet_id=packet_id,
                feature_id=feature_id,
                wave_id=wave_id,
                stage_key=stage_key,
                attempt_number=attempt_number,
                loop_round=loop_round,
                started_at=datetime.utcnow(),
                status="running",
                executor_id=args_dict.get("executor_id") or kwargs.get("executor_id"),
                worker_id=args_dict.get("worker_id") or kwargs.get("worker_id"),
                model=args_dict.get("model") or kwargs.get("model"),
                trace_id=args_dict.get("trace_id") or kwargs.get("trace_id"),
            )
            
            prompt = args_dict.get("prompt") or kwargs.get("prompt")
            if prompt:
                srun.prompt_hash = hashlib.sha256(prompt.encode("utf-8")).hexdigest()

            with get_db() as db:
                db.add(srun)
                db.commit()
                db.refresh(srun)
                
            return srun

        def _update_stage_run_success(srun_id: str, result) -> None:
            finished = datetime.utcnow()
            with get_db() as db:
                srun = db.query(StageRun).filter_by(id=srun_id).first()
                if srun:
                    srun.status = "done"
                    srun.finished_at = finished
                    if srun.started_at:
                        srun.duration_ms = int((finished - srun.started_at).total_seconds() * 1000)
                    
                    def get_val(key):
                        if isinstance(result, dict):
                            return result.get(key)
                        return getattr(result, key, None)
                    
                    if get_val("executor_id"):
                        srun.executor_id = get_val("executor_id")
                    if get_val("worker_id"):
                        srun.worker_id = get_val("worker_id")
                    if get_val("model"):
                        srun.model = get_val("model")
                    if get_val("trace_id"):
                        srun.trace_id = get_val("trace_id")
                    if get_val("error"):
                        srun.error = get_val("error")
                    if get_val("stdout_path"):
                        srun.stdout_path = get_val("stdout_path")
                    if get_val("stderr_path"):
                        srun.stderr_path = get_val("stderr_path")
                    if get_val("result_path"):
                        srun.result_path = get_val("result_path")
                    if get_val("artifacts_dir"):
                        srun.artifacts_dir = get_val("artifacts_dir")
                    if get_val("recovery_reason"):
                        srun.recovery_reason = get_val("recovery_reason")
                    
                    t_in = get_val("tokens_in")
                    t_out = get_val("tokens_out")
                    if t_in is not None:
                        srun.tokens_in = t_in
                    if t_out is not None:
                        srun.tokens_out = t_out
                    
                    if llm:
                        model = srun.model or get_val("model")
                        srun.cost_usd = compute_cost(model, srun.tokens_in, srun.tokens_out)
                    elif get_val("cost_usd") is not None:
                        srun.cost_usd = get_val("cost_usd")

                    db.commit()

        def _update_stage_run_failure(srun_id: str, exc: Exception) -> None:
            finished = datetime.utcnow()
            with get_db() as db:
                srun = db.query(StageRun).filter_by(id=srun_id).first()
                if srun:
                    srun.status = "failed"
                    srun.finished_at = finished
                    if srun.started_at:
                        srun.duration_ms = int((finished - srun.started_at).total_seconds() * 1000)
                    srun.error = traceback.format_exc()
                    db.commit()

        if is_async:
            @wraps(fn)
            async def async_wrapper(*args, **kwargs):
                srun = _setup_stage_run(args, kwargs)
                
                await broadcast_event("stage_started", {
                    "packet_id": srun.packet_id,
                    "stage_key": stage_key,
                    "stage_run_id": srun.id,
                    "attempt": srun.attempt_number,
                    "loop_round": srun.loop_round,
                    "started_at": srun.started_at.isoformat() + "Z",
                    "executor_id": srun.executor_id,
                    "model": srun.model,
                })

                try:
                    result = await fn(*args, **kwargs)
                    _update_stage_run_success(srun.id, result)
                    
                    with get_db() as db:
                        updated_srun = db.query(StageRun).filter_by(id=srun.id).first()
                        duration_ms = updated_srun.duration_ms if updated_srun else None
                        tokens_in = updated_srun.tokens_in if updated_srun else None
                        tokens_out = updated_srun.tokens_out if updated_srun else None
                        cost_usd = updated_srun.cost_usd if updated_srun else None

                    await broadcast_event("stage_finished", {
                        "packet_id": srun.packet_id,
                        "stage_key": stage_key,
                        "stage_run_id": srun.id,
                        "status": "done",
                        "finished_at": datetime.utcnow().isoformat() + "Z",
                        "duration_ms": duration_ms,
                        "tokens_in": tokens_in,
                        "tokens_out": tokens_out,
                        "cost_usd": float(cost_usd) if cost_usd is not None else None,
                    })
                    return result
                except Exception as e:
                    _update_stage_run_failure(srun.id, e)
                    
                    with get_db() as db:
                        updated_srun = db.query(StageRun).filter_by(id=srun.id).first()
                        duration_ms = updated_srun.duration_ms if updated_srun else None
                        error_msg = updated_srun.error if updated_srun else str(e)

                    await broadcast_event("stage_finished", {
                        "packet_id": srun.packet_id,
                        "stage_key": stage_key,
                        "stage_run_id": srun.id,
                        "status": "failed",
                        "finished_at": datetime.utcnow().isoformat() + "Z",
                        "duration_ms": duration_ms,
                        "error": error_msg,
                    })
                    raise
            return async_wrapper
        else:
            @wraps(fn)
            def sync_wrapper(*args, **kwargs):
                srun = _setup_stage_run(args, kwargs)
                
                try:
                    loop = asyncio.get_event_loop()
                except RuntimeError:
                    loop = asyncio.new_event_loop()
                    asyncio.set_event_loop(loop)
                
                if loop.is_running():
                    asyncio.ensure_future(broadcast_event("stage_started", {
                        "packet_id": srun.packet_id,
                        "stage_key": stage_key,
                        "stage_run_id": srun.id,
                        "attempt": srun.attempt_number,
                        "loop_round": srun.loop_round,
                        "started_at": srun.started_at.isoformat() + "Z",
                        "executor_id": srun.executor_id,
                        "model": srun.model,
                    }))
                else:
                    loop.run_until_complete(broadcast_event("stage_started", {
                        "packet_id": srun.packet_id,
                        "stage_key": stage_key,
                        "stage_run_id": srun.id,
                        "attempt": srun.attempt_number,
                        "loop_round": srun.loop_round,
                        "started_at": srun.started_at.isoformat() + "Z",
                        "executor_id": srun.executor_id,
                        "model": srun.model,
                    }))

                try:
                    result = fn(*args, **kwargs)
                    _update_stage_run_success(srun.id, result)
                    
                    with get_db() as db:
                        updated_srun = db.query(StageRun).filter_by(id=srun.id).first()
                        duration_ms = updated_srun.duration_ms if updated_srun else None
                        tokens_in = updated_srun.tokens_in if updated_srun else None
                        tokens_out = updated_srun.tokens_out if updated_srun else None
                        cost_usd = updated_srun.cost_usd if updated_srun else None

                    finished_payload = {
                        "packet_id": srun.packet_id,
                        "stage_key": stage_key,
                        "stage_run_id": srun.id,
                        "status": "done",
                        "finished_at": datetime.utcnow().isoformat() + "Z",
                        "duration_ms": duration_ms,
                        "tokens_in": tokens_in,
                        "tokens_out": tokens_out,
                        "cost_usd": float(cost_usd) if cost_usd is not None else None,
                    }
                    if loop.is_running():
                        asyncio.ensure_future(broadcast_event("stage_finished", finished_payload))
                    else:
                        loop.run_until_complete(broadcast_event("stage_finished", finished_payload))
                    return result
                except Exception as e:
                    _update_stage_run_failure(srun.id, e)
                    
                    with get_db() as db:
                        updated_srun = db.query(StageRun).filter_by(id=srun.id).first()
                        duration_ms = updated_srun.duration_ms if updated_srun else None
                        error_msg = updated_srun.error if updated_srun else str(e)

                    failed_payload = {
                        "packet_id": srun.packet_id,
                        "stage_key": stage_key,
                        "stage_run_id": srun.id,
                        "status": "failed",
                        "finished_at": datetime.utcnow().isoformat() + "Z",
                        "duration_ms": duration_ms,
                        "error": error_msg,
                    }
                    if loop.is_running():
                        asyncio.ensure_future(broadcast_event("stage_finished", failed_payload))
                    else:
                        loop.run_until_complete(broadcast_event("stage_finished", failed_payload))
                    raise
            return sync_wrapper
    return decorator


def create_for_return(packet_id: str, from_stage: str, to_stage: str, reason: str, trace_id: str | None = None) -> StageRun | None:
    with get_db() as db:
        packet = db.query(Packet).filter_by(id=packet_id).first()
        if not packet:
            return None

        # Find parent stage run
        parent_srun = db.query(StageRun).filter_by(
            packet_id=packet_id, stage_key=from_stage
        ).order_by(StageRun.created_at.desc()).first()
        
        parent_id = parent_srun.id if parent_srun else None
        eff_trace_id = trace_id or (parent_srun.trace_id if parent_srun else None)

        # Determine loop_round
        loop_round = 1
        prev_runs = db.query(StageRun).filter_by(
            packet_id=packet_id, stage_key=to_stage
        ).all()
        if prev_runs:
            loop_round = max(r.loop_round for r in prev_runs) + 1

        srun = StageRun(
            id=new_stage_run_uid(),
            packet_id=packet_id,
            feature_id=packet.feature_id,
            wave_id=packet.wave_id,
            stage_key=to_stage,
            attempt_number=packet.attempt_count,
            loop_round=loop_round,
            parent_stage_run_id=parent_id,
            recovery_reason=reason,
            trace_id=eff_trace_id,
            status="pending",
        )
        db.add(srun)
        db.commit()
        db.refresh(srun)
        
        try:
            loop = asyncio.get_event_loop()
        except RuntimeError:
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            
        payload = {
            "packet_id": packet_id,
            "from_stage": from_stage,
            "to_stage": to_stage,
            "reason": reason,
            "decision": f"recovery_return_to_{to_stage}",
            "loop_round": loop_round,
            "parent_stage_run_id": parent_id,
            "at": datetime.utcnow().isoformat() + "Z"
        }
        
        if loop.is_running():
            asyncio.ensure_future(broadcast_event("stage_returned", payload))
        else:
            loop.run_until_complete(broadcast_event("stage_returned", payload))
            
        return srun
