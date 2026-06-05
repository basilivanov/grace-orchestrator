# Golden Smoke Runbook

## Prerequisites

```bash
command -v python3
command -v agy
command -v opencode
```

All three must exist before the full TZ-008 golden smoke, because:
- deterministic T1 uses `python3`;
- Evidence Verifier uses `agy`;
- Reviewer uses `opencode`.

## Setup

```bash
git pull --ff-only origin main
git checkout -b golden/live-001

rm -f /tmp/grace-golden-live.db
export GRACE_DB_URL=sqlite:////tmp/grace-golden-live.db
export GRACE_AGENT_TIMEOUT=1200
export GRACE_CONTEXT_DISABLED=true
```

## Terminal 1 — API

```bash
grace api start
```

## Terminal 2 — Eval

```bash
mkdir -p artifacts

grace eval run grace/features/golden-smoke-live-001.yaml \
  --workers 1 \
  --timeout 1200 \
  --report artifacts/golden-live-001.json
```

## Post-run verification

```bash
git status --short
git log --oneline -5
cat artifacts/golden-live-001.json
find sandbox/golden/live_001 -maxdepth 2 -type f -print
```

Expected:
- one packet should reach merged
- changes should be only under `sandbox/golden/live_001/`
- report JSON should show no failed packet
