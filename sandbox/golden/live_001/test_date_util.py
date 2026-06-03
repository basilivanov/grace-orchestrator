# ############################################################################
# AI_HEADER: test_date_util
# ROLE: Tests for the date_util module.
# ############################################################################

# START_MODULE_CONTRACT
# purpose: Verify that today_iso returns a correctly formatted date string.
# inputs: None
# returns: None
# side_effects: None
# emitted_logs: None
# error_behavior: Fails if the date string doesn't match YYYY-MM-DD format.
# END_MODULE_CONTRACT

# START_MODULE_MAP
# mapping:
#   - function: test_today_iso
# END_MODULE_MAP

import datetime

from sandbox.golden.live_001.date_util import today_iso


# START_BLOCK_TEST_DATE_UTIL
# START_FUNCTION_CONTRACT
# name: test_today_iso
# purpose: Tests today_iso returns correct format and value.
# inputs:
#   None
# returns: None
# side_effects: None
# emitted_logs: None
# error_behavior: Raises AssertionError on failure.
# END_FUNCTION_CONTRACT
def test_today_iso() -> None:
    result = today_iso()
    assert isinstance(result, str)
    assert result == datetime.date.today().isoformat()


# END_BLOCK_TEST_DATE_UTIL
