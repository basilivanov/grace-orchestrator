# Review blocked: d941190 file-level review source mismatch

Status: BLOCKED / SOURCE MISMATCH
Date: 2026-06-12
Requested review target: `d941190b159c4d5e26cf7e42d5d766122d340eba`
Requested scope: file-level review of Business Feature Intake + Planning Pipeline Waves 1-4

## Summary

A real file-level review cannot be completed from the currently accessible GitHub source.

The local runner/user evidence says:

```text
git log --oneline origin/main -1
 d941190 feat: business feature intake + planning pipeline (Waves 1-4)

git rev-parse HEAD
 d941190b159c4d5e26cf7e42d5d766122d340eba

git rev-parse origin/main
 d941190b159c4d5e26cf7e42d5d766122d340eba
```

But the GitHub connector source available during review does not expose that commit or the expected files.

## Evidence

### 1. Commit compare failed

Attempted compare:

```text
base = 1f306db
head = d941190b159c4d5e26cf7e42d5d766122d340eba
```

Result from GitHub connector:

```text
404 Not Found
```

### 2. Commit fetch failed earlier by short SHA

Attempted fetch:

```text
d941190
```

Result from GitHub connector:

```text
No commit found for SHA: d941190
```

### 3. `main` content visible to reviewer is stale

The currently visible `src/grace_control/api/routers/features.py` contains only:

```text
GET /api/features/
GET /api/features/{feature_id}
```

It does not contain the expected new endpoints from Waves 1-4:

```text
POST /api/features
GET /api/features/{id}/planning
POST /api/features/{id}/approve-plan
POST /api/features/{id}/regenerate-plan
GET /api/features/{id}/planning/{run_id}/logs
```

Therefore the accessible GitHub source is not the same codebase state as the user's reported `origin/main`.

## Review decision

Do not treat the previous summary-based review as file-level verification.

Current decision:

```text
BLOCKED: file-level review cannot be performed until the reviewer can access the actual d941190 tree/diff.
```

## Required next input for real review

Provide one of the following:

### Option A — upload patch

Run locally in the real repo:

```bash
git show --stat --oneline d941190b159c4d5e26cf7e42d5d766122d340eba > /tmp/d941190.stat.txt
git show --find-renames --find-copies --patch d941190b159c4d5e26cf7e42d5d766122d340eba > /tmp/d941190.patch
```

Then upload both files.

### Option B — upload changed files bundle

Run:

```bash
mkdir -p /tmp/d941190-review-bundle

git diff --name-only 1f306db..d941190b159c4d5e26cf7e42d5d766122d340eba \
  | rsync -a --files-from=- ./ /tmp/d941190-review-bundle/

cd /tmp
tar -czf d941190-review-bundle.tar.gz d941190-review-bundle
```

Then upload `d941190-review-bundle.tar.gz`.

### Option C — make GitHub source visible

Ensure the GitHub repository accessible to the connector contains:

```text
d941190b159c4d5e26cf7e42d5d766122d340eba
```

Then rerun the review.

## What the real file-level review must check

Once the actual files are accessible, review must inspect at least:

```text
src/grace_control/api/routers/features.py
src/grace_control/api/routers/architect.py
src/grace_control/api/routers/admin.py
src/grace_control/db/schema.py
src/grace_control/services/feature_intake_service.py
src/grace_control/services/feature_planning_service.py
src/grace_control/services/process_supervisor.py
src/grace_control/services/agent_run_service.py
src/grace_control/ui/static/admin.js
src/grace_control/ui/static/admin.html
migrations / alembic version 0017
tests/api/*feature*planning*
tests/grace_control/services/*feature*planning*
tests/ui/*feature*planning*
```

Required review questions:

1. Does Admin UI really call `/api/features`, not `/api/architect/plan`?
2. Is `/api/architect/plan` now only a compatibility wrapper?
3. Is planning orchestration actually in services, not routers?
4. Does `FeaturePlanningRun` persist context/architect/materialize runs?
5. Are events feature-level and stored through `payload_json`?
6. Does approve materialize waves/packets exactly once?
7. Does approved feature enter existing queue semantics?
8. Does Wave 4 implement live streaming logs, or only a read endpoint?
9. Are log endpoints safe against arbitrary path reads?
10. Are tests meaningful and tied to the new behavior?

## Final status

No file-level acceptance can be issued yet.

This is intentionally a blocker report to prevent a false-positive review.
