"""Tests for ScopePathCanonicalizer."""
from __future__ import annotations

from pathlib import Path

from grace_control.services.scope_path_canonicalizer import ScopePathCanonicalizer


def _make_plan(scope: list[str]) -> dict:
    return {"waves": [{"title": "Wave 1", "packets": [
        {"title": "Split LLM", "role": "coder", "scope": scope,
         "verification": {"t0": [], "t1": [], "t2": []},
         "expected_evidence": []}
    ]}]}


class TestCanonicalizer:

    def test_canonicalizes_app_llm_file_to_services_llm(self):
        plan = _make_plan(["app/llm/russian.py"])
        result = ScopePathCanonicalizer().canonicalize_plan(plan)
        assert result.changed
        scope = result.plan["waves"][0]["packets"][0]["scope"]
        assert "apps/api/app/services/llm/russian.py" in scope
        assert "app/llm/russian.py" not in scope

    def test_canonicalizes_app_llm_dir_to_services_llm_dir(self):
        plan = _make_plan(["app/llm/"])
        result = ScopePathCanonicalizer().canonicalize_plan(plan)
        assert result.changed
        scope = result.plan["waves"][0]["packets"][0]["scope"]
        assert "apps/api/app/services/llm/" in scope

    def test_canonicalizes_import_path_app_services_llm_service(self):
        plan = _make_plan(["app.services.llm_service"])
        result = ScopePathCanonicalizer().canonicalize_plan(plan)
        assert result.changed
        scope = result.plan["waves"][0]["packets"][0]["scope"]
        assert "apps/api/app/services/llm_service.py" in scope

    def test_canonicalizes_import_path_app_services_llm_package(self):
        """app.services.llm → directory (package), not file."""
        plan = _make_plan(["app.services.llm"])
        result = ScopePathCanonicalizer().canonicalize_plan(plan)
        assert result.changed
        scope = result.plan["waves"][0]["packets"][0]["scope"]
        assert "apps/api/app/services/llm/" in scope
        assert "apps/api/app/services/llm.py" not in scope

    def test_canonicalizes_import_app_services_llm_russian(self):
        """app.services.llm.russian → file, not directory."""
        plan = _make_plan(["app.services.llm.russian"])
        result = ScopePathCanonicalizer().canonicalize_plan(plan)
        assert result.changed
        scope = result.plan["waves"][0]["packets"][0]["scope"]
        assert "apps/api/app/services/llm/russian.py" in scope
        assert "apps/api/app/services/llm/" not in scope

    def test_canonicalizer_persists_audit_report(self):
        plan = _make_plan(["app/llm/russian.py", "app.services.llm_service"])
        result = ScopePathCanonicalizer().canonicalize_plan(plan)
        assert result.changed
        assert len(result.fixes) == 2
        assert result.fixes[0]["code"] == "CANONICALIZE_SCOPE_PATH"
        assert result.fixes[0]["from"] == "app/llm/russian.py"
        assert result.fixes[0]["to"] == "apps/api/app/services/llm/russian.py"

    def test_already_canonical_path_stays_unchanged(self):
        plan = _make_plan(["apps/api/app/services/llm/russian.py"])
        result = ScopePathCanonicalizer().canonicalize_plan(plan)
        assert not result.changed

    def test_canonicalizer_handles_empty_plan(self):
        result = ScopePathCanonicalizer().canonicalize_plan({"waves": []})
        assert not result.changed

    def test_regression_scenario(self):
        """Full regression: app/llm/__init__.py + app.services.llm_service → canonical."""
        plan = _make_plan(["app/llm/__init__.py", "app/llm/russian.py",
                           "app.services.llm_service"])
        result = ScopePathCanonicalizer().canonicalize_plan(plan)
        assert result.changed
        scope = result.plan["waves"][0]["packets"][0]["scope"]
        assert "apps/api/app/services/llm/__init__.py" in scope
        assert "apps/api/app/services/llm/russian.py" in scope
        assert "apps/api/app/services/llm_service.py" in scope
        assert len(scope) == 3

    def test_preserves_root_app_paths_for_new_target(self, tmp_path: Path):
        plan = _make_plan([
            "app/core/config.py",
            "app/storage/migrations/script.py.mako",
        ])
        result = ScopePathCanonicalizer().canonicalize_plan(
            plan,
            target_repo_root=tmp_path,
        )
        assert not result.changed
        scope = result.plan["waves"][0]["packets"][0]["scope"]
        assert scope == [
            "app/core/config.py",
            "app/storage/migrations/script.py.mako",
        ]

    def test_existing_monorepo_still_expands_legacy_app_alias(
        self,
        tmp_path: Path,
    ):
        (tmp_path / "apps" / "api" / "app").mkdir(parents=True)
        plan = _make_plan(["app/llm/russian.py"])
        result = ScopePathCanonicalizer().canonicalize_plan(
            plan,
            target_repo_root=tmp_path,
        )
        assert result.changed
        scope = result.plan["waves"][0]["packets"][0]["scope"]
        assert scope == ["apps/api/app/services/llm/russian.py"]

    def test_root_config_files_are_not_import_paths(self, tmp_path: Path):
        plan = _make_plan(["AGENTS.md", "pyproject.toml", "alembic.ini"])
        result = ScopePathCanonicalizer().canonicalize_plan(
            plan,
            target_repo_root=tmp_path,
        )
        assert result.errors == []
