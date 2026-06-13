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
