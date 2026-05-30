#!/bin/bash
# Alert on orchestrator health issues

STATE_ROOT="${1:-state}"
ALERT_FILE="${2:-/tmp/orchestrator_alerts.log}"

# Run health check
HEALTH_OUTPUT=$(python3 "$(dirname "$0")/health_check.py" "$STATE_ROOT")
STATUS=$(echo "$HEALTH_OUTPUT" | jq -r '.status')

# Alert if not healthy
if [ "$STATUS" != "healthy" ]; then
    TIMESTAMP=$(date -Iseconds)
    echo "[$TIMESTAMP] ALERT: Orchestrator status is $STATUS" >> "$ALERT_FILE"
    echo "$HEALTH_OUTPUT" >> "$ALERT_FILE"

    # Could send to monitoring system here
    # curl -X POST https://monitoring.example.com/alerts -d "$HEALTH_OUTPUT"
fi

echo "$HEALTH_OUTPUT"
exit $?
