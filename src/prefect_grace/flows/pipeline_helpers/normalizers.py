# ############################################################################
# AI_HEADER: pipeline_helpers.normalizers
# ROLE: Pure scalar normalizers for feature_pipeline.
# ############################################################################

# START_MODULE_CONTRACT
# purpose: Normalize scalar values used by feature_pipeline without state access or side effects.
# inputs: Arbitrary scalar values.
# returns: Normalized strings.
# side_effects: None.
# emitted_logs: None.
# error_behavior: None.
# END_MODULE_CONTRACT

# START_MODULE_MAP
# mapping:
#   - function: normalize_observability_scope
# END_MODULE_MAP

from __future__ import annotations


# START_FUNCTION_CONTRACT
# name: normalize_observability_scope
# purpose: Normalize an observability scope value for feature pipeline comparisons.
# inputs:
#   value: Raw observability scope value.
# returns: Lowercase underscore-separated scope string.
# side_effects: None.
# emitted_logs: None.
# error_behavior: None.
# END_FUNCTION_CONTRACT
def normalize_observability_scope(value: object) -> str:
    return str(value or "").strip().lower().replace("-", "_")


_normalize_observability_scope = normalize_observability_scope
