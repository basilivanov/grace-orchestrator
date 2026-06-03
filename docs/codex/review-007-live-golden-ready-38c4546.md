# Codex Review 007 — Live golden readiness after `38c4546`

Commit reviewed: `38c45469e0eaa6a132e8ee3b954c16f26cb09398`

Previous review: `docs/codex/review-006-live-golden-hardening-4a9e72a.md`

Verdict: **PASS — ready to run the first controlled live golden smoke.**

I verified the review-006 fixes in `origin/main` by inspecting the current files.

---

## Review-006 checklist

### P0-1 — stale `tests/test_e2e_mvp0.py` merge expectation

Status: **fixed.**

The test now expects commit-only merge to fail closed:

```python
r = await c.post(f"/api/packets/{pid}/merge", json={"commit_sha": "abc"})
assert r.status_code == 400
assert "worktree_path" in r.json()["detail"]
```

It also verifies the packet remains `accepted` after rejected merge.

---

### P1-1 — fake branch merge event test was non-deterministic

Status: **fixed.**

The events test now expects fake branch merge to return 409 and confirms no `packet_merged` event is emitted:

```python
assert r_merge.status_code == 409
assert "packet_merged" not in event_types
```

---

### P1-2 — accepted packet + missing merge inputs

Status: **fixed.**

`tests/api/test_packet_merge.py` now includes:

```python
test_merge_accepted_packet_missing_inputs_400
```

which creates an accepted packet, calls `/merge` with `{}`, and asserts 400 with `worktree_path` in the response detail.

---

## Golden YAML

`grace/features/golden-smoke-live-001.yaml` exists and is appropriate for the first controlled live smoke:

- one feature;
- one wave;
- one backend packet;
- writes only `src/date_util.py` and `tests/test_date_util.py`;
- root-level verification: `python -m pytest tests/test_date_util.py -q`;
- frozen scope protects `src/prefect_grace/` and `src/grace_control/`.

---

## Caveat

GitHub combined status for `38c4546` shows no CI/status checks. I cannot independently verify the claimed `149 tests passing` from GitHub Actions because no statuses are attached to the commit.

Given the code inspection, the review-006 blockers are closed enough to proceed with the controlled live smoke.

---

## Recommended live smoke command

Use a disposable branch and fresh DB:

```bash
git pull --ff-only origin main
git checkout -b golden/live-001

rm -f /tmp/grace-golden-live.db
export GRACE_DB_URL=sqlite:////tmp/grace-golden-live.db
export GRACE_AGENT_TIMEOUT=900
export GRACE_CONTEXT_DISABLED=true
```

Terminal 1:

```bash
grace api start
```

Terminal 2:

```bash
grace eval run grace/features/golden-smoke-live-001.yaml \
  --workers 1 \
  --timeout 900 \
  --report artifacts/golden-live-001.json
```

After run:

```bash
git status --short
git log --oneline -5
cat artifacts/golden-live-001.json
```

---

## Final verdict

**Ready for first controlled live golden smoke.**

Still do not enable broad unattended autorun until the first smoke report and git result are manually inspected.
