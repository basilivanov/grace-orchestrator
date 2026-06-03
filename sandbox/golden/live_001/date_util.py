# ############################################################################
# AI_HEADER: date_util
# ROLE: Tiny utility to get today's date in ISO format.
# ############################################################################

# START_MODULE_CONTRACT
# purpose: Provides a utility function to get today's date in YYYY-MM-DD format.
# inputs: None
# returns: Date string in ISO format.
# side_effects: None
# emitted_logs: Logs the generated date
# error_behavior: None
# END_MODULE_CONTRACT

# START_MODULE_MAP
# mapping:
#   - function: today_iso
# END_MODULE_MAP

import datetime

from grace_control.core.structured_logger import log_event  # type: ignore[import-untyped]


# START_BLOCK_DATE_UTIL
# START_FUNCTION_CONTRACT
# name: today_iso
# purpose: Returns today's date in YYYY-MM-DD ISO format.
# inputs:
#   None
# returns: str
# side_effects: None
# emitted_logs: One log_event call
# error_behavior: None
# END_FUNCTION_CONTRACT
def today_iso() -> str:
    result = datetime.date.today().isoformat()
    log_event(
        "INFO",
        "today_iso_called",
        packet_id="FEAT-GOLDEN-SMOKE-LIVE-001-GOLDEN-SMOKE-LIVE-001-W01-P01-ADD-SANDBOX-DATE",
        result=result,
    )
    return result


# END_BLOCK_DATE_UTIL
