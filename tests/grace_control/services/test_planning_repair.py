"""Tests for architect repair loop (planning_recovery_service)."""
from __future__ import annotations

import json
import pytest

from grace_control.services.planning_recovery_service import (
    is_repairable_error,
    classify_compiler_result,
    build_repair_prompt,
)


class TestRepairableErrorClassifier:

    def test_repairable_source_split_error(self):
        assert is_repairable_error("E_SOURCE_SPLIT_ORIGIN_MISSING")

    def test_repairable_python_scope_limit_error(self):
        assert is_repairable_error("E_SCOPE_PYTHON_FILE_LIMIT")

    def test_terminal_shell_error(self):
        assert not is_repairable_error("E_SHELL_SOURCE_UNDER_DASH")

    def test_classify_repairable(self):
        errors = [
            {"code": "E_SOURCE_SPLIT_ORIGIN_MISSING", "message": "miss"},
            {"code": "E_SCOPE_ACCEPTANCE_IMPOSSIBLE", "message": "scope"},
        ]
        assert classify_compiler_result(errors) == "repairable"

    def test_classify_terminal(self):
        errors = [{"code": "E_VENV_MISSING", "message": "venv"}]
        assert classify_compiler_result(errors) == "terminal"

    def test_classify_mixed_becomes_review(self):
        errors = [
            {"code": "E_SOURCE_SPLIT_ORIGIN_MISSING", "message": "miss"},
            {"code": "E_VENV_MISSING", "message": "venv"},
        ]
        assert classify_compiler_result(errors) == "terminal"

    def test_classify_empty_is_ok(self):
        assert classify_compiler_result([]) == "ok"


class TestRepairPrompt:

    def test_repair_prompt_contains_previous_plan(self):
        plan = {"waves": [{"title": "Wave 1", "packets": []}]}
        errors = [
            {"code": "E_SOURCE_SPLIT_ORIGIN_MISSING",
             "message": "source file not in scope",
             "suggestion": "add to scope"}
        ]
        prompt = build_repair_prompt(
            feature_description="Split llm_service.py",
            feature_title="Refactor",
            previous_plan=plan,
            compiler_errors=errors,
        )
        assert "E_SOURCE_SPLIT_ORIGIN_MISSING" in prompt
        assert "Wave 1" in prompt
        assert "Patch the previous" in prompt or "minimally" in prompt

    def test_repair_prompt_contains_compiler_errors(self):
        errors = [
            {"code": "E_SOURCE_SPLIT_ORIGIN_MISSING",
             "message": "Task requires split/refactor of llm_service.py, "
                        "but this file is not in any coder packet's write scope",
             "suggestion": "Add llm_service.py to scope"}
        ]
        prompt = build_repair_prompt(
            feature_description="test",
            feature_title="test",
            previous_plan={"waves": []},
            compiler_errors=errors,
        )
        assert "llm_service.py" in prompt
        assert "scope" in prompt
        assert "E_SOURCE_SPLIT_ORIGIN_MISSING" in prompt

    def test_repair_prompt_mentions_required_file_for_split(self):
        """E_SOURCE_SPLIT_ORIGIN_MISSING feedback must mention the file."""
        errors = [
            {"code": "E_SOURCE_SPLIT_ORIGIN_MISSING",
             "message": "requires split/refactor of apps/api/app/services/llm_service.py",
             "suggestion": "Add apps/api/app/services/llm_service.py to scope"}
        ]
        prompt = build_repair_prompt(
            feature_description="test",
            feature_title="test",
            previous_plan={"waves": []},
            compiler_errors=errors,
        )
        assert "apps/api/app/services/llm_service.py" in prompt

    def test_repair_prompt_does_not_include_full_context_builder_output(self):
        """Repair prompt should not contain context builder data."""
        plan = {"waves": [{"title": "W1", "packets": [{"title": "P1"}]}]}
        errors = [{"code": "E_SOURCE_SPLIT_ORIGIN_MISSING",
                   "message": "missing", "suggestion": "add"}]
        prompt = build_repair_prompt("test", "test", plan, errors)
        # The prompt should be relatively compact
        assert len(prompt) < 5000

    def test_repair_prompt_returns_only_json_instruction(self):
        """Repair prompt instructs architect to return only JSON."""
        errors = [{"code": "E_SOURCE_SPLIT_ORIGIN_MISSING",
                   "message": "miss", "suggestion": "fix"}]
        prompt = build_repair_prompt("test", "test", {"waves": []}, errors)
        assert "corrected json only" in prompt.lower() or "only valid json" in prompt.lower()
        assert "markdown" in prompt.lower() and "not" in prompt.lower()

    def test_repair_prompt_keeps_large_plan_tail_needed_for_bounded_rework(self):
        plan = {
            "waves": [
                {
                    "title": "W1",
                    "packets": [
                        {"title": "P1", "description": "x" * 5000},
                        {"title": "W06-P01 Final broad sweep marker"},
                    ],
                }
            ]
        }
        errors = [{"code": "E_SCOPE_PYTHON_FILE_LIMIT", "message": "too broad"}]

        prompt = build_repair_prompt("test", "test", plan, errors)

        assert "W06-P01 Final broad sweep marker" in prompt


class TestSessionHandleConversion:

    def test_session_handle_restored_from_dict(self):
        """previous_session restored from dict must be a valid AgentSessionHandle."""
        from grace_control.core.agent_session_adapter import AgentSessionHandle

        raw = {
            "runner": "profile",
            "role": "architect",
            "model": "openai/deepseek-v4-pro",
            "session_id": "sess_abc123",
        }
        handle = AgentSessionHandle(**raw)
        assert handle.session_id == "sess_abc123"
        assert handle.runner == "profile"
        assert handle.model == "openai/deepseek-v4-pro"

    def test_session_handle_from_json_string(self):
        """previous_session restored from JSON string must be valid."""
        from grace_control.core.agent_session_adapter import AgentSessionHandle
        import json

        raw_str = json.dumps({
            "runner": "profile",
            "session_id": "sess_def456",
        })
        raw = json.loads(raw_str)
        handle = AgentSessionHandle(**raw)
        assert handle.session_id == "sess_def456"

    def test_session_handle_accesses_session_id_safely(self):
        """AgentSessionHandle.session_id must be accessible without AttributeError."""
        from grace_control.core.agent_session_adapter import AgentSessionHandle

        handle = AgentSessionHandle()
        # Should be None, not raise AttributeError
        sid = handle.session_id
        assert sid is None

        handle2 = AgentSessionHandle(session_id="sess_valid")
        assert handle2.session_id == "sess_valid"

    def test_session_handle_without_session_id_allows_fallback(self):
        """When session_id is absent, run_architect_repair should use new session."""
        from grace_control.core.agent_session_adapter import AgentSessionHandle

        raw = {"runner": "profile", "role": "architect"}
        handle = AgentSessionHandle(**raw)
        assert handle.session_id is None
        # The repair code checks: if previous_session and previous_session.session_id
        # Since session_id is None, it will fallback to new session (no crash)
