# ############################################################################
# AI_HEADER: test_runtime_state_store — runtime state port acceptance tests
# ROLE: Proves missing, malformed, valid, and physically present supervisor
#      state behavior without involving FastAPI or supervisor transport.
# ############################################################################

# START_MODULE_CONTRACT
# purpose: Verify RuntimeStateStore parsing and exists/read distinction.
# inputs: Temporary filesystem paths supplied by pytest.
# returns: Pytest assertions.
# side_effects: Creates temporary supervisor.json files only.
# emitted_logs: None.
# error_behavior: Fails when state parsing or presence semantics regress.
# END_MODULE_CONTRACT

# START_MODULE_MAP
# mapping:
#   - function: test_missing_state
#   - function: test_malformed_state_keeps_exists_true
#   - function: test_valid_state_returns_exact_mapping
# END_MODULE_MAP

from __future__ import annotations

from pathlib import Path

from grace_control.core.structured_logger import GraceLogger
from grace_control.services.runtime_state_store import RuntimeStateStore

_log = GraceLogger("test_runtime_state_store")


# START_BLOCK_RUNTIME_STATE_STORE_TESTS
# START_FUNCTION_CONTRACT
# name: test_missing_state
# purpose: Verify absent state reads as None and is not physically present.
# inputs: tmp_path — pytest temporary target directory.
# returns: None.
# side_effects: Reads temporary filesystem metadata.
# emitted_logs: None.
# error_behavior: AssertionError when missing-state semantics regress.
# END_FUNCTION_CONTRACT
def test_missing_state(tmp_path: Path) -> None:
    store = RuntimeStateStore(tmp_path)
    assert store.state_path == tmp_path / "supervisor.json"
    assert store.exists() is False
    assert store.read() is None


# START_FUNCTION_CONTRACT
# name: test_malformed_state_keeps_exists_true
# purpose: Verify malformed JSON is unreadable without erasing physical
#          presence information needed by mutation gating.
# inputs: tmp_path — pytest temporary target directory.
# returns: None.
# side_effects: Writes and reads temporary supervisor.json.
# emitted_logs: None.
# error_behavior: AssertionError when exists/read are conflated.
# END_FUNCTION_CONTRACT
def test_malformed_state_keeps_exists_true(tmp_path: Path) -> None:
    path = tmp_path / "supervisor.json"
    path.write_text("not-json")
    store = RuntimeStateStore(tmp_path)
    assert store.exists() is True
    assert store.read() is None


# START_FUNCTION_CONTRACT
# name: test_valid_state_returns_exact_mapping
# purpose: Verify valid JSON mappings are returned without field rewriting.
# inputs: tmp_path — pytest temporary target directory.
# returns: None.
# side_effects: Writes and reads temporary supervisor.json.
# emitted_logs: None.
# error_behavior: AssertionError when valid state is changed or rejected.
# END_FUNCTION_CONTRACT
def test_valid_state_returns_exact_mapping(tmp_path: Path) -> None:
    expected = {"version": 1, "api": {"pid": 7}, "workers": []}
    (tmp_path / "supervisor.json").write_text('{"version": 1, "api": {"pid": 7}, "workers": []}')
    assert RuntimeStateStore(tmp_path).read() == expected


# END_BLOCK_RUNTIME_STATE_STORE_TESTS
