# Codex Review 005 — Live golden readiness after `05b9729`

Commit reviewed: `05b9729399c23b1ebb401eb0fa7e0d773172787f`

Previous review: `docs/codex/review-004-pipeline-readiness-before-live-golden.md`

Verdict: **READY FOR DISPOSABLE LIVE GOLDEN / NOT YET PRODUCTION AUTORUN**

The three P0 blockers from review-004 are addressed enough to start a controlled live golden run in a disposable branch + fresh DB.

Do not yet treat the system as production-grade autonomous autorun, because there are still P1 hardening gaps and I did not see CI/test evidence in GitHub.

---

## P0 status from review-004

### P0-1 — root `verification` / `constraints` not propagated to packet `spec_json`

Status: **fixed enough for golden.**

`create_plan()` now propagates root defaults into each packet:

```python
root_verification = spec.get("verification", [])
root_constraints = spec.get("constraints", {})
enriched_spec.setdefault("verification", root_verification)
enriched_spec.setdefault("frozen_scope",
    root_constraints.get("frozen_scope", ["src/prefect_grace/"]))
```

This means explicit YAML and architect-generated plans with root-level `verification` should no longer create NORMAL packets with missing verification by default.

Remaining P1: only `frozen_scope` is propagated from `constraints`. `forbidden_imports` and `python_version` are still not used by the acceptance gate. That is not a live-golden blocker.

---

### P0-2 — merge endpoint marked `MERGED` even if git merge failed

Status: **fixed enough for golden.**

`merge_packet()` now attempts git merge before state transition:

```python
mr = git merge branch_name --no-edit --no-ff
if mr.returncode != 0:
    merge_ok = False
...
if not merge_ok:
    raise HTTPException(status_code=409, ...)
...
packet.state = PacketState.MERGED.value
```

This removes the previous false-green risk where `eval run` could show `merged` even though git merge failed.

Remaining P1: if someone calls merge manually without `worktree_path`/`branch_name`, it can still transition to `MERGED` without a real merge attempt. Worker normally supplies both, so this is not a blocker for controlled golden, but the endpoint should be hardened later.

Recommended hardening:

```python
if not worktree_path or not branch_name:
    raise HTTPException(status_code=400, detail="worktree_path and branch_name are required for merge")
```

unless `commit_sha`-only merge becomes a supported separate path.

---

### P0-3 — `grace eval run` crashed on missing `/api/events`

Status: **fixed enough for golden.**

`eval_run()` now wraps event fetching:

```python
try:
    r2 = c.get(...)
    evs = r2.json().get("data", []) if r2.status_code == 200 else []
except Exception:
    evs = []
```

So the missing events router should no longer break evaluation report collection.

Remaining P1: `/api/events` is still not actually implemented/included. Reports will be less useful, but the golden run should not crash because of it.

---

## Prompt/profile hardening

### Coder mode in `AGENTS.md`

Status: **fixed.**

`AGENTS.md` now explicitly says:

- Coder is not architect.
- Do not rename spec fields.
- Do not replace required functions/classes with convenient equivalents.
- If implementation conflicts with TZ, change implementation.
- If exact implementation is impossible, stop and return BLOCKER.

Good.

### Coder reasoning reduced

Status: **fixed.**

`agent_profiles.yaml` now has:

```yaml
coder-flash:
  reasoning: medium

roles:
  coder:
    reasoning: medium
```

This matches the intended “literal executor” behavior better than max/high reasoning for coder.

---

## Remaining P1 gaps before production autorun

### P1-1 — no visible regression tests for review-004 fixes

I did not find obvious tests covering:

- root `verification`/`constraints` propagation into packet `spec_json`;
- merge failure returns 409 and keeps packet out of `MERGED`;
- eval report survives missing `/api/events`.

Recommended tests:

```bash
pytest tests/grace_control/api/test_architect_plan.py -q
pytest tests/grace_control/api/test_packet_merge.py -q
pytest tests/grace_control/cli/test_eval_run.py -q
```

or add these if they do not exist.

This is not a blocker for a controlled disposable golden, but it is a blocker for trusting future refactors.

---

### P1-2 — merge endpoint should require merge inputs

As noted above, manual `/merge` without `worktree_path`/`branch_name` can still transition to `MERGED`.

Worker path is okay, but endpoint should fail closed.

---

### P1-3 — `/api/events` still missing

Eval is fallback-safe now, but event telemetry is still missing.

For production golden dashboards, add an events router:

```text
GET /api/events?entity_type=packet&entity_id=...
```

backed by the existing `events` table.

---

## Recommended command sequence now

### 1. Deterministic local tests

```bash
pytest tests/grace_control/core/test_command_runner.py -q
pytest tests/grace_control/core/test_scope_guard.py -q
pytest tests/grace_control/core/test_evidence.py -q
pytest tests/grace_control/core/test_acceptance_pipeline.py -q
pytest tests/grace_control/adapters/test_packet_executor_acceptance.py -q
pytest tests/grace_control -q
```

### 2. Disposable live golden only

Use a separate branch and fresh DB:

```bash
git checkout -b golden/live-001
rm -f /tmp/grace-golden-live.db
export GRACE_DB_URL=sqlite:////tmp/grace-golden-live.db
export GRACE_AGENT_TIMEOUT=900
export GRACE_CONTEXT_DISABLED=true
```

Start API and run exactly one small explicit YAML feature first:

```bash
grace api start
# second terminal
grace eval run path/to/golden.yaml --workers 1 --timeout 900 --report artifacts/golden-live-001.json
```

Use explicit packet-level or root-level `verification`, but keep it tiny.

After run, verify real git result manually:

```bash
git status --short
git log --oneline -5
git diff --name-only main~1...HEAD
cat artifacts/golden-live-001.json
```

### 3. Only then business-TZ / architect-generated golden

After the explicit golden works, try one business-TZ golden where architect generates the packets.

Keep `GRACE_CONTEXT_DISABLED=true` for first run if you want to test only planning persistence/execution, not context-collector LLM behavior.

---

## Final verdict

**Можно начинать live golden, но только disposable / controlled.**

The base is now good enough for the first real one-packet live run. Do not yet enable broad unattended autorun on main without the P1 hardening tests and merge endpoint input guard.
