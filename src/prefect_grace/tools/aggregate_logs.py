#!/usr/bin/env python3
"""
Aggregate execution logs from all packet runs.
"""
import json
from pathlib import Path
from typing import List, Dict


def aggregate_logs(state_root: Path) -> List[Dict]:
    """
    Collect all execution_trace.jsonl files from state/runs.

    Returns list of log events sorted by timestamp.
    """
    logs = []
    runs_dir = state_root / "runs"

    if not runs_dir.exists():
        return logs

    for trace_file in runs_dir.rglob("execution_trace.jsonl"):
        try:
            with open(trace_file) as f:
                for line in f:
                    if line.strip():
                        try:
                            logs.append(json.loads(line))
                        except json.JSONDecodeError:
                            # Skip malformed lines
                            continue
        except (IOError, OSError):
            # Skip files we can't read
            continue

    # Sort by timestamp
    logs.sort(key=lambda x: x.get("timestamp", ""))
    return logs


if __name__ == "__main__":
    import sys
    state_root = Path(sys.argv[1]) if len(sys.argv) > 1 else Path("state")
    logs = aggregate_logs(state_root)
    for log in logs:
        print(json.dumps(log))
