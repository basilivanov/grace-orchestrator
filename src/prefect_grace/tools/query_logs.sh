#!/bin/bash
# Query execution logs using jq

STATE_ROOT="${1:-state}"
LOGS_FILE="${2:-/tmp/all_logs.jsonl}"

# Get the directory where this script is located
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# Aggregate logs first
if ! python3 "$SCRIPT_DIR/aggregate_logs.py" "$STATE_ROOT" > "$LOGS_FILE" 2>/dev/null; then
    echo "Error: Failed to aggregate logs from $STATE_ROOT" >&2
    exit 1
fi

# Check if logs file is empty
if [ ! -s "$LOGS_FILE" ]; then
    echo "No logs found in $STATE_ROOT" >&2
    exit 0
fi

# Query functions
query_executor_selections() {
    echo "=== Executor Selections ==="
    jq -r 'select(.event == "EXECUTOR_SELECTED") |
           "\(.timestamp) | \(.packet_id) | \(.complexity) -> \(.model)"' \
           "$LOGS_FILE" 2>/dev/null || echo "No executor selections found"
}

query_failures() {
    echo "=== Failures ==="
    jq -r 'select(.event == "PACKET_END" and .status == "failed") |
           "\(.timestamp) | \(.packet_id) | \(.role) | \(.reason)"' \
           "$LOGS_FILE" 2>/dev/null || echo "No failures found"
}

query_metrics() {
    echo "=== Metrics Summary ==="
    jq -s '
           def safe_div(a; b): if b == 0 then 0 else a / b end;
           map(select(.event == "EXECUTION_METRICS")) |
           if length > 0 then {
             total_executions: length,
             total_cost: (map(.cost_usd // 0) | add),
             total_tokens: (map(.total_tokens // 0) | add),
             avg_duration: safe_div((map(.duration_seconds // 0) | add); length)
           } else {
             total_executions: 0,
             total_cost: 0,
             total_tokens: 0,
             avg_duration: 0
           } end' \
           "$LOGS_FILE" 2>/dev/null || echo '{"error": "No metrics found"}'
}

query_rotation_events() {
    echo "=== Executor Rotations ==="
    jq -r 'select(.event == "EXECUTOR_SELECTED" and .reason == "rotation") |
           "\(.timestamp) | \(.packet_id) | \(.previous_executor) -> \(.executor_id)"' \
           "$LOGS_FILE" 2>/dev/null || echo "No rotation events found"
}

query_all_events() {
    echo "=== All Events ==="
    jq -r '"\(.timestamp) | \(.event) | \(.packet_id // "N/A")"' \
           "$LOGS_FILE" 2>/dev/null || echo "No events found"
}

# Main menu
case "${3:-menu}" in
    selections) query_executor_selections ;;
    failures) query_failures ;;
    metrics) query_metrics ;;
    rotations) query_rotation_events ;;
    all) query_all_events ;;
    *)
        echo "Usage: $0 [state_root] [logs_file] [query]"
        echo ""
        echo "Queries:"
        echo "  selections - Show all executor selections"
        echo "  failures   - Show all packet failures"
        echo "  metrics    - Show metrics summary"
        echo "  rotations  - Show executor rotation events"
        echo "  all        - Show all events chronologically"
        echo ""
        echo "Examples:"
        echo "  $0 state /tmp/logs.jsonl selections"
        echo "  $0 state /tmp/logs.jsonl metrics"
        echo "  $0 state /tmp/logs.jsonl all"
        ;;
esac
