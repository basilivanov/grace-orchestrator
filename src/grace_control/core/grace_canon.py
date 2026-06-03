# ############################################################################
# AI_HEADER: grace_canon
# ROLE: GRACE Canon compliance checker — validates contracts, blocks, limits.
# ############################################################################

# START_MODULE_CONTRACT
# purpose: Validate Python files against GRACE Canon rules (contracts, blocks, size limits).
# inputs: File path or directory path.
# returns: CanonResult with passed flag and list of CanonViolation.
# side_effects: Reads files from disk.
# emitted_logs: None.
# error_behavior: Never raises — returns violations as result.
# END_MODULE_CONTRACT

# START_MODULE_MAP
# mapping:
#   - class: CanonViolation
#   - class: CanonResult
#   - class: GraceCanonChecker
# END_MODULE_MAP

from __future__ import annotations

import ast
from dataclasses import dataclass, field
from pathlib import Path


@dataclass
class CanonViolation:
    file: str
    line: int | None = None
    rule: str = ""
    message: str = ""
    severity: str = "error"


@dataclass
class CanonResult:
    passed: bool
    violations: list[CanonViolation] = field(default_factory=list)


class GraceCanonChecker:
    MAX_FILE_LINES = 1000

    # START_FUNCTION_CONTRACT
    # name: check_file
    # purpose: Validate a single Python file against all GRACE Canon rules.
    # inputs: file_path — Path to Python file.
    # returns: CanonResult.
    # side_effects: Reads file.
    # emitted_logs: None.
    # error_behavior: Returns violation if file unreadable.
    # END_FUNCTION_CONTRACT
    def check_file(self, file_path: Path) -> CanonResult:
        violations: list[CanonViolation] = []
        try:
            content = file_path.read_text()
            lines = content.split("\n")
        except Exception as e:
            return CanonResult(False, [CanonViolation(str(file_path), rule="file_readable",
                message=f"Cannot read file: {e}", severity="error")])

        self._check_file_size(file_path, len(lines), violations)
        self._check_ai_header(file_path, content, violations)
        self._check_module_contract(file_path, content, violations)
        self._check_module_map(file_path, content, violations)
        self._check_module_blocks(file_path, content, violations)
        self._check_function_contracts(file_path, content, violations)
        self._check_semantic_blocks(file_path, content, violations)

        return CanonResult(len(violations) == 0, violations)

    # START_FUNCTION_CONTRACT
    # name: check_directory
    # purpose: Validate all Python files in a directory tree.
    # inputs: dir_path — Path to directory.
    # returns: CanonResult combining all file results.
    # side_effects: Reads multiple files.
    # emitted_logs: None.
    # error_behavior: Never raises.
    # END_FUNCTION_CONTRACT
    def check_directory(self, dir_path: Path) -> CanonResult:
        all_violations: list[CanonViolation] = []
        for py_file in sorted(dir_path.rglob("*.py")):
            if "__pycache__" in str(py_file):
                continue
            if py_file.name == "__init__.py":
                continue  # package markers don't need full contracts
            result = self.check_file(py_file)
            all_violations.extend(result.violations)
        return CanonResult(len(all_violations) == 0, all_violations)

    def _check_file_size(self, path: Path, line_count: int, violations: list):
        if line_count > self.MAX_FILE_LINES:
            violations.append(CanonViolation(str(path),
                rule="file_size",
                message=f"File too large: {line_count} lines (max {self.MAX_FILE_LINES})",
                severity="error"))

    def _check_ai_header(self, path: Path, content: str, violations: list):
        if "AI_HEADER:" not in content:
            violations.append(CanonViolation(str(path),
                rule="ai_header",
                message="Missing AI_HEADER",
                severity="error"))

    def _check_module_contract(self, path: Path, content: str, violations: list):
        has_start = "START_MODULE_CONTRACT" in content
        has_end = "END_MODULE_CONTRACT" in content
        if not has_start:
            violations.append(CanonViolation(str(path),
                rule="module_contract",
                message="Missing START_MODULE_CONTRACT",
                severity="error"))
        if not has_end:
            violations.append(CanonViolation(str(path),
                rule="module_contract",
                message="Missing END_MODULE_CONTRACT",
                severity="error"))

    def _check_module_map(self, path: Path, content: str, violations: list):
        if "START_MODULE_MAP" not in content:
            violations.append(CanonViolation(str(path),
                rule="module_map",
                message="Missing MODULE_MAP",
                severity="warning"))

    def _check_function_contracts(self, path: Path, content: str, violations: list):
        try:
            tree = ast.parse(content)
        except SyntaxError:
            return
        for node in ast.walk(tree):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                if node.name.startswith("_"):
                    continue
                func_lines = node.end_lineno - node.lineno + 1 if node.end_lineno else 0
                # Check for FUNCTION_CONTRACT above the function
                start = max(0, node.lineno - 15)
                preceding = "\n".join(content.split("\n")[start:node.lineno])
                if "FUNCTION_CONTRACT" not in preceding:
                    violations.append(CanonViolation(str(path), node.lineno,
                        rule="function_contract",
                        message=f"Function '{node.name}' missing FUNCTION_CONTRACT",
                        severity="error"))

    def _check_module_blocks(self, path: Path, content: str, violations: list):
        if "#START_BLOCK_" not in content:
            violations.append(CanonViolation(str(path),
                rule="module_blocks",
                message="Missing module-level #START_BLOCK_* / #END_BLOCK_* sections",
                severity="error"))

    def _check_semantic_blocks(self, path: Path, content: str, violations: list):
        lines = content.split("\n")
        stack: list[tuple[str, int]] = []
        for i, line in enumerate(lines, 1):
            stripped = line.strip()
            if stripped.startswith("#START_BLOCK_"):
                name = stripped.split("#START_BLOCK_")[1].split()[0]
                stack.append((name, i))
            elif stripped.startswith("#END_BLOCK_"):
                name = stripped.split("#END_BLOCK_")[1].split()[0]
                if not stack:
                    violations.append(CanonViolation(str(path), i,
                        rule="semantic_blocks",
                        message=f"END_BLOCK_{name} without matching START",
                        severity="error"))
                else:
                    start_name, start_line = stack.pop()
                    if start_name != name:
                        violations.append(CanonViolation(str(path), i,
                            rule="semantic_blocks",
                            message=f"Mismatched blocks: START_{start_name} (line {start_line}) vs END_{name}",
                            severity="error"))

        for block_name, line in stack:
            violations.append(CanonViolation(str(path), line,
                rule="semantic_blocks",
                message=f"Unclosed START_BLOCK_{block_name}",
                severity="error"))
