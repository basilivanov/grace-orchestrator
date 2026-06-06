#!/usr/bin/env bash
# Start the GRACE supervisor in the foreground.
#
# The supervisor is the single entry point that owns API + worker
# processes. It exposes a unix-socket control endpoint that grace_ctl
# drives; you do not run this script more than once per environment.
#
# Required env (set by this script from .grace/config.yaml if present):
#   GRACE_DATABASE_URL — sqlite:/// or postgresql://...
#   GRACE_API_URL      — where workers call back to the API
# Optional:
#   GRACE_WORKERS      — number of worker processes (default 1)
#   GRACE_NO_WATCH     — if set, disable mtime auto-reload
set -euo pipefail

# Resolve directories. Two conventions:
#   1) Caller passes --target-dir and --source-dir explicitly.
#   2) Otherwise: target_dir = cwd, source_dir = $GRACE_SOURCE_DIR or $target_dir/..
DEFAULT_TARGET_DIR="${GRACE_TARGET_DIR:-$PWD}"
DEFAULT_SOURCE_DIR="${GRACE_SOURCE_DIR:-/tmp/grace-orchestrator-export}"

TARGET_DIR=""
SOURCE_DIR=""
WORKERS="${GRACE_WORKERS:-1}"
NO_WATCH_FLAG=()
POSITIONAL=()

while [[ $# -gt 0 ]]; do
  case "$1" in
    --target-dir) TARGET_DIR="$2"; shift 2 ;;
    --source-dir) SOURCE_DIR="$2"; shift 2 ;;
    --workers)    WORKERS="$2"; shift 2 ;;
    --no-watch)   NO_WATCH_FLAG+=("--no-watch"); shift ;;
    -h|--help)
      sed -n '2,17p' "$0"
      exit 0
      ;;
    *) POSITIONAL+=("$1"); shift ;;
  esac
done

TARGET_DIR="${TARGET_DIR:-$DEFAULT_TARGET_DIR}"
SOURCE_DIR="${SOURCE_DIR:-$DEFAULT_SOURCE_DIR}"

# Project-specific env from .grace/config.yaml (if present).
GRACE_CFG="$TARGET_DIR/.grace/config.yaml"
if [[ -f "$GRACE_CFG" ]]; then
  export GRACE_DATABASE_URL="${GRACE_DATABASE_URL:-$(grep -E '^\s*url:' "$GRACE_CFG" | head -1 | sed -E 's/.*url:\s*"?([^"]+)"?/\1/')}"
fi

# Project root for worker must be the target dir.
export GRACE_PROJECT_ROOT="$TARGET_DIR"
export GRACE_STATE_ROOT="$TARGET_DIR/.grace_state"
export GRACE_WORKTREE_ROOT="$TARGET_DIR/.grace_worktrees"
export GRACE_API_URL="${GRACE_API_URL:-http://127.0.0.1:8042}"
export GRACE_ALLOW_SANDBOX_BYPASS="${GRACE_ALLOW_SANDBOX_BYPASS:-true}"
export GRACE_LOG_DEBUG="${GRACE_LOG_DEBUG:-1}"
export GRACE_TARGET_DIR="$TARGET_DIR"
export GRACE_SUPERVISOR_SOCK="$TARGET_DIR/supervisor.sock"
export PYTHONPATH="${PYTHONPATH:-}:$SOURCE_DIR/src"

mkdir -p "$TARGET_DIR/.grace_state" "$TARGET_DIR/.grace_worktrees"

cd "$TARGET_DIR"

# Drop OPENCODE runtime vars from the parent shell.
# Without this, 'opencode run' in subprocesses picks them up and tries to
# attach to a nonexistent server session, failing with "Session not found".
for v in $(env | grep -E '^OPENCODE(_|$)' | cut -d= -f1); do unset "$v"; done
for v in $(env | grep -E '^OPENCODE$' | cut -d= -f1); do unset "$v"; done

# Hand off to the supervisor. From here on, the supervisor is the
# process tree root: SIGINT/SIGTERM go to it, and it propagates to
# children gracefully.
exec python3 -m grace_control.cli start \
  --target-dir "$TARGET_DIR" \
  --source-dir "$SOURCE_DIR" \
  --workers    "$WORKERS" \
  --api-url    "$GRACE_API_URL" \
  "${NO_WATCH_FLAG[@]}"
