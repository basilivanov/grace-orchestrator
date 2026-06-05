#!/usr/bin/env python3
"""
Validate execution logs against expected schema.
"""
import json
from pathlib import Path
from typing import List, Dict
from aggregate_logs import aggregate_logs


REQUIRED_FIELDS = {
    "EXECUTOR_SELECTED": ["executor_id", "model", "role"],
    "PACKET_START": ["packet_id", "role"],
    "PACKET_END": ["packet_id", "status"],
    "EXECUTION_METRICS": ["total_tokens", "cost_usd", "duration_seconds"]
}


def validate_logs(logs: List[Dict]) -> Dict:
    """
    Validate logs against schema.

    Returns:
        {
            "valid": bool,
            "errors": [str],
            "warnings": [str],
            "total_events": int
        }
    """
    errors = []
    warnings = []

    for i, log in enumerate(logs):
        event = log.get("event")

        if not event:
            errors.append(f"Line {i}: Missing 'event' field")
            continue

        # Check required fields
        if event in REQUIRED_FIELDS:
            for field in REQUIRED_FIELDS[event]:
                if field not in log:
                    errors.append(f"Line {i}: {event} missing field '{field}'")

        # Check timestamp format
        if "timestamp" not in log:
            warnings.append(f"Line {i}: Missing timestamp")
        elif not isinstance(log["timestamp"], str):
            warnings.append(f"Line {i}: Timestamp is not a string")

        # Check packet_id presence for packet events
        if event in ["PACKET_START", "PACKET_END"] and "packet_id" not in log:
            errors.append(f"Line {i}: {event} missing 'packet_id'")

        # Validate status values
        if event == "PACKET_END" and "status" in log:
            valid_statuses = ["success", "failed", "error"]
            if log["status"] not in valid_statuses:
                warnings.append(
                    f"Line {i}: Unknown status '{log['status']}' "
                    f"(expected one of {valid_statuses})"
                )

        # Validate numeric fields
        if event == "EXECUTION_METRICS":
            for field in ["total_tokens", "cost_usd", "duration_seconds"]:
                if field in log and not isinstance(log[field], (int, float)):
                    errors.append(
                        f"Line {i}: {field} should be numeric, got {type(log[field]).__name__}"
                    )

    return {
        "valid": len(errors) == 0,
        "errors": errors,
        "warnings": warnings,
        "total_events": len(logs)
    }


if __name__ == "__main__":
    import sys

    if len(sys.argv) < 2:
        print("Usage: validate_logs.py <state_root>")
        print("")
        print("Validates execution logs against expected schema.")
        print("")
        print("Example:")
        print("  validate_logs.py state")
        sys.exit(1)

    state_root = Path(sys.argv[1])

    try:
        logs = aggregate_logs(state_root)
    except Exception as e:
        print(json.dumps({
            "valid": False,
            "errors": [f"Failed to aggregate logs: {e}"],
            "warnings": [],
            "total_events": 0
        }, indent=2))
        sys.exit(1)

    result = validate_logs(logs)
    print(json.dumps(result, indent=2))

    # Exit with error code if validation failed
    sys.exit(0 if result["valid"] else 1)
