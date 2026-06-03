# Codex Review 004 — Pipeline readiness before live golden tests

Scope: prompt chain + architect → packet DB → worker → legacy runner → deterministic acceptance → release → merge → eval harness.

Verdict: **NOT READY for fully trusted live golden auto-merge on main.**

The acceptance gate itself is now MVP-acceptable, but the surrounding pipeline still has readiness gaps that can make live golden tests fail for the wrong reason or falsely pass.

Recommended status:

- ✅ Run deterministic/unit smoke tests now.
- ✅ Run dry-run / non-merging golden tests now.
- ⚠️ Run live golden tests only in a disposable branch/worktree/database and manually verify git result.
- ❌ Do not yet trust `grace eval run` as a production-quality pass/fail oracle for live auto-merge.

---

## P0-1 — LLM architect root `verification` / `constraints` are not propagated into packet `spec_json`

### Problem

Architect prompt asks the model to return root-level:

```json
{
  "waves": [...],
  "constraints": {
    "frozen_scope": ["src/prefect_grace/"],
    "forbidden_imports": [],
    "python_version": ">= 3.12"
  },
  "verification": ["pytest tests/ -x --timeout=60"]
}
```

But in `create_plan()`, each DB packet is persisted from only `pkt_spec`:

```python
enriched_spec = dict(pkt_spec)
...
Packet(... spec_json=enriched_spec, acceptance_profile=pkt_spec.get("acceptance_profile", "NORMAL"))
```

Root-level `spec["verification"]` and `spec["constraints"]` are not copied into each packet.

Acceptance contract builder later validates per-packet verification:

```python
if packet.acceptance_profile in (AcceptanceProfile.NORMAL, AcceptanceProfile.STRICT):
    if not packet.verification.get("t1", []):
        errors.append(f"{packet.acceptance_profile.value} requires verification.t1")
```

So a business-TZ → LLM plan may create NORMAL packets without `verification.t1`, and the deterministic gate will reject them as invalid packet contracts.

### Impact

Live golden tests using business descriptions / architect-generated plans can fail immediately even if the coder and acceptance gate are otherwise correct.

### Required fix

When persisting each packet, propagate root defaults:

```python
root_verification = spec.get("verification", [])
root_constraints = spec.get("constraints", {})

packet_verification = pkt_spec.get("verification", root_verification)
packet_frozen_scope = pkt_spec.get(
    "frozen_scope",
    root_constraints.get("frozen_scope", ["src/prefect_grace/"])
)

enriched_spec.setdefault("verification", packet_verification)
enriched_spec.setdefault("frozen_scope", packet_frozen_scope)
```

Better: adjust architect prompt to require packet-level `verification` and `frozen_scope`, not only root-level defaults.

---

## P0-2 — merge endpoint can mark packet MERGED even if git merge failed

### Problem

`POST /api/packets/{packet_id}/merge` transitions packet state to `MERGED` before attempting git merge:

```python
_state_machine.transition(current, PacketState.MERGED)
packet.state = PacketState.MERGED.value
```

Then it runs:

```python
git merge branch_name --no-edit --no-ff
```

But if merge fails, it only logs a warning:

```python
_log.warn("merge_failed", ...)
```

and still returns success with state `merged`.

### Impact

`grace eval run` treats all packets in `merged` state as pass. This can produce a false green golden result even when no code was merged.

### Required fix

Merge endpoint should:

1. Attempt git merge first.
2. If git merge fails, do **not** transition to `MERGED`.
3. Return HTTP 409/500 with stderr.
4. Keep packet in `ACCEPTED` or move to `FAILED_MERGE` if that state exists.
5. Only then clean up worktree.

Pseudo-flow:

```python
if worktree_path and branch_name:
    mr = git merge ...
    if mr.returncode != 0:
        raise HTTPException(status_code=409, detail={"merge_failed": mr.stderr})

_state_machine.transition(current, PacketState.MERGED)
packet.state = PacketState.MERGED.value
```

Also cleanup should prefer `git worktree remove` before `shutil.rmtree`.

---

## P0-3 — eval harness calls `/api/events`, but API app does not include events router

### Problem

`grace eval run` collects events with:

```python
r2 = c.get(f"/api/events?entity_type=packet&entity_id={pid}")
evs = r2.json()["data"]
```

But `api/main.py` includes routers for features, packets, workers, architect, and self-evolution only. No events router is included.

### Impact

Even if packets execute correctly, `grace eval run` can fail during report collection or produce broken reports.

### Required fix

Either:

- add/include an events router at `/api/events`; or
- remove event fetching from eval report; or
- make it optional/fallback-safe:

```python
try:
    r2 = c.get(...)
    evs = r2.json().get("data", []) if r2.status_code == 200 else []
except Exception:
    evs = []
```

For golden tests, this should not be able to crash the result collector.

---

## P1-1 — `grace eval run` is useful, but not yet a hard oracle

`eval run` does submit a feature, starts worker subprocesses, polls packet states, and marks pass only when all packets are `merged`.

But because merge can falsely mark `MERGED`, `eval run` should not be trusted until P0-2 is fixed.

Recommended short-term usage:

- Use eval reports as telemetry only.
- After each live golden, manually verify:

```bash
git log --oneline -5
git status --short
git diff --name-only origin/main...HEAD
```

or compare expected files directly.

---

## P1-2 — model/profile mismatch: coder-flash still has reasoning=max/high config

`agent_profiles.yaml` defines `coder-flash` as `deepseek/deepseek-v4-flash`, but the executor has `reasoning: max`, and role-level `coder` has `reasoning: high`.

Given the earlier observed behavior, coder should be literal executor, not architect-like.

Recommended:

```yaml
coder-flash:
  reasoning: medium

roles:
  coder:
    reasoning: medium
```

Keep architect/reviewer at max reasoning.

---

## P1-3 — verifier/reviewer prompts exist but are not the effective acceptance gate yet

The legacy E2E runner still creates fake verifier/reviewer launchers for handoff. The real safety now comes from deterministic `run_acceptance_pipeline()`, not live verifier/reviewer agents.

This is okay for MVP, but golden-test interpretation should be clear:

- Golden tests validate coder + deterministic acceptance.
- They do **not** yet validate live verifier/reviewer prompt quality.

If you want to test prompt quality, create a separate eval stage that directly runs verifier/reviewer on saved artifacts.

---

## P1-4 — `AGENTS.md` is good but minimal

`AGENTS.md` correctly says to follow exact TZ fields/signatures and not substitute “works” for “matches spec”. Good.

Before broader live tests, add a small coder-specific block:

```md
## Coder mode
- You are not the architect.
- Do not rename spec fields.
- Do not replace required functions/classes with convenient equivalents.
- If implementation conflicts with TZ, change implementation.
- If exact implementation is impossible, stop and return BLOCKER.
```

This should reduce the same class of mismatch seen earlier.

---

## Recommended launch sequence

### Phase 0 — local deterministic base

Run first:

```bash
pytest tests/grace_control/core/test_command_runner.py -q
pytest tests/grace_control/core/test_scope_guard.py -q
pytest tests/grace_control/core/test_evidence.py -q
pytest tests/grace_control/core/test_acceptance_pipeline.py -q
pytest tests/grace_control/adapters/test_packet_executor_acceptance.py -q
pytest tests/grace_control -q
```

### Phase 1 — dry golden

Use explicit YAML with packet-level `verification`, not LLM-generated business-TZ yet.

Run against a fresh DB:

```bash
rm -f /tmp/grace-golden.db
export GRACE_DB_URL=sqlite:////tmp/grace-golden.db
export GRACE_AGENT_TIMEOUT=600
export GRACE_CONTEXT_DISABLED=true

grace api start
# second terminal
grace eval run path/to/golden.yaml --workers 1 --timeout 600 --report artifacts/golden-dry.json
```

For this phase, use a harmless packet touching only a sandbox/test file.

### Phase 2 — live golden, but disposable

Only after Phase 0/1 passes:

```bash
git checkout -b golden/live-001
rm -f /tmp/grace-golden-live.db
export GRACE_DB_URL=sqlite:////tmp/grace-golden-live.db
export GRACE_AGENT_TIMEOUT=900
export GRACE_CONTEXT_DISABLED=true
```

Use explicit YAML, one packet, one file, simple verification.

After run, manually verify git result. Do not rely only on `merged` state.

### Phase 3 — business-TZ / architect-generated golden

Only after P0-1 is fixed. Otherwise generated packets can miss verification/frozen scope and fail for orchestration reasons.

---

## Final recommendation

Do **not** run full live golden tests as a trusted acceptance signal yet.

First fix:

1. Propagate root `verification` / `constraints.frozen_scope` into packet `spec_json`, or force packet-level fields in architect prompt.
2. Make merge endpoint fail closed: no `MERGED` state unless git merge succeeds.
3. Fix `/api/events` dependency in eval harness.

After those three, the base is ready for live golden tests.

Until then, run only dry/disposable live golden tests and manually inspect git state after each run.
