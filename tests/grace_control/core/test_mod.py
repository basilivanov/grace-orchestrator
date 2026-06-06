"""Tests for mod.py — feature processing module."""

from grace_control.mod import (
    list_handlers,
    process,
    register_handler,
    validate_feature,
)


def test_process_defaults():
    result = process("add login page")
    assert result["status"] == "ok"
    assert "add login page" in result["summary"]
    assert result["processed_paths"] == ["src/grace_control/"]


def test_process_with_scope():
    result = process("add api endpoint", target_scope=["src/api/"])
    assert result["status"] == "ok"
    assert result["processed_paths"] == ["src/api/"]


def test_process_with_metadata():
    result = process("refactor", metadata={"reason": "tech-debt"})
    assert result["status"] == "ok"
    assert result["metadata"]["reason"] == "tech-debt"


def test_process_empty_description():
    result = process("")
    assert result["status"] == "error"
    assert "task_description" in str(result["errors"])


def test_process_whitespace_description():
    result = process("   ")
    assert result["status"] == "error"


def test_validate_feature_valid():
    errors = validate_feature("add tests", ["src/x.py"])
    assert errors == []


def test_validate_feature_empty_description():
    errors = validate_feature("")
    assert len(errors) > 0
    assert "task_description" in errors[0]


def test_validate_feature_invalid_scope():
    errors = validate_feature("task", [""])
    assert len(errors) > 0
    assert "Invalid scope path" in errors[0]


def test_register_and_list_handlers():
    register_handler("test_type", lambda desc, scope=None, meta=None: {"status": "handled"})
    assert "test_type" in list_handlers()


def test_process_dispatches_to_handler():
    def handler(desc, scope=None, meta=None):
        return {"status": "handled", "data": desc}
    register_handler("dispatch_test", handler)
    result = process("custom task", metadata={"feature_type": "dispatch_test"})
    assert result["status"] == "handled"
    assert result["data"] == "custom task"


def test_process_no_handler_for_type():
    result = process("plain task")
    assert result["status"] == "ok"
