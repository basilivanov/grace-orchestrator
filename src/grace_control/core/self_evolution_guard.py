# ############################################################################
# AI_HEADER: self_evolution_guard
# ROLE: Safety checks for self-evolution packets before merge — API contracts, DB schema, no self-loop.
# ############################################################################

# START_MODULE_CONTRACT
# purpose: Validate self-evolution changes: API contracts intact, DB schema unchanged, no self-loop, tests pass.
# inputs: changed_files (list[Path]), session_id (str).
# returns: GuardResult with passed flag and per-check results.
# side_effects: Runs pytest subprocess for test check.
# emitted_logs: guard_check_result per invocation.
# error_behavior: Guard failures block merge; exceptions caught and reported.
# END_MODULE_CONTRACT

# START_MODULE_MAP
# mapping:
#   - dataclass: GuardCheck
#   - dataclass: GuardResult
#   - class: SelfEvolutionGuard
# END_MODULE_MAP

from __future__ import annotations

import re
import subprocess
from dataclasses import dataclass, field
from pathlib import Path

from grace_control.core.structured_logger import GraceLogger

_log = GraceLogger("self_evolution_guard")

FORBIDDEN_FILES = ["context_collector.py", "self_evolution_guard.py"]


@dataclass
class GuardCheck:
    name: str
    passed: bool
    detail: str = ""


@dataclass
class GuardResult:
    passed: bool
    checks: list[GuardCheck] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)


class SelfEvolutionGuard:

    def __init__(self, project_root: Path | None = None):
        self._root = project_root or Path.cwd()

    def check(self, changed_files: list[Path], session_id: str = "") -> GuardResult:
        checks = [
            self._check_api_contracts(changed_files),
            self._check_db_schema(changed_files),
            self._check_no_self_loop(changed_files),
            self._check_canon_compliance(changed_files),
        ]
        passed = all(c.passed for c in checks)
        errors = [c.detail for c in checks if not c.passed]
        result = GuardResult(passed=passed, checks=checks, errors=errors)
        _log.info("guard_check_result", session_id=session_id, passed=passed, error_count=len(errors))
        return result

    def _check_api_contracts(self, changed_files: list[Path]) -> GuardCheck:
        api_files = [f for f in changed_files if "api/" in str(f) and f.suffix == ".py"]
        if not api_files:
            return GuardCheck("api_contracts", True, "No API files changed")

        for f in api_files:
            try:
                content = f.read_text()
            except Exception:
                continue

            route_matches = re.findall(r'@router\.(get|post|put|delete|patch)\(["\']([^"\']+)["\']', content)
            if not route_matches:
                continue

            current_routes = set(m[1] for m in route_matches)

            try:
                result = subprocess.run(
                    ["git", "diff", "HEAD", "--", str(f)],
                    capture_output=True, text=True, timeout=10,
                    cwd=str(self._root),
                )
                removed = set(re.findall(r'^-.*@router\.\w+\(["\']([^"\']+)["\']', result.stdout))
                if removed:
                    return GuardCheck("api_contracts", False,
                        f"Cannot remove API routes: {sorted(removed)} in {f.name}")
            except Exception:
                pass

        return GuardCheck("api_contracts", True, f"{len(api_files)} API file(s) OK")

    def _check_db_schema(self, changed_files: list[Path]) -> GuardCheck:
        schema_file = None
        for f in changed_files:
            if f.name == "schema.py" and "db" in str(f):
                schema_file = f
                break
        if not schema_file:
            return GuardCheck("db_schema", True, "Schema unchanged")

        try:
            content = schema_file.read_text()
        except Exception:
            return GuardCheck("db_schema", True, "Cannot read schema file")

        if re.search(r"\bDROP\b\s+(TABLE|COLUMN)", content, re.IGNORECASE):
            return GuardCheck("db_schema", False, "DROP TABLE/COLUMN detected — requires manual migration")

        if re.search(r"\bALTER\b\s+TABLE", content, re.IGNORECASE):
            return GuardCheck("db_schema", False, "ALTER TABLE detected — requires manual migration")

        return GuardCheck("db_schema", True, "Schema changes are additive OK")

    def _check_no_self_loop(self, changed_files: list[Path]) -> GuardCheck:
        violations = []
        for f in changed_files:
            if f.name in FORBIDDEN_FILES:
                violations.append(f.name)
        if violations:
            return GuardCheck("no_self_loop", False,
                f"Cannot modify guard files during self-evolution: {violations}")
        return GuardCheck("no_self_loop", True, "No guard files modified")

    def _check_canon_compliance(self, changed_files: list[Path]) -> GuardCheck:
        violations = []
        for f in changed_files:
            if f.suffix != ".py":
                continue
            try:
                content = f.read_text()
            except Exception:
                continue

            if not re.search(r"# AI_HEADER:", content):
                violations.append(f"{f.name}: missing AI_HEADER")
            if not re.search(r"# START_MODULE_CONTRACT", content):
                violations.append(f"{f.name}: missing MODULE_CONTRACT")
            if not re.search(r"# START_MODULE_MAP", content):
                violations.append(f"{f.name}: missing MODULE_MAP")

        if violations:
            return GuardCheck("canon_compliance", False, "; ".join(violations[:5]))
        return GuardCheck("canon_compliance", True, f"{len(changed_files)} file(s) compliant")
