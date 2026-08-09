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
            elif code == "E_SCOPE_ACCEPTANCE_IMPOSSIBLE":
                self._try_fix_acceptance_scope(patched, err, report)
            elif code == "E_SCOPE_PATH_NOT_CANONICAL":
                self._try_fix_noncanonical_path(patched, err, report)
            elif code == "E_EVIDENCE_CONTRADICTS_INSTRUCTIONS":
                self._try_fix_evidence_contradiction(patched, err, report)
            elif code == "E_SCOPE_PYTHON_FILE_LIMIT":
                self._try_fix_redundant_broad_sweep(patched, err, report)
            elif code == "E_EVIDENCE_ABSOLUTE_PATTERN":
                self._try_fix_absolute_evidence_pattern(patched, err, report)
            elif code == "E_EVIDENCE_DESCRIPTIVE_PATTERN":
                self._try_fix_descriptive_evidence_pattern(patched, err, report)
            elif code == "E_EVIDENCE_DIFF_HAS_PATTERN":
                self._try_fix_diff_evidence_pattern(patched, err, report)
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

    def _try_fix_diff_evidence_pattern(
        self,
        plan: dict,
        err: dict,
        report: PlanAutofixReport,
    ) -> None:
        """Remove patterns from controller-produced diff evidence."""
        packet_title = err.get("packet_title", "")
        for wave in plan.get("waves", []):
            for packet in wave.get("packets", []) or []:
                if packet.get("title") != packet_title:
                    continue
                for evidence in packet.get("expected_evidence", []) or []:
                    if evidence.get("kind") != "diff" or not evidence.get("artifact_patterns"):
                        continue
                    previous = list(evidence.get("artifact_patterns", []))
                    evidence["artifact_patterns"] = []
                    report.fixes.append({
                        "code": "AUTO_USE_CONTROLLER_DIFF_EVIDENCE",
                        "reason": "E_EVIDENCE_DIFF_HAS_PATTERN",
                        "previous_patterns": previous,
                        "packet_title": packet_title,
                    })
                    return
        report.skipped.append({
            "code": "SKIPPED_DIFF_EVIDENCE_PATTERN_NOT_FOUND",
            "reason": "no patterned diff evidence was found in the packet",
            "error_code": "E_EVIDENCE_DIFF_HAS_PATTERN",
            "packet_title": packet_title,
        })

    def _try_fix_redundant_broad_sweep(
        self,
        plan: dict,
        err: dict,
        report: PlanAutofixReport,
    ) -> None:
        """Leave broad coder sweeps for an architect to split explicitly.

        A plan alone cannot prove that earlier packet scopes cover every file
        below broad directories such as app, scripts, and tests.  Silently
        deleting a cleanup packet can therefore delete required implementation
        work.  The safe deterministic action is no action; architect recovery
        must replace the broad packet with bounded packets or prove it is not
        needed in a newly compiled plan.
        """
        packet_title = err.get("packet_title", "")
        report.skipped.append({
            "code": "SKIPPED_BROAD_SWEEP_REQUIRES_ARCHITECT_SPLIT",
            "reason": "plan metadata cannot prove repository-wide scope is redundant",
            "error_code": "E_SCOPE_PYTHON_FILE_LIMIT",
            "packet_title": packet_title,
        })

    def _try_fix_absolute_evidence_pattern(
        self,
        plan: dict,
        err: dict,
        report: PlanAutofixReport,
    ) -> None:
        """Drop an external absolute path from a coder evidence pattern."""
        packet_title = err.get("packet_title", "")
        details = err.get("details") if isinstance(err.get("details"), dict) else {}
        path = details.get("pattern", "")
        if not path:
            match = re.search(r"artifact pattern '([^']+)'", err.get("message", ""))
            path = match.group(1) if match else ""
        for wave in plan.get("waves", []):
            for packet in wave.get("packets", []) or []:
                if packet.get("title") != packet_title:
                    continue
                for evidence in packet.get("expected_evidence", []) or []:
                    patterns = evidence.get("artifact_patterns", [])
                    if path in patterns:
                        evidence["artifact_patterns"] = [p for p in patterns if p != path]
                        report.fixes.append({
                            "code": "AUTO_DROP_ABSOLUTE_EVIDENCE_PATTERN",
                            "reason": "E_EVIDENCE_ABSOLUTE_PATTERN",
                            "pattern": path,
                            "packet_title": packet_title,
                        })
                        return
        report.skipped.append({
            "code": "SKIPPED_ABSOLUTE_EVIDENCE_PATTERN_NOT_FOUND",
            "reason": "absolute artifact pattern was not found in packet evidence",
            "error_code": "E_EVIDENCE_ABSOLUTE_PATTERN",
            "packet_title": packet_title,
        })

    def _try_fix_descriptive_evidence_pattern(
        self,
        plan: dict,
        err: dict,
        report: PlanAutofixReport,
    ) -> None:
        """Replace a prose evidence label with deterministic command artifacts."""
        packet_title = err.get("packet_title", "")
        details = err.get("details") if isinstance(err.get("details"), dict) else {}
        pattern = details.get("pattern", "")
        evidence_id = details.get("evidence_id", "")
        for wave in plan.get("waves", []):
            for packet in wave.get("packets", []) or []:
                if packet.get("title") != packet_title:
                    continue
                evidence_items = packet.get("expected_evidence", []) or []
                evidence = next(
                    (
                        item for item in evidence_items
                        if isinstance(item, dict)
                        and (not evidence_id or item.get("id") == evidence_id)
                        and pattern in (item.get("artifact_patterns", []) or [])
                    ),
                    None,
                )
                if evidence is None:
                    break
                replacement = self._command_artifact_paths(packet, evidence, pattern)
                if not replacement:
                    path_match = re.match(r"^([^\s]+\.[A-Za-z0-9]+)\s+", pattern)
                    if path_match:
                        replacement = [path_match.group(1)]
                if not replacement:
                    break
                existing = evidence.get("artifact_patterns", []) or []
                evidence["artifact_patterns"] = [
                    value for value in existing if value != pattern
                ] + replacement
                report.fixes.append({
                    "code": "AUTO_CANONICALIZE_EVIDENCE_PATTERN",
                    "reason": "E_EVIDENCE_DESCRIPTIVE_PATTERN",
                    "pattern": pattern,
                    "replacement": replacement,
                    "packet_title": packet_title,
                })
                return
        report.skipped.append({
            "code": "SKIPPED_DESCRIPTIVE_EVIDENCE_PATTERN",
            "reason": "no unambiguous verification command or relative file path",
            "error_code": "E_EVIDENCE_DESCRIPTIVE_PATTERN",
            "packet_title": packet_title,
            "pattern": pattern,
        })

    @staticmethod
    def _command_artifact_paths(packet: dict, evidence: dict, pattern: str) -> list[str]:
        """Map a descriptive stdout label to its verification stdout artifacts."""
        verification = packet.get("verification", {}) or {}
        if not isinstance(verification, dict):
            return []
        lowered = pattern.lower()
        producer = str(evidence.get("producer", "")).lower()
        needle = ""
        if "pytest" in lowered or producer == "pytest":
            needle = "pytest"
        elif "alembic" in lowered or producer == "alembic":
            needle = "alembic"
        elif lowered.endswith(" output"):
            needle = lowered.removesuffix(" output").strip()
        elif lowered.startswith("run: "):
            needle = lowered.removeprefix("run: ").strip()
        path_tokens = re.findall(r"[A-Za-z0-9_.-]+(?:/[A-Za-z0-9_.-]+)+", pattern)
        matches: list[str] = []
        for stage in ("t0", "t1", "t2"):
            commands = verification.get(stage, []) or []
            for index, command in enumerate(commands, start=1):
                if not isinstance(command, str):
                    continue
                command_lower = command.lower()
                if command_lower.strip() == lowered:
                    matched = True
                elif needle:
                    exact_command_label = (
                        lowered.endswith(" output") or lowered.startswith("run: ")
                    )
                    matched = (
                        command_lower.strip() == needle
                        if exact_command_label else needle in command_lower
                    )
                elif path_tokens:
                    matched = any(token in command for token in path_tokens)
                    if matched and "grace_lint.py" in command_lower:
                        matched = False
                else:
                    matched = False
                if matched:
                    matches.append(f"{stage}/cmd_{index:03d}_stdout.log")
        return list(dict.fromkeys(matches))

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
        """Add active reference files outside scope. Falls back to a dedicated
        import-migration packet when no sibling coder packet is found."""
        msg = err.get("message", "")

        # Prefer structured details over regex from message
        details = err.get("details") if isinstance(err.get("details"), dict) else {}
        outside_refs = details.get("outside_refs", [])
        if outside_refs:
            refs = [r for r in outside_refs if self._is_allowed_path(r)]
        else:
            refs = [_clean_path(p) for p in _ERROR_PATH_PATTERN.findall(msg)]
            refs = [r for r in refs if self._is_allowed_path(r)]

        if not refs:
            report.skipped.append({
                "code": "SKIPPED_NO_REFS",
                "reason": "no reference files found in error message",
                "error_code": "E_IMPORT_MIGRATION_SCOPE_INCOMPLETE",
            })
            return

        waves = plan.get("waves", [])

        # Try to find an existing coder packet with sibling scope files
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

        if best_packet is not None:
            wi, pi = best_packet
            pkt = waves[wi]["packets"][pi]
            scope = pkt.get("scope", []) or []
            new_refs = [r for r in refs if r not in scope
                        and not self._is_table(plan, "frozen_scope", r)]
            if not new_refs:
                return
            if len(scope) + len(new_refs) > MAX_AUTO_SCOPE_FILES:
                # Take first batch
                new_refs = new_refs[:max(0, MAX_AUTO_SCOPE_FILES - len(scope))]
            pkt["scope"] = scope + new_refs
            report.fixes.append({
                "code": "AUTO_ADD_IMPORT_REFERENCE_FILES",
                "reason": "E_IMPORT_MIGRATION_SCOPE_INCOMPLETE",
                "files": new_refs,
                "packet_title": pkt.get("title", f"wave-{wi}-pkt-{pi}"),
            })
            return

        # No sibling packet — create a dedicated import-migration packet
        new_refs = [r for r in refs
                    if not self._is_table(plan, "frozen_scope", r)]
        if not new_refs:
            report.skipped.append({
                "code": "SKIPPED_ALL_REFS_FROZEN",
                "reason": "all reference files are in frozen_scope",
                "error_code": "E_IMPORT_MIGRATION_SCOPE_INCOMPLETE",
            })
            return

        # Collect frozen_scope from existing coder packets
        existing_frozen: set[str] = set()
        for w in waves:
            for p in w.get("packets", []):
                if p.get("role") == "coder":
                    for f in (p.get("frozen_scope") or []):
                        existing_frozen.add(f)

        # Collect existing verification from first existing coder packet as template
        v0 = {"t0": [], "t1": [], "t2": []}
        depends_on: list[str] = []
        for w in waves:
            for p in w.get("packets", []):
                if p.get("role") == "coder":
                    v0 = p.get("verification", v0) or v0
                    depends_on.append(p.get("title", ""))
                    break
            if depends_on:
                break

        # Find or create a wave to put the migration packet in
        target_wave = waves[-1] if waves else None
        if target_wave is None:
            target_wave = {"title": "Migration", "packets": []}
            waves.append(target_wave)

        migration_pkt = {
            "title": "Migrate imports from old LLM service",
            "role": "coder",
            "scope": new_refs,
            "frozen_scope": sorted(existing_frozen) if existing_frozen else [],
            "depends_on": depends_on,
            "conflict_keys": [],
            "acceptance_profile": "NORMAL",
            "coder_instructions": [
                "Update active consumers to import from the new package structure "
                "or keep the old module as a compatibility shim. Do NOT change behavior."
            ],
            "acceptance_criteria": [
                "All consumer files updated to use correct import paths",
            ],
            "verification": {"t0": [], "t1": [], "t2": []},
        }
        target_wave.setdefault("packets", [])
        target_wave["packets"].append(migration_pkt)
        report.fixes.append({
            "code": "AUTO_CREATE_IMPORT_MIGRATION_PACKET",
            "reason": "E_IMPORT_MIGRATION_SCOPE_INCOMPLETE",
            "files": new_refs,
            "packet_title": migration_pkt["title"],
        })

    def _try_fix_acceptance_scope(
        self,
        plan: dict,
        err: dict,
        report: PlanAutofixReport,
    ) -> None:
        """T1/T2 runs test files outside write scope — add tests to scope."""
        msg = err.get("message", "")
        # Extract test file paths from error message: {'test_x.py', 'test_y.py'}
        import re as _re
        test_match = _re.search(r"tests \{([^}]+)\}", msg)
        if not test_match:
            report.skipped.append({
                "code": "SKIPPED_NO_TEST_REFS",
                "reason": "no test file set found in error message",
                "error_code": "E_SCOPE_ACCEPTANCE_IMPOSSIBLE",
            })
            return
        test_paths_str = test_match.group(1)
        test_files = [
            t.strip().strip("'").strip('"')
            for t in test_paths_str.split(",")
            if t.strip()
        ]
        if not test_files:
            return

        waves = plan.get("waves", [])
        # Find the coder packet that the error is about (from packet_title)
        packet_title = err.get("packet_title", "")
        target_packet = None
        for w in waves:
            for p in w.get("packets", []):
                if p.get("title") == packet_title:
                    target_packet = p
                    break
            if target_packet:
                break

        if target_packet is None:
            report.skipped.append({
                "code": "SKIPPED_PACKET_NOT_FOUND",
                "reason": f"packet '{packet_title}' not found in plan",
                "error_code": "E_SCOPE_ACCEPTANCE_IMPOSSIBLE",
            })
            return

        scope = target_packet.get("scope", []) or []
        new_tests = [t for t in test_files if t not in scope]
        if not new_tests:
            return

        target_packet["scope"] = scope + new_tests
        report.fixes.append({
            "code": "AUTO_ADD_TEST_FILES_TO_SCOPE",
            "reason": "E_SCOPE_ACCEPTANCE_IMPOSSIBLE",
            "files": new_tests,
            "packet_title": packet_title,
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
        """Replace non-canonical scope path with full filesystem path.
        Always runs ScopePathCanonicalizer on the bad path instead of
        trusting error message suggestions."""
        msg = err.get("message", "")
        import re as _re
        path_match = _re.search(r"scope path '([^']+)'", msg)
        if not path_match:
            report.skipped.append({
                "code": "SKIPPED_NO_PATH_FOUND",
                "reason": "no path found in error message",
                "error_code": "E_SCOPE_PATH_NOT_CANONICAL",
            })
            return

        bad_path = path_match.group(1)

        # Always use canonicalizer — don't trust error message suggestion
        from grace_control.services.scope_path_canonicalizer import ScopePathCanonicalizer
        canonicalizer = ScopePathCanonicalizer()
        suggested = canonicalizer._canonicalize(bad_path)
        if suggested == bad_path or suggested == canonicalizer._canonicalize(suggested):
            # Path didn't change or is already canonical — try inline canonicalize
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

    def _try_fix_evidence_contradiction(
        self,
        plan: dict,
        err: dict,
        report: PlanAutofixReport,
    ) -> None:
        """Change expectation from 'exists' to 'deleted' when instructions
        explicitly remove the same file path.

        The compiler must provide a positive explicit-target marker.  A loose
        keyword match is not enough to make deletion safe: instructions often
        say to remove stale content from a file that must continue to exist.
        """
        details = err.get("details") if isinstance(err.get("details"), dict) else {}
        file_path = details.get("file", "")
        evidence_id = details.get("evidence_id", "")
        suggested = details.get("suggested_fix", "deleted")

        if details.get("remove_target_explicit") is not True:
            report.skipped.append({
                "code": "SKIPPED_AMBIGUOUS_EVIDENCE_DELETION",
                "reason": "compiler did not prove that the evidence path is the deletion target",
                "error_code": "E_EVIDENCE_CONTRADICTS_INSTRUCTIONS",
                "evidence_id": evidence_id,
                "file": file_path,
            })
            return

        if not file_path or not evidence_id:
            # Fall back to parsing error message
            import re as _re
            msg = err.get("message", "")
            file_m = _re.search(r"expects '([^']+)' to exist", msg)
            if file_m:
                file_path = file_m.group(1)
            id_m = _re.search(r"Evidence '([^']+)'", msg)
            if id_m:
                evidence_id = id_m.group(1)

        if not file_path or not evidence_id:
            report.skipped.append({
                "code": "SKIPPED_NO_EVIDENCE_REF",
                "reason": "no evidence_id or file_path in error details or message",
                "error_code": "E_EVIDENCE_CONTRADICTS_INSTRUCTIONS",
            })
            return

        # Find the packet containing this evidence and fix it
        waves = plan.get("waves", [])
        fixed = False
        for wi, wave in enumerate(waves):
            for pi, pkt in enumerate(wave.get("packets", [])):
                evidence = pkt.get("expected_evidence", [])
                if not isinstance(evidence, list):
                    continue
                for ei, ev in enumerate(evidence):
                    if not isinstance(ev, dict):
                        continue
                    if ev.get("id") == evidence_id:
                        patterns = ev.get("artifact_patterns", ev.get("pattern", []))
                        if isinstance(patterns, str):
                            patterns = [patterns]
                        if file_path in patterns:
                            ev["expectation"] = suggested
                            pkt["expected_evidence"][ei] = ev
                            fixed = True
                            report.fixes.append({
                                "code": "AUTO_SET_EVIDENCE_EXPECTATION",
                                "reason": "E_EVIDENCE_CONTRADICTS_INSTRUCTIONS",
                                "evidence_id": evidence_id,
                                "file": file_path,
                                "packet_title": pkt.get("title", f"wave-{wi}-pkt-{pi}"),
                                "from": "exists",
                                "to": suggested,
                            })
                            break
                if fixed:
                    break
            if fixed:
                break

        if not fixed:
            report.skipped.append({
                "code": "SKIPPED_EVIDENCE_NOT_FOUND",
                "reason": f"evidence '{evidence_id}' with file '{file_path}' not found in plan",
                "error_code": "E_EVIDENCE_CONTRADICTS_INSTRUCTIONS",
                "evidence_id": evidence_id,
                "file": file_path,
            })
