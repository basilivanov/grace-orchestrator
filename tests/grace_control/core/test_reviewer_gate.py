"""Tests for reviewer gate parser and helpers."""

import pytest
from grace_control.core.reviewer_gate import (
    ReviewerReport,
    ReviewerVerdict,
    parse_reviewer_json,
    skipped_reviewer_report,
)


class TestParseReviewer:
    def test_valid_pass_json(self):
        raw = '{"verdict": "PASS", "summary": "good to merge", "risks": [], "required_changes": []}'
        r = parse_reviewer_json(raw)
        assert r.verdict == ReviewerVerdict.PASS
        assert r.summary == "good to merge"
        assert r.skipped is False

    def test_valid_rework_json(self):
        raw = '{"verdict": "REWORK_TO_CODER", "summary": "needs fixes", "required_changes": ["fix edge case"]}'
        r = parse_reviewer_json(raw)
        assert r.verdict == ReviewerVerdict.REWORK_TO_CODER
        assert "fix edge case" in r.required_changes

    def test_valid_return_to_architect_json(self):
        raw = '{"verdict": "RETURN_TO_ARCHITECT", "summary": "wrong scope", "architect_questions": ["replan?"]}'
        r = parse_reviewer_json(raw)
        assert r.verdict == ReviewerVerdict.RETURN_TO_ARCHITECT
        assert "replan?" in r.architect_questions

    def test_invalid_json(self):
        raw = "garbage"
        r = parse_reviewer_json(raw)
        assert r.verdict == ReviewerVerdict.REWORK_TO_CODER
        assert r.required_changes

    def test_unknown_verdict(self):
        raw = '{"verdict": "INVALID", "summary": "test"}'
        r = parse_reviewer_json(raw)
        assert r.verdict == ReviewerVerdict.REWORK_TO_CODER
        assert "unknown" in r.summary

    def test_skipped_report(self):
        r = skipped_reviewer_report("deterministic acceptance failed")
        assert r.skipped is True
        assert r.verdict == ReviewerVerdict.REWORK_TO_CODER
        assert "deterministic" in r.reason
