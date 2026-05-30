"""
Orchestrator health check module.
"""
from pathlib import Path
from typing import Dict, List
from datetime import datetime, timedelta
import json


class HealthStatus:
    HEALTHY = "healthy"
    DEGRADED = "degraded"
    FAILING = "failing"


def check_executor_rotation(logs: List[Dict]) -> Dict:
    """
    Check if executor rotation is working.

    Returns:
        {
            "status": "healthy" | "degraded" | "failing",
            "issues": [str],
            "details": {...}
        }
    """
    issues = []

    # Find packets with multiple failures
    failures_by_packet = {}
    for log in logs:
        if log.get("event") == "PACKET_END" and log.get("status") == "failed":
            packet_id = log.get("packet_id")
            executor_id = log.get("executor_id")

            if packet_id not in failures_by_packet:
                failures_by_packet[packet_id] = []
            failures_by_packet[packet_id].append(executor_id)

    # Check for stuck executors (5+ failures without rotation)
    stuck_count = 0
    for packet_id, executors in failures_by_packet.items():
        if len(executors) >= 5 and len(set(executors)) == 1:
            issues.append(f"Packet {packet_id} stuck on executor {executors[0]}")
            stuck_count += 1

    # Determine status
    if stuck_count == 0:
        status = HealthStatus.HEALTHY
    elif stuck_count <= 2:
        status = HealthStatus.DEGRADED
    else:
        status = HealthStatus.FAILING

    return {
        "status": status,
        "issues": issues,
        "details": {
            "stuck_executors": stuck_count,
            "total_failures": sum(len(execs) for execs in failures_by_packet.values())
        }
    }


def check_deadlocks(logs: List[Dict]) -> Dict:
    """
    Check for packets stuck in running state.
    """
    issues = []
    now = datetime.now()

    # Find packets that started but never ended
    started = {}
    ended = set()

    for log in logs:
        if log.get("event") == "PACKET_START":
            packet_id = log.get("packet_id")
            timestamp = log.get("timestamp")
            started[packet_id] = timestamp
        elif log.get("event") == "PACKET_END":
            packet_id = log.get("packet_id")
            ended.add(packet_id)

    # Check for packets running >1 hour
    stuck_count = 0
    for packet_id, start_time in started.items():
        if packet_id not in ended:
            # Parse timestamp and check duration
            try:
                start_dt = datetime.fromisoformat(start_time.replace('Z', '+00:00'))
                duration = (now - start_dt).total_seconds()
                if duration > 3600:  # 1 hour
                    issues.append(f"Packet {packet_id} stuck for {duration/3600:.1f}h")
                    stuck_count += 1
            except:
                pass

    # Determine status
    if stuck_count == 0:
        status = HealthStatus.HEALTHY
    elif stuck_count <= 2:
        status = HealthStatus.DEGRADED
    else:
        status = HealthStatus.FAILING

    return {
        "status": status,
        "issues": issues,
        "details": {
            "stuck_packets": stuck_count,
            "running_packets": len(started) - len(ended)
        }
    }


def check_metrics_collection(logs: List[Dict]) -> Dict:
    """
    Check if metrics are being collected.
    """
    issues = []

    # Count executions and metrics
    packet_ends = [log for log in logs if log.get("event") == "PACKET_END"]
    metrics = [log for log in logs if log.get("event") == "EXECUTION_METRICS"]

    if len(packet_ends) == 0:
        return {
            "status": HealthStatus.HEALTHY,
            "issues": [],
            "details": {"no_executions": True}
        }

    # Check metrics coverage
    coverage = len(metrics) / len(packet_ends) if packet_ends else 0

    if coverage < 0.5:
        issues.append(f"Low metrics coverage: {coverage*100:.0f}%")
        status = HealthStatus.FAILING
    elif coverage < 0.9:
        issues.append(f"Partial metrics coverage: {coverage*100:.0f}%")
        status = HealthStatus.DEGRADED
    else:
        status = HealthStatus.HEALTHY

    return {
        "status": status,
        "issues": issues,
        "details": {
            "metrics_coverage": coverage,
            "total_executions": len(packet_ends),
            "metrics_collected": len(metrics)
        }
    }


def check_orchestrator_health(state_root: Path) -> Dict:
    """
    Main health check function.

    Returns:
        {
            "status": "healthy" | "degraded" | "failing",
            "checks": {...},
            "timestamp": str
        }
    """
    import sys
    from pathlib import Path as P

    # Add tools directory to path for imports
    tools_dir = P(__file__).parent.parent / "tools"
    if str(tools_dir) not in sys.path:
        sys.path.insert(0, str(tools_dir))

    from aggregate_logs import aggregate_logs

    logs = aggregate_logs(state_root)

    checks = {
        "executor_rotation": check_executor_rotation(logs),
        "deadlocks": check_deadlocks(logs),
        "metrics_collection": check_metrics_collection(logs)
    }

    # Overall status is worst of all checks
    statuses = [check["status"] for check in checks.values()]
    if HealthStatus.FAILING in statuses:
        overall_status = HealthStatus.FAILING
    elif HealthStatus.DEGRADED in statuses:
        overall_status = HealthStatus.DEGRADED
    else:
        overall_status = HealthStatus.HEALTHY

    return {
        "status": overall_status,
        "checks": checks,
        "timestamp": datetime.now().isoformat()
    }
