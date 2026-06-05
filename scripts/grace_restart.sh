#!/usr/bin/env bash
set -euo pipefail
# grace_restart — clean restart of GRACE API + worker

PROJECT="$(cd "$(dirname "$0")/.." && pwd)"
GRACE_DB_URL="${GRACE_DB_URL:-sqlite:////tmp/grace-eval/default.db}"
GRACE_STATE_ROOT="${GRACE_STATE_ROOT:-/tmp/grace-eval}"
PORT="${PORT:-8042}"
VENV_PYTHON="${PROJECT}/.venv/bin/python"
API_LOG="/tmp/grace-api.log"

echo "=== GRACE Restart ==="
echo "Project: $PROJECT"
echo "DB: $GRACE_DB_URL"
echo "State: $GRACE_STATE_ROOT"
echo "Port: $PORT"

# 1. Graceful shutdown of old processes
echo "[1/4] Stopping old processes..."
pkill -f "run_api.py" 2>/dev/null || true
pkill -f "self-w0" 2>/dev/null || true
sleep 1

# 2. Force-clean port if still stuck
echo "[2/4] Freeing port $PORT..."
fuser -k "${PORT}/tcp" 2>/dev/null || true
sleep 1

# 3. Clean stale worktrees
echo "[3/4] Pruning stale worktrees..."
if [ -d "$GRACE_STATE_ROOT" ]; then
    find "$GRACE_STATE_ROOT/worktrees" -maxdepth 1 -name "pkt_*" -type d 2>/dev/null | while read wt; do
        echo "  Removing stale worktree: $wt"
        git -C "$PROJECT" worktree remove "$wt" --force 2>/dev/null || rm -rf "$wt"
    done
    git -C "$PROJECT" worktree prune 2>/dev/null || true
fi

# 4. Start API
echo "[4/4] Starting API..."
PYTHONDONTWRITEBYTECODE=1 \
GRACE_DB_URL="$GRACE_DB_URL" \
GRACE_STATE_ROOT="$GRACE_STATE_ROOT" \
"$VENV_PYTHON" "$PROJECT/scripts/run_api.py" > "$API_LOG" 2>&1 &

API_PID=$!
echo "API PID: $API_PID"

# Wait for readiness
for i in $(seq 1 10); do
    sleep 1
    if curl -s -o /dev/null "http://localhost:${PORT}/api/health" 2>/dev/null; then
        echo "API ready on port $PORT"
        break
    fi
    if [ $i -eq 10 ]; then
        echo "WARN: API not responding after 10s"
        tail -5 "$API_LOG"
    fi
done

echo "=== Done ==="
echo "Logs: tail -f $API_LOG"
