# ############################################################################
# AI_HEADER: scope_path_canonicalizer
# ROLE: Deterministic pre-coder path canonicalizer — converts architect's
#        Python import paths or short paths into canonical filesystem paths.
# ############################################################################

from __future__ import annotations

import re
from pathlib import Path

from pydantic import BaseModel

from grace_control.core.structured_logger import GraceLogger

_log = GraceLogger("scope_path_canonicalizer")


def _import_to_fs(m: re.Match) -> str:
    """Convert app.services.llm_service → apps/api/app/services/llm_service.py
    or app.services.llm → apps/api/app/services/llm/ (directory)"""
    parts = m.group(1).split(".")
    # Last part is module filename. If import has exactly 3 parts (app.XX.YY)
    # and last part has no underscore, it's likely a package directory.
    if len(parts) >= 2:
        last = parts[-1]
        # app.X.Y with 3 parts: app, X, Y → Y could be package or file
        if len(parts) == 2 and "_" not in last:
            # Package directory: app.services.llm → apps/api/app/services/llm/
            return "apps/api/app/" + "/".join(parts) + "/"
        # File: app.services.llm_service → apps/api/app/services/llm_service.py
        return "apps/api/app/" + "/".join(parts) + ".py"
    # Fallback for unusual patterns
    return "apps/api/app/" + "/".join(parts) + ".py"


# ── Canonicalization rules (ordered: first match wins) ─────────────────
_RULES: list[tuple[re.Pattern, str | callable]] = [
    # apps/api/app/llm/<file>.py → apps/api/app/services/llm/<file>.py
    (re.compile(r"^apps/api/app/llm/(\S+\.py)$"), r"apps/api/app/services/llm/\1"),
    # apps/api/app/llm/ (directory) → apps/api/app/services/llm/
    (re.compile(r"^apps/api/app/llm/$"), "apps/api/app/services/llm/"),

    # app/llm/<file>.py → apps/api/app/services/llm/<file>.py
    (re.compile(r"^app/llm/(\S+\.py)$"), r"apps/api/app/services/llm/\1"),
    # app/llm/ (directory) → apps/api/app/services/llm/
    (re.compile(r"^app/llm/$"), "apps/api/app/services/llm/"),

    # app/services/<rest>.py → apps/api/app/services/<rest>.py
    (re.compile(r"^app/services/(\S+\.py)$"), r"apps/api/app/services/\1"),
    # app/services/<rest>/ → apps/api/app/services/<rest>/
    (re.compile(r"^app/services/(\S+)/$"), r"apps/api/app/services/\1/"),

    # app/<any>.py → apps/api/app/services/<any>.py
    (re.compile(r"^app/(\w[\w/]*\.py)$"), r"apps/api/app/services/\1"),

    # app.<any>.<module> (import path like app.services.llm_service)
    # → apps/api/app/services/<any>/<module>.py
    (re.compile(r"^app\.(\w+(?:\.\w+)+)$"), _import_to_fs),
]


class ScopeCanonicalizationResult(BaseModel):
    changed: bool = False
    plan: dict | None = None
    fixes: list[dict] = []
    warnings: list[dict] = []
    errors: list[dict] = []


class ScopePathCanonicalizer:

    def canonicalize_plan(
        self,
        plan: dict,
        *,
        target_repo_root: Path | None = None,
    ) -> ScopeCanonicalizationResult:
        import copy
        patched = copy.deepcopy(plan)
        result = ScopeCanonicalizationResult(plan=patched)

        waves = patched.get("waves", [])
        for wi, wave in enumerate(waves):
            for pi, pkt in enumerate(wave.get("packets", [])):
                scope = pkt.get("scope", []) or []
                new_scope: list[str] = []
                for si, path in enumerate(scope):
                    canonical = self._canonicalize(path)
                    if canonical != path:
                        result.changed = True
                        result.fixes.append({
                            "code": "CANONICALIZE_SCOPE_PATH",
                            "from": path,
                            "to": canonical,
                            "packet_title": pkt.get("title", f"wave-{wi}-pkt-{pi}"),
                            "scope_index": si,
                        })
                        new_scope.append(canonical)
                    else:
                        new_scope.append(path)
                pkt["scope"] = new_scope

        if result.changed:
            result.plan = patched
            _log.info("scope_canonicalization_applied",
                      fixes=len(result.fixes))

        return result

    def _canonicalize(self, path: str) -> str:
        """Apply rules in order; first match wins."""
        stripped = path.strip()
        for pattern, replacement in _RULES:
            if callable(replacement):
                m = pattern.match(stripped)
                if m:
                    return replacement(m)
            m = pattern.match(stripped)
            if m:
                return pattern.sub(replacement, stripped, count=1)

        # Check if path already looks canonical
        if stripped.startswith("apps/") or stripped.startswith("src/"):
            return stripped

        # If path has `.py` but doesn't match any rule → return as-is
        if stripped.endswith(".py"):
            return stripped

        return stripped
