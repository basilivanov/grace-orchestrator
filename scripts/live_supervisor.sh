#!/usr/bin/env bash
# Start the GRACE supervisor in the foreground.
#
# The supervisor is the single entry point that owns API + worker
# processes. It exposes a unix-socket control endpoint that grace_ctl
# drives; you do not run this script more than once per environment.
#
# Optional --repo-dir keeps the writable project repository separate from the
# control-state --target-dir. It defaults to GRACE_TARGET_REPO_ROOT/target-dir.
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
DEFAULT_SOURCE_DIR="${GRACE_SOURCE_DIR:-$(cd "$(dirname "$0")/.." && pwd)}"

TARGET_DIR=""
SOURCE_DIR=""
REPO_DIR=""
WORKERS="${GRACE_WORKERS:-1}"
NO_WATCH_FLAG=()
POSITIONAL=()

while [[ $# -gt 0 ]]; do
  case "$1" in
    --target-dir) TARGET_DIR="$2"; shift 2 ;;
    --source-dir) SOURCE_DIR="$2"; shift 2 ;;
    --repo-dir)   REPO_DIR="$2"; shift 2 ;;
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

# A supervisor may be launched through sudo -E, which intentionally preserves
# the caller's environment.  Resolve HOME from the actual runtime user so
# mini-swe/opencode state is writable by the worker owner instead of inheriting
# another user's private config directory.
if [[ -n "${GRACE_HOME:-}" ]]; then
  export HOME="$GRACE_HOME"
else
  RUNTIME_HOME="$(getent passwd "$(id -un)" 2>/dev/null | cut -d: -f6 || true)"
  if [[ -n "$RUNTIME_HOME" ]]; then
    export HOME="$RUNTIME_HOME"
  fi
fi

# Load runtime-only provider/model settings without exposing them on the
# supervisor command line.  Explicit caller environment keeps precedence.
RUNTIME_ENV_FILE="${GRACE_ENV_FILE:-$TARGET_DIR/.env}"
if [[ -r "$RUNTIME_ENV_FILE" ]]; then
  while IFS='=' read -r env_key env_value || [[ -n "$env_key" ]]; do
    [[ "$env_key" =~ ^[A-Za-z_][A-Za-z0-9_]*$ ]] || continue
    env_value="${env_value%$'\r'}"
    if [[ -z "${!env_key+x}" ]]; then
      export "$env_key=$env_value"
    fi
  done < "$RUNTIME_ENV_FILE"
fi

# Project-specific env from .grace/config.yaml (if present).
GRACE_CFG="$TARGET_DIR/.grace/config.yaml"
if [[ -f "$GRACE_CFG" ]]; then
  export GRACE_DATABASE_URL="${GRACE_DATABASE_URL:-$(grep -E '^\s*url:' "$GRACE_CFG" | head -1 | sed -E 's/.*url:\s*"?([^"]+)"?/\1/')}"
fi

# Keep the control-plane DB inside its runtime target by default.  A missing
# .grace/config.yaml must not silently redirect the API and workers to the
# shared /tmp/grace_live.db, because that hides the target's durable history.
export GRACE_DATABASE_URL="${GRACE_DATABASE_URL:-sqlite:///$TARGET_DIR/grace.db}"
# Scripts/run_api.py and scripts/live_worker.py also accept this legacy name.
export GRACE_DB_URL="${GRACE_DB_URL:-$GRACE_DATABASE_URL}"

# The control-plane runtime directory may be separate from the actual target
# repository (for example, a durable state directory under $HOME).  Keep the
# repository identity explicit so accepted packets merge into the project,
# while DB/artifacts/worktrees remain in the control runtime.
REPO_DIR="${REPO_DIR:-${GRACE_TARGET_REPO_ROOT:-$TARGET_DIR}}"
export GRACE_TARGET_REPO_ROOT="$REPO_DIR"
export GRACE_PROJECT_ROOT="${GRACE_PROJECT_ROOT:-$GRACE_TARGET_REPO_ROOT}"
export GRACE_STATE_ROOT="${GRACE_STATE_ROOT:-$TARGET_DIR/.grace/state}"
export GRACE_WORKTREE_ROOT="${GRACE_WORKTREE_ROOT:-$TARGET_DIR/.grace/worktrees}"
export GRACE_API_URL="${GRACE_API_URL:-http://127.0.0.1:8042}"
export GRACE_ALLOW_SANDBOX_BYPASS="${GRACE_ALLOW_SANDBOX_BYPASS:-true}"
export GRACE_RECOVERY_CONTROLLER_ENABLED="${GRACE_RECOVERY_CONTROLLER_ENABLED:-true}"
export GRACE_LOG_DEBUG="${GRACE_LOG_DEBUG:-0}"
# Agent timeout is an inactivity timeout: stdout/stderr or run artifacts must
# make progress within this window.  The hard cap is an independent safety net.
export GRACE_AGENT_TIMEOUT="${GRACE_AGENT_TIMEOUT:-600}"
export GRACE_AGENT_MAX_TIMEOUT="${GRACE_AGENT_MAX_TIMEOUT:-3600}"
# Coder routing is defined by enabled profiles and their priorities in
# agent_profiles.yaml.  An explicitly exported GRACE_CODER_EXECUTOR_LADDER
# remains available as an emergency per-launch override; the supervisor must
# not create one implicitly because that would bypass profile priorities.
export GRACE_TARGET_DIR="$TARGET_DIR"
export GRACE_SOURCE_DIR="$SOURCE_DIR"
# Prefer the W-engine installed with this orchestrator source tree.  The
# mini runner still falls back safely when this optional path is absent.
export GRACE_MINI_SWE_BINARY="${GRACE_MINI_SWE_BINARY:-$SOURCE_DIR/.venv/bin/mini}"
export GRACE_SUPERVISOR_SOCK="$TARGET_DIR/supervisor.sock"
export PYTHONPATH="${PYTHONPATH:-}:$SOURCE_DIR/src"

PYTHON_BIN="${GRACE_PYTHON_EXECUTABLE:-$SOURCE_DIR/.venv/bin/python}"
if [[ ! -x "$PYTHON_BIN" ]]; then
  PYTHON_BIN="$(command -v python3)"
fi

mkdir -p "$TARGET_DIR/.grace/state" "$TARGET_DIR/.grace/worktrees"

# Exactly one supervisor may own a control runtime.  The advisory lock is held
# by this file descriptor across exec and is released automatically on exit.
SUPERVISOR_LOCK_FILE="$TARGET_DIR/.grace/supervisor.lock"
exec {SUPERVISOR_LOCK_FD}>"$SUPERVISOR_LOCK_FILE"
if ! flock -n "$SUPERVISOR_LOCK_FD"; then
  printf 'GRACE supervisor is already running for %s\n' "$TARGET_DIR" >&2
  exit 73
fi

cd "$TARGET_DIR"

# Drop OPENCODE runtime vars from the parent shell.
# Without this, 'opencode run' in subprocesses picks them up and tries to
# attach to a nonexistent server session, failing with "Session not found".
for v in $(env | grep -E '^OPENCODE(_|$)' | cut -d= -f1); do unset "$v"; done
for v in $(env | grep -E '^OPENCODE$' | cut -d= -f1); do unset "$v"; done

# Hand off to the supervisor. From here on, the supervisor is the
# process tree root: SIGINT/SIGTERM go to it, and it propagates to
# children gracefully.
exec "$PYTHON_BIN" -m grace_control.cli start \
  --target-dir "$TARGET_DIR" \
  --source-dir "$SOURCE_DIR" \
  --workers    "$WORKERS" \
  --api-url    "$GRACE_API_URL" \
  "${NO_WATCH_FLAG[@]}"
