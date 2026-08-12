# ############################################################################
# AI_HEADER: runtime_state_store — persistent supervisor runtime-state access
# ROLE: Owns the narrow filesystem boundary for the live supervisor state file.
#      Lifecycle composition injects this store into read and control services.
# ############################################################################

# START_MODULE_CONTRACT
# purpose: Locate, inspect, and parse the supervisor.json state file for one
#          explicitly supplied runtime target directory.
# inputs: target_dir: filesystem directory containing supervisor.json.
# returns: RuntimeStateStore methods expose the path, physical presence, and a
#          parsed mapping when the state file is readable and valid.
# side_effects: Reads one local JSON file; never writes runtime state.
# emitted_logs: None.
# error_behavior: Missing, unreadable, malformed, or non-mapping JSON returns
#                 None from read(); exists() remains a physical-path check.
# END_MODULE_CONTRACT

# START_MODULE_MAP
# mapping:
#   - class: RuntimeStateStore
#     methods:
#       - __init__
#       - target_dir
#       - state_path
#       - exists
#       - read
# END_MODULE_MAP

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from grace_control.core.structured_logger import GraceLogger

_log = GraceLogger("runtime_state_store")


# START_BLOCK_RUNTIME_STATE_STORE
class RuntimeStateStore:
    # START_FUNCTION_CONTRACT
    # name: __init__
    # purpose: Bind the state store to one runtime target directory.
    # inputs: target_dir — directory containing supervisor.json.
    # returns: None.
    # side_effects: None.
    # emitted_logs: None.
    # error_behavior: Path-like input is normalized to Path.
    # END_FUNCTION_CONTRACT
    def __init__(self, target_dir: Path) -> None:
        self._target_dir = Path(target_dir)
        self._state_file_path = self._target_dir / "supervisor.json"

    # START_FUNCTION_CONTRACT
    # name: target_dir
    # purpose: Return the explicitly configured runtime target directory.
    # inputs: None.
    # returns: Path for the runtime target directory.
    # side_effects: None.
    # emitted_logs: None.
    # error_behavior: Never raises after construction.
    # END_FUNCTION_CONTRACT
    @property
    def target_dir(self) -> Path:
        return self._target_dir

    # START_FUNCTION_CONTRACT
    # name: state_path
    # purpose: Return the supervisor state-file path for this target.
    # inputs: None.
    # returns: target_dir / supervisor.json.
    # side_effects: None.
    # emitted_logs: None.
    # error_behavior: Never raises after construction.
    # END_FUNCTION_CONTRACT
    @property
    def state_path(self) -> Path:
        return self._state_file_path

    # START_FUNCTION_CONTRACT
    # name: exists
    # purpose: Determine whether supervisor.json physically exists.
    # inputs: None.
    # returns: True when the state path exists, otherwise False.
    # side_effects: Performs a filesystem metadata read.
    # emitted_logs: None.
    # error_behavior: Filesystem errors are treated as non-existence by Path.
    # END_FUNCTION_CONTRACT
    def exists(self) -> bool:
        return self._state_file_path.exists()

    # START_FUNCTION_CONTRACT
    # name: read
    # purpose: Read and parse supervisor.json without conflating parse success
    #          with physical file presence.
    # inputs: None.
    # returns: Parsed state mapping, or None for missing/unreadable/malformed
    #          or non-mapping JSON.
    # side_effects: Reads supervisor.json from the local filesystem.
    # emitted_logs: None.
    # error_behavior: JSON and OS read errors return None.
    # END_FUNCTION_CONTRACT
    def read(self) -> dict[str, Any] | None:
        try:
            value = json.loads(self._state_file_path.read_text())
        except (json.JSONDecodeError, OSError, UnicodeError):
            return None
        return value if isinstance(value, dict) else None


# END_BLOCK_RUNTIME_STATE_STORE
