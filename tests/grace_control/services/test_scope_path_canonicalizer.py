"""Tests for ScopePathCanonicalizer."""
from __future__ import annotations

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
        plan = _make_plan(["app.services.llm"])
        result = ScopePathCanonicalizer().canonicalize_plan(plan)
        assert result.changed
        scope = result.plan["waves"][0]["packets"][0]["scope"]
        # app.services.llm maps to a file path by default
        assert "apps/api/app/services/llm.py" in scope or "apps/api/app/services/llm/" in scope

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
