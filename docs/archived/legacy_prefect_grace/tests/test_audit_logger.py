"""
Tests for audit logger.
"""

import json
import os
from pathlib import Path

import pytest

from prefect_grace.audit.logger import log_sandbox_bypass_attempt


class TestAuditLogger:
    """Tests for audit logging functionality."""

    def test_audit_log_created(self, tmp_path):
        """Verify audit log file is created with correct format."""
        audit_log_path = tmp_path / "audit" / "test.jsonl"

        log_sandbox_bypass_attempt(
            packet_id="test-packet-1",
            allowed=True,
            reason="sandbox=danger-full-access, approval=never",
            policy_reason="Allowed by environment variable",
            audit_log_path=str(audit_log_path),
        )

        assert audit_log_path.exists()
        content = audit_log_path.read_text()
        entry = json.loads(content.strip())

        assert entry["packet_id"] == "test-packet-1"
        assert entry["allowed"] is True
        assert entry["reason"] == "sandbox=danger-full-access, approval=never"
        assert entry["policy_reason"] == "Allowed by environment variable"
        assert "timestamp" in entry
        assert "hostname" in entry
        assert "user" in entry

    def test_multiple_audit_entries(self, tmp_path):
        """Verify multiple entries are appended correctly."""
        audit_log_path = tmp_path / "audit" / "test.jsonl"

        # Log first attempt
        log_sandbox_bypass_attempt(
            packet_id="test-packet-1",
            allowed=True,
            reason="test reason 1",
            policy_reason="policy reason 1",
            audit_log_path=str(audit_log_path),
        )

        # Log second attempt
        log_sandbox_bypass_attempt(
            packet_id="test-packet-2",
            allowed=False,
            reason="test reason 2",
            policy_reason="policy reason 2",
            audit_log_path=str(audit_log_path),
        )

        # Verify both entries exist
        lines = audit_log_path.read_text().strip().split("\n")
        assert len(lines) == 2

        entry1 = json.loads(lines[0])
        entry2 = json.loads(lines[1])

        assert entry1["packet_id"] == "test-packet-1"
        assert entry1["allowed"] is True
        assert entry2["packet_id"] == "test-packet-2"
        assert entry2["allowed"] is False

    def test_audit_log_format(self, tmp_path):
        """Verify JSON structure of audit log entries."""
        audit_log_path = tmp_path / "audit" / "test.jsonl"

        log_sandbox_bypass_attempt(
            packet_id="test-packet",
            allowed=True,
            reason="test reason",
            policy_reason="test policy reason",
            audit_log_path=str(audit_log_path),
        )

        content = audit_log_path.read_text()
        entry = json.loads(content.strip())

        # Verify all required fields are present
        required_fields = [
            "timestamp",
            "packet_id",
            "allowed",
            "reason",
            "policy_reason",
            "hostname",
            "user",
        ]
        for field in required_fields:
            assert field in entry, f"Missing required field: {field}"

        # Verify timestamp format (ISO 8601)
        assert "T" in entry["timestamp"]
        assert entry["timestamp"].endswith("Z") or "+" in entry["timestamp"]

    def test_audit_log_graceful_failure(self, tmp_path, caplog):
        """Verify warnings on write failure without raising exceptions."""
        # Use a path that will fail (file instead of directory)
        bad_path = tmp_path / "file.txt"
        bad_path.write_text("existing file")
        audit_log_path = bad_path / "cannot" / "create.jsonl"

        # Should not raise, but should log warning
        log_sandbox_bypass_attempt(
            packet_id="test-packet",
            allowed=True,
            reason="test reason",
            policy_reason="test policy reason",
            audit_log_path=str(audit_log_path),
        )

        # Verify warning was logged
        assert any("Failed to write sandbox bypass audit log" in record.message for record in caplog.records)

    def test_audit_log_default_path(self, monkeypatch, tmp_path):
        """Verify default audit log path is used when not specified."""
        # We can't easily test the actual default path, but we can verify
        # that None is handled correctly by checking the function doesn't crash
        audit_log_path = tmp_path / "default.jsonl"

        # Mock the default path
        import prefect_grace.audit.logger as logger_module
        original_default = logger_module.DEFAULT_AUDIT_LOG_PATH
        monkeypatch.setattr(logger_module, "DEFAULT_AUDIT_LOG_PATH", str(audit_log_path))

        log_sandbox_bypass_attempt(
            packet_id="test-packet",
            allowed=True,
            reason="test reason",
            policy_reason="test policy reason",
            audit_log_path=None,  # Use default
        )

        assert audit_log_path.exists()

        # Restore original
        monkeypatch.setattr(logger_module, "DEFAULT_AUDIT_LOG_PATH", original_default)

    def test_audit_log_denied_attempt(self, tmp_path):
        """Verify denied attempts are logged correctly."""
        audit_log_path = tmp_path / "audit" / "test.jsonl"

        log_sandbox_bypass_attempt(
            packet_id="test-packet-denied",
            allowed=False,
            reason="sandbox=danger-full-access, approval=never",
            policy_reason="Sandbox bypass not allowed. Set GRACE_ALLOW_SANDBOX_BYPASS=true",
            audit_log_path=str(audit_log_path),
        )

        content = audit_log_path.read_text()
        entry = json.loads(content.strip())

        assert entry["packet_id"] == "test-packet-denied"
        assert entry["allowed"] is False
        assert "not allowed" in entry["policy_reason"].lower()
