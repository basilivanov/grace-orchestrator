"""Tests for FeaturePathManifestBuilder — generic path manifest without hardcoded names."""
from __future__ import annotations

import pytest
from pathlib import Path

from grace_control.services.feature_path_manifest_service import (
    FeaturePathManifestBuilder,
    FeaturePathManifest,
)
from grace_control.services.grace_knowledge_graph_service import (
    GraceKnowledgeGraph,
    GraceModule,
    GraceSlice,
)


def _kg_with_backend_services() -> GraceKnowledgeGraph:
    return GraceKnowledgeGraph(
        project="solarsage-astro",
        modules=[
            GraceModule(
                id="M-BACKEND-SERVICES",
                slice="SLICE-BACKEND-SERVICES",
                layer="backend",
                paths=["apps/api/app/services/", "apps/api/app/core/"],
                owns="Backend business logic and service orchestration.",
            ),
            GraceModule(
                id="M-BACKEND-API",
                slice="SLICE-BACKEND-API-ROUTERS",
                layer="backend",
                paths=["apps/api/app/api/", "apps/api/app/schemas/"],
            ),
        ],
    )


class TestManifestForLLMService:

    def test_manifest_for_llm_service_split_is_derived_not_hardcoded(self):
        """No 'llm'-specific branches exist. The path is derived generically."""
        builder = FeaturePathManifestBuilder()
        manifest = builder.build(
            feature_text="Split apps/api/app/services/llm_service.py into llm package",
            context_paths=["apps/api/app/services/llm_service.py"],
        )
        assert manifest.found
        assert manifest.source_path == "apps/api/app/services/llm_service.py"
        assert manifest.package_path == "apps/api/app/services/llm/"

    def test_manifest_for_horary_service_split_uses_same_generic_logic(self):
        """Same generic code path for horary_service.py."""
        builder = FeaturePathManifestBuilder()
        manifest = builder.build(
            feature_text="Split apps/api/app/services/horary_service.py into horary package",
            context_paths=["apps/api/app/services/horary_service.py"],
        )
        assert manifest.found
        assert manifest.source_path == "apps/api/app/services/horary_service.py"
        assert manifest.package_path == "apps/api/app/services/horary/"

    def test_bare_filename_without_context_returns_no_manifest(self):
        """Bare 'llm_service.py' without context paths → not found."""
        builder = FeaturePathManifestBuilder()
        manifest = builder.build(
            feature_text="Split llm_service.py into llm package",
            context_paths=[],
        )
        assert not manifest.found
        assert manifest.package_path is None

    def test_bare_filename_selects_matching_context_not_first_service(self):
        """horary_service.py matches its own path, not first service file."""
        builder = FeaturePathManifestBuilder()
        manifest = builder.build(
            feature_text="Split horary_service.py into package",
            context_paths=[
                "apps/api/app/services/llm_service.py",
                "apps/api/app/services/horary_service.py",
            ],
        )
        assert manifest.source_path == "apps/api/app/services/horary_service.py"
        assert manifest.found
        assert manifest.package_path == "apps/api/app/services/horary/"

    def test_manifest_uses_longest_kg_prefix(self):
        """Builder selects M-BACKEND-SERVICES by longest path match."""
        kg = _kg_with_backend_services()
        builder = FeaturePathManifestBuilder()
        manifest = builder.build(
            feature_text="Split llm_service.py into llm package",
            context_paths=["apps/api/app/services/llm_service.py"],
            kg=kg,
        )
        assert manifest.owning_module_id == "M-BACKEND-SERVICES"

    def test_manifest_builds_forbidden_near_misses_from_package_name(self):
        """Forbidden paths are derived dynamically, not hardcoded."""
        builder = FeaturePathManifestBuilder()
        manifest = builder.build(
            feature_text="Split llm_service.py",
            context_paths=["apps/api/app/services/llm_service.py"],
        )
        forbidden = manifest.forbidden_near_misses
        assert any("apps/api/app/llm/" in f for f in forbidden)
        assert any("app/llm/" in f for f in forbidden)
        assert any("app.services.llm" in f for f in forbidden)

    def test_manifest_for_horary_has_different_forbidden_paths(self):
        """Horary split gets different forbidden paths than LLM."""
        builder = FeaturePathManifestBuilder()
        manifest = builder.build(
            feature_text="Split horary_service.py",
            context_paths=["apps/api/app/services/horary_service.py"],
        )
        assert any("apps/api/app/horary/" in f for f in manifest.forbidden_near_misses)
        assert any("app/horary/" in f for f in manifest.forbidden_near_misses)
        # Confirm it does NOT contain llm-specific paths
        assert not any("llm" in f for f in manifest.forbidden_near_misses)

    def test_manifest_omits_concrete_paths_when_source_file_not_found(self):
        """No manifest when source file can't be resolved."""
        builder = FeaturePathManifestBuilder()
        manifest = builder.build(
            feature_text="Fix typo in notification template",
            context_paths=[],
        )
        assert not manifest.found

    def test_kg_prompt_block_has_no_llm_specific_branch(self):
        """Prompt block must not reference llm specifically."""
        builder = FeaturePathManifestBuilder()
        manifest = builder.build(
            feature_text="Split apps/api/app/services/llm_service.py",
            context_paths=["apps/api/app/services/llm_service.py"],
        )
        block = builder.build_prompt_block(manifest)
        # The block should contain the EXACT paths, not "llm" as a keyword check
        assert "apps/api/app/services/llm/" in block
        assert "apps/api/app/llm/" in block  # forbidden near-miss
        # Confirm the source string is correct
        assert "llm_service.py" in block

    def test_prompt_block_contains_owner_module_info_when_kg_available(self):
        """Prompt block includes owning module ID and canonical roots."""
        kg = _kg_with_backend_services()
        builder = FeaturePathManifestBuilder()
        manifest = builder.build(
            feature_text="Split llm_service.py",
            context_paths=["apps/api/app/services/llm_service.py"],
            kg=kg,
        )
        block = builder.build_prompt_block(manifest)
        assert "M-BACKEND-SERVICES" in block
        assert "apps/api/app/services/" in block
