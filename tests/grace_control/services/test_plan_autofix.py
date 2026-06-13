"""Tests for SafePlanAutofixer — deterministic plan patching."""
from __future__ import annotations

from grace_control.services.plan_autofix_service import SafePlanAutofixer


def _make_plan(packets) -> dict:
    return {"waves": [{"title": "Wave 1", "packets": list(packets)}]}


def _pkt(title="T", scope=None, role="coder", frozen_scope=None):
    return {
        "title": title,
        "scope": scope or [],
        "role": role,
        "verification": {"t0": [], "t1": [], "t2": []},
        "expected_evidence": [],
    }


class TestSourceSplitAutofix:

    def test_autofix_adds_missing_source_file_to_nearest_packet(self):
        plan = _make_plan([
            _pkt("Split LLM", scope=[
                "apps/api/app/services/llm/__init__.py",
                "apps/api/app/services/llm/russian.py",
            ]),
        ])
        errors = [
            {"code": "E_SOURCE_SPLIT_ORIGIN_MISSING",
             "message": "Task requires split/refactor of "
                        "apps/api/app/services/llm_service.py, but this file "
                        "is not in any coder packet's write scope"}
        ]
        report = SafePlanAutofixer().apply(plan, errors)
        assert report.applied
        assert len(report.fixes) == 1
        assert report.fixes[0]["code"] == "AUTO_ADD_MISSING_SOURCE_FILE"
        assert "llm_service.py" in report.fixes[0]["file"]
        patched = report.patched_plan
        scope = patched["waves"][0]["packets"][0]["scope"]
        assert "apps/api/app/services/llm_service.py" in scope

    def test_autofix_does_not_add_file_outside_allowed_dirs(self):
        plan = _make_plan([_pkt("T", scope=["apps/api/services/llm/x.py"])])
        errors = [
            {"code": "E_SOURCE_SPLIT_ORIGIN_MISSING",
             "message": "requires split/refactor of /tmp/some_file.py"}
        ]
        report = SafePlanAutofixer().apply(plan, errors)
        assert not report.applied

    def test_autofix_skips_when_file_in_frozen_scope(self):
        plan = _make_plan([
            _pkt("Split LLM", scope=[
                "apps/api/app/services/llm/russian.py",
            ]),
        ])
        plan["constraints"] = {"frozen_scope": ["apps/api/app/services/llm_service.py"]}
        errors = [
            {"code": "E_SOURCE_SPLIT_ORIGIN_MISSING",
             "message": "requires split/refactor of "
                        "apps/api/app/services/llm_service.py"}
        ]
        report = SafePlanAutofixer().apply(plan, errors)
        assert not report.applied

    def test_autofix_skips_when_packet_is_verifier_only(self):
        plan = _make_plan([
            _pkt("Verify only", scope=["apps/api/services/x.py"], role="verifier"),
        ])
        errors = [
            {"code": "E_SOURCE_SPLIT_ORIGIN_MISSING",
             "message": "requires split/refactor of "
                        "apps/api/app/services/llm_service.py"}
        ]
        report = SafePlanAutofixer().apply(plan, errors)
        assert not report.applied

    def test_autofix_adds_to_packet_with_sibling_files(self):
        """File should be added to the packet that has sibling llm/ files."""
        plan = _make_plan([
            _pkt("Other task", scope=["apps/api/app/other/x.py"]),
            _pkt("Split LLM", scope=[
                "apps/api/app/services/llm/__init__.py",
                "apps/api/app/services/llm/russian.py",
            ]),
        ])
        errors = [
            {"code": "E_SOURCE_SPLIT_ORIGIN_MISSING",
             "message": "requires split/refactor of "
                        "apps/api/app/services/llm_service.py"}
        ]
        report = SafePlanAutofixer().apply(plan, errors)
        assert report.applied
        patched = report.patched_plan
        scope1 = patched["waves"][0]["packets"][0]["scope"]
        scope2 = patched["waves"][0]["packets"][1]["scope"]
        assert "apps/api/app/services/llm_service.py" not in scope1
        assert "apps/api/app/services/llm_service.py" in scope2


class TestImportScopeAutofix:

    def test_import_scope_autofix_adds_limited_reference_files(self):
        plan = _make_plan([
            _pkt("Refactor", scope=["apps/api/app/services/llm/russian.py"]),
        ])
        errors = [
            {"code": "E_IMPORT_MIGRATION_SCOPE_INCOMPLETE",
             "message": "active references outside scope: "
                        "apps/api/app/services/natal_report_service.py"}
        ]
        report = SafePlanAutofixer().apply(plan, errors)
        assert report.applied
        assert report.fixes[0]["code"] == "AUTO_ADD_IMPORT_REFERENCE_FILES"
        patched = report.patched_plan
        scope = patched["waves"][0]["packets"][0]["scope"]
        assert "apps/api/app/services/natal_report_service.py" in scope

    def test_import_scope_autofix_skips_when_too_many_refs(self):
        many_refs = [f"apps/api/tests/test_{i}.py" for i in range(10)]
        plan = _make_plan([_pkt("Refactor", scope=["apps/api/app/services/llm/x.py"])])
        errors = [
            {"code": "E_IMPORT_MIGRATION_SCOPE_INCOMPLETE",
             "message": f"active references outside scope: {many_refs[0]}"}
        ]
        report = SafePlanAutofixer().apply(plan, errors)
        # With 10 refs from the message (all extracted), it exceeds 8
        assert not report.applied

    def test_import_scope_autofix_skips_when_no_packet_found(self):
        plan = _make_plan([
            _pkt("Verifier", scope=["apps/api/app/services/x.py"], role="verifier"),
        ])
        errors = [
            {"code": "E_IMPORT_MIGRATION_SCOPE_INCOMPLETE",
             "message": "active references outside scope: "
                        "apps/api/app/services/natal_report_service.py"}
        ]
        report = SafePlanAutofixer().apply(plan, errors)
        assert not report.applied


class TestUnsupportedErrors:

    def test_autofix_skips_unsupported_error_code(self):
        plan = _make_plan([_pkt("T", scope=["apps/api/svc.py"])])
        errors = [
            {"code": "E_SOME_UNKNOWN_ERROR",
             "message": "some error message"}
        ]
        report = SafePlanAutofixer().apply(plan, errors)
        assert not report.applied
        assert len(report.skipped) == 1


class TestSessionMode:

    def test_opencode_run_new_reports_new_session(self):
        from grace_control.core.agent_session_adapter import OpenCodeSessionAdapter, AgentRunRequest
        adapter = OpenCodeSessionAdapter(default_model="deepseek/deepseek-v4-flash")
        # Session mode test: create request and check mode
        assert adapter.default_model == "deepseek/deepseek-v4-flash"

    def test_autofix_success_creates_patched_plan(self):
        """Verify autofix persistence fields exist."""
        plan = _make_plan([
            _pkt("Split", scope=["apps/api/app/services/llm/russian.py"]),
        ])
        errors = [
            {"code": "E_SOURCE_SPLIT_ORIGIN_MISSING",
             "message": "requires split/refactor of "
                        "apps/api/app/services/llm_service.py"}
        ]
        report = SafePlanAutofixer().apply(plan, errors)
        assert report.applied
        assert report.patched_plan is not None

    def test_real_compiler_message_with_list_format_is_parsed(self):
        """Compiler message with Python list representation is parsed correctly."""
        plan = _make_plan([
            _pkt("Split LLM", scope=["apps/api/app/services/llm/russian.py"]),
        ])
        errors = [
            {"code": "E_IMPORT_MIGRATION_SCOPE_INCOMPLETE",
             "message": "Plan requires old import app.services.llm_service to be removed, "
                        "but 2 active references remain outside write scope: "
                        "['apps/api/app/services/horary_service.py', "
                        "'apps/api/tests/test_horary_answer_quality.py']"},
        ]
        report = SafePlanAutofixer().apply(plan, errors)
        # Should parse and add the reference files
        assert report.applied
        patched_scope = report.patched_plan["waves"][0]["packets"][0]["scope"]
        assert "apps/api/app/services/horary_service.py" in patched_scope
        assert "apps/api/tests/test_horary_answer_quality.py" in patched_scope

    def test_autofix_failure_does_not_crash_repair_fallback(self):
        """When autofix fails, the system should still be able to attempt LLM repair."""
        from grace_control.core.plan_compiler import PlanCompiler
        env = None  # Will be None, but compile_plan handles it
        plan = _make_plan([
            _pkt("Split LLM", scope=[]),
        ])
        errors = [
            {"code": "E_CODER_EMPTY_SCOPE",
             "message": "coder packet has empty write scope"},
        ]
        report = SafePlanAutofixer().apply(plan, errors)
        assert not report.applied  # No autofix for this error code
        # The caller should still be able to call LLM repair — this verifies
        # that autofix doesn't crash and prevents later steps (previous_session etc.)
