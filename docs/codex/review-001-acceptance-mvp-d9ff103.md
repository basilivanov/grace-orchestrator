# Codex Review 001 — Acceptance MVP after `d9ff103`

Commit reviewed: `d9ff103aaea4c8ee37f0cd2e91d7fe29c0c6a37b`

Spec: `docs/grace-control-acceptance-mvp.md`

Verdict: **REWORK_REQUIRED — do not accept yet.**

The second implementation fixed some surface-level blockers, but there are still P0 issues that can incorrectly accept/merge packets or fail to prove the spec contract.

---

## What is now fixed / partially fixed

- `ExecutionResult` now has `acceptance_report_path`, `acceptance_verdict`, `acceptance_summary`.
- `_call_legacy_runner()` now passes `keep_worktree=True` to `run_e2e_packet()`.
- `VerificationSpec(t0/t1/t2)` exists.
- `CommandResult` now has `stdout_path`, `stderr_path`, `timed_out`; timeout returns `exit_code=-1`.
- `AGENTS.md` now contains a useful TZ compliance rule.

These are not enough to accept the task.

---

## P0-1 — accepted path can still accept legacy non-accepted result

File: `src/grace_control/adapters/packet_executor.py`

Current accepted path:

```python
accept_report = pipe.run(... legacy_result={"ok": result.ok, "domain_status": result.domain_status}, ...)
...
if not accept_report.is_accepted:
    return ExecutionResult(accepted=False, ...)
...
execution_result = self._parse_result(result)
```

Then `_parse_result()` is now:

```python
def _parse_result(self, result) -> ExecutionResult:
    return ExecutionResult(
        accepted=True,
        domain_status=result.domain_status,
        worktree_path=result.worktree_path or "",
        branch_name=result.branch_name or "",
    )
```

This is a critical regression.

The acceptance pipeline only blocks `legacy_result.ok == False`. It does **not** block `legacy_result.domain_status != "accepted"`.

So this path is possible:

```text
legacy_result.ok = True
legacy_result.domain_status = "rejected" / "blocked" / anything not accepted
acceptance deterministic gates pass
accept_report.is_accepted == True
_parse_result() returns accepted=True
worker merges
```

Spec requires:

```text
If legacy_result.domain_status != "accepted": final_verdict cannot be ACCEPTED.
ExecutionResult.accepted = acceptance_report.final_verdict == FinalVerdict.ACCEPTED
```

Required fix:

- Do not call `_parse_result()` to build the final accepted result.
- Build final `ExecutionResult` from `acceptance_report` only.
- The pipeline must block both:
  - `legacy_result.ok is False`
  - `legacy_result.domain_status != "accepted"`

Suggested shape:

```python
accepted = acceptance_report.final_verdict == FinalVerdict.ACCEPTED
return ExecutionResult(
    accepted=accepted,
    reason=None if accepted else acceptance_report.summary,
    domain_status=acceptance_report.final_verdict.value,
    worktree_path=result.worktree_path or "",
    branch_name=result.branch_name or "",
    evidence_path=evidence_path,
    acceptance_report_path=acceptance_report_path,
    acceptance_verdict=acceptance_report.final_verdict.value,
    acceptance_summary=acceptance_report.summary,
)
```

---

## P0-2 — exact `run_acceptance_pipeline(...)` function is still missing

Spec requires a public pure function:

```python
run_acceptance_pipeline(
    packet: ExecutionPacketContract,
    legacy_result,
    project_root: Path,
    worktree_path: Path,
    branch_name: str,
    run_dir: Path,
) -> AcceptanceReport
```

Current code only has `AcceptancePipeline.run(...)`. A repo search for `run_acceptance_pipeline` returns no results.

Required fix:

- Add exact public function `run_acceptance_pipeline(...)` in `src/grace_control/core/acceptance_pipeline.py`.
- Adapter must import and call this function, not instantiate `AcceptancePipeline` directly.
- Keep class internally if useful, but the spec-facing API must exist.

---

## P0-3 — `AcceptanceReport` still does not match required contract

Spec requires `AcceptanceReport` fields:

```python
packet_id: str
final_verdict: FinalVerdict
profile: AcceptanceProfile
stages: list[StageResult]
scope_violations: list[str]
evidence_issues: list[str]
legacy_domain_status: str
legacy_ok: bool
summary: str
```

Current `AcceptanceReport` has:

```python
packet_id
final_verdict
stages
scope_violations
evidence_paths
reasons
verifier_report
reviewer_verdict
```

Missing required spec fields:

- `profile`
- `evidence_issues`
- `legacy_domain_status`
- `legacy_ok`
- `summary`

Required fix:

- Either rename/reshape to the exact spec contract, or add compatibility fields exactly as specified.
- Do not rely on `reasons[0]` as a replacement for `summary`.

---

## P0-4 — commands still run in `project_root`, not the produced worktree

Spec requires acceptance commands to run inside `worktree_path`, not `project_root`.

Current adapter builds:

```python
scope_guard = ScopeGuard(worktree_repo)
pipe = AcceptancePipeline(repo_root=self.project_root, scope_guard=scope_guard)
```

`AcceptancePipeline` creates `CommandRunner(self._root)`, and `_root` is `repo_root`. Because adapter passes `self.project_root`, T0/T1/T2 commands run against the original project, not the agent-produced worktree.

Also, `worktree_path` is passed into `.run(...)` but ignored by the implementation.

Required fix:

- `run_acceptance_pipeline(... worktree_path=Path(...))` must construct command runner with `worktree_path` as cwd/root.
- T0/T1/T2 commands must run in produced worktree.
- Add a test that proves command cwd is the worktree path.

---

## P0-5 — command runner still does not meet spec in actual pipeline path

Spec says:

- public function `run_command(...)`
- command is `str`
- use `shlex.split()`
- reject unsupported shell syntax such as `&&`, `||`, pipes, redirects
- always write stdout/stderr to deterministic files
- output names: `cmd_001_stdout.log`, `cmd_001_stderr.log`

Current implementation:

- still only has `CommandRunner.run(...)`, no public `run_command(...)`
- accepts `list[str] | str`, not string-only spec contract
- does not reject shell syntax; `echo ok && false` becomes args and may succeed incorrectly
- only writes files if `output_dir` is passed
- acceptance pipeline never passes `output_dir`, so actual T0/T1/T2 evidence does not write files
- filename counter uses `len(list(output_dir.glob("cmd_*"))) + 1`; because each command creates two files, numbering can jump `001`, `003`, `005` instead of deterministic command sequence

Required fix:

- Implement exact `run_command(...)` function.
- Make pipeline use `run_command(..., output_dir=run_dir / stage_name)` or equivalent.
- Reject shell operators before `subprocess.run`.
- Always create stdout/stderr files.
- Use a deterministic command index passed by the stage runner, not `glob()` count.

---

## P0-6 — legacy list-form `verification: [...]` can crash adapter

Spec says legacy list form:

```yaml
verification:
  - pytest -q
  - ruff check src/
```

must be treated as T1 commands.

Current adapter does:

```python
spec.get("verification", {}).get("t0", [])
spec.get("verification", {}).get("t1", [])
spec.get("verification", {}).get("t2", [])
```

If `verification` is a list, this becomes:

```text
list object has no attribute get
```

Adapter catches this as `acceptance_pipeline_error` and returns blocked. That violates the spec fallback behavior.

Required fix:

```python
verification_raw = spec.get("verification", {})
if isinstance(verification_raw, list):
    t0 = []
    t1 = verification_raw
    t2 = []
elif isinstance(verification_raw, dict):
    t0 = verification_raw.get("t0", [])
    t1 = verification_raw.get("t1", [])
    t2 = verification_raw.get("t2", [])
else:
    # invalid contract -> BLOCKED with clear summary
```

Also normalize command strings/lists consistently.

---

## P0-7 — accepted `ExecutionResult` loses acceptance metadata

On rejection, adapter fills:

```python
acceptance_report_path
acceptance_verdict
acceptance_summary
```

On accepted path, adapter does this instead:

```python
execution_result = self._parse_result(result)
execution_result.evidence_path = evidence_path
execution_result.duration_ms = ...
```

Since `_parse_result()` only sets `accepted`, `domain_status`, `worktree_path`, `branch_name`, accepted results return with:

```text
acceptance_report_path = ""
acceptance_verdict = ""
acceptance_summary = ""
```

Required fix:

- Use one builder for both accepted and rejected paths.
- Always populate acceptance report path/verdict/summary.

---

## P0-8 — `PacketRun.result_json` is still legacy-only

Spec requires:

```json
{
  "legacy_result": { ... },
  "acceptance_report": { ... }
}
```

Current adapter still does:

```python
existing.result_json = result.to_dict()
```

This stores only the legacy result.

Required fix:

```python
existing.result_json = {
    "legacy_result": safe_legacy_dict,
    "acceptance_report": acceptance_report.to_dict(),
}
```

Add adapter integration test for this exact shape.

---

## P0-9 — adapter tests still do not test adapter integration

`tests/grace_control/adapters/test_packet_executor_acceptance.py` still mostly tests properties of `AcceptanceReport` / `ExecutionResult` manually.

Examples:

```python
report = _make_report(PacketVerdict.ACCEPTED)
assert report.is_accepted is True
```

and:

```python
result = ExecutionResult(accepted=False, ...)
assert result.accepted is False
```

These tests do not prove the adapter behavior.

Spec required adapter tests with mocks:

- mock `_call_legacy_runner`
- mock `run_acceptance_pipeline`
- call `PacketExecutionAdapter.execute()`
- verify accepted/rework/blocked branches
- verify report saved
- verify `PacketRun.result_json` contains `legacy_result` and `acceptance_report`
- verify registry gets real allowed/frozen scope
- verify accepted worktree still exists after `execute()` returns

Required fix:

Rewrite `tests/grace_control/adapters/test_packet_executor_acceptance.py` so most tests call `await adapter.execute(...)`.

---

## P1 — self-evolution guard branch now looks broken

In `packet_executor.py`, self-evolution rejection creates:

```python
ExecutionResult(
    accepted=False,
    domain_status="rejected",
    errors=guard_result.errors,
    evidence_path=None,
    ...
)
```

But `ExecutionResult` has no `errors` field, and `evidence_path` is typed as string.

This may raise a Pydantic validation error on self-evolution rejections.

Required fix:

```python
ExecutionResult(
    accepted=False,
    domain_status="rejected",
    reason="; ".join(guard_result.errors),
    evidence_path="",
    ...
)
```

---

## Required final grep/checklist before declaring done

Run or logically verify:

```bash
grep -R "def run_acceptance_pipeline" -n src/grace_control/core/acceptance_pipeline.py

grep -R "legacy_domain_status\|legacy_ok\|summary" -n src/grace_control/core/contracts.py src/grace_control/core/acceptance_pipeline.py

grep -R "keep_worktree=True" -n src/grace_control/adapters/packet_executor.py

grep -R "accepted=True" -n src/grace_control/adapters/packet_executor.py
# must not appear in _parse_result or final accepted builder except in controlled tests

grep -R "existing.result_json = result.to_dict" -n src/grace_control/adapters/packet_executor.py
# must return no results

grep -R "run_command" -n src/grace_control/core/command_runner.py

grep -R "&&\|||\||>\|<" -n src/grace_control/core/command_runner.py
# command_runner must explicitly reject unsupported shell syntax
```

Required test proof:

```bash
pytest tests/grace_control/core/test_command_runner.py -q
pytest tests/grace_control/core/test_acceptance_pipeline.py -q
pytest tests/grace_control/adapters/test_packet_executor_acceptance.py -q
pytest tests/grace_control -q
```

Adapter tests must include at least one test where:

```text
legacy_result.ok = True
legacy_result.domain_status = "rejected"
deterministic commands pass
expected result.accepted == False
```

This is the current most dangerous merge bug.

---

## Minimal patch order

1. Add exact `FinalVerdict` alias or replace `PacketVerdict` with `FinalVerdict` per spec.
2. Reshape `AcceptanceReport` to include required fields.
3. Add exact `run_acceptance_pipeline(...)` function.
4. Move command execution root to `worktree_path`.
5. Implement exact `run_command(...)` and make pipeline always pass `output_dir`.
6. Fix verification parser for dict-form and list-form.
7. Replace accepted path builder in adapter; stop using `_parse_result()` for final accepted result.
8. Store `{legacy_result, acceptance_report}` in `PacketRun.result_json`.
9. Rewrite adapter integration tests to call `execute()`.

---

## Verdict

Still **REWORK_REQUIRED**.

The previous 8 blocker checklist was partially addressed, but the current code still has a dangerous accepted path and does not yet match the spec contract closely enough for MVP acceptance.
