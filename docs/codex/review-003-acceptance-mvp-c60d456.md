# Codex Review 003 — Acceptance MVP after `c60d456`

Commit reviewed: `c60d456567785ca2e72fa3d319eddb88bbf6e2f5`

Previous review: `docs/codex/review-002-acceptance-mvp-ad759ba.md`

Spec: `docs/grace-control-acceptance-mvp.md`

Verdict: **ACCEPTED FOR MVP / PASS WITH P1 FOLLOW-UPS**

I do not see remaining P0 blockers in the acceptance-gate path. The dangerous scope-diff issue from review-002 is fixed.

---

## P0 status

### P0 from review-002: committed worktree diff invisibility

Status: **fixed**.

`run_acceptance_pipeline()` now uses the module-level committed-diff helper:

```python
changed_files = get_changed_files(worktree_path, base_ref="main")
```

This means committed agent changes are compared against `main...HEAD`, instead of relying only on `git diff HEAD` from the worktree.

This closes the previous risk where adapter committed the worktree before acceptance and then scope guard could see `changed_files=[]`.

---

## Other previously open items

### T0 command output files

Status: **fixed**.

T0 now passes an output directory:

```python
run_dir_t0 = Path(run_dir) / "t0" if run_dir else worktree_root
t0_result = self._run_t0(..., output_dir=run_dir_t0)
```

and `_run_t0()` passes that into the runner:

```python
r = self._runner.run(cmd, output_dir=output_dir)
```

### `_parse_result()` no longer accepts

Status: **fixed enough**.

`_parse_result()` now returns:

```python
accepted=False
reason="legacy result is not an acceptance gate"
```

This removes the previous dangerous helper that returned `accepted=True` without an `AcceptanceReport`.

### Real legacy gate tests

Status: **fixed enough**.

Core acceptance tests now include:

```python
test_legacy_ok_false_blocks_accept
test_legacy_domain_status_rejected_blocks_accept
test_legacy_ok_true_domain_accepted_allowed
```

These use the real pipeline path rather than only adapter mocks.

### Materialized packet visible sections

Status: **fixed enough**.

`_materialize_packet()` now renders real `frozen_scope`, `verification`, and `expected_evidence` from `spec_json`, instead of hardcoding only `src/prefect_grace/**`, `pytest -v`, and `ruff check src/`.

---

## Acceptance-gate safety review

The current accepted path is now conceptually correct:

1. Adapter builds packet contract from DB packet data.
2. Legacy runner is called with real allowed/frozen scope and `keep_worktree=True`.
3. Adapter rejects cleaned/missing worktree for successful legacy runs.
4. Adapter commits worktree changes.
5. `run_acceptance_pipeline()` computes changed files from `worktree_path` against `main...HEAD`.
6. T0 checks contract + scope + cheap commands.
7. T1/T2 run according to profile/spec.
8. Evidence is checked.
9. Legacy `ok=False` or `domain_status != "accepted"` prevents `ACCEPTED`.
10. Final `ExecutionResult` is built from `acceptance_report`, not from legacy verdict.
11. `PacketRun.result_json` stores both `legacy_result` and `acceptance_report`.

No P0 merge-safety issue found in this review pass.

---

## P1 follow-ups

These are not blockers for MVP acceptance, but should be cleaned up soon.

### P1-1 — add explicit committed out-of-scope regression test

The implementation now uses `get_changed_files(worktree_path, base_ref="main")`, which fixes the previous P0.

Still, add an explicit regression test:

```text
Given a real temp git repo/worktree
And a committed change to apps/bad.tsx
And allowed_write_scope = ["src/**"]
When run_acceptance_pipeline(...) runs
Then final_verdict == REWORK_REQUIRED
And scope_violations contains apps/bad.tsx
```

This test should prove the exact bug from review-002 never returns.

### P1-2 — `CommandRunner.run()` still has a separate list-command execution path

For string commands, `CommandRunner.run()` delegates to `run_command(...)`.

For `list[str]` commands, it still uses its own subprocess implementation.

This is acceptable for MVP because the spec-facing API exists and string commands go through `run_command(...)`, but it leaves two paths to maintain.

Recommended cleanup:

- Normalize list commands to a safe command string where possible, then delegate to `run_command(...)`; or
- Make the acceptance contract use only string commands internally.

### P1-3 — adapter tests still contain confusing mocked-pipeline expectations

Adapter tests still include cases where mocked pipeline returns `ACCEPTED` even when legacy failed/domain rejected, and the adapter accepts because it trusts the mocked report.

This is not a blocker because real pipeline tests now cover legacy rejection. But the test names/comments are misleading.

Recommended cleanup:

- Rename these tests to clarify they test “adapter trusts pipeline report”.
- Keep legacy-gate tests in core pipeline tests.

### P1-4 — STRICT profile with empty expected evidence needs a policy decision

Current behavior may allow STRICT packets with T1/T2 passing and empty `expected_evidence`.

Original spec wording implied `expected_evidence` may be empty for FAST, while STRICT should require required evidence.

Recommended decision:

- Either keep current behavior and document that STRICT can pass with empty `expected_evidence` if T1/T2 pass; or
- Make STRICT with empty `expected_evidence` BLOCKED.

This is a policy/spec interpretation issue, not an immediate merge-safety bug.

### P1-5 — command output temp dirs for no-output_dir path

`CommandRunner.run()` now creates temp output dirs when no output_dir is provided.

This satisfies “always write stdout/stderr”, but those temp dirs are not tied to `run_dir` and may be harder to audit.

For acceptance pipeline this is mostly okay because T0/T1/T2 pass output dirs. Still, keep an eye on any direct `CommandRunner.run()` usage outside the pipeline.

---

## Suggested next gate

Before calling this fully production-ready, run locally:

```bash
pytest tests/grace_control/core/test_command_runner.py -q
pytest tests/grace_control/core/test_scope_guard.py -q
pytest tests/grace_control/core/test_evidence.py -q
pytest tests/grace_control/core/test_acceptance_pipeline.py -q
pytest tests/grace_control/adapters/test_packet_executor_acceptance.py -q
pytest tests/grace_control -q
```

Optional but recommended:

```bash
pytest tests/grace_control/core \
  --cov=src/grace_control/core/contracts.py \
  --cov=src/grace_control/core/command_runner.py \
  --cov=src/grace_control/core/scope_guard.py \
  --cov=src/grace_control/core/evidence.py \
  --cov=src/grace_control/core/acceptance_pipeline.py \
  --cov-fail-under=100
```

---

## Final verdict

**ACCEPTED FOR MVP.**

No remaining P0 blocker found. The deterministic merge gate is now structurally in place and the previous dangerous scope-diff bug is fixed.

Keep the P1 follow-ups as a small hardening task, not as a blocker for this MVP slice.
