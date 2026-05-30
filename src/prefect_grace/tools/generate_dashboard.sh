#!/bin/bash
# Generate cost dashboard

set -e

STATE_ROOT="${1:-state}"
OUTPUT_DIR="${2:-.}"

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# Validate state root exists
if [ ! -d "$STATE_ROOT" ]; then
    echo "Error: State root directory not found: $STATE_ROOT"
    echo "Usage: $0 [STATE_ROOT] [OUTPUT_DIR]"
    exit 1
fi

# Create output directory if needed
mkdir -p "$OUTPUT_DIR"

# Generate metrics JSON
echo "Generating metrics from $STATE_ROOT..."
python3 "$SCRIPT_DIR/aggregate_metrics.py" "$STATE_ROOT" > "$OUTPUT_DIR/metrics.json"

if [ $? -ne 0 ]; then
    echo "Error: Failed to generate metrics"
    exit 1
fi

# Copy dashboard HTML
cp "$SCRIPT_DIR/dashboard.html" "$OUTPUT_DIR/dashboard.html"

echo ""
echo "Dashboard generated successfully!"
echo ""
echo "  Metrics: $OUTPUT_DIR/metrics.json"
echo "  Dashboard: $OUTPUT_DIR/dashboard.html"
echo ""
echo "Open in browser:"
echo "  file://$(cd "$OUTPUT_DIR" && pwd)/dashboard.html"
echo ""
