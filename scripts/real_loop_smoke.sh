#!/usr/bin/env bash
set -euo pipefail

# real_loop_smoke.sh — thin shell wrapper over real_loop_smoke.py
# All paths/ports via env or CLI; no hardcoded absolute paths.
# Usage:
#   scripts/real_loop_smoke.sh --scenario one-wave-basic-backend \
#     --target-project /path/to/project \
#     --work-root /tmp/grace-real-smoke \
#     --profile NORMAL
#
# Or via env:
#   GRACE_REAL_SMOKE_TARGET_PROJECT=/path GRACE_REAL_SMOKE_WORK_ROOT=/tmp scripts/real_loop_smoke.sh --scenario one-wave-basic-backend

SELF_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SCRIPT_DIR="$(cd "$SELF_DIR" && pwd)"

GRACE_API_URL="${GRACE_API_URL:-http://127.0.0.1:8042}"
GRACE_REAL_SMOKE_WORK_ROOT="${GRACE_REAL_SMOKE_WORK_ROOT:-/tmp/grace-real-smoke}"
GRACE_REAL_SMOKE_TARGET_PROJECT="${GRACE_REAL_SMOKE_TARGET_PROJECT:-}"
GRACE_REAL_SMOKE_SOURCE_DIR="${GRACE_REAL_SMOKE_SOURCE_DIR:-}"
GRACE_REAL_SMOKE_PROFILE="${GRACE_REAL_SMOKE_PROFILE:-NORMAL}"
GRACE_DEV_TOOLS_ENABLED="${GRACE_DEV_TOOLS_ENABLED:-1}"
GRACE_DEV_KEEP_FAILED_WORKTREES="${GRACE_DEV_KEEP_FAILED_WORKTREES:-1}"

SCENARIO=""
VERBOSE=false
TIMEOUT_MINUTES=30

while [[ $# -gt 0 ]]; do
  case "$1" in
    --scenario) SCENARIO="$2"; shift 2 ;;
    --target-project) GRACE_REAL_SMOKE_TARGET_PROJECT="$2"; shift 2 ;;
    --work-root) GRACE_REAL_SMOKE_WORK_ROOT="$2"; shift 2 ;;
    --profile) GRACE_REAL_SMOKE_PROFILE="$2"; shift 2 ;;
    --source-dir) GRACE_REAL_SMOKE_SOURCE_DIR="$2"; shift 2 ;;
    --api-url) GRACE_API_URL="$2"; shift 2 ;;
    --timeout) TIMEOUT_MINUTES="$2"; shift 2 ;;
    --verbose) VERBOSE=true; shift ;;
    --help)
      echo "Usage: $0 --scenario <name> [options]"
      echo ""
      echo "Scenarios: one-wave-basic-backend, two-wave-recovery-resume, backend-frontend-browser-smoke"
      echo ""
      echo "Options:"
      echo "  --target-project PATH   Target project directory (or GRACE_REAL_SMOKE_TARGET_PROJECT)"
      echo "  --work-root PATH        Work root for runs (or GRACE_REAL_SMOKE_WORK_ROOT) [default: /tmp/grace-real-smoke]"
      echo "  --profile NAME          FAST, NORMAL, or STRICT [default: NORMAL]"
      echo "  --api-url URL           GRACE API URL [default: http://127.0.0.1:8042]"
      echo "  --source-dir PATH       Source dir for fixture specs"
      echo "  --timeout MINUTES       Max run time per scenario [default: 30]"
      echo "  --verbose               Verbose output"
      exit 0
      ;;
    *) echo "Unknown option: $1"; exit 1 ;;
  esac
done

if [[ -z "$SCENARIO" ]]; then
  echo "ERROR: --scenario is required"
  echo "Usage: $0 --scenario <name> [options]"
  exit 1
fi

if [[ -z "$GRACE_REAL_SMOKE_TARGET_PROJECT" ]]; then
  echo "ERROR: --target-project (or GRACE_REAL_SMOKE_TARGET_PROJECT) is required"
  exit 1
fi

if [[ ! -d "$GRACE_REAL_SMOKE_TARGET_PROJECT" ]]; then
  echo "ERROR: target project does not exist: $GRACE_REAL_SMOKE_TARGET_PROJECT"
  exit 1
fi

export GRACE_API_URL
export GRACE_REAL_SMOKE_WORK_ROOT
export GRACE_REAL_SMOKE_TARGET_PROJECT
export GRACE_REAL_SMOKE_SOURCE_DIR
export GRACE_REAL_SMOKE_PROFILE
export GRACE_DEV_TOOLS_ENABLED
export GRACE_DEV_KEEP_FAILED_WORKTREES

TIMESTAMP=$(date +%Y%m%d-%H%M%S)
RUN_DIR="$GRACE_REAL_SMOKE_WORK_ROOT/runs/$TIMESTAMP-$SCENARIO"
mkdir -p "$RUN_DIR"

echo "[smoke] Scenario : $SCENARIO"
echo "[smoke] API URL  : $GRACE_API_URL"
echo "[smoke] Work root: $GRACE_REAL_SMOKE_WORK_ROOT"
echo "[smoke] Run dir  : $RUN_DIR"
echo "[smoke] Profile  : $GRACE_REAL_SMOKE_PROFILE"
echo "[smoke] Target   : $(cd "$GRACE_REAL_SMOKE_TARGET_PROJECT" && pwd)"
echo ""

# Check API is alive first
API_CHECK=$(curl -sS --max-time 5 "$GRACE_API_URL/api/admin/system/health" 2>/dev/null || true)
if [[ -z "$API_CHECK" ]]; then
  echo "ERROR: GRACE API not reachable at $GRACE_API_URL"
  echo "Start the API first: python3 scripts/run_api.py"
  exit 1
fi
echo "[smoke] API health: OK"

# Delegate to Python harness
exec python3 "$SCRIPT_DIR/real_loop_smoke.py" \
  --scenario "$SCENARIO" \
  --run-dir "$RUN_DIR" \
  --api-url "$GRACE_API_URL" \
  --target-project "$(cd "$GRACE_REAL_SMOKE_TARGET_PROJECT" && pwd)" \
  --profile "$GRACE_REAL_SMOKE_PROFILE" \
  $( $VERBOSE && echo "--verbose" ) \
  $( [[ -n "$GRACE_REAL_SMOKE_SOURCE_DIR" ]] && echo "--source-dir $GRACE_REAL_SMOKE_SOURCE_DIR" ) \
  --timeout "$TIMEOUT_MINUTES"
