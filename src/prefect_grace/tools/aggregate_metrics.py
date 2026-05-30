#!/usr/bin/env python3
"""
Aggregate metrics from execution history.
"""
import json
from pathlib import Path
from typing import Dict, List
from collections import defaultdict


def aggregate_metrics(state_root: Path) -> Dict:
    """
    Aggregate metrics from all executions.

    Returns:
        {
            "total_executions": int,
            "total_cost_usd": float,
            "total_tokens": int,
            "avg_duration_seconds": float,
            "by_model": {...},
            "by_complexity": {...},
            "by_role": {...},
            "savings": {...}
        }
    """
    from prefect_grace.tools.aggregate_logs import aggregate_logs

    logs = aggregate_logs(state_root)

    # Look for EXECUTION_METRICS events or estimate from packet executions
    metrics_logs = [log for log in logs if log.get("event") == "EXECUTION_METRICS"]

    # If no explicit metrics, estimate from packet executions
    if not metrics_logs:
        # Count packet executions as proxy
        packet_runs = [log for log in logs if log.get("event") == "packet_execution_completed"]

        if not packet_runs:
            return _empty_metrics()

        # Estimate metrics based on packet runs
        return _estimate_metrics_from_runs(packet_runs)

    # Aggregate totals
    total_cost = sum(log.get("cost_usd", 0) for log in metrics_logs)
    total_tokens = sum(log.get("total_tokens", 0) for log in metrics_logs)
    total_duration = sum(log.get("duration_seconds", 0) for log in metrics_logs)

    # Aggregate by model
    by_model = defaultdict(lambda: {"count": 0, "cost": 0.0, "tokens": 0})
    for log in metrics_logs:
        model = log.get("model", "unknown")
        by_model[model]["count"] += 1
        by_model[model]["cost"] += log.get("cost_usd", 0)
        by_model[model]["tokens"] += log.get("total_tokens", 0)

    # Aggregate by complexity
    by_complexity = defaultdict(lambda: {"count": 0, "cost": 0.0, "tokens": 0})
    for log in metrics_logs:
        complexity = log.get("complexity", "unknown")
        by_complexity[complexity]["count"] += 1
        by_complexity[complexity]["cost"] += log.get("cost_usd", 0)
        by_complexity[complexity]["tokens"] += log.get("total_tokens", 0)

    # Aggregate by role
    by_role = defaultdict(lambda: {"count": 0, "cost": 0.0, "tokens": 0})
    for log in metrics_logs:
        role = log.get("role", "unknown")
        by_role[role]["count"] += 1
        by_role[role]["cost"] += log.get("cost_usd", 0)
        by_role[role]["tokens"] += log.get("total_tokens", 0)

    # Calculate savings
    # Compare actual cost vs if all used premium model
    premium_cost_per_token = 75.0 / 1_000_000  # claude-opus-4 output pricing
    hypothetical_premium_cost = total_tokens * premium_cost_per_token
    savings_usd = hypothetical_premium_cost - total_cost
    savings_pct = (savings_usd / hypothetical_premium_cost * 100) if hypothetical_premium_cost > 0 else 0

    return {
        "total_executions": len(metrics_logs),
        "total_cost_usd": total_cost,
        "total_tokens": total_tokens,
        "avg_duration_seconds": total_duration / len(metrics_logs) if metrics_logs else 0,
        "by_model": dict(by_model),
        "by_complexity": dict(by_complexity),
        "by_role": dict(by_role),
        "savings": {
            "actual_cost_usd": total_cost,
            "premium_only_cost_usd": hypothetical_premium_cost,
            "savings_usd": savings_usd,
            "savings_pct": savings_pct
        }
    }


def _empty_metrics() -> Dict:
    """Return empty metrics structure."""
    return {
        "total_executions": 0,
        "total_cost_usd": 0.0,
        "total_tokens": 0,
        "avg_duration_seconds": 0.0,
        "by_model": {},
        "by_complexity": {},
        "by_role": {},
        "savings": {
            "actual_cost_usd": 0.0,
            "premium_only_cost_usd": 0.0,
            "savings_usd": 0.0,
            "savings_pct": 0.0
        }
    }


def _estimate_metrics_from_runs(packet_runs: List[Dict]) -> Dict:
    """
    Estimate metrics from packet execution logs.

    This is a fallback when explicit EXECUTION_METRICS events are not available.
    Uses heuristics to estimate costs and tokens.
    """
    # Model pricing (per 1M tokens, output)
    MODEL_PRICING = {
        "claude-opus-4": 75.0,
        "claude-sonnet-4": 15.0,
        "claude-haiku-4": 4.0,
    }

    # Estimate tokens per packet (rough heuristic)
    ESTIMATED_TOKENS_PER_PACKET = 50000

    # Count by packet_id to avoid duplicates
    unique_packets = {}
    for log in packet_runs:
        packet_id = log.get("packet_id", "unknown")
        if packet_id not in unique_packets:
            unique_packets[packet_id] = log

    total_executions = len(unique_packets)

    # Estimate model distribution (assume 60% sonnet, 30% haiku, 10% opus)
    estimated_tokens = total_executions * ESTIMATED_TOKENS_PER_PACKET

    opus_tokens = int(estimated_tokens * 0.10)
    sonnet_tokens = int(estimated_tokens * 0.60)
    haiku_tokens = int(estimated_tokens * 0.30)

    opus_cost = opus_tokens * MODEL_PRICING["claude-opus-4"] / 1_000_000
    sonnet_cost = sonnet_tokens * MODEL_PRICING["claude-sonnet-4"] / 1_000_000
    haiku_cost = haiku_tokens * MODEL_PRICING["claude-haiku-4"] / 1_000_000

    total_cost = opus_cost + sonnet_cost + haiku_cost

    # Calculate savings vs all-opus
    premium_cost = estimated_tokens * MODEL_PRICING["claude-opus-4"] / 1_000_000
    savings_usd = premium_cost - total_cost
    savings_pct = (savings_usd / premium_cost * 100) if premium_cost > 0 else 0

    return {
        "total_executions": total_executions,
        "total_cost_usd": total_cost,
        "total_tokens": estimated_tokens,
        "avg_duration_seconds": 0.0,  # Not available from logs
        "by_model": {
            "claude-opus-4": {"count": int(total_executions * 0.10), "cost": opus_cost, "tokens": opus_tokens},
            "claude-sonnet-4": {"count": int(total_executions * 0.60), "cost": sonnet_cost, "tokens": sonnet_tokens},
            "claude-haiku-4": {"count": int(total_executions * 0.30), "cost": haiku_cost, "tokens": haiku_tokens},
        },
        "by_complexity": {
            "high": {"count": int(total_executions * 0.10), "cost": opus_cost, "tokens": opus_tokens},
            "medium": {"count": int(total_executions * 0.60), "cost": sonnet_cost, "tokens": sonnet_tokens},
            "low": {"count": int(total_executions * 0.30), "cost": haiku_cost, "tokens": haiku_tokens},
        },
        "by_role": {},
        "savings": {
            "actual_cost_usd": total_cost,
            "premium_only_cost_usd": premium_cost,
            "savings_usd": savings_usd,
            "savings_pct": savings_pct
        },
        "note": "Metrics estimated from packet execution logs (EXECUTION_METRICS events not found)"
    }


if __name__ == "__main__":
    import sys
    state_root = Path(sys.argv[1]) if len(sys.argv) > 1 else Path("state")
    metrics = aggregate_metrics(state_root)
    print(json.dumps(metrics, indent=2))
