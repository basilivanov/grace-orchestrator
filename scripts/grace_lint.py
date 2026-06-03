#!/usr/bin/env python3
"""GRACE Canon linter — checks AI_HEADER, MODULE_CONTRACT, MODULE_MAP, FUNCTION_CONTRACT."""

import ast
import re
import sys
import argparse
from dataclasses import dataclass, field
from pathlib import Path


@dataclass
class Violation:
    code: str
    message: str
    file: str
    line: int = 1


def _top_level_count(content: str) -> int:
    """Count top-level statements via AST for compressed-file detection."""
    try:
        tree = ast.parse(content)
        count = 0
        for node in ast.iter_child_nodes(tree):
            if isinstance(node, (ast.Import, ast.ImportFrom, ast.FunctionDef,
                                ast.AsyncFunctionDef, ast.ClassDef, ast.Assign)):
                count += 1
        return count
    except SyntaxError:
        return 0


def _physical_lines(content: str) -> int:
    return len([l for l in content.split("\n") if l.strip()])


def lint_file(filepath: Path, skip_function_contracts: bool = False) -> list[Violation]:
    violations: list[Violation] = []
    try:
        content = filepath.read_text()
    except Exception:
        return [Violation("GRC000", f"cannot read file", str(filepath), 1)]

    # GRC000: syntax error
    try:
        tree = ast.parse(content)
    except SyntaxError as e:
        return [Violation("GRC000", f"syntax error: {e}", str(filepath), e.lineno or 1)]

    # Skip empty __init__.py
    if filepath.name == "__init__.py" and not content.strip():
        return []

    lines = content.split("\n")
    path = str(filepath)

    # GRC030: compressed file (> 5 top-level stmts, < 5 physical lines)
    tls = _top_level_count(content)
    phys = _physical_lines(content)
    if tls > 5 and phys < 5:
        violations.append(Violation("GRC030", f"suspicious compressed file: {tls} top-level stmts on {phys} lines",
                                    path, 1))

    # GRC001: missing AI_HEADER
    if not re.search(r'# AI_HEADER:', content):
        violations.append(Violation("GRC001", "missing # AI_HEADER:", path, 1))

    # GRC020: missing module contract
    has_start_mc = "# START_MODULE_CONTRACT" in content
    has_end_mc = "# END_MODULE_CONTRACT" in content
    if not has_start_mc and not has_end_mc:
        violations.append(Violation("GRC020", "missing MODULE_CONTRACT", path, 1))
    # GRC002: pairing mismatch
    if has_start_mc != has_end_mc:
        which = "START without END" if has_start_mc else "END without START"
        violations.append(Violation("GRC002", f"MODULE_CONTRACT pairing: {which}", path, 1))

    # GRC021: missing module map
    has_start_mm = "# START_MODULE_MAP" in content
    has_end_mm = "# END_MODULE_MAP" in content
    if not has_start_mm and not has_end_mm:
        violations.append(Violation("GRC021", "missing MODULE_MAP", path, 1))
    # GRC003: pairing mismatch
    if has_start_mm != has_end_mm:
        which = "START without END" if has_start_mm else "END without START"
        violations.append(Violation("GRC003", f"MODULE_MAP pairing: {which}", path, 1))

    # GRC004: block start/end mismatch
    starts = re.findall(r'# START_BLOCK_(\w+)', content)
    ends = re.findall(r'# END_BLOCK_(\w+)', content)
    if len(starts) != len(ends):
        violations.append(Violation("GRC004", f"BLOCK mismatch: {len(starts)} starts, {len(ends)} ends", path, 1))
    else:
        for s, e in zip(starts, sorted(ends)):
            if s != e:
                violations.append(Violation("GRC004", f"mismatched BLOCK: START_{s} vs END_{e}", path, 1))
                break

    # GRC005: file exceeds 1000 lines
    if len(lines) > 1000:
        violations.append(Violation("GRC005", f"file too large: {len(lines)} lines (max 1000)", path, 1))

    # GRC010/011: function contracts
    if not skip_function_contracts:
        for node in ast.walk(tree):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                if node.name.startswith("_"):
                    continue
                # Find if nearest contract is before this function
                func_line = node.lineno
                before = "\n".join(lines[:func_line])
                has_contract = bool(re.search(r'# START_FUNCTION_CONTRACT\s*\n', before))
                last_end = before.rfind("# END_FUNCTION_CONTRACT")
                last_start = before.rfind("# START_FUNCTION_CONTRACT")
                has_end = last_end > last_start

                if not has_contract:
                    violations.append(Violation("GRC010",
                        f"public function '{node.name}' missing FUNCTION_CONTRACT", path, node.lineno))
                elif has_contract and has_end:
                    # GRC011: check required fields
                    match = re.search(r'# START_FUNCTION_CONTRACT\s*\n(.*?)# END_FUNCTION_CONTRACT',
                                     "\n".join(lines), re.DOTALL)
                    if match:
                        contract = match.group(1)
                        req_fields = ["name", "purpose", "inputs", "returns", "side_effects"]
                        missing = [f for f in req_fields if f"{f}:" not in contract]
                        if missing:
                            violations.append(Violation("GRC011",
                                f"function '{node.name}' contract missing: {', '.join(missing)}",
                                path, node.lineno))

                # GRC012: function exceeds 4000 tokens
                func_lines = lines[node.lineno - 1:node.end_lineno] if node.end_lineno else []
                func_body = "\n".join(func_lines)
                est_tokens = len(func_body) // 4  # ~4 chars per token
                if est_tokens > 4000:
                    violations.append(Violation("GRC012",
                        f"function '{node.name}' too large: ~{est_tokens} tokens (max 4000)",
                        path, node.lineno))

    return violations


def main():
    parser = argparse.ArgumentParser(description="GRACE Canon linter")
    parser.add_argument("paths", nargs="+", help="files or directories to check")
    parser.add_argument("--skip-function-contracts", action="store_true",
                       help="skip GRC010/GRC011 checks")
    parser.add_argument("--quiet", action="store_true")
    args = parser.parse_args()

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
            violations = lint_file(fp, skip_function_contracts=args.skip_function_contracts)
            for v in violations:
                total += 1
                print(f"{v.file}:{v.line}: {v.code} {v.message}")

    if total > 0:
        sys.exit(1)
    sys.exit(0)


if __name__ == "__main__":
    main()
