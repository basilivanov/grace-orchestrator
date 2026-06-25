"""Service for computing and reading stage metrics (P50/P95/avg/max/count)."""
from __future__ import annotations

import asyncio
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from statistics import median_low

from grace_control.core.structured_logger import GraceLogger
from grace_control.db import get_db
from grace_control.db.schema import StageRun, StageMetric
from grace_control.config.model_pricing import compute_cost, MODEL_PRICING

_log = GraceLogger("stage_metrics")

PERIOD_KINDS = ("24h", "7d", "30d")


def _period_range(period_kind: str) -> tuple[datetime, datetime]:
    """Возвращает фиксированный период: начало часа для 24h, начало дня для 7d/30d."""
    now = datetime.now(timezone.utc)
    if period_kind == "24h":
        start = now.replace(minute=0, second=0, microsecond=0) - timedelta(hours=24)
        return start, start + timedelta(hours=24)
    elif period_kind == "7d":
        start = now.replace(hour=0, minute=0, second=0, microsecond=0) - timedelta(days=7)
        return start, start + timedelta(days=7)
    elif period_kind == "30d":
        start = now.replace(hour=0, minute=0, second=0, microsecond=0) - timedelta(days=30)
        return start, start + timedelta(days=30)
    return now - timedelta(hours=24), now


def _percentile(sorted_values: list[int], pct: float) -> int | None:
    if not sorted_values:
        return None
    k = (len(sorted_values) - 1) * pct / 100.0
    f = int(k)
    c = f + 1 if f < len(sorted_values) - 1 else f
    return sorted_values[c]


def get_stage_metrics(stage_key: str, period: str = "24h") -> dict:
    with get_db() as db:
        row = db.query(StageMetric).filter_by(
            stage_key=stage_key, period_kind=period
        ).order_by(StageMetric.computed_at.desc()).first()
        if row:
            return {
                "stage_key": row.stage_key,
                "period": row.period_kind,
                "count": row.count,
                "p50_ms": row.p50_ms,
                "p95_ms": row.p95_ms,
                "avg_ms": row.avg_ms,
                "max_ms": row.max_ms,
                "min_ms": row.min_ms,
                "success_count": row.success_count,
                "failure_count": row.failure_count,
                "success_rate": float(row.success_rate) if row.success_rate else None,
                "avg_tokens_in": row.avg_tokens_in,
                "avg_tokens_out": row.avg_tokens_out,
                "avg_cost_usd": float(row.avg_cost_usd) if row.avg_cost_usd else None,
                "total_cost_usd": float(row.total_cost_usd) if row.total_cost_usd else None,
                "avg_idle_seconds": row.avg_idle_seconds,
            }

        period_start, period_end = _period_range(period)
        runs = db.query(StageRun).filter(
            StageRun.stage_key == stage_key,
            StageRun.finished_at.isnot(None),
            StageRun.finished_at >= period_start,
            StageRun.finished_at < period_end,
        ).all()

        if not runs:
            return {"stage_key": stage_key, "period": period, "count": 0}

        durs = sorted(r.duration_ms for r in runs if r.duration_ms is not None)
        count = len(runs)
        success_count = sum(1 for r in runs if r.status == "done")
        failure_count = count - success_count

        return {
            "stage_key": stage_key,
            "period": period,
            "count": count,
            "p50_ms": _percentile(durs, 50),
            "p95_ms": _percentile(durs, 95),
            "avg_ms": round(sum(durs) / len(durs)) if durs else None,
            "max_ms": max(durs) if durs else None,
            "min_ms": min(durs) if durs else None,
            "success_count": success_count,
            "failure_count": failure_count,
            "success_rate": round(success_count / count, 4) if count else None,
        }


def get_all_stages_reference() -> dict:
    stages = [
        {"key": "context_builder", "label": "Context Builder", "description": "Собирает контекст для архитектора", "is_llm": False, "is_acceptance": False, "profile_required": "NORMAL"},
        {"key": "architect", "label": "Architect", "description": "Генерирует план и декомпозицию", "is_llm": True, "is_acceptance": False, "profile_required": "NORMAL"},
        {"key": "materialize", "label": "Materialize", "description": "Материализует планы в БД", "is_llm": False, "is_acceptance": False, "profile_required": "NORMAL"},
        {"key": "executor", "label": "Executor (claim)", "description": "Забирает пакет из очереди", "is_llm": False, "is_acceptance": False, "profile_required": "NORMAL"},
        {"key": "coder", "label": "Coder", "description": "Основная стадия исполнения", "is_llm": True, "is_acceptance": False, "profile_required": "NORMAL"},
        {"key": "t0_scope_lint", "label": "T0 Scope & Lint", "description": "Проверка scope и линтер", "is_llm": False, "is_acceptance": True, "profile_required": "NORMAL"},
        {"key": "t1_unit_tests", "label": "T1 Unit Tests", "description": "Unit-тесты изменённых файлов", "is_llm": False, "is_acceptance": True, "profile_required": "NORMAL"},
        {"key": "t2_e2e_smoke", "label": "T2 E2E / Smoke", "description": "Smoke или E2E тесты", "is_llm": False, "is_acceptance": True, "profile_required": "STRICT"},
        {"key": "t3_visual", "label": "T3 Visual Regression", "description": "Визуальная регрессия", "is_llm": False, "is_acceptance": True, "profile_required": "STRICT"},
        {"key": "verifier", "label": "Evidence Verifier", "description": "LLM-агент проверяет evidence", "is_llm": True, "is_acceptance": False, "profile_required": "STRICT"},
        {"key": "reviewer", "label": "Reviewer Gate", "description": "LLM-агент проверяет безопасность", "is_llm": True, "is_acceptance": False, "profile_required": "STRICT"},
        {"key": "merge", "label": "Merge", "description": "Финальная стадия слияния", "is_llm": False, "is_acceptance": False, "profile_required": "NORMAL"},
    ]
    return {"stages": stages}


async def recompute_metrics(period_kind: str = "24h") -> dict:
    period_start, period_end = _period_range(period_kind)
    stage_keys = [
        "context_builder", "architect", "materialize", "executor", "coder",
        "t0_scope_lint", "t1_unit_tests", "t2_e2e_smoke", "t3_visual",
        "verifier", "reviewer", "merge",
    ]

    results = []
    with get_db() as db:
        for stage_key in stage_keys:
            runs = db.query(StageRun).filter(
                StageRun.stage_key == stage_key,
                StageRun.finished_at.isnot(None),
                StageRun.finished_at >= period_start,
                StageRun.finished_at < period_end,
            ).all()

            count = len(runs)
            success_count = sum(1 for r in runs if r.status == "done")
            failure_count = count - success_count
            durs = sorted(r.duration_ms for r in runs if r.duration_ms is not None)
            tokens_in_list = [r.tokens_in for r in runs if r.tokens_in is not None]
            tokens_out_list = [r.tokens_out for r in runs if r.tokens_out is not None]
            costs = [r.cost_usd for r in runs if r.cost_usd is not None]
            idle_times = []

            for r in runs:
                if r.started_at and r.started_at:
                    from grace_control.db.schema import Packet
                    pkt = db.query(Packet).filter_by(id=r.packet_id).first()
                    if pkt:
                        idle = (r.started_at - pkt.created_at).total_seconds()
                        idle_times.append(idle)

            metric = StageMetric(
                stage_key=stage_key,
                period_kind=period_kind,
                period_start=period_start,
                period_end=period_end,
                count=count,
                p50_ms=_percentile(durs, 50),
                p95_ms=_percentile(durs, 95),
                avg_ms=round(sum(durs) / len(durs)) if durs else None,
                max_ms=max(durs) if durs else None,
                min_ms=min(durs) if durs else None,
                success_count=success_count,
                failure_count=failure_count,
                success_rate=round(success_count / count, 4) if count else None,
                avg_tokens_in=round(sum(tokens_in_list) / len(tokens_in_list)) if tokens_in_list else None,
                avg_tokens_out=round(sum(tokens_out_list) / len(tokens_out_list)) if tokens_out_list else None,
                avg_cost_usd=round(sum(costs) / len(costs), 6) if costs else None,
                total_cost_usd=round(sum(costs), 6) if costs else None,
                avg_idle_seconds=round(sum(idle_times) / len(idle_times)) if idle_times else None,
                computed_at=datetime.now(timezone.utc),
            )

            existing = db.query(StageMetric).filter_by(
                stage_key=stage_key, period_kind=period_kind, period_start=period_start
            ).first()
            if existing:
                existing.count = metric.count
                existing.p50_ms = metric.p50_ms
                existing.p95_ms = metric.p95_ms
                existing.avg_ms = metric.avg_ms
                existing.max_ms = metric.max_ms
                existing.min_ms = metric.min_ms
                existing.success_count = metric.success_count
                existing.failure_count = metric.failure_count
                existing.success_rate = metric.success_rate
                existing.avg_tokens_in = metric.avg_tokens_in
                existing.avg_tokens_out = metric.avg_tokens_out
                existing.avg_cost_usd = metric.avg_cost_usd
                existing.total_cost_usd = metric.total_cost_usd
                existing.avg_idle_seconds = metric.avg_idle_seconds
                existing.computed_at = metric.computed_at
            else:
                db.add(metric)
            results.append(stage_key)

        db.commit()

    from grace_control.api.ws_broadcast import broadcast_metrics_updated
    import asyncio as _asyncio
    _asyncio.ensure_future(broadcast_metrics_updated(
        stage_keys=results,
        period=period_kind,
        computed_at=datetime.now(timezone.utc).isoformat() + "Z",
    ))

    return {"ok": True, "stage_keys": results, "period": period_kind}
