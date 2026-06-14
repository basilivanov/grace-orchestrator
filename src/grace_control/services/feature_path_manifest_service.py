# ############################################################################
# AI_HEADER: feature_path_manifest_service
# ROLE: Generic FeaturePathManifestBuilder — derives concrete path manifest
#        from KG modules + context paths, without hardcoded service names.
# ############################################################################

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path

from grace_control.core.structured_logger import GraceLogger
from grace_control.services.grace_knowledge_graph_service import (
    GraceKnowledgeGraph,
    GraceModule,
)

_log = GraceLogger("feature_path_manifest")


@dataclass
class FeaturePathManifest:
    source_path: str | None = None
    owning_module_id: str | None = None
    owning_module_paths: list[str] = field(default_factory=list)
    package_path: str | None = None
    example_files: list[str] = field(default_factory=list)
    forbidden_near_misses: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    found: bool = False


class FeaturePathManifestBuilder:

    _SPLIT_KEYWORDS = [
        "split", "break up", "extract", "move", "refactor",
        "decompose", "modularize",
        "разбить", "разделить", "вынести", "распилить", "рефактор",
    ]

    def build(
        self,
        *,
        feature_text: str,
        context_paths: list[str] | None = None,
        kg: GraceKnowledgeGraph | None = None,
    ) -> FeaturePathManifest:
        manifest = FeaturePathManifest()
        all_text = feature_text.lower()
        context_paths = context_paths or []

        is_split = any(kw in all_text for kw in self._SPLIT_KEYWORDS)
        if not is_split:
            return manifest

        # 1. Find existing source file candidate
        source_path = self._find_source_file(all_text, context_paths)
        if not source_path:
            manifest.warnings.append(
                "Cannot derive concrete path manifest: no source file found in feature text or context paths"
            )
            return manifest

        manifest.source_path = source_path

        # 2. Find owning KG module by longest path prefix
        if kg:
            mod, _ = self._find_owning_module(source_path, kg.modules)
            if mod:
                manifest.owning_module_id = mod.id
                manifest.owning_module_paths = mod.paths

        # 3. Derive candidate split package path
        pkg_path = self._derive_package_path(source_path)
        if pkg_path:
            manifest.package_path = pkg_path
            base_dir = pkg_path  # ends with /
            manifest.example_files = [
                f"{base_dir}__init__.py",
                f"{base_dir}example_module.py",
            ]

        # 4. Build forbidden near-misses
        if pkg_path:
            manifest.forbidden_near_misses = self._build_forbidden(manifest)

        manifest.found = True
        return manifest

    def build_prompt_block(self, manifest: FeaturePathManifest) -> str:
        """Build the concrete path manifest section for the Architect prompt."""
        if not manifest.found:
            return ""

        parts: list[str] = []
        parts.append("\n### Concrete path manifest for this feature")

        if manifest.source_path:
            parts.append(f"Existing source:")
            parts.append(f"- {manifest.source_path}")

        if manifest.owning_module_id:
            parts.append(f"Owning KG module:")
            parts.append(f"- {manifest.owning_module_id}")
            if manifest.owning_module_paths:
                for p in manifest.owning_module_paths:
                    parts.append(f"  - {p}")

        if manifest.package_path:
            parts.append(f"Correct new package directory:")
            parts.append(f"- {manifest.package_path}")
            parts.append(f"Correct new file examples:")
            for f in manifest.example_files:
                parts.append(f"- {f}")

        if manifest.forbidden_near_misses:
            parts.append(f"Forbidden near-misses (DO NOT USE):")
            for f in manifest.forbidden_near_misses:
                parts.append(f"- {f}")

        return "\n".join(parts)

    # ── Private helpers ────────────────────────────────────────────

    def _find_source_file(self, feature_text: str, context_paths: list[str]) -> str | None:
        """Find existing source file from feature text or context paths."""
        # First, try to find a .py file mentioned in the feature text
        path_pattern = re.compile(r"(\S+_service\.py|\S+_splitted\.py|\S+\.py)")
        matches = path_pattern.findall(feature_text)
        for m in matches:
            # Accept paths that look like service files
            if m != ".py":
                # Try to resolve to full path
                if "/" not in m:
                    # Feature text may contain just filename; combine with context paths
                    for ctx in context_paths:
                        if m in ctx and ctx.endswith(m):
                            return ctx
                    # If no context matches, use filename with best guess from KG later
                    return m
                return m

        # Fallback: look for _service.py patterns in context paths
        service_files = [c for c in context_paths if c.endswith("_service.py")]
        if service_files:
            return service_files[0]

        return None

    def _find_owning_module(
        self,
        source_path: str,
        modules: list[GraceModule],
    ) -> tuple[GraceModule | None, int]:
        """Find KG module with longest matching prefix."""
        best_mod: GraceModule | None = None
        best_len = 0
        for mod in modules:
            for path in mod.paths:
                prefix = path.rstrip("/")
                if source_path.startswith(prefix) and len(prefix) > best_len:
                    best_mod = mod
                    best_len = len(prefix)
        return best_mod, best_len

    def _derive_package_path(self, source_path: str) -> str | None:
        """Derive split package path from source file path.
        apps/api/app/services/llm_service.py → apps/api/app/services/llm/
        """
        # Handle _service.py: services/llm_service.py → services/llm/
        if source_path.endswith("_service.py"):
            parent = str(Path(source_path).parent)
            stem = Path(source_path).stem  # llm_service
            # Strip trailing _service → llm
            name = stem[:-8] if stem.endswith("_service") else stem
            return parent + "/" + name + "/"

        # For other files, derive only if feature says split
        return None

    def _build_forbidden(self, manifest: FeaturePathManifest) -> list[str]:
        """Build forbidden near-miss paths from the correct package path."""
        forbidden: list[str] = []
        if not manifest.package_path or not manifest.source_path:
            return forbidden

        pkg = manifest.package_path  # e.g. apps/api/app/services/llm/
        pkg_parts = Path(pkg).parts  # ('apps', 'api', 'app', 'services', 'llm')
        name = Path(pkg.rstrip("/")).stem  # llm (last directory name)
        source_name = Path(manifest.source_path).stem  # llm_service

        # Derive wrong sibling: apps/api/app/<name>/
        # From apps/api/app/services/llm/ → wrong = apps/api/app/llm/
        if "services" in pkg:
            idx = pkg_parts.index("services")
            wrong = "/".join(pkg_parts[:idx]) + "/" + name + "/"
            forbidden.append(wrong)

        # app/<name>/
        forbidden.append(f"app/{name}/")

        # app.services.<name> inside packet.scope
        forbidden.append(f"app.services.{name}")

        # Also add app.services.<full_source_stem> (e.g. app.services.llm_service)
        if source_name:
            forbidden.append(f"app.services.{source_name}")

        return forbidden
