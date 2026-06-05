# Codex Review 006 — Live golden hardening after `4a9e72a`

Commit reviewed: `4a9e72a449785473362666e970a7f015d84f67f0`

Previous review: `docs/codex/review-005-live-golden-readiness-05b9729.md`

Verdict: **REWORK_REQUIRED before running the full test suite / live golden as a trusted signal.**

The merge endpoint hardening is directionally correct, but the test suite has at least one stale E2E test that still expects the old unsafe `commit_sha`-only merge behavior. There are also weak tests around merge success/failure.

---

## What is fixed

### P1-2 — merge endpoint requires `worktree_path` and `branch_name`

Status: **fixed.**

`merge_packet()` now fails closed immediately when inputs are missing:

```python
if not worktree_path or not branch_name:
    raise HTTPException(status_code=400,
        detail="worktree_path and branch_name are required for merge")
```

This closes the review-005 concern where a manual `/merge` call could transition a packet to `MERGED` without a real merge path.

---

### P1-1 — root verification propagation tests added

Status: **fixed enough.**

`tests/api/test_architect_api.py` now includes:

- `test_plan_propagates_root_verification_into_packets`
- `test_plan_packet_level_verification_overrides_root`

Good: this protects the root `verification` / `constraints.frozen_scope` propagation behavior.

---

### P1-1 — merge input guard tests added

Status: **fixed enough.**

`tests/api/test_packet_merge.py` now covers:

- missing `worktree_path` / `branch_name` returns 400;
- non-existent packet returns 404 when merge inputs are present;
- non-ACCEPTED packet returns 400.

Good.

---

## P0-1 — stale E2E test still expects unsafe commit-only merge

File: `tests/test_e2e_mvp0.py`

Current test still does:

```python
r = await c.post(f"/api/packets/{pid}/merge", json={"commit_sha": "abc"})
assert r.status_code == 200
assert r.json()["data"]["state"] == "merged"
```

But after this hardening, `/merge` correctly requires:

```json
{
  "worktree_path": "...",
  "branch_name": "..."
}
```

So this test should now fail with 400.

### Required fix

Change this E2E test into one of two forms:

#### Option A — API state-machine E2E only

If this test is only a state-machine/API smoke, update expectation:

```python
r = await c.post(f"/api/packets/{pid}/merge", json={"commit_sha": "abc"})
assert r.status_code == 400
assert "worktree_path" in r.json()["detail"]
```

Then do not assert final state is `merged`.

#### Option B — real merge E2E

If the test should verify `ACCEPTED → MERGED`, create a real temp git repo, real branch, real worktree path, then call `/merge` with real values.

For now, Option A is probably better because `tests/test_e2e_mvp0.py` is an ASGI/API vertical slice, not a git integration test.

---

## P1-1 — merge success/failure tests are still weak

`tests/api/test_events_api.py::test_merge_generates_event` now calls merge with:

```python
{"worktree_path": "/tmp/fake-wt", "branch_name": "agent/test"}
```

Then it conditionally accepts either outcome:

```python
if r_merge.status_code == 200:
    assert "packet_merged" in event_types
else:
    assert "packet_merged" not in event_types
```

This test cannot catch much because both success and failure are acceptable.

### Required improvement

Split it into two deterministic tests:

1. **merge failure path** with a fake branch:

```python
assert r_merge.status_code == 409
assert "packet_merged" not in event_types
```

2. **merge success path** only if using a real temp git branch/worktree:

```python
assert r_merge.status_code == 200
assert "packet_merged" in event_types
```

For immediate hardening, at least make the current fake-branch test assert `409` explicitly.

---

## P1-2 — new `test_merge_requires_worktree_and_branch` uses nonexistent packet

Current test:

```python
r = await api.post("/api/packets/nonexistent/merge", json={})
assert r.status_code == 400
```

This is consistent with current endpoint order: input validation happens before packet lookup. That is acceptable, but add a second test with an existing accepted packet and missing inputs, so the guard is proven on the real state path too.

Suggested test:

```python
# create packet → claim → release accepted
r = await api.post(f"/api/packets/{pid}/merge", json={})
assert r.status_code == 400
assert "worktree_path" in r.json()["detail"]
```

---

## P1-3 — no CI/status evidence visible

GitHub combined status for `4a9e72a449785473362666e970a7f015d84f67f0` returned no statuses.

Before live golden, run at least:

```bash
pytest tests/test_e2e_mvp0.py -q
pytest tests/api/test_packet_merge.py -q
pytest tests/api/test_events_api.py -q
pytest tests/api/test_architect_api.py -q
pytest tests/grace_control -q
```

Expected right now: `tests/test_e2e_mvp0.py` should fail until updated.

---

## Recommended immediate patch

1. Update `tests/test_e2e_mvp0.py` to expect 400 on commit-only merge, or create real git merge inputs.
2. Make `test_merge_generates_event` deterministic: fake branch must return 409 and no `packet_merged` event.
3. Add accepted-packet-with-missing-merge-input test.
4. Run focused tests.

---

## Live golden selection note

Do not use `grace/features/golden.yaml` as the first live golden yet. It has two waves and NORMAL packets without explicit `verification`, making it too broad/noisy for first live validation.

Use the micro YAML from the previous recommendation:

```yaml
title: Golden Smoke Live 001
description: "Minimal live golden test: one backend utility plus one test."

verification:
  - python -m pytest tests/test_date_util.py -q

constraints:
  frozen_scope:
    - src/prefect_grace/
    - src/grace_control/

waves:
  - title: Backend smoke
    packets:
      - title: Add date utility
        scope:
          - src/date_util.py
          - tests/test_date_util.py
        acceptance_profile: NORMAL
```

But first fix the stale E2E test so the local suite is not knowingly red.

---

## Final verdict

**REWORK_REQUIRED before trusted live golden.**

The code hardening is mostly correct, but at least one existing E2E test still encodes the old unsafe merge contract. Fix that before using live golden as a meaningful signal.
