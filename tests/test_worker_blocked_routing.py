"""Tests for worker blocked routing — release_status_from_result and _handle_rejection skip."""

import pytest

from grace_control.adapters.packet_executor import ExecutionResult
from grace_control.worker.worker import release_status_from_result


def test_release_status_accepted():
    """accepted=True → status='accepted'."""
    r = ExecutionResult(accepted=True, domain_status="accepted", reason="ok")
    assert release_status_from_result(r) == "accepted"


def test_release_status_blocked():
    """accepted=False, domain_status='blocked' → status='blocked'."""
    r = ExecutionResult(accepted=False, domain_status="blocked", reason="scope impossible")
    assert release_status_from_result(r) == "blocked"


def test_release_status_rejected():
    """accepted=False, domain_status='rejected' → status='rejected'."""
    r = ExecutionResult(accepted=False, domain_status="rejected", reason="tests failed")
    assert release_status_from_result(r) == "rejected"


def test_release_status_default_rejected():
    """accepted=False, domain_status='unknown' → status='rejected'."""
    r = ExecutionResult(accepted=False, domain_status="runner_error", reason="crash")
    assert release_status_from_result(r) == "rejected"



