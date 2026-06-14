# ############################################################################
# AI_HEADER: grace_knowledge_graph_service
# ROLE: Parse grace/knowledge-graph.xml and extract relevant module/path map
#        for the Architect prompt.
# ############################################################################

from __future__ import annotations

import re
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Any

from pydantic import BaseModel

from grace_control.core.structured_logger import GraceLogger

_log = GraceLogger("grace_knowledge_graph")


class GraceModule(BaseModel):
    id: str
    slice: str | None = None
    layer: str | None = None
    paths: list[str] = []
    owns: str | None = None


class GraceSlice(BaseModel):
    id: str
    module: str | None = None
    priority: str | None = None
    paths: list[str] = []
    owns: str | None = None


class GraceKnowledgeGraph(BaseModel):
    project: str
    updated: str | None = None
    modules: list[GraceModule] = []
    slices: list[GraceSlice] = []


class GraceKnowledgeGraphExtract(BaseModel):
    loaded: bool = False
    relevant_modules: list[GraceModule] = []
    relevant_slices: list[GraceSlice] = []
    warnings: list[str] = []


class GraceKnowledgeGraphService:

    def load(self, target_repo_root: Path) -> GraceKnowledgeGraph | None:
        """Parse grace/knowledge-graph.xml from target repo."""
        kg_path = target_repo_root / "grace" / "knowledge-graph.xml"
        if not kg_path.exists():
            _log.info("kg_not_found", path=str(kg_path))
            return None

        try:
            tree = ET.parse(kg_path)
            root = tree.getroot()
            project = root.get("project", "")
            updated = root.get("updated", "")

            modules: list[GraceModule] = []
            for elem in root.iter("module"):
                mid = elem.get("id", "")
                paths = [p.strip() for p in (elem.get("path", "").split(",")) if p.strip()]
                modules.append(GraceModule(
                    id=mid,
                    slice=elem.get("slice"),
                    layer=elem.get("layer"),
                    paths=paths,
                    owns=elem.get("owns"),
                ))

            slices: list[GraceSlice] = []
            for elem in root.iter("slice"):
                sid = elem.get("id", "")
                owns_elem = elem.find("owns")
                paths_elem = elem.find("paths")
                slice_paths = [p.strip() for p in (paths_elem.text or "").split(";") if p.strip()] if paths_elem is not None else []
                slices.append(GraceSlice(
                    id=sid,
                    module=elem.get("module"),
                    priority=elem.get("priority"),
                    paths=slice_paths,
                    owns=owns_elem.text.strip() if owns_elem is not None and owns_elem.text else None,
                ))

            kg = GraceKnowledgeGraph(project=project, updated=updated, modules=modules, slices=slices)
            _log.info("kg_loaded", project=project, modules=len(modules), slices=len(slices))
            return kg

        except Exception as e:
            _log.warn("kg_parse_error", error=str(e)[:200])
            return None

    def extract_relevant_modules(
        self,
        graph: GraceKnowledgeGraph,
        *,
        feature_text: str = "",
        context_paths: list[str] | None = None,
    ) -> GraceKnowledgeGraphExtract:
        """Select relevant modules by feature keywords and context paths."""
        extract = GraceKnowledgeGraphExtract(loaded=True)
        all_text = feature_text.lower()
        context_paths = context_paths or []

        # Score modules by keyword match
        for mod in graph.modules:
            score = 0
            # Check feature text for keywords
            mod_keywords = mod.id.lower().replace("m-", "").split("-")
            for kw in mod_keywords:
                if kw in all_text and len(kw) > 2:
                    score += 2

            # Check context paths against module paths
            for kg_path in mod.paths:
                for ctx_p in context_paths:
                    if ctx_p.startswith(kg_path) and len(ctx_p) > 0:
                        score += 3

            # Check mod.owns text
            if mod.owns:
                for kw in mod_keywords:
                    if kw in mod.owns.lower() and len(kw) > 2:
                        score += 1

            if score > 2:
                extract.relevant_modules.append(mod)

        # If no modules matched but feature mentions service/backend, add M-BACKEND-SERVICES
        if not extract.relevant_modules:
            for mod in graph.modules:
                if mod.id == "M-BACKEND-SERVICES" and ("service" in all_text or "backend" in all_text):
                    extract.relevant_modules.append(mod)
                    break

        for mod in extract.relevant_modules:
            _log.info("kg_relevant_module", module_id=mod.id, paths=mod.paths)

        return extract

    def build_kg_prompt_block(self, extract: GraceKnowledgeGraphExtract, feature_text: str) -> str:
        """Build the GRACE canon block for the Architect prompt."""
        if not extract.loaded or not extract.relevant_modules:
            return ""

        parts: list[str] = []
        parts.append("\n## GRACE CANON — Knowledge Graph Extract")
        parts.append("The following module/path map is authoritative for this target repo.")
        parts.append("Use it before inventing or inferring paths.")

        for mod in extract.relevant_modules:
            parts.append(f"\n- {mod.id}")
            if mod.slice:
                parts.append(f"  slice: {mod.slice}")
            if mod.layer:
                parts.append(f"  layer: {mod.layer}")
            if mod.owns:
                parts.append(f"  owns: {mod.owns}")
            if mod.paths:
                parts.append(f"  canonical paths:")
                for p in mod.paths:
                    parts.append(f"    - {p}")

        # For LLM split features, add concrete manifest
        if ("llm" in feature_text.lower() and "service" in feature_text.lower()):
            parts.append("\n### Concrete path manifest for this feature")
            parts.append("Existing source:")
            parts.append("- apps/api/app/services/llm_service.py")
            parts.append("Correct new package directory:")
            parts.append("- apps/api/app/services/llm/")
            parts.append("Correct new file examples:")
            parts.append("- apps/api/app/services/llm/__init__.py")
            parts.append("- apps/api/app/services/llm/russian.py")
            parts.append("- apps/api/app/services/llm/client.py")
            parts.append("Forbidden near-misses (DO NOT USE):")
            parts.append("- apps/api/app/llm/")
            parts.append("- app/llm/")
            parts.append("- app.services.llm inside packet.scope")

        return "\n".join(parts)
