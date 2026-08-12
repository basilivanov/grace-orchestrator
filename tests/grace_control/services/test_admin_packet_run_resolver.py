# ############################################################################
# AI_HEADER: test_admin_packet_run_resolver — packet-run selector regression tests
# ROLE: Verifies the shared PacketRunResolver preserves canonical, legacy,
#       numeric and invalid selector behavior without involving admin services.
# ############################################################################

# START_MODULE_CONTRACT
# purpose: Test packet-run selector resolution order and missing-selector
#          behavior for the lower-level admin read collaborator.
# inputs: Mock SQLAlchemy sessions and PacketRunResolver.
# returns: Pytest assertions; no production values are returned.
# side_effects: None; database access is represented by mocks.
# emitted_logs: None.
# error_behavior: Raises AssertionError when selector semantics regress.
# END_MODULE_CONTRACT

# START_MODULE_MAP
# mapping:
#   - function: test_resolver_prefers_canonical_id
#   - function: test_resolver_supports_legacy_composed_id
#   - function: test_resolver_supports_numeric_run_number
#   - function: test_resolver_rejects_invalid_selector
# END_MODULE_MAP

from __future__ import annotations

from unittest.mock import Mock, call

from grace_control.db.schema import PacketRun
from grace_control.services.admin_packet_run_resolver import PacketRunResolver

_PACKET_ID = "packet-1"


# START_BLOCK_TESTS
def _mock_db(*results: object) -> tuple[Mock, Mock]:
    db = Mock()
    query = db.query.return_value
    query.filter_by.return_value = query
    query.first.side_effect = list(results)
    return db, query


# START_FUNCTION_CONTRACT
# name: test_resolver_prefers_canonical_id
# purpose: Verify a packet-scoped canonical PacketRun ID is returned first.
# inputs: None; uses a mocked SQLAlchemy session.
# returns: None after the canonical selector assertion passes.
# side_effects: None.
# emitted_logs: None.
# error_behavior: AssertionError when canonical lookup is not first or scoped.
# END_FUNCTION_CONTRACT
def test_resolver_prefers_canonical_id() -> None:
    expected = Mock(spec=PacketRun)
    db, query = _mock_db(expected)

    result = PacketRunResolver().resolve_run(db, _PACKET_ID, "run-1")

    assert result is expected
    db.query.assert_called_once_with(PacketRun)
    assert query.filter_by.call_args_list == [call(packet_id=_PACKET_ID, id="run-1")]


# START_FUNCTION_CONTRACT
# name: test_resolver_supports_legacy_composed_id
# purpose: Verify the existing packet-prefixed legacy selector fallback.
# inputs: None; uses a mocked SQLAlchemy session.
# returns: None after the legacy selector assertion passes.
# side_effects: None.
# emitted_logs: None.
# error_behavior: AssertionError when the legacy fallback is skipped or changed.
# END_FUNCTION_CONTRACT
def test_resolver_supports_legacy_composed_id() -> None:
    expected = Mock(spec=PacketRun)
    db, query = _mock_db(None, expected)

    result = PacketRunResolver().resolve_run(db, _PACKET_ID, "R01")

    assert result is expected
    assert query.filter_by.call_args_list == [
        call(packet_id=_PACKET_ID, id="R01"),
        call(id=f"{_PACKET_ID}-R01"),
    ]


# START_FUNCTION_CONTRACT
# name: test_resolver_supports_numeric_run_number
# purpose: Verify numeric selectors resolve by packet-scoped run_number after
#          canonical and legacy ID checks.
# inputs: None; uses a mocked SQLAlchemy session.
# returns: None after the numeric selector assertion passes.
# side_effects: None.
# emitted_logs: None.
# error_behavior: AssertionError when numeric fallback is unscoped or reordered.
# END_FUNCTION_CONTRACT
def test_resolver_supports_numeric_run_number() -> None:
    expected = Mock(spec=PacketRun)
    db, query = _mock_db(None, None, expected)

    result = PacketRunResolver().resolve_run(db, _PACKET_ID, "7")

    assert result is expected
    assert query.filter_by.call_args_list == [
        call(packet_id=_PACKET_ID, id="7"),
        call(id=f"{_PACKET_ID}-7"),
        call(packet_id=_PACKET_ID, run_number=7),
    ]


# START_FUNCTION_CONTRACT
# name: test_resolver_rejects_invalid_selector
# purpose: Verify invalid/non-numeric selectors return None after ID fallbacks.
# inputs: None; uses a mocked SQLAlchemy session.
# returns: None after the invalid-selector assertion passes.
# side_effects: None.
# emitted_logs: None.
# error_behavior: AssertionError when invalid input raises or queries a run
#                 number.
# END_FUNCTION_CONTRACT
def test_resolver_rejects_invalid_selector() -> None:
    db, query = _mock_db(None, None)

    result = PacketRunResolver().resolve_run(db, _PACKET_ID, "not-a-run")

    assert result is None
    assert query.filter_by.call_args_list == [
        call(packet_id=_PACKET_ID, id="not-a-run"),
        call(id=f"{_PACKET_ID}-not-a-run"),
    ]


# END_BLOCK_TESTS
