# ############################################################################
# AI_HEADER: test_ci_repo_hygiene — tracked runtime-artifact gate tests
# ROLE: Verifies the repository hygiene policy rejects confirmed generated
#       paths while preserving the existing legacy package checks.
# ############################################################################

# START_MODULE_CONTRACT
# purpose: Characterize the tracked-path hygiene matcher and CLI diagnostics.
# inputs: Policy module and temporary pyproject metadata.
# returns: Pytest assertions; no repository state is changed.
# side_effects: Reads the policy module and writes temporary test metadata.
# emitted_logs: None.
# error_behavior: Fails if generated paths are missed or allowed paths rejected.
# END_MODULE_CONTRACT

# START_MODULE_MAP
# mapping:
#   - function: test_confirmed_runtime_paths_are_rejected
#   - function: test_allowed_source_and_fixture_paths_are_kept
#   - function: test_cli_errors_contain_each_offending_path
#   - function: test_existing_legacy_entrypoint_check_remains_active
# END_MODULE_MAP

from __future__ import annotations

import importlib.util
from pathlib import Path

from grace_control.core.structured_logger import GraceLogger

_log = GraceLogger("test_ci_repo_hygiene")

_SCRIPT = Path(__file__).resolve().parents[2] / "scripts" / "ci_repo_hygiene.py"
_SPEC = importlib.util.spec_from_file_location("ci_repo_hygiene_under_test", _SCRIPT)
assert _SPEC is not None and _SPEC.loader is not None
_MODULE = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(_MODULE)


# START_FUNCTION_CONTRACT
# name: test_confirmed_runtime_paths_are_rejected
# purpose: Prove every confirmed generated path family is executable policy.
# inputs: None; supplies representative tracked paths.
# returns: None.
# side_effects: None.
# emitted_logs: None.
# error_behavior: Fails if any generated path is accepted.
# END_FUNCTION_CONTRACT
def test_confirmed_runtime_paths_are_rejected():
    paths = (
        "%2Ftmp%2Fsomething.db",
        ".goldw/packets/pkt/EXECUTION_PACKET.md",
        ".lw3/packets/pkt/EXECUTION_PACKET.md",
        ".grace-live-wt/packets/pkt/EXECUTION_PACKET.md",
        "src/gold-test/result.txt",
        "runtime.db",
        "state/runtime.db-shm",
        "state/runtime.db-wal",
    )
    assert _MODULE.tracked_runtime_artifacts(paths) == paths


# START_FUNCTION_CONTRACT
# name: test_allowed_source_and_fixture_paths_are_kept
# purpose: Prove supported source and intentional golden fixture paths are not
#          falsely rejected by the narrow runtime matcher.
# inputs: None; supplies allowed tracked paths.
# returns: None.
# side_effects: None.
# emitted_logs: None.
# error_behavior: Fails if legitimate source/fixture paths are blocked.
# END_FUNCTION_CONTRACT
def test_allowed_source_and_fixture_paths_are_kept():
    paths = (
        "src/hello.py",
        "tests/test_hello.py",
        "fixtures/golden/accepted.yaml",
        "grace/packets/FEAT-HELLO-GRACE-TEST/brief.md",
    )
    assert _MODULE.tracked_runtime_artifacts(paths) == ()


# START_FUNCTION_CONTRACT
# name: test_cli_errors_contain_each_offending_path
# purpose: Prove hygiene diagnostics print every offending tracked path.
# inputs: monkeypatch, capsys — pytest output and policy substitutions.
# returns: None.
# side_effects: Captures deterministic CLI output.
# emitted_logs: None.
# error_behavior: Fails if an offending path is omitted from output.
# END_FUNCTION_CONTRACT
def test_cli_errors_contain_each_offending_path(monkeypatch, capsys):
    paths = ("%2Ftmp%2Fbad.db", ".goldw/packets/pkt/packet.md")
    monkeypatch.setattr(_MODULE, "tracked_files", lambda: paths)
    assert _MODULE.main() == 1
    output = capsys.readouterr().out
    assert "FAIL: repo-hygiene" in output
    for path in paths:
        assert path in output


# START_FUNCTION_CONTRACT
# name: test_existing_legacy_entrypoint_check_remains_active
# purpose: Prove the pre-existing pyproject legacy-entrypoint check remains.
# inputs: tmp_path — temporary pyproject metadata.
# returns: None.
# side_effects: Writes one temporary pyproject file.
# emitted_logs: None.
# error_behavior: Fails if a forbidden legacy entrypoint is silently accepted.
# END_FUNCTION_CONTRACT
def test_existing_legacy_entrypoint_check_remains_active(tmp_path):
    (tmp_path / "pyproject.toml").write_text("[project.scripts]\ngracectl = 'legacy:main'\n")
    errors = _MODULE.check_repo_hygiene(repo_root=tmp_path, paths=())
    assert "legacy entrypoint 'gracectl' found in pyproject.toml" in errors
