# Codex Review 016 — TZ-014 pre-self-improvement hardening after `2f05a41`

Commit reviewed: `2f05a41149b0bc06bdfc0da9a8405dc9bf020e52`

Spec: `docs/codex/tz-014-pre-self-improvement-hardening.md`

Verdict: **REWORK_REQUIRED BEFORE SELF-IMPROVEMENT. PASS FOR FAST GOLDEN.**

Most core wiring from TZ-014 is implemented correctly: `base_ref` now flows into `run_e2e_packet`, acceptance changed-files no longer hardcodes `main`, and `llm_runner` writes prompts under `GRACE_STATE_ROOT` when set. However, the architect prompt still contains a contradictory old instruction and the self-improvement/admin UI prompt rules from the TZ are incomplete. Tests requested by the TZ also appear missing.

---

## Fixed well

### Patch 1 — `base_ref` is passed into legacy worktree creation

Status: **fixed.**

`PacketExecutionAdapter.execute()` now calls:

```python
result = await self._call_legacy_runner(..., attempt=run_number, base_ref=base_ref)
```

`_call_legacy_runner(...)` now accepts:

```python
base_ref: str = "HEAD"
```

and passes it into:

```python
run_e2e_packet(..., base_ref=base_ref, ...)
```

`run_e2e_packet(...)` already accepts `base_ref` and passes it into `run_managed_packet(...)`.

This closes the previous mismatch where commit diff base could differ from worktree creation base.

---

### Patch 2 — acceptance changed-files no longer hardcodes `main`

Status: **fixed.**

`run_acceptance_pipeline(...)` now accepts:

```python
base_ref: str | None = None
base_sha: str | None = None
```

and uses:

```python
changed_base = base_sha or base_ref or os.environ.get("GRACE_BASE_REF", "HEAD")
changed_files = get_changed_files(worktree_path, base_ref=changed_base)
```

The later verifier/reviewer context collection in the adapter also changed from:

```python
base_ref="main"
```

to:

```python
base_ref=base_sha or base_ref
```

This aligns acceptance diff with the same base used for worktree/commit diff.

---

### Patch 4 — `llm_runner` uses `GRACE_STATE_ROOT`

Status: **fixed.**

`llm_runner` now writes prompt files to:

```python
Path(GRACE_STATE_ROOT) / "llm_prompts"
```

when `GRACE_STATE_ROOT` is set.

The opencode instruction now uses the absolute prompt path:

```python
Read the task from {tmp}.
```

This prevents LLM prompt files from being written into the wrong repo during external/self-improvement runs.

---

### Patch 5 — self-improvement runbook

Status: **fixed enough.**

`docs/codex/self-improvement-runbook.md` exists and includes:

```bash
GRACE_TARGET_REPO_ROOT
GRACE_STATE_ROOT
GRACE_WORKTREE_ROOT
GRACE_BASE_REF
GRACE_DB_URL
```

and the basic clean-repo / `/tmp` roots guidance.

---

## P0-1 — Architect prompt still contains contradictory old verification instruction

Status: **not fixed.**

The JSON example was updated to the new canonical shape:

```json
"verification": {
  "t0": [],
  "t1": ["python3 -m pytest tests/test_auth.py -q"],
  "t2": []
}
```

But the rules section still says:

```text
Include `verification` list with shell commands to run (pytest, ruff, mypy).
```

This contradicts the new contract and can cause the architect to generate old-style verification or mixed-format output.

### Required fix

Replace rule 8 with:

```text
8. Include `verification` as an object, never as a plain list:
   {
     "t0": [],
     "t1": ["python3 -m pytest path/to/test.py -q"],
     "t2": []
   }
   Use T0 for cheap syntax/static gates, T1 for targeted packet tests, T2 for broader/full checks.
```

Also add:

```text
Each packet should include expected_evidence proving its verification command or changed artifact.
```

---

## P0-2 — Self-improvement/admin UI prompt requirements are incomplete

Status: **not fixed.**

TZ-014 explicitly required self-improvement-specific instructions:

```text
For admin UI/static/template changes:
- use acceptance_profile NORMAL or STRICT depending on risk;
- include targeted syntax/static checks in verification.t1;
- include expected_evidence for changed admin/template/static files;
- if JavaScript is touched, include a syntax/build/smoke check where available;
- if Python/API/worker code is touched, use STRICT unless the change is tests-only or docs-only.
```

Current self-improvement prompt only lists metadata fields and restart guidance. It does not tell the architect how to choose FAST/NORMAL/STRICT for admin UI/core changes, and it does not require admin/static/JS evidence.

### Required fix

Inside the `if self_improvement:` prompt block, add:

```text
For admin UI/static/template changes:
- use acceptance_profile NORMAL or STRICT depending on risk;
- include targeted syntax/static checks in verification.t1;
- include expected_evidence for changed admin/template/static files;
- if JavaScript is touched, include a syntax/build/smoke check where available;
- if Python/API/worker code is touched, use STRICT unless the change is tests-only or docs-only.

Use FAST only for tiny sandbox/docs/test-only changes.
Use NORMAL for ordinary product/UI changes with deterministic tests.
Use STRICT for auth, billing, payments, security, migrations, core orchestrator, worker, merge/git logic, self-improvement runtime.
```

This matters because the next planned task is admin UI self-improvement.

---

## P1-1 — Required tests from TZ-014 appear missing

Status: **not fixed / not evidenced.**

The commit touches implementation files and adds the runbook, but I did not find evidence of the requested tests being added:

```text
test_adapter_passes_base_ref_to_legacy_runner
test_call_legacy_runner_passes_base_ref_to_run_e2e_packet
test_acceptance_pipeline_uses_base_sha_for_changed_files
test_adapter_verifier_context_changed_files_uses_same_base
test_architect_prompt_mentions_t0_t1_t2_verification_shape
test_architect_prompt_mentions_expected_evidence
test_architect_prompt_self_improvement_requires_admin_ui_checks
test_llm_runner_writes_prompt_under_grace_state_root
test_llm_runner_opencode_instruction_uses_absolute_prompt_path_when_state_root_set
```

For a one-off FAST golden this is tolerable. For self-improvement, these are important regression tests.

### Required fix

Add at least these focused tests before running the admin UI self-improvement task:

```text
tests/grace_control/adapters/test_git_contract.py
  - test_adapter_passes_base_ref_to_run_e2e_packet
  - test_acceptance_pipeline_uses_base_sha_for_changed_files

tests/api/test_architect_prompt_contract.py
  - test_architect_prompt_mentions_t0_t1_t2_verification_shape
  - test_architect_prompt_self_improvement_requires_admin_ui_checks

tests/grace_control/core/test_llm_runner.py
  - test_llm_runner_writes_prompt_under_grace_state_root
  - test_llm_runner_opencode_instruction_uses_absolute_prompt_path_when_state_root_set
```

Mock subprocess/LLM calls. Do not invoke real `opencode` or `agy`.

---

## P1-2 — Runbook wording is now slightly stale

Status: **minor.**

Runbook still says:

```text
use GRACE_BASE_REF=HEAD for local runs unless base_ref is explicitly passed through end-to-end
```

But this commit now passes `base_ref` through the main path. Better wording:

```text
Use GRACE_BASE_REF=HEAD for local self-improvement runs unless you intentionally want origin/main or a pinned SHA. The selected base_ref is used consistently for worktree creation, commit diff, and acceptance diff.
```

Not a blocker.

---

## Golden readiness

This commit should not block the current FAST golden. The golden does not use architect LLM generation, verifier, or reviewer, and the base_ref/acceptance/llm_runner changes are directionally safe.

Still run from clean repo and with:

```bash
export GRACE_BASE_REF=HEAD
```

---

## Required rework checklist before self-improvement/admin UI

1. Fix architect prompt rule 8: `verification` object, not list.
2. Add self-improvement/admin UI verification/evidence/profile rules.
3. Add focused tests for base_ref flow, architect prompt, and llm_runner prompt root.
4. Optionally update runbook wording about base_ref now being end-to-end.

---

## Suggested commands after rework

```bash
pytest tests/grace_control/adapters/test_git_contract.py -q
pytest tests/api/test_architect_prompt_contract.py -q
pytest tests/grace_control/core/test_llm_runner.py -q
pytest tests/grace_control/core/test_acceptance_pipeline.py -q
pytest tests -q
```

No GitHub combined statuses were attached to `2f05a41149b0bc06bdfc0da9a8405dc9bf020e52`, so I could not independently verify local test claims.

---

## Final verdict

**REWORK_REQUIRED BEFORE SELF-IMPROVEMENT. PASS FOR FAST GOLDEN.**

The git/base_ref and LLM state-root wiring are mostly fixed. The remaining issue is the architect prompt: it still gives one old-format instruction and lacks the self-improvement/admin UI checks that were explicitly requested in TZ-014.
