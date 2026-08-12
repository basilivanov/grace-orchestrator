# ############################################################################
# AI_HEADER: test_version_provider — deterministic Git version tests
# ROLE: Proves ordered candidate fallback and empty-result behavior for the
#      isolated VersionProvider subprocess boundary.
# ############################################################################

# START_MODULE_CONTRACT
# purpose: Verify VersionProvider selects the first successful Git candidate.
# inputs: Temporary paths and monkeypatched subprocess results.
# returns: Pytest assertions.
# side_effects: No real subprocess or network calls; subprocess is mocked.
# emitted_logs: None.
# error_behavior: Fails when fallback order or empty-result semantics regress.
# END_MODULE_CONTRACT

# START_MODULE_MAP
# mapping:
#   - function: test_first_valid_candidate_wins
#   - function: test_invalid_candidate_falls_through
#   - function: test_all_candidates_fail
# END_MODULE_MAP

from __future__ import annotations

from pathlib import Path

from grace_control.core.structured_logger import GraceLogger
from grace_control.services import version_provider
from grace_control.services.version_provider import VersionProvider

_log = GraceLogger("test_version_provider")


# START_BLOCK_VERSION_PROVIDER_TESTS
# START_FUNCTION_CONTRACT
# name: test_first_valid_candidate_wins
# purpose: Verify the first successful candidate terminates lookup.
# inputs: monkeypatch — mocked subprocess.run; tmp_path — candidate paths.
# returns: None.
# side_effects: Records mocked subprocess calls only.
# emitted_logs: None.
# error_behavior: AssertionError when candidate ordering changes.
# END_FUNCTION_CONTRACT
def test_first_valid_candidate_wins(monkeypatch, tmp_path: Path) -> None:
    calls: list[Path] = []

    class FakeGitService:
        def run_bounded(self, _args, repo: Path, *, max_output_bytes: int, timeout: int):
            calls.append(repo)
            return type("Result", (), {"success": True, "stdout": "abc123\n"})()

    monkeypatch.setattr(version_provider, "GitService", FakeGitService)
    first = tmp_path / "first"
    second = tmp_path / "second"
    assert VersionProvider((first, second)).current_sha() == "abc123"
    assert calls == [first]


# START_FUNCTION_CONTRACT
# name: test_invalid_candidate_falls_through
# purpose: Verify a failed Git candidate does not block later candidates.
# inputs: monkeypatch — mocked subprocess.run; tmp_path — candidate paths.
# returns: None.
# side_effects: Records mocked subprocess calls only.
# emitted_logs: None.
# error_behavior: AssertionError when fallback does not continue.
# END_FUNCTION_CONTRACT
def test_invalid_candidate_falls_through(monkeypatch, tmp_path: Path) -> None:
    calls: list[Path] = []

    class FakeGitService:
        def run_bounded(self, _args, repo: Path, *, max_output_bytes: int, timeout: int):
            calls.append(repo)
            success = len(calls) != 1
            return type("Result", (), {"success": success, "stdout": "def456\n" if success else ""})()

    monkeypatch.setattr(version_provider, "GitService", FakeGitService)
    first = tmp_path / "first"
    second = tmp_path / "second"
    assert VersionProvider((first, second)).current_sha() == "def456"
    assert calls == [first, second]


# START_FUNCTION_CONTRACT
# name: test_all_candidates_fail
# purpose: Verify all candidate failures produce the historical empty string.
# inputs: monkeypatch — mocked subprocess.run; tmp_path — candidate paths.
# returns: None.
# side_effects: Records mocked subprocess calls only.
# emitted_logs: None.
# error_behavior: AssertionError when failure leaks or raises unexpectedly.
# END_FUNCTION_CONTRACT
def test_all_candidates_fail(monkeypatch, tmp_path: Path) -> None:
    class FakeGitService:
        def run_bounded(self, _args, _repo: Path, *, max_output_bytes: int, timeout: int):
            return type("Result", (), {"success": False, "stdout": ""})()

    monkeypatch.setattr(version_provider, "GitService", FakeGitService)
    assert VersionProvider((tmp_path / "one", tmp_path / "two")).current_sha() == ""


# END_BLOCK_VERSION_PROVIDER_TESTS
