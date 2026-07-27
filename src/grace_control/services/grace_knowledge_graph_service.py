# ############################################################################
# AI_HEADER: grace_knowledge_graph_service
# ROLE: Parse a target project's GRACE knowledge graph and extract the relevant
#       module/path map for the Architect prompt.
# ############################################################################

from __future__ import annotations

import re
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Any

from pydantic import BaseModel

from grace_control.core.structured_logger import GraceLogger

_log = GraceLogger("grace_knowledge_graph")

_KNOWLEDGE_GRAPH_CANDIDATES = (
    Path("grace/knowledge-graph.xml"),
    Path("docs/knowledge-graph.xml"),
)


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

    def __init__(self, trace=None, event_logger=None, artifact_store=None):
        self._trace = trace
        self._event_logger = event_logger
        self._artifact_store = artifact_store

    def _emit(self, event: str, **kw):
        if self._event_logger and self._trace:
            self._event_logger.emit(
                trace=self._trace, event=event, stage="knowledge_graph",
                component="GraceKnowledgeGraphService", **kw,
            )

    def load(self, target_repo_root: Path) -> GraceKnowledgeGraph | None:
        """Parse the first supported knowledge-graph path in a target repo."""
        candidate_paths = [target_repo_root / relative for relative in _KNOWLEDGE_GRAPH_CANDIDATES]
        kg_path = next((path for path in candidate_paths if path.is_file()), None)
        if kg_path is None:
            searched = [str(path) for path in candidate_paths]
            _log.info("kg_not_found", paths=searched)
            self._emit(event="knowledge_graph.load_missing", status="missing",
                       payload={"paths": searched})
            return None

        try:
            self._emit(event="knowledge_graph.load_started", status="started",
                       payload={"path": str(kg_path)})
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
            self._emit(event="knowledge_graph.load_completed", status="completed",
                       payload={"path": str(kg_path), "project": project,
                                "module_count": len(modules), "slice_count": len(slices)})
            return kg

        except Exception as e:
            _log.warn("kg_parse_error", error=str(e)[:200])
            self._emit(event="knowledge_graph.load_missing", status="error",
                       payload={"error": str(e)[:200]})
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

        # Persist observability artifacts
        if self._artifact_store and self._trace:
            extract_payload = {
                "project": graph.project,
                "updated": graph.updated,
                "module_count": len(graph.modules),
                "relevant_modules": [m.id for m in extract.relevant_modules],
                "canonical_paths": list(set(p for m in extract.relevant_modules for p in m.paths)),
                "warnings": extract.warnings,
            }
            self._artifact_store.write_json(
                trace=self._trace, stage="knowledge_graph", name="extract.json",
                payload=extract_payload, kind="kg_extract",
            )
        self._emit(event="knowledge_graph.extract_completed", status="completed",
                   payload={"relevant_modules": len(extract.relevant_modules)})

        return extract

    def build_kg_prompt_block(
        self,
        extract: GraceKnowledgeGraphExtract,
        feature_text: str,
        *,
        context_paths: list[str] | None = None,
    ) -> str:
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

        # Build concrete path manifest generically (no hardcoded service names)
        from grace_control.services.feature_path_manifest_service import FeaturePathManifestBuilder
        from grace_control.services.grace_knowledge_graph_service import GraceKnowledgeGraph
        manifest_builder = FeaturePathManifestBuilder(
            trace=self._trace, event_logger=self._event_logger, artifact_store=self._artifact_store,
        )
        manifest = manifest_builder.build(
            feature_text=feature_text,
            context_paths=context_paths or [],
            kg=GraceKnowledgeGraph(
                project="",
                modules=extract.relevant_modules,
                slices=extract.relevant_slices,
            ) if extract.relevant_modules else None,
        )
        manifest_block = manifest_builder.build_prompt_block(manifest)
        if manifest_block:
            parts.append(manifest_block)

        # Persist prompt block artifact
        block_text = "\n".join(parts)
        if self._artifact_store and self._trace:
            self._artifact_store.write_text(
                trace=self._trace, stage="knowledge_graph", name="prompt_block.txt",
                content=block_text, kind="kg_prompt_block",
            )
        self._emit(event="knowledge_graph.prompt_block_built", status="completed",
                   payload={"block_length": len(block_text)})

        return block_text
