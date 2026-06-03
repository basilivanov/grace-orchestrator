# TZ 014 — Pre-self-improvement hardening: base_ref, acceptance diff, architect prompt, LLM state root

Audience: Flash coder / literal executor.

Goal: close the remaining P1 issues from `review-015-pre-golden-pipeline-readiness.md` before using self-improvement to modify the admin UI.

This task is not about adding new admin UI features. It only hardens the pipeline so future self-improvement/admin UI work runs safely and predictably.

---

## 0. Required outcome

After this task:

```text
worktree creation base == commit diff base == acceptance diff base
architect-generated plans use verification.t0/t1/t2 shape
LLM prompt files go to GRACE_STATE_ROOT, not Path.cwd()/.grace_state
```

This must work for:

```text
1. current repo golden/self-improvement
2. future external target projects
3. NORMAL/STRICT runs with verifier/reviewer
```

---

## 1. Patch 1 — pass base_ref into legacy worktree creation

### Problem

`PacketExecutionAdapter.execute()` resolves `base_sha` before agent run, but `_call_legacy_runner(...)` still calls `run_e2e_packet(...)` without passing `base_ref`.

Current shape:

```python
result = await self._call_legacy_runner(..., attempt=run_number)
```

and later:

```python
run_e2e_packet(..., attempt=attempt, keep_worktree=True, ...)
```

So `run_e2e_packet(...)` uses its default `base_ref="HEAD"`.

This can become inconsistent:

```text
commit diff base = GRACE_BASE_REF / base_sha
worktree creation base = HEAD
```

### Required behavior

Use the same `base_ref` everywhere.

In `PacketExecutionAdapter.execute()`:

```python
base_ref = os.environ.get("GRACE_BASE_REF", "HEAD")
base_sha = resolve base_ref before agent run

result = await self._call_legacy_runner(
    ...,
    attempt=run_number,
    base_ref=base_ref,
)
```

Update `_call_legacy_runner(...)` signature:

```python
async def _call_legacy_runner(
    ...,
    attempt: int = 1,
    base_ref: str = "HEAD",
):
```

Pass into `run_e2e_packet(...)`:

```python
run_e2e_packet(..., base_ref=base_ref, ...)
```

### Tests required

Add/update tests in:

```text
tests/grace_control/adapters/test_packet_executor_acceptance.py
```

or create:

```text
tests/grace_control/adapters/test_git_contract.py
```

Tests:

```text
test_adapter_passes_base_ref_to_legacy_runner
test_call_legacy_runner_passes_base_ref_to_run_e2e_packet
test_worktree_creation_base_and_commit_diff_base_match
```

Use mocks; do not run real agents.

---

## 2. Patch 2 — remove hardcoded `base_ref="main"` in acceptance changed-files detection

### Problem

`run_acceptance_pipeline(...)` currently does:

```python
changed_files = get_changed_files(worktree_path, base_ref="main")
```

This ignores:

```text
GRACE_BASE_REF
resolved base_sha
actual worktree base
```

For self-improvement/external projects, this can produce wrong scope validation.

### Required behavior

Acceptance changed-files detection must use the same base as worktree creation and commit diff.

Preferred minimal implementation:

1. Extend `run_acceptance_pipeline(...)` signature:

```python
def run_acceptance_pipeline(
    packet,
    legacy_result,
    project_root: Path,
    worktree_path: Path,
    branch_name: str,
    run_dir: Path,
    base_ref: str | None = None,
    base_sha: str | None = None,
) -> AcceptanceReport:
```

2. Choose changed-files base:

```python
changed_base = base_sha or base_ref or os.environ.get("GRACE_BASE_REF", "HEAD")
changed_files = get_changed_files(worktree_path, base_ref=changed_base)
```

3. In `PacketExecutionAdapter.execute()`, pass both:

```python
accept_report = run_acceptance_pipeline(
    ...,
    base_ref=base_ref,
    base_sha=base_sha,
)
```

4. Also update the later verifier/reviewer context collection in adapter:

Current:

```python
changed_files = _get_changed_files(wt_path, base_ref="main")
```

Replace with:

```python
changed_files = _get_changed_files(wt_path, base_ref=base_sha or base_ref)
```

### Tests required

Add tests:

```text
test_acceptance_pipeline_uses_base_sha_for_changed_files
test_acceptance_pipeline_uses_base_ref_when_base_sha_missing
test_adapter_verifier_context_changed_files_uses_same_base
test_no_hardcoded_main_in_acceptance_changed_files
```

The last test may be simple source-level assertion if convenient:

```python
assert 'base_ref="main"' not in acceptance_pipeline_source
```

---

## 3. Patch 3 — update architect prompt to new verification contract

### Problem

The architect prompt still asks the LLM to output old-style verification:

```json
"verification": ["pytest tests/ -x --timeout=60"]
```

The pipeline supports this legacy list by converting it to T1, but new canonical contract is:

```json
"verification": {
  "t0": [],
  "t1": ["..."],
  "t2": []
}
```

For self-improvement/admin UI tasks, the architect must produce more explicit gates.

### Required behavior

File:

```text
src/grace_control/api/routers/architect.py
```

Update `_call_architect_llm(...)` prompt.

Replace old prompt examples with new shape.

Required example packet:

```json
{
  "title": "Add login endpoint",
  "scope": ["src/auth.py", "tests/test_auth.py"],
  "acceptance_profile": "NORMAL",
  "depends_on": [],
  "description": "what this packet does",
  "verification": {
    "t0": [],
    "t1": ["python3 -m pytest tests/test_auth.py -q"],
    "t2": []
  },
  "expected_evidence": [
    {
      "id": "auth_test_green",
      "kind": "command",
      "required": true,
      "pattern": "tests/test_auth.py"
    }
  ]
}
```

Root-level plan must also use:

```json
"verification": {
  "t0": [],
  "t1": [],
  "t2": []
}
```

not list format.

### Self-improvement-specific prompt requirements

In SELF-IMPROVEMENT MODE, add explicit instruction:

```text
For admin UI/static/template changes:
- use acceptance_profile NORMAL or STRICT depending on risk;
- include targeted syntax/static checks in verification.t1;
- include expected_evidence for changed admin/template/static files;
- if JavaScript is touched, include a syntax/build/smoke check where available;
- if Python/API/worker code is touched, use STRICT unless the change is tests-only or docs-only.
```

Also instruct:

```text
Use FAST only for tiny sandbox/docs/test-only changes.
Use NORMAL for ordinary product changes with deterministic tests.
Use STRICT for auth, billing, payments, security, migrations, core orchestrator, worker, merge/git logic, self-improvement runtime.
```

### Parser compatibility

Do not remove legacy list support from `build_packet_contract(...)` in this task. Keep backwards compatibility.

### Tests required

Add tests in existing architect tests or create:

```text
tests/api/test_architect_prompt_contract.py
```

Tests:

```text
test_architect_prompt_mentions_t0_t1_t2_verification_shape
test_architect_prompt_mentions_expected_evidence
test_architect_prompt_self_improvement_requires_admin_ui_checks
test_build_packet_contract_still_accepts_legacy_verification_list
```

---

## 4. Patch 4 — llm_runner must use GRACE_STATE_ROOT for prompt files

### Problem

`src/grace_control/core/llm_runner.py` writes prompt files to:

```python
project_root = cwd or Path.cwd()
prompt_dir = project_root / ".grace_state" / "llm_prompts"
```

This can pollute the target repo or control-plane cwd, especially in external-project mode.

### Required behavior

Prompt files should go to:

```text
GRACE_STATE_ROOT/llm_prompts
```

when `GRACE_STATE_ROOT` is set.

Implementation:

```python
state_root = Path(os.environ.get("GRACE_STATE_ROOT", "")) if os.environ.get("GRACE_STATE_ROOT") else None
if state_root:
    prompt_dir = state_root / "llm_prompts"
else:
    prompt_dir = project_root / ".grace_state" / "llm_prompts"
```

The subprocess cwd can remain:

```python
cwd=str(project_root)
```

because CLI tools may need project context.

But prompt file path must be handled carefully:

Current opencode instruction uses relative path:

```python
Read the task from .grace_state/llm_prompts/{tmp.name}
```

If prompt_dir is outside cwd, use absolute path:

```python
instruction = f"Read the task from {tmp}. Respond ONLY with valid JSON, no other text."
```

For agy:

```python
cmd = ["agy", "--model", model, "--prompt-file", str(tmp), "--json"]
```

already uses absolute path if `tmp` is absolute.

### Cleanup behavior

Keep existing cleanup:

```python
tmp.unlink(missing_ok=True)
```

Do not delete the whole prompt dir.

### Tests required

Create/update:

```text
tests/grace_control/core/test_llm_runner.py
```

Tests should mock subprocess creation; do not call real LLM.

Required tests:

```text
test_llm_runner_writes_prompt_under_grace_state_root
test_llm_runner_opencode_instruction_uses_absolute_prompt_path_when_state_root_set
test_llm_runner_falls_back_to_cwd_grace_state_when_env_missing
test_llm_runner_cleanup_removes_prompt_file
```

---

## 5. Patch 5 — runbook update for self-improvement/admin UI

Update or create:

```text
docs/codex/self-improvement-runbook.md
```

Content should say:

```text
Before self-improvement:
- run from clean target repo;
- use explicit /tmp state/worktree roots;
- use GRACE_BASE_REF=HEAD for local runs unless base_ref is explicitly passed through end-to-end;
- admin UI changes should use NORMAL/STRICT, not FAST by default;
- core/runtime/worker/git/merge changes require STRICT;
- verify no runtime state is created in target repo except intentional files.
```

Also include command skeleton:

```bash
export GRACE_TARGET_REPO_ROOT="$PWD"
export GRACE_STATE_ROOT="/tmp/grace-self-improvement/<run-id>/state"
export GRACE_WORKTREE_ROOT="/tmp/grace-self-improvement/<run-id>/worktrees"
export GRACE_BASE_REF="HEAD"
export GRACE_DB_URL="sqlite:////tmp/grace-self-improvement/<run-id>/grace.db"
```

---

## 6. Acceptance criteria

Done only if:

1. `base_ref` is passed into `run_e2e_packet(...)`.
2. Worktree base, commit diff base, and acceptance changed-files base are the same.
3. No hardcoded `base_ref="main"` remains in acceptance path.
4. Architect prompt emits canonical `verification: {t0,t1,t2}` and `expected_evidence` examples.
5. Legacy verification list still works in parser.
6. `llm_runner` uses `GRACE_STATE_ROOT/llm_prompts` when env var is set.
7. No real LLM is called in tests.
8. Existing FAST golden still works.

---

## 7. Tests to run

Run focused tests:

```bash
pytest tests/grace_control/adapters/test_packet_executor_acceptance.py -q
pytest tests/grace_control/adapters/test_git_contract.py -q
pytest tests/grace_control/core/test_acceptance_pipeline.py -q
pytest tests/grace_control/core/test_llm_runner.py -q
pytest tests/api/test_architect_prompt_contract.py -q
pytest tests -q
```

If some test files do not exist, create them or place equivalent tests in existing suites.

---

## 8. Do not do in this task

Do not implement admin UI changes.
Do not remove legacy verification list support.
Do not change FAST/NORMAL/STRICT routing semantics.
Do not make reviewer run for FAST.
Do not call real LLMs in unit tests.
Do not change merge strategy.
Do not remove legacy runner.
Do not introduce microservices or external queues.

---

## 9. Final coder report format

Coder must report:

```text
Files changed
Base_ref flow fixed: yes/no
Acceptance changed-files base fixed: yes/no
Architect prompt updated: yes/no
LLM prompt state root fixed: yes/no
Tests added
Tests run
Remaining blockers
```
