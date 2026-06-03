# Codex Review 002 — Acceptance MVP after `ad759ba`

Commit reviewed: `ad759bab5e532f75db44ae14086e3706ebcba268`

Previous review: `docs/codex/review-001-acceptance-mvp-d9ff103.md`

Spec: `docs/grace-control-acceptance-mvp.md`

Verdict: **REWORK_REQUIRED — much closer, but still do not accept yet.**

This implementation fixes several earlier mismatches, but there is still one dangerous P0 correctness bug in scope detection, plus several P1 contract/test gaps.

---

## What is now fixed

Good progress:

- `FinalVerdict` exists.
- `AcceptanceReport` now includes spec fields: `profile`, `evidence_issues`, `legacy_domain_status`, `legacy_ok`, `summary`.
- Public `run_acceptance_pipeline(...)` now exists.
- `keep_worktree=True` is passed to `run_e2e_packet(...)`.
- Adapter no longer uses `_parse_result()` in the normal accepted path.
- Accepted/rejected `ExecutionResult` is built from `acceptance_report`.
- `PacketRun.result_json` now stores both `legacy_result` and `acceptance_report`.
- `run_command(...)` exists and writes stdout/stderr files.
- `legacy_result.ok == False` and `legacy_result.domain_status != "accepted"` are now blocked by the pipeline.
- Adapter tests now actually call `PacketExecutionAdapter.execute()` with mocks.

These are meaningful fixes.

---

## P0-1 — scope guard can miss committed out-of-scope changes

This is the main remaining blocker.

### Current flow

In `PacketExecutionAdapter.execute()`, after the legacy runner returns a worktree, the adapter commits all agent changes before running the deterministic acceptance pipeline:

```python
_sp.run(["git", "add", "-A"], cwd=str(wt), ...)
_sp.run(["git", "commit", "-m", ...], cwd=str(wt), ...)
```

Then it calls:

```python
accept_report = run_acceptance_pipeline(
    packet=pkt_contract,
    legacy_result=result,
    project_root=self.project_root,
    worktree_path=wt_path,
    branch_name=result.branch_name or "",
    run_dir=run_dir,
)
```

Inside `run_acceptance_pipeline()`, changed files are collected through:

```python
changed_files = pipe._scope.get_changed_files()
```

But `ScopeGuard.get_changed_files()` currently defaults to:

```python
git diff --name-only HEAD
```

That checks only uncommitted working tree changes. Since the adapter just committed the worktree before acceptance, `git diff HEAD` can return empty.

### Why this is dangerous

If the agent changed an out-of-scope file and committed it, scope guard may see:

```text
changed_files = []
```

Then `_run_t0()` sees no violations and scope passes.

That means out-of-scope/frozen changes can be merged if tests pass.

### Spec requirement

The spec explicitly requires worktree diff against base ref:

```bash
git -C {worktree_path} diff --name-only {base_ref}...HEAD
```

The repo now has a module-level helper that does this:

```python
def get_changed_files(worktree_path: Path, base_ref: str = "main") -> list[str]:
    git -C worktree diff --name-only main...HEAD
```

But `run_acceptance_pipeline()` does not use it.

### Required fix

In `src/grace_control/core/acceptance_pipeline.py`:

```python
from grace_control.core.scope_guard import get_changed_files

changed_files = get_changed_files(worktree_path, base_ref="main")
```

Do not use `pipe._scope.get_changed_files()` for the main acceptance path.

Also add a regression test:

```text
Given a git repo/worktree with a committed change to apps/bad.tsx
And allowed_write_scope = ["src/**"]
When run_acceptance_pipeline(...) runs
Then final_verdict == REWORK_REQUIRED
And scope_violations contains apps/bad.tsx
```

This test must use a real temp git repo/worktree or a fake scope that simulates committed diff. The important point: committed out-of-scope changes must be detected.

---

## P1-1 — T0 commands do not write stdout/stderr files

Spec says command runner must always write stdout/stderr to files.

Current T1/T2 pass `output_dir`:

```python
commands = [self._runner.run(cmd, output_dir=run_dir) for cmd in cmds]
```

But T0 does not:

```python
r = self._runner.run(cmd)
```

So T0 command output is captured in memory and no deterministic `cmd_NNN_stdout.log` / `cmd_NNN_stderr.log` files are produced for T0.

Required fix:

- Pass a T0 output dir too, e.g. `run_dir / "t0"`.
- Thread `run_dir` into `_run_t0(...)` like T1/T2.
- Add test that T0 writes command output files.

---

## P1-2 — `run_command(...)` exists but pipeline does not use it directly

The spec-facing `run_command(...)` function now exists. Good.

But the pipeline still uses `CommandRunner.run(...)`, which is a second implementation path.

Risk: `run_command(...)` and `CommandRunner.run(...)` can diverge. In fact they already have slightly different behavior.

Required fix options:

Preferred:

```python
class CommandRunner:
    def run(...):
        return run_command(...)
```

So there is exactly one command execution implementation.

Or remove `CommandRunner` from the acceptance path and use `run_command(...)` directly.

---

## P1-3 — adapter tests still encode the wrong behavior for legacy-failed + mocked accepted pipeline

Current test:

```python
async def test_legacy_failed_acceptance_would_pass(...):
    ...
    pipeline_report=_make_accepted_report(),
    expect_accepted=True,  # Adapter trusts the pipeline report
```

And similarly for `domain_status="rejected"`:

```python
expect_accepted=True,  # Adapter trusts the pipeline report
```

This is now philosophically consistent with “pipeline is authority”, but it weakens the original acceptance requirement.

The spec/test plan explicitly wanted:

```text
legacy failed + acceptance would pass → ExecutionResult.accepted False
```

A better test is not to mock the pipeline for this case. Use the real `run_acceptance_pipeline(...)` with a fake legacy result:

```text
legacy_result.ok=False + deterministic commands pass -> final_verdict != ACCEPTED
legacy_result.ok=True + domain_status="rejected" + deterministic commands pass -> final_verdict != ACCEPTED
```

Required fix:

- Keep adapter tests for “adapter trusts pipeline report”.
- Add core pipeline tests proving legacy `ok=False` and `domain_status != accepted` cannot produce ACCEPTED.
- Optionally add adapter-level test with real pipeline for those two cases.

---

## P1-4 — `_parse_result()` still returns `accepted=True`

`_parse_result()` is no longer used in the normal accepted path, but it still exists and returns:

```python
ExecutionResult(accepted=True, ...)
```

This is dangerous dead code because any future caller can reintroduce the exact legacy-trust bug.

Required fix:

Either delete `_parse_result()` or make it explicitly non-authoritative:

```python
def _parse_result(self, result) -> ExecutionResult:
    return ExecutionResult(
        accepted=False,
        reason="legacy result is not an acceptance gate",
        domain_status=result.domain_status,
        worktree_path=result.worktree_path or "",
        branch_name=result.branch_name or "",
    )
```

Do not leave a helper that returns `accepted=True` without an `AcceptanceReport`.

---

## P1-5 — NORMAL profile with empty `expected_evidence` may be too strict / unclear

`EvidenceCollector.has_required_evidence()` currently returns `False` when `expected_evidence` is empty for NORMAL/STRICT:

```python
if not expected_evidence:
    return False
```

This means a NORMAL packet with valid T0/T1 commands but no `expected_evidence` will be BLOCKED.

The spec says:

```text
NORMAL: require at least one successful command evidence from T1 or T0.
STRICT: require all required expected_evidence items.
```

So for NORMAL, empty expected evidence should not necessarily block if a T0/T1 command succeeded.

Required fix:

- For FAST: evidence optional.
- For NORMAL: require at least one successful command from T0 or T1, even if `expected_evidence` is empty.
- For STRICT: require all required expected_evidence.

Also use the spec-facing `check_expected_evidence(...)` in the pipeline, not only `EvidenceCollector.has_required_evidence(...)`.

---

## P1-6 — `_materialize_packet()` still hardcodes Frozen Scope and Verification text

`_materialize_packet()` now dumps the full YAML spec under `## Specification`, but the visible top-level packet sections still say:

```markdown
## Frozen Scope
- src/prefect_grace/**

## Verification
pytest -v
ruff check src/
```

This can mislead the legacy/coder agent, even if registry contains the real scope.

Required fix:

- Render `frozen_scope` from `spec_json.frozen_scope`.
- Render `verification.t0/t1/t2` or legacy list-form from `spec_json.verification`.
- Render `expected_evidence` from `spec_json.expected_evidence`.

This is less critical than the deterministic gate, but still a spec mismatch.

---

## P2 — no CI evidence from GitHub Actions

GitHub Actions workflow runs for `ad759bab5e532f75db44ae14086e3706ebcba268` were not found during review.

The commit message says “tests green”, but I did not see CI evidence from GitHub Actions.

Required if this becomes a hard acceptance gate:

- Add CI or include a machine-readable local test artifact in `docs/codex/` or `.grace` evidence.

---

## Required fix checklist for coder

1. Fix scope detection in `run_acceptance_pipeline()` to use committed diff against `main...HEAD`.
2. Add regression test for committed out-of-scope file after adapter/worktree commit.
3. Pass output dir for T0 commands.
4. Make `CommandRunner.run()` delegate to `run_command(...)` or use `run_command(...)` directly.
5. Add/adjust tests for legacy failed and legacy non-accepted domain status using the real pipeline.
6. Delete or neutralize `_parse_result()` so it cannot return `accepted=True`.
7. Adjust NORMAL evidence semantics or clearly document/validate expected evidence as required for NORMAL.
8. Render real frozen scope and verification sections in `_materialize_packet()`.

---

## Minimal grep/checks before next review

```bash
# Main P0: acceptance must use committed worktree diff, not git diff HEAD only
grep -R "get_changed_files(worktree_path" -n src/grace_control/core/acceptance_pipeline.py

# This should not be the main acceptance changed-files source anymore
grep -R "pipe._scope.get_changed_files" -n src/grace_control/core/acceptance_pipeline.py

# T0 should write files too
grep -R "_run_t0" -n src/grace_control/core/acceptance_pipeline.py
grep -R "output_dir=.*t0\|/ \"t0\"" -n src/grace_control/core/acceptance_pipeline.py

# No helper should be able to return accepted=True without acceptance report
grep -R "accepted=True" -n src/grace_control/adapters/packet_executor.py

# Real pipeline tests for legacy gates
grep -R "domain_status.*rejected\|legacy.*ok.*False" -n tests/grace_control/core tests/grace_control/adapters
```

---

## Verdict

Still **REWORK_REQUIRED**.

This is much closer than `d9ff103`. The remaining blocker is narrower but important: committed worktree changes can be invisible to scope guard, which breaks the core acceptance safety promise.
