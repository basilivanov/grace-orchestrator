# ############################################################################
# AI_HEADER: str_util
# ROLE: Tiny utility to reverse strings.
# ############################################################################

# START_MODULE_CONTRACT
# purpose: Provides a utility function to reverse strings.
# inputs: string
# returns: Reversed string.
# side_effects: None
# emitted_logs: Logs the operation
# error_behavior: None
# END_MODULE_CONTRACT

# START_MODULE_MAP
# mapping:
#   - function: reverse_str
# END_MODULE_MAP

from grace_control.core.structured_logger import log_event  # type: ignore[import-untyped]


# START_BLOCK_STR_UTIL
# START_FUNCTION_CONTRACT
# name: reverse_str
# purpose: Returns the reversed string.
# inputs:
#   s (str): The string to reverse
# returns: str
# side_effects: None
# emitted_logs: One log_event call
# error_behavior: None
# END_FUNCTION_CONTRACT
def reverse_str(s: str) -> str:
    result = s[::-1]
    log_event(
        "INFO",
        "reverse_str_called",
        packet_id="pkt_y2Zm5HF1Qy",
        input_str=s,
        result=result,
    )
    return result


# END_BLOCK_STR_UTIL
