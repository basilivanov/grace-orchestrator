#!/usr/bin/env python3
"""
Interactive log viewer for execution traces.
"""
import json
from pathlib import Path
from typing import List, Dict
from aggregate_logs import aggregate_logs


def view_packet_trace(logs: List[Dict], packet_id: str):
    """Show all events for a specific packet."""
    packet_logs = [log for log in logs if log.get("packet_id") == packet_id]

    if not packet_logs:
        print(f"No logs found for packet {packet_id}")
        return

    print(f"\n=== Trace for {packet_id} ===\n")

    for log in packet_logs:
        timestamp = log.get("timestamp", "")
        event = log.get("event", "")
        print(f"{timestamp} | {event}")

        # Show relevant details
        if event == "EXECUTOR_SELECTED":
            print(f"  Model: {log.get('model')}")
            print(f"  Complexity: {log.get('complexity')}")
            if log.get('reason'):
                print(f"  Reason: {log.get('reason')}")
        elif event == "PACKET_START":
            print(f"  Role: {log.get('role')}")
        elif event == "PACKET_END":
            print(f"  Status: {log.get('status')}")
            if log.get('duration_seconds'):
                print(f"  Duration: {log.get('duration_seconds')}s")
            if log.get('reason'):
                print(f"  Reason: {log.get('reason')}")
        elif event == "EXECUTION_METRICS":
            print(f"  Tokens: {log.get('total_tokens')}")
            print(f"  Cost: ${log.get('cost_usd', 0):.4f}")
            if log.get('duration_seconds'):
                print(f"  Duration: {log.get('duration_seconds')}s")

        print()


def view_timeline(logs: List[Dict], limit: int = 50):
    """Show chronological timeline of events."""
    if not logs:
        print("No logs found")
        return

    print(f"\n=== Timeline (last {limit} events) ===\n")

    for log in logs[-limit:]:
        timestamp = log.get("timestamp", "")
        event = log.get("event", "")
        packet_id = log.get("packet_id", "N/A")
        print(f"{timestamp} | {event:30s} | {packet_id}")


def list_packets(logs: List[Dict]):
    """List all unique packet IDs."""
    packet_ids = set()
    for log in logs:
        if "packet_id" in log:
            packet_ids.add(log["packet_id"])

    if not packet_ids:
        print("No packets found")
        return

    print(f"\n=== Packets ({len(packet_ids)} total) ===\n")
    for packet_id in sorted(packet_ids):
        print(packet_id)


if __name__ == "__main__":
    import sys

    if len(sys.argv) < 2:
        print("Usage: view_trace.py <state_root> [packet_id|timeline|packets] [limit]")
        print("")
        print("Commands:")
        print("  timeline       - Show chronological timeline of events")
        print("  packets        - List all packet IDs")
        print("  <packet_id>    - Show trace for specific packet")
        print("")
        print("Examples:")
        print("  view_trace.py state timeline")
        print("  view_trace.py state timeline 100")
        print("  view_trace.py state packets")
        print("  view_trace.py state FEAT-XYZ-V1")
        sys.exit(1)

    state_root = Path(sys.argv[1])

    try:
        logs = aggregate_logs(state_root)
    except Exception as e:
        print(f"Error aggregating logs: {e}", file=sys.stderr)
        sys.exit(1)

    if len(sys.argv) >= 3:
        arg = sys.argv[2]
        if arg == "timeline":
            limit = int(sys.argv[3]) if len(sys.argv) >= 4 else 50
            view_timeline(logs, limit)
        elif arg == "packets":
            list_packets(logs)
        else:
            view_packet_trace(logs, arg)
    else:
        view_timeline(logs)
