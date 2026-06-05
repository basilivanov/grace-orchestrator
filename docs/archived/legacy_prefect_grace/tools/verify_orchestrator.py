#!/usr/bin/env python3
"""
Verify orchestrator health using cheap model analysis.
"""
import json
from pathlib import Path
from typing import Dict, List
from datetime import datetime, timedelta
from aggregate_logs import aggregate_logs
from verification_patterns import SUCCESS_PATTERNS, FAILURE_PATTERNS


def verify_executor_selection(logs: List[Dict]) -> Dict:
    """Verify complexity routing works."""
    issues = []

    # Find EXECUTOR_SELECTED events
    selections = [log for log in logs if log.get("event") == "EXECUTOR_SELECTED"]

    for sel in selections:
        complexity = sel.get("complexity", "").lower()
        model = sel.get("model", "")

        # Check routing
        if complexity == "simple" and "flash" not in model.lower():
            issues.append(f"Simple packet used {model} instead of cheap model")
        elif complexity == "complex" and "opus" not in model.lower():
            issues.append(f"Complex packet used {model} instead of premium model")

    return {
        "passed": len(issues) == 0,
        "issues": issues,
        "total_selections": len(selections)
    }


def verify_executor_rotation(logs: List[Dict]) -> Dict:
    """Verify rotation after consecutive failures."""
    issues = []

    # Track failures by packet_id
    failures = {}

    for log in logs:
        if log.get("event") == "PACKET_END" and log.get("status") == "failed":
            packet_id = log.get("packet_id")
            executor_id = log.get("executor_id")

            if packet_id not in failures:
                failures[packet_id] = []
            failures[packet_id].append(executor_id)

    # Check for rotation
    for packet_id, executors in failures.items():
        if len(executors) >= 3 and len(set(executors)) == 1:
            issues.append(f"Packet {packet_id} failed 3+ times with same executor")

    return {
        "passed": len(issues) == 0,
        "issues": issues,
        "total_packets_with_failures": len(failures)
    }


def verify_status_transitions(logs: List[Dict]) -> Dict:
    """Verify all packets reach terminal state."""
    issues = []

    # Track packet statuses
    packet_statuses = {}

    for log in logs:
        if log.get("event") in ["PACKET_START", "PACKET_END"]:
            packet_id = log.get("packet_id")
            status = log.get("status")
            timestamp = log.get("timestamp", "")

            if packet_id:
                packet_statuses[packet_id] = {
                    "status": status,
                    "timestamp": timestamp
                }

    # Check for stuck packets
    now = datetime.now()
    for packet_id, info in packet_statuses.items():
        status = info.get("status", "")
        timestamp_str = info.get("timestamp", "")

        if status == "running":
            try:
                timestamp = datetime.fromisoformat(timestamp_str.replace("Z", "+00:00"))
                if now - timestamp > timedelta(hours=1):
                    issues.append(f"Packet {packet_id} stuck in 'running' for >1 hour")
            except (ValueError, AttributeError):
                # Can't parse timestamp, skip time check
                issues.append(f"Packet {packet_id} in 'running' state (timestamp unparseable)")

    return {
        "passed": len(issues) == 0,
        "issues": issues,
        "total_packets": len(packet_statuses)
    }


def verify_metrics_present(logs: List[Dict]) -> Dict:
    """Verify metrics collected for all executions."""
    issues = []

    # Find EXECUTION_METRICS events
    metrics_logs = [log for log in logs if log.get("event") == "EXECUTION_METRICS"]

    for metric in metrics_logs:
        packet_id = metric.get("packet_id", "unknown")

        if "tokens_used" not in metric:
            issues.append(f"Packet {packet_id}: missing token count")
        if "cost_usd" not in metric:
            issues.append(f"Packet {packet_id}: missing cost")
        if "duration_seconds" not in metric:
            issues.append(f"Packet {packet_id}: missing duration")

    return {
        "passed": len(issues) == 0,
        "issues": issues,
        "total_metrics": len(metrics_logs)
    }


def check_packet_success(logs: List[Dict], packet_id: str) -> Dict:
    """
    Check if a packet succeeded according to success criteria.

    Returns:
        {
            "success": bool,
            "criteria_met": {
                "status_accepted": bool,
                "returncode_zero": bool,
                "metrics_present": bool,
                "events_complete": bool
            },
            "issues": [str]
        }
    """
    packet_logs = [log for log in logs if log.get("packet_id") == packet_id]
    issues = []

    # Check status
    end_events = [log for log in packet_logs if log.get("event") == "PACKET_END"]
    status_accepted = any(log.get("status") == "accepted" for log in end_events)

    # Check returncode
    returncode_zero = any(log.get("returncode") == 0 for log in end_events)

    # Check metrics
    metrics_events = [log for log in packet_logs if log.get("event") == "EXECUTION_METRICS"]
    metrics_present = len(metrics_events) > 0

    # Check events
    required_events = {"PACKET_START", "EXECUTOR_SELECTED", "PACKET_END"}
    present_events = {log.get("event") for log in packet_logs}
    events_complete = required_events.issubset(present_events)

    if not status_accepted:
        issues.append("Status not accepted")
    if not returncode_zero:
        issues.append("Non-zero return code")
    if not metrics_present:
        issues.append("Metrics not collected")
    if not events_complete:
        missing = required_events - present_events
        issues.append(f"Missing events: {missing}")

    return {
        "success": len(issues) == 0,
        "criteria_met": {
            "status_accepted": status_accepted,
            "returncode_zero": returncode_zero,
            "metrics_present": metrics_present,
            "events_complete": events_complete
        },
        "issues": issues
    }


def check_feature_success(logs: List[Dict], feature_id: str) -> Dict:
    """
    Check if a feature succeeded according to success criteria.

    Returns:
        {
            "success": bool,
            "total_packets": int,
            "successful_packets": int,
            "packet_results": {packet_id: result}
        }
    """
    # Get all packets for feature
    feature_logs = [log for log in logs if log.get("feature_id") == feature_id]
    packet_ids = {log.get("packet_id") for log in feature_logs if log.get("packet_id")}

    # Check each packet
    packet_results = {}
    for packet_id in packet_ids:
        packet_results[packet_id] = check_packet_success(logs, packet_id)

    # Feature succeeds if all packets succeed
    all_success = all(r["success"] for r in packet_results.values())

    return {
        "success": all_success,
        "total_packets": len(packet_ids),
        "successful_packets": sum(1 for r in packet_results.values() if r["success"]),
        "packet_results": packet_results
    }


def verify_orchestrator(state_root: Path) -> Dict:
    """
    Main verification function.

    Returns:
        {
            "verdict": "PASS" | "FAIL",
            "checks": {...},
            "metrics": {...}
        }
    """
    logs = aggregate_logs(state_root)

    if not logs:
        return {
            "verdict": "FAIL",
            "checks": {},
            "metrics": {},
            "error": "No logs found in state directory"
        }

    checks = {
        "executor_selection": verify_executor_selection(logs),
        "executor_rotation": verify_executor_rotation(logs),
        "status_transitions": verify_status_transitions(logs),
        "metrics_present": verify_metrics_present(logs)
    }

    # Calculate metrics
    metrics_logs = [log for log in logs if log.get("event") == "EXECUTION_METRICS"]
    total_cost = sum(log.get("cost_usd", 0) for log in metrics_logs)

    metrics = {
        "total_executions": len(metrics_logs),
        "total_cost_usd": round(total_cost, 4),
        "avg_cost_per_execution": round(total_cost / len(metrics_logs), 4) if metrics_logs else 0,
        "total_log_events": len(logs)
    }

    # Determine verdict
    all_passed = all(check["passed"] for check in checks.values())

    return {
        "verdict": "PASS" if all_passed else "FAIL",
        "checks": checks,
        "metrics": metrics
    }


if __name__ == "__main__":
    import sys
    state_root = Path(sys.argv[1]) if len(sys.argv) > 1 else Path("state")
    result = verify_orchestrator(state_root)
    print(json.dumps(result, indent=2))
