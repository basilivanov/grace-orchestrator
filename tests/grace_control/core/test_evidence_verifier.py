"""Tests for evidence verifier parser and helpers."""

import pytest
from grace_control.core.evidence_verifier import (
    EvidenceVerifierReport,
    EvidenceVerifierVerdict,
    parse_evidence_verifier_json,
    skipped_evidence_report,
)


class TestParseEvidenceVerifier:
    def test_valid_pass_json(self):
        raw = '{"verdict": "PASS", "summary": "all good", "missing_evidence": [], "failed_checks": []}'
        r = parse_evidence_verifier_json(raw)
        assert r.verdict == EvidenceVerifierVerdict.PASS
        assert r.summary == "all good"
        assert r.skipped is False

    def test_valid_rework_json(self):
        raw = '{"verdict": "REWORK_TO_CODER", "summary": "bad impl", "coder_instructions": ["fix tests"]}'
        r = parse_evidence_verifier_json(raw)
        assert r.verdict == EvidenceVerifierVerdict.REWORK_TO_CODER
        assert "fix tests" in r.coder_instructions

    def test_valid_return_to_architect_json(self):
        raw = '{"verdict": "RETURN_TO_ARCHITECT", "summary": "bad spec", "spec_conflicts": ["scope too narrow"]}'
        r = parse_evidence_verifier_json(raw)
        assert r.verdict == EvidenceVerifierVerdict.RETURN_TO_ARCHITECT
        assert "scope too narrow" in r.spec_conflicts

    def test_invalid_json(self):
        raw = "not json at all"
        r = parse_evidence_verifier_json(raw)
        assert r.verdict == EvidenceVerifierVerdict.REWORK_TO_CODER
        assert r.failed_checks

    def test_unknown_verdict(self):
        raw = '{"verdict": "INVALID", "summary": "test"}'
        r = parse_evidence_verifier_json(raw)
        assert r.verdict == EvidenceVerifierVerdict.REWORK_TO_CODER
        assert "unrecognized" in str(r).lower() or "unknown" in r.summary

    def test_skipped_report(self):
        r = skipped_evidence_report("deterministic acceptance failed")
        assert r.skipped is True
        assert r.verdict == EvidenceVerifierVerdict.REWORK_TO_CODER
        assert "deterministic" in r.reason
