#!/usr/bin/env python3
"""
Orchestrator health check CLI.
"""
import json
import sys
from pathlib import Path

# Add parent directory to path
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from prefect_grace.platform.health_check import check_orchestrator_health


def main():
    if len(sys.argv) < 2:
        print("Usage: health_check.py <state_root>")
        sys.exit(1)

    state_root = Path(sys.argv[1])
    result = check_orchestrator_health(state_root)

    print(json.dumps(result, indent=2))

    # Exit code based on status
    if result["status"] == "healthy":
        sys.exit(0)
    elif result["status"] == "degraded":
        sys.exit(1)
    else:  # failing
        sys.exit(2)


if __name__ == "__main__":
    main()
