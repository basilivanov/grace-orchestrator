# ############################################################################
# AI_HEADER: version_provider — deterministic Git version lookup
# ROLE: Isolates the small Git version boundary used by lifecycle snapshots.
#      Callers provide candidate repositories explicitly and receive one short
#      commit identifier or an empty string when no candidate is usable.
# ############################################################################

# START_MODULE_CONTRACT
# purpose: Resolve the current short Git commit from ordered candidate paths.
# inputs: candidates: deterministic repository directories to probe.
# returns: Short commit SHA from the first successful candidate, or "".
# side_effects: Runs bounded Git commands in candidate directories.
# emitted_logs: None.
# error_behavior: Timeout, missing Git, invalid repository, and OS failures
#                 fall through to the next candidate.
# END_MODULE_CONTRACT

# START_MODULE_MAP
# mapping:
#   - class: VersionProvider
#     methods:
#       - __init__
#       - current_sha
# END_MODULE_MAP

from __future__ import annotations

from collections.abc import Sequence
from pathlib import Path

from grace_control.core.structured_logger import GraceLogger
from grace_control.services.git_service import GitService

_log = GraceLogger("version_provider")


# START_BLOCK_VERSION_PROVIDER
class VersionProvider:
    # START_FUNCTION_CONTRACT
    # name: __init__
    # purpose: Bind version lookup to an ordered set of candidate directories.
    # inputs: candidates — repository directories checked in order.
    # returns: None.
    # side_effects: None.
    # emitted_logs: None.
    # error_behavior: Candidates are copied to keep lookup ordering stable.
    # END_FUNCTION_CONTRACT
    def __init__(self, candidates: Sequence[Path]) -> None:
        self._candidates = tuple(Path(candidate) for candidate in candidates)
        self._git = GitService()

    # START_FUNCTION_CONTRACT
    # name: current_sha
    # purpose: Return the first successful Git short commit SHA.
    # inputs: None.
    # returns: Short commit SHA, or an empty string when all candidates fail.
    # side_effects: Runs Git commands with a two-second timeout.
    # emitted_logs: None.
    # error_behavior: Candidate command failures are ignored and the next
    #                 candidate is attempted.
    # END_FUNCTION_CONTRACT
    def current_sha(self) -> str:
        for candidate in self._candidates:
            result = self._git.run_bounded(
                ["rev-parse", "--short", "HEAD"],
                candidate,
                max_output_bytes=128,
                timeout=2,
            )
            if result.success and result.stdout.strip():
                return result.stdout.strip()
        return ""


# END_BLOCK_VERSION_PROVIDER
