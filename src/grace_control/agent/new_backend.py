# ############################################################################
# AI_HEADER: new_backend
# ROLE: Back-compat shim — ApiAgentBackend moved to api_backend.py in W7 of
#       source/codex/tz-api-first-cleanup-waves-w0-w11.md. Old code that
#       imports `NewDirectBackend` still works.
# ############################################################################

# START_MODULE_CONTRACT
# purpose: Re-export ApiAgentBackend as NewDirectBackend for legacy imports.
# inputs: N/A.
# returns: N/A.
# side_effects: None.
# emitted_logs: None.
# error_behavior: None.
# END_MODULE_CONTRACT

# START_MODULE_MAP
# mapping:
#   - alias: NewDirectBackend -> ApiAgentBackend
# END_MODULE_MAP

from grace_control.agent.api_backend import ApiAgentBackend as NewDirectBackend  # noqa: F401
