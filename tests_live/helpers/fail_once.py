#!/usr/bin/env python3
"""fail_once.py — controlled failure injection for live test replay scenarios.

First call with a given --key exits non-zero (simulates failure).
Subsequent calls with the same --key exit zero (simulates fix after replay).
"""

import argparse
import os
import sys
import tempfile

_TRACKING_DIR = os.environ.get(
    "GRACE_LIVE_TEST_FAIL_TRACKING_DIR",
    os.path.join(tempfile.gettempdir(), "grace-fail-once"),
)


def _flag_path(key: str) -> str:
    os.makedirs(_TRACKING_DIR, exist_ok=True)
    return os.path.join(_TRACKING_DIR, f"fail_once_{key}.flag")


def main() -> None:
    parser = argparse.ArgumentParser(description="Fail-once helper")
    parser.add_argument("--key", required=True, help="Failure scenario key")
    args = parser.parse_args()

    flag = _flag_path(args.key)
    if os.path.exists(flag):
        # Already failed once — pass now
        os.remove(flag)
        print(f"fail_once[{args.key}]: PASS (already failed before)")
        sys.exit(0)
    else:
        # First call — fail
        with open(flag, "w") as f:
            f.write("failed")
        print(f"fail_once[{args.key}]: FAIL (first attempt)")
        sys.exit(1)


if __name__ == "__main__":
    main()
