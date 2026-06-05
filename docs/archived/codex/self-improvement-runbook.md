# Self-Improvement Runbook

## Before running

- run from clean target repo (`git status --short` should be clean)
- use explicit `/tmp` state/worktree roots
- use `GRACE_BASE_REF=HEAD` for local runs unless base_ref is explicitly passed through end-to-end
- admin UI changes should use `NORMAL` or `STRICT`, not `FAST` by default
- core/runtime/worker/git/merge changes require `STRICT`
- verify no runtime state is created in target repo except intentional files
- use returned NanoID UIDs from API responses (`feature_id=feat_...`, `packet_id=pkt_...`); never derive IDs from title/slug such as `FEAT-...`

## Identity model

The control plane now separates canonical IDs from readable labels:

```text
Feature.id = feat_<nanoid>   # canonical UID / API identity
Feature.slug = title slug    # readable label only

Wave.id = wave_<nanoid>
Wave.slug = title slug

Packet.id = pkt_<nanoid>
Packet.slug = title slug
```

Self-improvement scripts, admin UI links, merge/retry actions, and polling must use returned UIDs.
Slugs/titles are display/search metadata only and must not be used as primary keys or idempotency keys.

## Environment

```bash
export GRACE_TARGET_REPO_ROOT="$PWD"
export GRACE_STATE_ROOT="/tmp/grace-self-improvement/<run-id>/state"
export GRACE_WORKTREE_ROOT="/tmp/grace-self-improvement/<run-id>/worktrees"
export GRACE_BASE_REF="HEAD"
export GRACE_DB_URL="sqlite:////tmp/grace-self-improvement/<run-id>/grace.db"
export GRACE_AGENT_TIMEOUT=1200
export GRACE_CONTEXT_DISABLED=true
```

## Terminal 1 — API

```bash
grace api start
```

## Terminal 2 — Eval

```bash
grace eval run grace/features/self-improvement.yaml \
  --workers 1 \
  --timeout 1200 \
  --control-plane-root "$PWD" \
  --target-repo-root "$PWD" \
  --state-root /tmp/grace-self-improvement/<run-id>/state \
  --worktree-root /tmp/grace-self-improvement/<run-id>/worktrees \
  --base-ref HEAD \
  --report /tmp/grace-self-improvement/<run-id>/report.json
```

## Reading IDs from plan responses

When creating a self-improvement/admin feature through `/api/architect/plan`, capture IDs from the response:

```bash
FEATURE_ID=$(jq -r '.data.feature_id' plan.json)
PACKET_ID=$(jq -r '.data.packet_summaries[0].id // .data.packet_ids[0] // .data.packets[0]' plan.json)
```

Do not compute IDs from title, slug, wave order, or packet order.
