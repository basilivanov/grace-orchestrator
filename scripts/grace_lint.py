#!/usr/bin/env python3
"""GRACE Canon linter — thin CLI wrapper around grace_control.tools.grace_lint.checker."""

import sys
import argparse
from pathlib import Path

# W10: import the core checker instead of duplicating logic.
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from grace_control.tools.grace_lint.checker import lint_file, load_allowlist, DEFAULT_RULES


def main():
    parser = argparse.ArgumentParser(description="GRACE Canon linter")
    parser.add_argument("paths", nargs="+", help="files or directories to check")
    parser.add_argument("--skip-function-contracts", action="store_true",
                       help="skip GRC010/GRC011 checks")
    parser.add_argument("--quiet", action="store_true")
    parser.add_argument("--rules", nargs="*", help="space-separated rule codes to enable (default: all)")
    parser.add_argument("--allowlist", default=".grace/lint_allowlist.yaml",
                       help="path to allowlist YAML")
    args = parser.parse_args()

    rules_enabled = args.rules or DEFAULT_RULES
    allowlist = load_allowlist(Path(args.allowlist) if args.allowlist else None)

    total = 0
    for target in args.paths:
        p = Path(target)
        if not p.exists():
            if not args.quiet:
                print(f"WARN: not found: {target}", file=sys.stderr)
            continue

        files: list[Path] = []
        if p.is_file() and p.suffix == ".py":
            files = [p]
        elif p.is_dir():
            files = sorted(p.rglob("*.py"))
        else:
            continue

        for fp in files:
            if "__pycache__" in str(fp):
                continue
            violations = lint_file(fp, allowlist, args.skip_function_contracts, rules_enabled)
            for v in violations:
                total += 1
                print(f"{v.file}:{v.line}: {v.code} {v.message}")

    if total > 0:
        sys.exit(1)
    sys.exit(0)


if __name__ == "__main__":
    main()
