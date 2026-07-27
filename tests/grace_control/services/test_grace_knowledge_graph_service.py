"""Tests for GraceKnowledgeGraphService."""
from __future__ import annotations

from pathlib import Path

from grace_control.services.grace_knowledge_graph_service import (
    GraceKnowledgeGraphService,
    GraceModule,
    GraceSlice,
    GraceKnowledgeGraph,
)


SAMPLE_KG = """<?xml version="1.0" encoding="UTF-8"?>
<knowledge-graph project="solarsage-astro" updated="2026-06-11">
  <slice-registry>
    <slice id="SLICE-BACKEND-SERVICES" priority="P0" module="M-BACKEND-SERVICES">
      <owns>Backend business logic and service orchestration.</owns>
      <paths>apps/api/app/services/; apps/api/app/core/</paths>
    </slice>
    <slice id="SLICE-BACKEND-API-ROUTERS" priority="P0" module="M-BACKEND-API">
      <owns>FastAPI routers and endpoint bindings.</owns>
      <paths>apps/api/app/api/; apps/api/app/schemas/</paths>
    </slice>
  </slice-registry>
  <modules>
    <module id="M-BACKEND-SERVICES" slice="SLICE-BACKEND-SERVICES" layer="backend" path="apps/api/app/services/, apps/api/app/core/" />
    <module id="M-BACKEND-API" slice="SLICE-BACKEND-API-ROUTERS" layer="backend" path="apps/api/app/api/, apps/api/app/schemas/" />
  </modules>
</knowledge-graph>"""


class TestKnowledgeGraphLoad:

    def test_loads_grace_knowledge_graph_xml(self, tmp_path):
        kg_path = tmp_path / "grace"
        kg_path.mkdir()
        (kg_path / "knowledge-graph.xml").write_text(SAMPLE_KG)
        svc = GraceKnowledgeGraphService()
        kg = svc.load(tmp_path)
        assert kg is not None
        assert kg.project == "solarsage-astro"
        assert len(kg.modules) == 2
        assert kg.modules[0].id == "M-BACKEND-SERVICES"

    def test_loads_docs_knowledge_graph_xml_when_grace_path_is_absent(self, tmp_path):
        docs_path = tmp_path / "docs"
        docs_path.mkdir()
        (docs_path / "knowledge-graph.xml").write_text(SAMPLE_KG)

        kg = GraceKnowledgeGraphService().load(tmp_path)

        assert kg is not None
        assert kg.project == "solarsage-astro"
        assert [module.id for module in kg.modules] == [
            "M-BACKEND-SERVICES",
            "M-BACKEND-API",
        ]

    def test_grace_knowledge_graph_path_precedes_docs_fallback(self, tmp_path):
        grace_path = tmp_path / "grace"
        docs_path = tmp_path / "docs"
        grace_path.mkdir()
        docs_path.mkdir()
        (grace_path / "knowledge-graph.xml").write_text(
            SAMPLE_KG.replace('project="solarsage-astro"', 'project="grace-layout"')
        )
        (docs_path / "knowledge-graph.xml").write_text(
            SAMPLE_KG.replace('project="solarsage-astro"', 'project="docs-layout"')
        )

        kg = GraceKnowledgeGraphService().load(tmp_path)

        assert kg is not None
        assert kg.project == "grace-layout"

    def test_extracts_backend_services_module_from_kg(self, tmp_path):
        kg_path = tmp_path / "grace"
        kg_path.mkdir()
        (kg_path / "knowledge-graph.xml").write_text(SAMPLE_KG)
        svc = GraceKnowledgeGraphService()
        kg = svc.load(tmp_path)
        assert kg is not None
        extract = svc.extract_relevant_modules(kg, feature_text="Split llm_service.py into services package")
        assert len(extract.relevant_modules) >= 1
        mids = [m.id for m in extract.relevant_modules]
        assert "M-BACKEND-SERVICES" in mids

    def test_kg_missing_falls_back_with_warning(self, tmp_path):
        svc = GraceKnowledgeGraphService()
        kg = svc.load(tmp_path)
        assert kg is None

    def test_extract_builds_prompt_block(self, tmp_path):
        kg_path = tmp_path / "grace"
        kg_path.mkdir()
        (kg_path / "knowledge-graph.xml").write_text(SAMPLE_KG)
        svc = GraceKnowledgeGraphService()
        kg = svc.load(tmp_path)
        extract = svc.extract_relevant_modules(kg, feature_text="Split llm_service.py into services package")
        block = svc.build_kg_prompt_block(extract, "Split llm_service.py into llm package")
        assert block
        assert "GRACE CANON" in block
        assert "M-BACKEND-SERVICES" in block
        assert "apps/api/app/services/" in block

    def test_prompt_block_includes_forbidden_near_misses(self, tmp_path):
        kg_path = tmp_path / "grace"
        kg_path.mkdir()
        (kg_path / "knowledge-graph.xml").write_text(SAMPLE_KG)
        svc = GraceKnowledgeGraphService()
        kg = svc.load(tmp_path)
        extract = svc.extract_relevant_modules(kg, feature_text="Split llm_service.py into llm package")
        block = svc.build_kg_prompt_block(
            extract, "Split apps/api/app/services/llm_service.py into llm package",
            context_paths=["apps/api/app/services/llm_service.py"],
        )
        assert "Forbidden near-misses" in block
        assert "apps/api/app/llm/" in block

    def test_architect_prompt_includes_relevant_kg_module_paths(self, tmp_path):
        """M-BACKEND-SERVICES must include apps/api/app/services/ and core/."""
        kg_path = tmp_path / "grace"
        kg_path.mkdir()
        (kg_path / "knowledge-graph.xml").write_text(SAMPLE_KG)
        svc = GraceKnowledgeGraphService()
        kg = svc.load(tmp_path)
        extract = svc.extract_relevant_modules(kg, feature_text="Split llm_service.py")
        for mod in extract.relevant_modules:
            if mod.id == "M-BACKEND-SERVICES":
                assert any("apps/api/app/services/" in p for p in mod.paths)
                assert any("apps/api/app/core/" in p for p in mod.paths)
                return
        assert False, "M-BACKEND-SERVICES not found in relevant modules"

    def test_empty_feature_text_returns_empty_extract(self, tmp_path):
        kg_path = tmp_path / "grace"
        kg_path.mkdir()
        (kg_path / "knowledge-graph.xml").write_text(SAMPLE_KG)
        svc = GraceKnowledgeGraphService()
        kg = svc.load(tmp_path)
        extract = svc.extract_relevant_modules(kg, feature_text="")
        assert len(extract.relevant_modules) == 0
