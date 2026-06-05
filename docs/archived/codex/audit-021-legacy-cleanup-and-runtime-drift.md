# Audit 021 — Legacy cleanup, runtime drift, and dirty tails

Audience: user + future coder/architect.

Question: can we already remove all legacy, or should we rewrite it first?

Verdict: **do not delete all legacy yet.** The project is already conceptually a new `grace_control` control plane, but the actual packet execution path still depends on `prefect_grace` runtime pieces. The correct next step is **quarantine + rewrite-by-slices**, not mass deletion.

---

## 0. Executive summary

Current architecture is mixed:

```text
grace_control = new control plane
prefect_grace = legacy execution engine / worktree / agent runner / packet parser / compat tails
```

The README itself describes this split:

```text
grace_control/ — new Control Plane
prefect_grace/ — legacy execution engine
prefect_grace/prefect_compat.py — compatibility layer
```

So legacy is not only old docs; parts of it are still runtime-critical.

Immediate recommendation:

```text
1. Do not delete src/prefect_grace yet.
2. Stop adding new logic to src/prefect_grace.
3. Create a native grace_control execution runner.
4. Move only still-needed pieces across one by one.
5. Delete/archive legacy only after tests/golden fixtures prove parity.
```

---

## 1. Current runtime dependency chain

The live worker still uses this path:

```text
Worker
  → PacketExecutionAdapter.execute(...)
    → _call_legacy_runner(...)
      → prefect_grace.platform.e2e_packet_runner.run_e2e_packet(...)
        → prefect_grace.platform.managed_packet_runner.run_managed_packet(...)
          → WorktreeManager
          → launch_codex_for_packet
          → evaluate_worktree_scope
```

Evidence in code:

```python
from prefect_grace.platform.e2e_packet_runner import run_e2e_packet
```

inside `PacketExecutionAdapter._call_legacy_runner(...)`.

This means deleting `src/prefect_grace` now would break packet execution.

---

## 2. Runtime-critical legacy: do NOT delete yet

Keep until rewritten or moved into `grace_control`:

```text
src/prefect_grace/platform/e2e_packet_runner.py
src/prefect_grace/platform/managed_packet_runner.py
src/prefect_grace/platform/worktree_manager.py
src/prefect_grace/platform/worktree_scope_lifecycle.py
src/prefect_grace/platform/packet_parser.py
src/prefect_grace/tasks/codex_launcher.py
src/prefect_grace/platform/status_model.py
```

Reason:

```text
packet execution still calls them directly or indirectly.
```

But they should be considered **legacy runtime substrate**, not the future API.

---

## 3. Legacy pieces that should be rewritten first

### 3.1 `e2e_packet_runner.py`

Problem:

```text
It still describes fake verifier/reviewer handoff and dry-run-oriented old E2E flow.
```

The new control plane already runs real deterministic acceptance + evidence verifier + reviewer from `grace_control` after the legacy runner returns.

So this old runner now mostly provides:

```text
worktree creation
agent launch
scope lifecycle
basic result shape
```

But it also still contains old fake verifier/reviewer handoff logic that is no longer the source of truth.

Action:

```text
Rewrite as native grace_control execution runner.
```

Target new module:

```text
src/grace_control/core/packet_worktree_runner.py
```

or:

```text
src/grace_control/execution/packet_runner.py
```

It should do only:

```text
create per-packet worktree
launch coder agent
collect changed files
scope/frozen_scope check
return worktree_path, branch_name, changed_files, agent status
```

It should not run fake verifier/reviewer.

---

### 3.2 Legacy packet registry YAML

Current `_call_legacy_runner(...)` writes:

```text
state/packet_registry.yaml
```

with fake-ish fields:

```text
feature_id = packet_id[:15]
wave_id = W01
phase = PHASE-TEST
```

This is dirty and conflicts with the new NanoID UID model.

Action:

```text
Remove registry dependency after native runner exists.
```

Until then, keep it as compatibility only and mark it explicitly:

```text
LEGACY_COMPAT_ONLY: required by old launcher lookup
```

---

### 3.3 Default frozen scope still points to legacy package

Current architect/default packet materialization still uses:

```text
frozen_scope default = src/prefect_grace/
```

This made sense before, but after the new control plane is primary, defaults should protect:

```text
src/grace_control/core/
src/grace_control/adapters/
src/grace_control/worker/
src/grace_control/api/routers/packets.py
src/grace_control/db/schema.py
```

Action:

```text
Replace old default frozen_scope with project config / .grace/project.yaml defaults.
```

Do not keep `src/prefect_grace/` as the only default frozen scope.

---

### 3.4 `pyproject.toml` still packages legacy as first-class package

Current package config still says:

```text
packages = ["src/prefect_grace", "src/grace_control"]
```

It also exposes legacy entry points:

```text
prefect-grace = prefect_grace.cli_compat:prefect_grace_main
gracectl = prefect_grace.cli_compat:gracectl_main
```

And dependency list still includes:

```text
prefect>=3.0.0
```

Action:

```text
Phase 1: mark legacy entry points deprecated.
Phase 2: remove legacy entry points after external usage check.
Phase 3: remove prefect dependency if no import really needs it.
Phase 4: remove src/prefect_grace from package after native runner replacement.
```

Do not remove now unless tests prove no runtime import depends on it.

---

### 3.5 pytest config points only to old tests

Current `pyproject.toml` says:

```text
testpaths = ["src/prefect_grace/tests"]
```

But new tests live under `tests/` and `src/grace_control/...` related test paths.

Action:

```text
Update pytest config to include current tests.
```

Suggested:

```toml
testpaths = ["tests", "src/grace_control/tests", "src/prefect_grace/tests"]
```

Later, after legacy removal:

```toml
testpaths = ["tests"]
```

---

## 4. Docs/runtime drift found

### 4.1 README claims parallel-safe claim, but claim does not enforce scope concurrency

README says:

```text
Wave 4: DAG validator, scope conflict detector, parallel-safe claim
```

But `/api/packets/claim` currently:

```text
lists READY packets
skips active lease only for same packet
sets packet RUNNING
increments attempt_count
returns claim
```

It does not check active packet scope conflicts.

There is a `dag_validator.detect_scope_conflicts(...)`, but it only checks exact scope intersections during plan validation. It does not protect runtime parallel claims from:

```text
same broad directory scope
parent/child scope overlap
accepted-but-not-merged packets
stale merge base conflicts
```

Action:

```text
Add runtime ScopeConcurrencyGuard before claim.
Update README until implemented.
```

---

### 4.2 README state machine is outdated

README says 8 states and shows old transition graph.

Current work added/uses states like:

```text
BLOCKED
CANCELLED
possibly review/evidence stage as computed state
```

Action:

```text
Update README state machine after admin/stage observability TZ is implemented.
```

Do not rely on README as source of truth right now.

---

### 4.3 README says tests are 38 tests / old paths

Current commit history and reports mention much larger test counts, but README still says:

```text
38 tests, 8.8s
```

Action:

```text
Replace exact stale test count with command-only docs.
```

Example:

```bash
pytest tests -q
```

Do not hardcode test count in README.

---

### 4.4 CI is disabled

`.github/workflows/ci.yml` currently only does:

```text
echo "CI disabled"
```

Action:

```text
Before serious legacy cleanup, restore CI for at least:
- pytest core tests
- JS syntax tests when admin lands
- source-audit tests
- golden fixture unit tests
```

Do not do large delete/refactor while CI is disabled.

---

## 5. Code smells / dirty tails found

### 5.1 Worker has duplicated `except Exception` block

`worker.py` has two consecutive `except Exception` handlers in the same try chain. The second is unreachable/dead code.

Action:

```text
Clean this in a small safe patch.
```

---

### 5.2 `architect.py` module header still says “YAML with waves (legacy)”

This is not necessarily wrong, but wording is confusing now.

Better wording:

```text
Two modes: explicit YAML plan or business-TZ LLM-generated plan.
```

Do not call explicit YAML legacy unless it is truly deprecated.

---

### 5.3 `PacketExecutionAdapter` is too large and mixed

It currently owns too much:

```text
DB packet materialization
legacy runner call
git commit verification
acceptance pipeline
self-evolution guard
evidence verifier
reviewer
PacketRun result updates
error handling
```

Action:

```text
Split later after golden stability:
- execution stage runner
- acceptance stage runner
- verifier/reviewer stage runner
- run result writer
- stage event recorder
```

Do not split before golden/admin/recovery fixtures unless a targeted refactor is needed.

---

### 5.4 `GRACE_ALLOW_SANDBOX_BYPASS=true` default in legacy adapter

`_call_legacy_runner(...)` sets:

```python
os.environ.setdefault("GRACE_ALLOW_SANDBOX_BYPASS", "true")
```

This needs audit. It may be harmless historical compatibility, but the name is dangerous.

Action:

```text
Find what it controls.
If it bypasses real scope safety, remove/fail closed.
If it only allows golden sandbox paths, rename and document.
```

---

## 6. What can be deleted or archived soon

Only after confirming with grep/tests:

```text
old generated docs that are superseded by docs/codex/TZ-0xx
old prompt examples that still teach FEAT-W01-P01 IDs
old fake verifier/reviewer docs if not used by tests
old screenshots/log dumps under repo if any
old runtime state accidentally committed
old sandbox golden output if accidental
```

Recommended cleanup strategy:

```text
1. Move historical docs to docs/archive/legacy-prefect-grace/ if still useful.
2. Delete generated runtime files from repo.
3. Keep docs/codex review/TZ files because they are active project memory.
4. Add source-audit tests for banned stale patterns.
```

Patterns to audit:

```text
FEAT-
-W01
-P01
prefect_grace as default/future path
legacy result is source of truth
fake verifier/reviewer accepted
src/prefect_grace/ as only frozen scope
CI disabled
38 tests
MVP-0 ready if outdated
```

---

## 7. What should NOT be deleted yet

Do not delete now:

```text
src/prefect_grace/platform/worktree_manager.py
src/prefect_grace/platform/managed_packet_runner.py
src/prefect_grace/platform/e2e_packet_runner.py
src/prefect_grace/platform/packet_parser.py
src/prefect_grace/tasks/codex_launcher.py
src/prefect_grace/platform/worktree_scope_lifecycle.py
```

Reason:

```text
live execution still depends on them.
```

Do not delete `prefect_grace` package from `pyproject.toml` until `PacketExecutionAdapter._call_legacy_runner(...)` no longer imports it.

---

## 8. Proposed cleanup/rewrite plan

### Phase 0 — No deletion, add audit guards

```text
Add tests/source audits for:
- no FEAT-W01-P01 ID assumptions
- no new imports from prefect_grace in grace_control except allowed adapter seam
- no docs claiming parallel-safe claim until implemented
- CI not disabled
```

### Phase 1 — Native runner seam

Add native runner under `grace_control`:

```text
src/grace_control/execution/worktree_runner.py
```

Responsibilities:

```text
create per-packet worktree
launch coder executor
collect changed files
check scope/frozen_scope
return branch/worktree/result
```

This replaces the useful part of:

```text
run_e2e_packet + run_managed_packet
```

but not all at once.

### Phase 2 — Move worktree manager

Move or copy with tests:

```text
prefect_grace.platform.worktree_manager
→ grace_control.git.worktree_manager
```

Keep old module as compatibility shim temporarily:

```python
from grace_control.git.worktree_manager import *
```

### Phase 3 — Replace `_call_legacy_runner(...)`

Change:

```text
PacketExecutionAdapter._call_legacy_runner
```

into:

```text
PacketExecutionAdapter._call_native_coder_runner
```

The new result should not include fake verifier/reviewer fields.

### Phase 4 — Delete old fake handoff path

After native runner is proven by golden fixtures:

```text
remove fake verifier/reviewer handoff from live path
keep only unit tests if needed
```

### Phase 5 — Remove packaging/CLI legacy

After no runtime imports remain:

```text
remove prefect-grace entry point
remove gracectl entry point
remove src/prefect_grace from packages
remove Prefect dependency if unused
update README
update pyproject testpaths
restore CI
```

---

## 9. Suggested immediate TZ

Create next cleanup TZ:

```text
TZ 021 — Legacy quarantine and native runner migration plan
```

Scope should be small:

```text
1. Add import audit: grace_control may import prefect_grace only in one allowed adapter module.
2. Add docs/runtime drift audit test for README dangerous claims.
3. Add source audit for src/prefect_grace default frozen scope.
4. Introduce native runner interface/protocol, but initially delegate to legacy.
5. Add tests around interface contract.
6. Do not delete runtime legacy yet.
```

This gives a safe bridge instead of a risky big deletion.

---

## 10. Suggested tests before any legacy deletion

```bash
pytest tests/api/test_architect_api.py -q
pytest tests/grace_control/core/test_uid.py -q
pytest tests/test_no_legacy_id_assumptions.py -q
pytest tests/integration/test_wave_gate_flow.py -q
pytest tests/test_worker_blocked_routing.py -q
pytest tests -q
```

Plus staged golden fixtures once implemented:

```bash
grace golden fixture run-one fixtures/golden/merge_clean_success.yaml ...
grace golden fixture run-one fixtures/golden/merge_dirty_target_repo.yaml ...
grace golden fixture run-one fixtures/golden/recovery_coder_fail_twice_switch_model.yaml ...
```

Do not perform mass deletion until these are green.

---

## 11. Final verdict

```text
Can we clean all legacy now? No.
Can we start cleaning? Yes.
Should we rewrite legacy? Yes, but by extracting the still-used runtime pieces into grace_control first.
```

Recommended next move:

```text
Quarantine legacy imports + add native runner interface + add audit tests.
```

Then gradually replace:

```text
prefect_grace legacy runtime → grace_control native runtime
```

Only after that should old docs, entry points, package includes, and `src/prefect_grace` be removed.
