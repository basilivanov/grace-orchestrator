# ############################################################################
# AI_HEADER: test_str_util
# ROLE: Tests for str_util
# ############################################################################

# START_MODULE_CONTRACT
# purpose: Test string reversing functionality.
# inputs: None
# returns: None
# side_effects: None
# emitted_logs: None
# error_behavior: Fails on incorrect output
# END_MODULE_CONTRACT

from sandbox.golden.live_002.str_util import reverse_str


# START_BLOCK_TEST_STR_UTIL
def test_reverse_str():
    assert reverse_str("hello") == "olleh"
    assert reverse_str("") == ""
    assert reverse_str("a") == "a"
    assert reverse_str("racecar") == "racecar"


# END_BLOCK_TEST_STR_UTIL
