# ############################################################################
# AI_HEADER: lifecycle_settings — dynamic lifecycle target configuration
# ROLE: Owns the small environment/settings/default precedence used by the
#      lifecycle composition root without freezing values at import time.
# ############################################################################

# START_MODULE_CONTRACT
# purpose: Resolve the supervisor runtime target directory for lifecycle
#          composition at the moment a service graph is built.
# inputs: GRACE_TARGET_DIR and optional settings.target_dir.
# returns: Path for the runtime target directory.
# side_effects: Reads process environment through the configuration boundary.
# emitted_logs: None.
# error_behavior: Empty values fall through to the local live-runtime default.
# END_MODULE_CONTRACT

# START_MODULE_MAP
# mapping:
#   - function: get_lifecycle_target_dir
# END_MODULE_MAP

from __future__ import annotations

import os
from pathlib import Path

from grace_control.config.settings import settings
from grace_control.core.structured_logger import GraceLogger

_log = GraceLogger("lifecycle_settings")
_DEFAULT_TARGET_DIR = Path("/") / "tmp" / "grace-live-wt"


# START_FUNCTION_CONTRACT
# name: get_lifecycle_target_dir
# purpose: Apply GRACE_TARGET_DIR -> settings.target_dir -> local default
#          precedence dynamically for each lifecycle composition call.
# inputs: Current process environment and settings object.
# returns: Resolved supervisor target directory Path.
# side_effects: Reads environment and settings; does not mutate either.
# emitted_logs: None.
# error_behavior: Falsey values fall through to the local default directory.
# END_FUNCTION_CONTRACT
def get_lifecycle_target_dir() -> Path:
    return Path(os.environ.get("GRACE_TARGET_DIR") or getattr(settings, "target_dir", "") or _DEFAULT_TARGET_DIR)
