# ############################################################################
# AI_HEADER: api_lifespan
# ROLE: Startup/shutdown for the FastAPI app. Extracted from api/main.py in
#       W5 of source/codex/tz-api-first-cleanup-waves-w0-w11.md. Owns the
#       three background loops (lease, wave_gate, feature_gate).
# ############################################################################

# START_MODULE_CONTRACT
# purpose: Run init_db on startup; spawn the lease / wave_gate / feature_gate
#          background tasks; cancel them on shutdown. Loops are best-effort
#          and never raise out of lifespan.
# inputs: FastAPI app (lifespan context).
# returns: None.
# side_effects: DB init, three asyncio.create_task calls, one cancel.
# emitted_logs: wave_gate_loop_error, feature_gate_loop_error.
# error_behavior: Init errors propagate; per-loop errors are logged + swallowed.
# END_MODULE_CONTRACT

# START_MODULE_MAP
# mapping:
#   - function: lifespan
#   - function: _safe_loop
# END_MODULE_MAP

from __future__ import annotations

import asyncio
import os
from contextlib import asynccontextmanager

from fastapi import FastAPI

from grace_control.config.settings import settings
from grace_control.core.feature_gate import check_feature_completion
from grace_control.core.lease_manager import lease_expiration_loop
from grace_control.core.stuck_scanner import stuck_scan_loop
from grace_control.core.structured_logger import GraceLogger
from grace_control.core.wave_gate import check_wave_gates
from grace_control.db import init_db
from grace_control.services.stage_metrics_service import recompute_metrics as _recompute_metrics

_log = GraceLogger("lifespan")
_lease_task: asyncio.Task | None = None


async def _metrics_recalc_loop():
    """Пересчёт метрик: 24h раз в 60с, 7d раз в 10 минут, 30d раз в час."""
    import time
    while True:
        try:
            await _recompute_metrics("24h")
        except Exception as e:
            _log.error("metrics_24h_recalc_error", error=str(e)[:200])
        await asyncio.sleep(60)
        # 7d каждые 10 минут
        if int(time.time()) % 600 < 60:
            try:
                await _recompute_metrics("7d")
            except Exception as e:
                _log.error("metrics_7d_recalc_error", error=str(e)[:200])
        # 30d каждый час
        if int(time.time()) % 3600 < 60:
            try:
                await _recompute_metrics("30d")
            except Exception as e:
                _log.error("metrics_30d_recalc_error", error=str(e)[:200])


# START_FUNCTION_CONTRACT
# name: _safe_loop
# purpose: Run `fn()` every `interval` seconds, log + swallow exceptions.
# inputs: name (str, used in error log key), fn (callable, no args), interval (int, seconds).
# returns: None (runs forever until cancelled).
# side_effects: None.
# emitted_logs: {name}_loop_error.
# error_behavior: Catches and logs every exception; never raises.
# END_FUNCTION_CONTRACT
async def _safe_loop(name: str, fn, interval: int) -> None:
    while True:
        try:
            fn()
        except Exception as e:
            _log.error(f"{name}_loop_error", error=str(e)[:500])
        await asyncio.sleep(interval)


# START_FUNCTION_CONTRACT
# name: lifespan
# purpose: FastAPI lifespan context manager — init DB, spawn loops, cancel on shutdown.
# inputs: app (FastAPI) — required by the @asynccontextmanager protocol.
# returns: AsyncIterator[None].
# side_effects: init_db(), three asyncio.create_task(), one task.cancel().
# emitted_logs: wave_gate_loop_error, feature_gate_loop_error (via _safe_loop).
# error_behavior: init_db errors propagate; per-loop errors are swallowed.
# END_FUNCTION_CONTRACT
@asynccontextmanager
async def lifespan(app: FastAPI):
    global _lease_task
    db_url = os.environ.get("GRACE_DB_URL") or settings.database_url
    init_db(db_url)
    _lease_task = asyncio.create_task(lease_expiration_loop())
    # W08: Stuck scanner background loop
    asyncio.create_task(stuck_scan_loop())
    asyncio.create_task(_safe_loop(
        "wave_gate", check_wave_gates, settings.wave_gate_interval_seconds))
    asyncio.create_task(_safe_loop(
        "feature_gate", check_feature_completion, settings.feature_gate_interval_seconds))
    asyncio.create_task(_metrics_recalc_loop())
    yield
    if _lease_task:
        _lease_task.cancel()
