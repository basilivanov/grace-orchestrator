# ############################################################################
# AI_HEADER: plan_autofixer
# ROLE: SafePlanAutofixer — deterministic plan patching for known compiler
#        errors. Runs before architect repair to avoid unnecessary LLM calls.
# ############################################################################

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path

from grace_control.core.structured_logger import GraceLogger

_log = GraceLogger("plan_autofixer")

MAX_AUTO_SCOPE_FILES = 30

ALLOWED_DIRS = ("apps/", "src/", "packages/", "tests/", "scripts/")

_ERROR_PATH_PATTERN = re.compile(r"(\S+\.py)")


def _clean_path(p: str) -> str:
    """Strip quotes, brackets, and leading artifacts from an extracted path."""
    p = p.strip()
    # Remove common compiler message artifacts: ['  ",  '  preceding the path
    for ch in ("['", '["', "['\\", '["\\', "', '", "\", '", "']", '"]', "'", '"', "[", "]", "\\"):
        p = p.replace(ch, "")
    return p.strip()


@dataclass
class PlanAutofixReport:
    applied: bool = False
    fixes: list[dict] = field(default_factory=list)
    skipped: list[dict] = field(default_factory=list)
    patched_plan: dict | None = None


class SafePlanAutofixer:

    def apply(
        self,
        plan: dict,
        compiler_errors: list[dict],
    ) -> PlanAutofixReport:
        report = PlanAutofixReport()
        patched = self._deep_copy_plan(plan)

        for err in compiler_errors:
            code = err.get("code", "")
            msg = err.get("message", "")

            if code == "E_SOURCE_SPLIT_ORIGIN_MISSING":
                self._try_fix_source_split(patched, err, report)
            elif code == "E_IMPORT_MIGRATION_SCOPE_INCOMPLETE":
                self._try_fix_import_scope(patched, err, report)
            elif code == "E_SCOPE_PATH_NOT_CANONICAL":
                self._try_fix_noncanonical_path(patched, err, report)
            else:
                report.skipped.append({
                    "code": "SKIPPED_UNSUPPORTED_ERROR",
                    "reason": f"no autofix for {code}",
                    "error_code": code,
                })

        if report.fixes:
            report.applied = True
            report.patched_plan = patched
            _log.info("autofix_applied", fixes=len(report.fixes),
                      skipped=len(report.skipped))
        else:
            _log.info("autofix_noop", skipped=len(report.skipped))

        return report

    # ── Helpers ────────────────────────────────────────────────────

    def _try_fix_source_split(
        self,
        plan: dict,
        err: dict,
        report: PlanAutofixReport,
    ) -> None:
        """Add missing source file to the nearest coder packet's scope."""
        msg = err.get("message", "")
        paths = [_clean_path(p) for p in _ERROR_PATH_PATTERN.findall(msg)]
        paths = [p for p in paths if self._is_allowed_path(p)]
        if not paths:
            report.skipped.append({
                "code": "SKIPPED_NO_PATH",
                "reason": "no exact .py path found in error message",
                "error_code": "E_SOURCE_SPLIT_ORIGIN_MISSING",
            })
            return

        target = paths[0]
        # Find nearest packet: one that already has sibling files in the same dir
        waves = plan.get("waves", [])
        best = None
        best_packet = None
        best_wave = None

        for wi, wave in enumerate(waves):
            for pi, pkt in enumerate(wave.get("packets", [])):
                scope = pkt.get("scope", []) or []
                role = pkt.get("role", "coder")
                if role != "coder":
                    continue
                if target in scope:
                    continue
                for s in scope:
                    score = self._path_similarity(s, target)
                    if score > (best or 0):
                        best = score
                        best_packet = (wi, pi)
                        best_wave = wave
                        current_scope = scope

        if best_packet is None:
            report.skipped.append({
                "code": "SKIPPED_NO_NEAREST_PACKET",
                "reason": "no coder packet found with scope containing sibling files",
                "error_code": "E_SOURCE_SPLIT_ORIGIN_MISSING",
                "file": target,
            })
            return

        wi, pi = best_packet
        pkt = waves[wi]["packets"][pi]
        scope = pkt.get("scope", []) or []

        # Safety checks
        if target in scope:
            return
        if not self._is_allowed_path(target):
            report.skipped.append({
                "code": "SKIPPED_PATH_OUTSIDE_ALLOWED",
                "reason": f"file {target} not under allowed dirs",
                "error_code": "E_SOURCE_SPLIT_ORIGIN_MISSING",
                "file": target,
            })
            return
        if len(scope) >= MAX_AUTO_SCOPE_FILES:
            report.skipped.append({
                "code": "SKIPPED_SCOPE_EXCEEDS_LIMIT",
                "reason": f"scope would exceed {MAX_AUTO_SCOPE_FILES} files",
                "error_code": "E_SOURCE_SPLIT_ORIGIN_MISSING",
                "file": target,
            })
            return
        if self._is_table(plan, "frozen_scope", target):
            report.skipped.append({
                "code": "SKIPPED_FILE_IN_FROZEN_SCOPE",
                "reason": f"file {target} is in frozen_scope",
                "error_code": "E_SOURCE_SPLIT_ORIGIN_MISSING",
                "file": target,
            })
            return

        # Apply
        pkt["scope"] = scope + [target]
        report.fixes.append({
            "code": "AUTO_ADD_MISSING_SOURCE_FILE",
            "reason": "E_SOURCE_SPLIT_ORIGIN_MISSING",
            "file": target,
            "packet_title": pkt.get("title", f"wave-{wi}-pkt-{pi}"),
        })

    def _try_fix_import_scope(
        self,
        plan: dict,
        err: dict,
        report: PlanAutofixReport,
    ) -> None:
        """Add active reference files outside scope to nearest packet."""
        msg = err.get("message", "")
        refs = [_clean_path(p) for p in _ERROR_PATH_PATTERN.findall(msg)]
        # Reject paths that aren't under allowed dirs
        allowed = [r for r in refs if self._is_allowed_path(r)]
        if not refs:
            report.skipped.append({
                "code": "SKIPPED_NO_REFS",
                "reason": "no reference files found in error message",
                "error_code": "E_IMPORT_MIGRATION_SCOPE_INCOMPLETE",
            })
            return

        # Filter to allowed dirs only
        allowed = [r for r in refs if self._is_allowed_path(r)]
        if len(refs) != len(allowed):
            report.skipped.append({
                "code": "SKIPPED_REF_OUTSIDE_ALLOWED",
                "reason": f"{len(refs) - len(allowed)} refs outside allowed dirs",
                "file": refs[0] if refs else None,
            })
            refs = allowed

        if len(refs) > 8:
            report.skipped.append({
                "code": "SKIPPED_TOO_MANY_REFS",
                "reason": f"{len(refs)} refs exceeds limit of 8",
                "error_code": "E_IMPORT_MIGRATION_SCOPE_INCOMPLETE",
                "file": refs[0] if refs else None,
            })
            return

        # Find nearest coder packet
        waves = plan.get("waves", [])
        best_packet = None
        for wi, wave in enumerate(waves):
            for pi, pkt in enumerate(wave.get("packets", [])):
                if pkt.get("role", "coder") != "coder":
                    continue
                scope = pkt.get("scope", []) or []
                if any(r in scope for r in refs):
                    continue
                if self._has_sibling_imports(scope, refs):
                    best_packet = (wi, pi)

        if best_packet is None:
            report.skipped.append({
                "code": "SKIPPED_NO_PACKET_FOR_REFS",
                "reason": "no packet found with sibling import files",
                "error_code": "E_IMPORT_MIGRATION_SCOPE_INCOMPLETE",
            })
            return

        wi, pi = best_packet
        pkt = waves[wi]["packets"][pi]
        scope = pkt.get("scope", []) or []

        new_refs = [r for r in refs if r not in scope and not self._is_table(plan, "frozen_scope", r)]
        if not new_refs:
            return
        if len(scope) + len(new_refs) > MAX_AUTO_SCOPE_FILES:
            report.skipped.append({
                "code": "SKIPPED_SCOPE_EXCEEDS_LIMIT",
                "reason": "adding refs would exceed MAX_AUTO_SCOPE_FILES",
            })
            return

        pkt["scope"] = scope + new_refs
        report.fixes.append({
            "code": "AUTO_ADD_IMPORT_REFERENCE_FILES",
            "reason": "E_IMPORT_MIGRATION_SCOPE_INCOMPLETE",
            "files": new_refs,
            "packet_title": pkt.get("title", f"wave-{wi}-pkt-{pi}"),
        })

    # ── Utility methods ────────────────────────────────────────────

    def _deep_copy_plan(self, plan: dict) -> dict:
        import copy
        return copy.deepcopy(plan)

    def _path_similarity(self, a: str, b: str) -> float:
        """Simple heuristic: how related are two paths.
        Higher score = more likely same package/refactor scope."""
        ap = Path(a)
        bp = Path(b)
        if not ap.suffix == ".py" or not bp.suffix == ".py":
            return 0.0
        # Same parent directory
        if ap.parent == bp.parent:
            return 1.0
        # One is in a subdir of the other's parent
        # e.g. llm/russian.py and llm_service.py → llm/ is sub of llm_service.py.parent
        a_parent = ap.parent.as_posix()
        b_parent = bp.parent.as_posix()
        if a_parent.startswith(b_parent) or b_parent.startswith(a_parent):
            return 0.85
        # Same grandparent
        if ap.parent.parent == bp.parent.parent:
            return 0.8
        # One is parent of the other
        if ap.parent == bp or bp.parent == ap:
            return 0.7
        # Same repo area (apps/api/app/services/...)
        if a.startswith("apps/api") and b.startswith("apps/api"):
            return 0.3
        return 0.0

    def _has_sibling_imports(self, scope: list[str], refs: list[str]) -> bool:
        """Check if scope has files in the same area as refs."""
        for s in scope:
            for r in refs:
                if self._path_similarity(s, r) > 0.5:
                    return True
        return False

    def _is_allowed_path(self, path: str) -> bool:
        return any(path.startswith(d) for d in ALLOWED_DIRS)

    def _is_table(self, plan: dict, key: str, path: str) -> bool:
        frozen = plan.get("constraints", {}).get(key, []) or []
        return path in frozen

    def _try_fix_noncanonical_path(
        self,
        plan: dict,
        err: dict,
        report: PlanAutofixReport,
    ) -> None:
        """Replace non-canonical scope path with full filesystem path."""
        msg = err.get("message", "")
        import re as _re
        path_match = _re.search(r"scope path '([^']+)'", msg)
        suggestion_match = _re.search(r"replace '([^']+)' with the full", msg)
        if not path_match:
            report.skipped.append({
                "code": "SKIPPED_NO_PATH_FOUND",
                "reason": "no path found in error message",
                "error_code": "E_SCOPE_PATH_NOT_CANONICAL",
            })
            return

        bad_path = path_match.group(1)
        suggested = suggestion_match.group(1) if suggestion_match else None

        if not suggested:
            # Try canonicalizing inline
            from grace_control.services.scope_path_canonicalizer import ScopePathCanonicalizer
            suggested = ScopePathCanonicalizer()._canonicalize(bad_path)
            if suggested == bad_path:
                report.skipped.append({
                    "code": "SKIPPED_NO_SUGGESTION",
                    "reason": f"cannot determine canonical path for '{bad_path}'",
                    "error_code": "E_SCOPE_PATH_NOT_CANONICAL",
                    "file": bad_path,
                })
                return

        # Find the packet containing this path and replace it
        waves = plan.get("waves", [])
        replaced = False
        for wi, wave in enumerate(waves):
            for pi, pkt in enumerate(wave.get("packets", [])):
                scope = pkt.get("scope", []) or []
                if bad_path in scope:
                    idx = scope.index(bad_path)
                    scope[idx] = suggested
                    replaced = True
                    pkt["scope"] = scope
                    report.fixes.append({
                        "code": "AUTO_CANONICALIZE_SCOPE_PATH",
                        "from": bad_path,
                        "to": suggested,
                        "reason": "E_SCOPE_PATH_NOT_CANONICAL",
                        "packet_title": pkt.get("title", f"wave-{wi}-pkt-{pi}"),
                    })
                    break
            if replaced:
                break

        if not replaced:
            report.skipped.append({
                "code": "SKIPPED_PATH_NOT_IN_SCOPE",
                "reason": f"path '{bad_path}' not found in any packet scope",
                "error_code": "E_SCOPE_PATH_NOT_CANONICAL",
                "file": bad_path,
            })
