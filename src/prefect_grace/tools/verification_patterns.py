"""
Success and failure patterns for orchestrator verification.
"""

SUCCESS_PATTERNS = {
    "executor_selection": {
        "description": "Verify complexity routing works",
        "checks": [
            "Simple packets use coder-cheap (gemini-3.5-flash)",
            "Medium packets use coder-standard (gemini-3.1-pro)",
            "Complex packets use coder-premium (claude-opus-4)"
        ]
    },
    "executor_rotation": {
        "description": "Verify rotation after failures",
        "checks": [
            "After 2 consecutive failures, different executor selected",
            "Rotation respects priority order"
        ]
    },
    "status_transitions": {
        "description": "All packets reach terminal state",
        "checks": [
            "No packets stuck in 'running' state",
            "All packets either 'accepted' or 'blocked'"
        ]
    },
    "metrics_present": {
        "description": "Metrics collected for all executions",
        "checks": [
            "Token counts recorded",
            "Cost calculated",
            "Duration tracked"
        ]
    }
}

FAILURE_PATTERNS = {
    "executor_stuck": "Same executor fails 3+ times without rotation",
    "wrong_model": "Complex packet routed to cheap model",
    "status_drift": "Packet stuck in 'running' for >1 hour",
    "missing_logs": "No log_event calls for critical decisions"
}
