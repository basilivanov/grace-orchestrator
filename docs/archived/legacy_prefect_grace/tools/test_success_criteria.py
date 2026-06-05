#!/usr/bin/env python3
"""
Test success criteria detection.

This script tests the success detection functions to ensure they correctly
identify successful and failed packets according to the criteria defined in
docs/SUCCESS_CRITERIA.md.
"""
import sys
from pathlib import Path

# Add parent directory to path for imports
sys.path.insert(0, str(Path(__file__).parent))

from verify_orchestrator import check_packet_success, check_feature_success


def test_packet_success():
    """Test packet success detection."""
    print("Testing packet success detection...")

    # Mock logs for successful packet
    logs = [
        {"event": "PACKET_START", "packet_id": "P1", "timestamp": "2026-05-30T10:00:00Z"},
        {"event": "EXECUTOR_SELECTED", "packet_id": "P1", "model": "gemini-3.5-flash", "complexity": "simple"},
        {"event": "PACKET_END", "packet_id": "P1", "status": "accepted", "returncode": 0, "timestamp": "2026-05-30T10:05:00Z"},
        {"event": "EXECUTION_METRICS", "packet_id": "P1", "tokens_used": 100, "cost_usd": 0.001, "duration_seconds": 300}
    ]

    result = check_packet_success(logs, "P1")

    assert result["success"] == True, "Expected packet to be successful"
    assert len(result["issues"]) == 0, f"Expected no issues, got: {result['issues']}"
    assert result["criteria_met"]["status_accepted"] == True
    assert result["criteria_met"]["returncode_zero"] == True
    assert result["criteria_met"]["metrics_present"] == True
    assert result["criteria_met"]["events_complete"] == True

    print("  ✓ Packet success detection works")


def test_packet_failure_status():
    """Test packet failure detection - wrong status."""
    print("Testing packet failure detection (wrong status)...")

    # Mock logs for failed packet
    logs = [
        {"event": "PACKET_START", "packet_id": "P2", "timestamp": "2026-05-30T10:00:00Z"},
        {"event": "EXECUTOR_SELECTED", "packet_id": "P2", "model": "gemini-3.5-flash"},
        {"event": "PACKET_END", "packet_id": "P2", "status": "failed", "returncode": 1, "timestamp": "2026-05-30T10:05:00Z"}
    ]

    result = check_packet_success(logs, "P2")

    assert result["success"] == False, "Expected packet to fail"
    assert len(result["issues"]) > 0, "Expected issues to be reported"
    assert "Status not accepted" in result["issues"]
    assert "Non-zero return code" in result["issues"]
    assert "Metrics not collected" in result["issues"]

    print("  ✓ Packet failure detection works (wrong status)")


def test_packet_failure_missing_events():
    """Test packet failure detection - missing events."""
    print("Testing packet failure detection (missing events)...")

    # Mock logs with missing EXECUTOR_SELECTED event
    logs = [
        {"event": "PACKET_START", "packet_id": "P3", "timestamp": "2026-05-30T10:00:00Z"},
        {"event": "PACKET_END", "packet_id": "P3", "status": "accepted", "returncode": 0, "timestamp": "2026-05-30T10:05:00Z"}
    ]

    result = check_packet_success(logs, "P3")

    assert result["success"] == False, "Expected packet to fail due to missing events"
    assert any("Missing events" in issue for issue in result["issues"])
    assert result["criteria_met"]["events_complete"] == False

    print("  ✓ Packet failure detection works (missing events)")


def test_feature_success():
    """Test feature success detection."""
    print("Testing feature success detection...")

    # Mock logs for feature with 2 successful packets
    logs = [
        # Packet 1
        {"event": "PACKET_START", "packet_id": "FEAT-XYZ-V1", "feature_id": "FEAT-XYZ"},
        {"event": "EXECUTOR_SELECTED", "packet_id": "FEAT-XYZ-V1", "feature_id": "FEAT-XYZ", "model": "gemini-3.5-flash"},
        {"event": "PACKET_END", "packet_id": "FEAT-XYZ-V1", "feature_id": "FEAT-XYZ", "status": "accepted", "returncode": 0},
        {"event": "EXECUTION_METRICS", "packet_id": "FEAT-XYZ-V1", "feature_id": "FEAT-XYZ", "tokens_used": 100},

        # Packet 2
        {"event": "PACKET_START", "packet_id": "FEAT-XYZ-V2", "feature_id": "FEAT-XYZ"},
        {"event": "EXECUTOR_SELECTED", "packet_id": "FEAT-XYZ-V2", "feature_id": "FEAT-XYZ", "model": "gemini-3.1-pro"},
        {"event": "PACKET_END", "packet_id": "FEAT-XYZ-V2", "feature_id": "FEAT-XYZ", "status": "accepted", "returncode": 0},
        {"event": "EXECUTION_METRICS", "packet_id": "FEAT-XYZ-V2", "feature_id": "FEAT-XYZ", "tokens_used": 200}
    ]

    result = check_feature_success(logs, "FEAT-XYZ")

    assert result["success"] == True, "Expected feature to be successful"
    assert result["total_packets"] == 2
    assert result["successful_packets"] == 2

    print("  ✓ Feature success detection works")


def test_feature_partial_failure():
    """Test feature with partial failures."""
    print("Testing feature with partial failures...")

    # Mock logs for feature with 1 success, 1 failure
    logs = [
        # Packet 1 - success
        {"event": "PACKET_START", "packet_id": "FEAT-ABC-V1", "feature_id": "FEAT-ABC"},
        {"event": "EXECUTOR_SELECTED", "packet_id": "FEAT-ABC-V1", "feature_id": "FEAT-ABC", "model": "gemini-3.5-flash"},
        {"event": "PACKET_END", "packet_id": "FEAT-ABC-V1", "feature_id": "FEAT-ABC", "status": "accepted", "returncode": 0},
        {"event": "EXECUTION_METRICS", "packet_id": "FEAT-ABC-V1", "feature_id": "FEAT-ABC", "tokens_used": 100},

        # Packet 2 - failure
        {"event": "PACKET_START", "packet_id": "FEAT-ABC-V2", "feature_id": "FEAT-ABC"},
        {"event": "EXECUTOR_SELECTED", "packet_id": "FEAT-ABC-V2", "feature_id": "FEAT-ABC", "model": "gemini-3.1-pro"},
        {"event": "PACKET_END", "packet_id": "FEAT-ABC-V2", "feature_id": "FEAT-ABC", "status": "failed", "returncode": 1}
    ]

    result = check_feature_success(logs, "FEAT-ABC")

    assert result["success"] == False, "Expected feature to fail"
    assert result["total_packets"] == 2
    assert result["successful_packets"] == 1

    print("  ✓ Feature partial failure detection works")


def test_empty_logs():
    """Test with empty logs."""
    print("Testing with empty logs...")

    logs = []

    result = check_packet_success(logs, "NONEXISTENT")

    assert result["success"] == False, "Expected failure for nonexistent packet"
    assert len(result["issues"]) > 0

    print("  ✓ Empty logs handled correctly")


def run_all_tests():
    """Run all success criteria tests."""
    print("\n" + "="*60)
    print("Running Success Criteria Tests")
    print("="*60 + "\n")

    try:
        test_packet_success()
        test_packet_failure_status()
        test_packet_failure_missing_events()
        test_feature_success()
        test_feature_partial_failure()
        test_empty_logs()

        print("\n" + "="*60)
        print("✓ All success criteria tests passed")
        print("="*60 + "\n")
        return 0

    except AssertionError as e:
        print(f"\n✗ Test failed: {e}")
        return 1
    except Exception as e:
        print(f"\n✗ Unexpected error: {e}")
        import traceback
        traceback.print_exc()
        return 1


if __name__ == "__main__":
    sys.exit(run_all_tests())
