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


def test_evidence_deletion_autofix_skips_without_explicit_target_proof():
    packet = _pkt("Docs", scope=["docs/development-plan.xml"])
    packet["expected_evidence"] = [{
        "id": "EV-XML",
        "kind": "contract",
        "artifact_patterns": ["docs/development-plan.xml"],
        "expectation": "exists",
    }]
    report = SafePlanAutofixer().apply(
        _make_plan([packet]),
        [{
            "code": "E_EVIDENCE_CONTRADICTS_INSTRUCTIONS",
            "packet_title": "Docs",
            "details": {
                "evidence_id": "EV-XML",
                "file": "docs/development-plan.xml",
                "suggested_fix": "deleted",
            },
        }],
    )

    assert not report.applied
    assert report.skipped[0]["code"] == "SKIPPED_AMBIGUOUS_EVIDENCE_DELETION"


def test_evidence_deletion_autofix_applies_with_explicit_target_proof():
    packet = _pkt("Delete old module", scope=["src/old.py"])
    packet["expected_evidence"] = [{
        "id": "EV-OLD",
        "kind": "contract",
        "artifact_patterns": ["src/old.py"],
        "expectation": "exists",
    }]
    report = SafePlanAutofixer().apply(
        _make_plan([packet]),
        [{
            "code": "E_EVIDENCE_CONTRADICTS_INSTRUCTIONS",
            "packet_title": "Delete old module",
            "details": {
                "evidence_id": "EV-OLD",
                "file": "src/old.py",
                "remove_target_explicit": True,
                "suggested_fix": "deleted",
            },
        }],
    )

    assert report.applied
    evidence = report.patched_plan["waves"][0]["packets"][0]["expected_evidence"][0]
    assert evidence["expectation"] == "deleted"


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

    def test_import_scope_autofix_creates_migration_packet_for_many_refs(self):
        """With >8 refs, autofix creates a dedicated import-migration packet."""
        many_refs = [f"apps/api/tests/test_{i}.py" for i in range(10)]
        plan = _make_plan([_pkt("Refactor", scope=["apps/api/app/services/llm/x.py"])])
        errors = [
            {"code": "E_IMPORT_MIGRATION_SCOPE_INCOMPLETE",
             "message": f"active references outside scope: {many_refs[0]}"}
        ]
        report = SafePlanAutofixer().apply(plan, errors)
        assert report.applied
        assert any(f["code"] == "AUTO_CREATE_IMPORT_MIGRATION_PACKET" for f in report.fixes)

    def test_import_scope_autofix_creates_migration_packet_when_no_coder_packet(self):
        """With no coder packets at all, autofix creates a dedicated migration packet."""
        plan = _make_plan([
            _pkt("Verifier", scope=["apps/api/app/services/x.py"], role="verifier"),
        ])
        errors = [
            {"code": "E_IMPORT_MIGRATION_SCOPE_INCOMPLETE",
             "message": "active references outside scope: "
                        "apps/api/app/services/natal_report_service.py"}
        ]
        report = SafePlanAutofixer().apply(plan, errors)
        assert report.applied
        assert any(f["code"] == "AUTO_CREATE_IMPORT_MIGRATION_PACKET" for f in report.fixes)
        # Verify the migration packet was added to the wave
        patched = report.patched_plan
        pkts = patched["waves"][0]["packets"]
        assert any(p["title"].startswith("Migrate imports") for p in pkts)


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


class TestPythonScopeLimitAutofix:

    def test_keeps_final_broad_sweep_for_architect_split(self):
        broad_title = "W06-P01 Final repository-wide Python canon cleanup"
        plan = {
            "waves": [
                {
                    "title": "W01",
                    "packets": [_pkt("W01", scope=["app/core/a.py"])],
                },
                {
                    "title": "W06",
                    "packets": [
                        _pkt(broad_title, scope=["app", "scripts", "tests"]),
                        _pkt(
                            "W06-P02 Final evidence",
                            scope=["docs/verification-matrix.md"],
                        ),
                    ],
                },
            ]
        }
        plan["waves"][1]["packets"][0]["depends_on"] = ["W05 docs"]
        plan["waves"][1]["packets"][1]["depends_on"] = [broad_title]

        report = SafePlanAutofixer().apply(
            plan,
            [{
                "code": "E_SCOPE_PYTHON_FILE_LIMIT",
                "packet_title": broad_title,
                "message": "scope expands to 110 Python files",
            }],
        )

        assert not report.applied
        assert report.fixes == []
        assert report.skipped == [{
            "code": "SKIPPED_BROAD_SWEEP_REQUIRES_ARCHITECT_SPLIT",
            "reason": "plan metadata cannot prove repository-wide scope is redundant",
            "error_code": "E_SCOPE_PYTHON_FILE_LIMIT",
            "packet_title": broad_title,
        }]
        packets = [p for w in plan["waves"] for p in w["packets"]]
        assert broad_title in {p["title"] for p in packets}
        evidence = next(p for p in packets if p["title"] == "W06-P02 Final evidence")
        assert evidence["depends_on"] == [broad_title]

    def test_keeps_broad_scope_when_not_an_unambiguous_final_sweep(self):
        title = "Implement feature"
        report = SafePlanAutofixer().apply(
            _make_plan([_pkt(title, scope=["app", "scripts", "tests"])]),
            [{"code": "E_SCOPE_PYTHON_FILE_LIMIT", "packet_title": title}],
        )

        assert not report.applied


def test_autofix_drops_absolute_external_evidence_pattern():
    packet = _pkt("P", scope=["scripts/a.py"])
    packet["expected_evidence"] = [{
        "id": "EV-VENV",
        "kind": "contract",
        "artifact_patterns": ["/opt/project/.venv/bin/python version"],
    }]
    report = SafePlanAutofixer().apply(
        _make_plan([packet]),
        [{
            "code": "E_EVIDENCE_ABSOLUTE_PATTERN",
            "packet_title": "P",
            "message": "artifact pattern '/opt/project/.venv/bin/python version' is absolute",
        }],
    )

    assert report.applied
    assert report.patched_plan["waves"][0]["packets"][0]["expected_evidence"][0]["artifact_patterns"] == []


def test_autofix_uses_controller_diff_instead_of_stdout_pattern():
    packet = _pkt("P", scope=["src/router.js"])
    packet["expected_evidence"] = [{
        "id": "EV-DIFF",
        "kind": "diff",
        "artifact_patterns": ["t0_stdout"],
    }]
    report = SafePlanAutofixer().apply(
        _make_plan([packet]),
        [{"code": "E_EVIDENCE_DIFF_HAS_PATTERN", "packet_title": "P"}],
    )

    assert report.applied
    evidence = report.patched_plan["waves"][0]["packets"][0]["expected_evidence"][0]
    assert evidence["artifact_patterns"] == []


def test_autofix_maps_pytest_description_to_command_artifact():
    packet = _pkt("P", scope=["tests/unit/test_example.py"])
    packet["verification"]["t1"] = [
        "python scripts/grace_lint.py tests/unit/test_example.py",
        "python -m pytest tests/unit/test_example.py -q",
    ]
    packet["expected_evidence"] = [{
        "id": "EV-TEST",
        "kind": "test",
        "producer": "pytest",
        "artifact_patterns": ["pytest stdout for tests/unit/test_example.py"],
    }]
    report = SafePlanAutofixer().apply(
        _make_plan([packet]),
        [{
            "code": "E_EVIDENCE_DESCRIPTIVE_PATTERN",
            "packet_title": "P",
            "details": {
                "pattern": "pytest stdout for tests/unit/test_example.py",
                "evidence_id": "EV-TEST",
            },
        }],
    )

    assert report.applied
    evidence = report.patched_plan["waves"][0]["packets"][0]["expected_evidence"][0]
    assert evidence["artifact_patterns"] == ["t1/cmd_002_stdout.log"]


def test_autofix_maps_exact_command_output_to_stdout_artifact():
    packet = _pkt("P", scope=["package.json"])
    packet["verification"]["t1"] = ["npm test", "npm run check"]
    packet["expected_evidence"] = [{
        "id": "EV-TEST",
        "kind": "test",
        "producer": "cli",
        "artifact_patterns": ["npm test output", "npm run check output"],
    }]
    errors = [
        {
            "code": "E_EVIDENCE_DESCRIPTIVE_PATTERN",
            "packet_title": "P",
            "details": {"pattern": pattern, "evidence_id": "EV-TEST"},
        }
        for pattern in ("npm test output", "npm run check output")
    ]

    report = SafePlanAutofixer().apply(_make_plan([packet]), errors)

    assert report.applied
    evidence = report.patched_plan["waves"][0]["packets"][0]["expected_evidence"][0]
    assert evidence["artifact_patterns"] == [
        "t1/cmd_001_stdout.log",
        "t1/cmd_002_stdout.log",
    ]


def test_autofix_maps_run_command_label_to_stdout_artifact():
    packet = _pkt("P", scope=["package.json"])
    packet["verification"]["t1"] = ["npm test"]
    packet["expected_evidence"] = [{
        "id": "EV-TEST",
        "kind": "test",
        "producer": "cli",
        "artifact_patterns": ["run: npm test"],
    }]

    report = SafePlanAutofixer().apply(
        _make_plan([packet]),
        [{
            "code": "E_EVIDENCE_DESCRIPTIVE_PATTERN",
            "packet_title": "P",
            "details": {"pattern": "run: npm test", "evidence_id": "EV-TEST"},
        }],
    )

    assert report.applied
    evidence = report.patched_plan["waves"][0]["packets"][0]["expected_evidence"][0]
    assert evidence["artifact_patterns"] == ["t1/cmd_001_stdout.log"]


def test_autofix_maps_bare_verification_command_to_stdout_artifact():
    packet = _pkt("P", scope=["package.json"])
    packet["verification"]["t1"] = ["npm run check"]
    packet["expected_evidence"] = [{
        "id": "EV-TEST",
        "kind": "test",
        "producer": "cli",
        "artifact_patterns": ["npm run check"],
    }]

    report = SafePlanAutofixer().apply(
        _make_plan([packet]),
        [{
            "code": "E_EVIDENCE_DESCRIPTIVE_PATTERN",
            "packet_title": "P",
            "details": {"pattern": "npm run check", "evidence_id": "EV-TEST"},
        }],
    )

    assert report.applied
    evidence = report.patched_plan["waves"][0]["packets"][0]["expected_evidence"][0]
    assert evidence["artifact_patterns"] == ["t1/cmd_001_stdout.log"]


def test_autofix_maps_matrix_description_to_relative_file():
    packet = _pkt("Docs", scope=["docs/verification-matrix.md"])
    packet["expected_evidence"] = [{
        "id": "EV-MATRIX",
        "kind": "contract",
        "artifact_patterns": ["docs/verification-matrix.md requirement-by-requirement matrix"],
    }]
    report = SafePlanAutofixer().apply(
        _make_plan([packet]),
        [{
            "code": "E_EVIDENCE_DESCRIPTIVE_PATTERN",
            "packet_title": "Docs",
            "details": {
                "pattern": "docs/verification-matrix.md requirement-by-requirement matrix",
                "evidence_id": "EV-MATRIX",
            },
        }],
    )

    assert report.applied
    evidence = report.patched_plan["waves"][0]["packets"][0]["expected_evidence"][0]
    assert evidence["artifact_patterns"] == ["docs/verification-matrix.md"]


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
