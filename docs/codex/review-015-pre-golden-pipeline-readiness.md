# Codex Review 015 — Pre-golden pipeline / prompts / roles readiness

Scope reviewed: current `main` before running the test golden feature.

Verdict: **GO FOR FAST GOLDEN, WITH OPERATIONAL GUARDS. P1/P2 hardening remains before self-improvement/external runs.**

The current `golden-smoke-live-001.yaml` is FAST, sandboxed, uses `python3`, and should not call Evidence Verifier or Reviewer. The main remaining risks for this specific golden are operational git cleanliness and base-ref consistency, not prompts/roles.

---

## 1. Golden feature YAML

Status: **OK for first FAST golden.**

File:

```text
grace/features/golden-smoke-live-001.yaml
```

Current properties:

```yaml
acceptance_profile: FAST
scope:
  - sandbox/golden/live_001/
verification:
  t0: []
  t1:
    - python3 -m pytest sandbox/golden/live_001/test_date_util.py -q
  t2: []
expected_evidence:
  - id: sandbox_date_util_test_green
    kind: command
    required: true
    pattern: sandbox/golden/live_001/test_date_util.py
```

This is the right shape for a cheap first smoke:

```text
coder
→ deterministic acceptance
→ skip Evidence Verifier
→ skip Reviewer
→ merge
```

Note: `expected_evidence` is ignored for FAST by `check_expected_evidence(...)`, so the command evidence is not enforced in FAST. The T1 command still runs and must pass.

---

## 2. Role/profile config

Status: **OK for current golden.**

File:

```text
src/prefect_grace/agent_profiles.yaml
```

Profiles exist for:

```text
architect-premium → architect/reviewer, deepseek-v4-pro
reviewer-premium  → reviewer, deepseek-v4-pro
coder-flash       → coder, deepseek-v4-flash
coder-agy-flash   → coder, gemini-3.5-flash
verifier-cheap    → verifier, gemini-3.5-flash
```

For FAST golden, only coder should matter. Evidence Verifier and Reviewer should not be called.

P1 note: `agent_profiles.yaml` still has:

```yaml
codex:
  workdir: /tmp/grace-orchestrator-export
```

This can be misleading/stale for external projects. I did not find evidence this value controls the current FAST path, but clean it up later or document whether it is ignored.

---

## 3. Verifier/reviewer prompts

Status: **OK, not used by FAST golden.**

Files:

```text
src/prefect_grace/prompts/evidence_verifier_prompt.md
src/prefect_grace/prompts/reviewer_prompt.md
```

They are consistent with current JSON models:

```text
PASS | REWORK_TO_CODER | RETURN_TO_ARCHITECT
```

and the decision split is correct:

```text
implementation/evidence gaps → coder
bad/impossible packet/spec → architect
```

No blocker here.

---

## 4. Architect prompt / generated plans

Status: **OK for YAML golden. P1 before self-improvement.**

The golden file already has explicit waves/packets, so the architect LLM is not used to generate the plan.

However, the architect prompt still asks for old-style verification:

```json
"verification": ["pytest tests/ -x --timeout=60"]
```

while the newer pipeline prefers:

```json
"verification": {
  "t0": [],
  "t1": ["..."],
  "t2": []
}
```

This is not an immediate blocker because `build_packet_contract(...)` converts list-style `verification` into T1 commands. Still, before self-improvement/admin UI tasks, update the architect prompt to emit:

```json
"verification": {"t0": [], "t1": [], "t2": []},
"expected_evidence": [...]
```

Suggested P1 test:

```text
test_architect_generated_plan_uses_t0_t1_t2_verification_shape
```

---

## 5. Acceptance profile routing

Status: **OK.**

Current adapter behavior:

```text
FAST   → deterministic only, verifier/reviewer skipped
NORMAL → deterministic + Evidence Verifier, Reviewer skipped by default
STRICT → deterministic + Evidence Verifier + Reviewer
```

For the golden packet:

```yaml
acceptance_profile: FAST
```

so `agy` and `opencode` should not be called after deterministic acceptance.

---

## 6. Deterministic acceptance

Status: **OK enough for golden, with one P1 base-ref issue.**

Good:

- explicit `verification.t0: []` skips default T0 commands;
- T1 command runs with `CommandRunner(worktree_path)`;
- expected evidence is checked against `worktree_path` for non-FAST profiles;
- scope guard uses worktree-based `ScopeGuard(worktree_path)`.

P1 issue:

```python
changed_files = get_changed_files(worktree_path, base_ref="main")
```

inside `run_acceptance_pipeline(...)` is still hardcoded to `main`.

For the current golden this is usually okay if local `main` is clean and the worktree branch is based on local `HEAD/main`. But for external/CI and `GRACE_BASE_REF=origin/main`, acceptance changed-file detection should use the same base SHA/ref as worktree creation and commit diff.

Suggested follow-up:

```text
Pass base_ref/base_sha into run_acceptance_pipeline and use it for get_changed_files(...).
```

Suggested test:

```text
test_acceptance_changed_files_uses_configured_base_ref_not_hardcoded_main
```

Not a FAST golden blocker.

---

## 7. Git/base-ref state

Status: **OK for golden if run cleanly. P1 external hardening remains.**

Recent fix resolves `base_sha` before agent run and uses `<base_sha>...HEAD` for detecting already-committed changes. That fixes the important self-commit/no-op false rejection in the default path.

Remaining P1:

```text
base_ref is not passed into run_e2e_packet(...), so worktree creation still uses run_e2e_packet default HEAD.
```

For golden, keep:

```bash
export GRACE_BASE_REF=HEAD
```

or leave it unset. Do not run this golden with `GRACE_BASE_REF=origin/main` until worktree creation gets the same base ref.

---

## 8. Merge path

Status: **OK enough for golden if target repo is clean.**

Good:

- Worker sends `target_repo_root`, `worktree_path`, `branch_name`, `commit_sha`.
- WorkerAPIClient now accepts/sends `target_repo_root`.
- Merge endpoint validates target repo, branch, worktree existence, and dirty target repo.
- No automatic stash.
- Dirty target repo returns 409 and leaves packet accepted.

Operational requirement before golden:

```bash
git status --short
```

must be clean or only contain expected untracked files you intentionally remove/ignore. Since merge now fails closed on dirty target repo, run from a clean checkout.

P1 hardening:

- worktree registration check currently uses substring matching against `git worktree list --porcelain`; later parse `worktree <path>` lines and compare resolved paths.
- worker merge failure path should have a regression test that accepted packet is not released as failed after merge failure.

---

## 9. Eval runner

Status: **OK enough for golden if invoked from GRACE repo.**

Good:

- `--control-plane-root` exists;
- `--target-repo-root` exists;
- state/worktree default to `/tmp/grace-eval/<feature>/...`;
- DB default is `state_root/grace.db`;
- `blocked` is terminal.

For current golden, run from the GRACE repo or pass both roots explicitly.

External-project caveat:

```bash
grace eval run ... --control-plane-root /path/to/grace-orchestrator --target-repo-root /path/to/target
```

must be documented/used later. If omitted from an external target repo, imports can still fail.

---

## 10. LLM runner / prompts storage

Status: **not relevant for FAST golden, P1 before NORMAL/STRICT/external.**

`llm_runner` writes prompt files to:

```python
Path.cwd() / ".grace_state" / "llm_prompts"
```

It does not use `GRACE_STATE_ROOT`.

For FAST golden this should not matter after architect planning, because verifier/reviewer are skipped and the YAML has waves already. But for generated plans, NORMAL/STRICT, and external projects, this can again create runtime state inside the wrong repo.

Suggested follow-up:

```text
llm_runner should write prompts under GRACE_STATE_ROOT/llm_prompts by default.
```

Suggested test:

```text
test_llm_runner_uses_grace_state_root_for_prompt_files
```

---

## 11. Current blockers for the test golden

I do **not** see a code/prompt/role blocker that should stop the current FAST golden.

The remaining blockers are operational:

1. local target repo must be clean;
2. run with `GRACE_BASE_REF=HEAD` or unset;
3. ensure the API server is restarted after latest code;
4. use `/tmp` state/worktrees/db/report;
5. delete old `.grace_state`, `.grace_worktrees`, old `/tmp/grace-eval/...` before run.

---

## 12. Recommended run command

From the GRACE repo root:

```bash
git pull --ff-only origin main
git status --short
```

If dirty, stop and clean/commit/stash manually. Merge endpoint will reject dirty target repo.

Then:

```bash
pkill -f "grace api" || true
rm -rf /tmp/grace-eval/golden-smoke-live-001
mkdir -p /tmp/grace-eval/golden-smoke-live-001

export GRACE_TARGET_REPO_ROOT="$PWD"
export GRACE_STATE_ROOT="/tmp/grace-eval/golden-smoke-live-001/state"
export GRACE_WORKTREE_ROOT="/tmp/grace-eval/golden-smoke-live-001/worktrees"
export GRACE_BASE_REF="HEAD"
export GRACE_DB_URL="sqlite:////tmp/grace-eval/golden-smoke-live-001/grace.db"
export GRACE_AGENT_TIMEOUT=1200
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
  --timeout 1200 \
  --control-plane-root "$PWD" \
  --target-repo-root "$PWD" \
  --state-root /tmp/grace-eval/golden-smoke-live-001/state \
  --worktree-root /tmp/grace-eval/golden-smoke-live-001/worktrees \
  --base-ref HEAD \
  --report /tmp/grace-eval/golden-smoke-live-001/report.json
```

After run:

```bash
cat /tmp/grace-eval/golden-smoke-live-001/report.json
find /tmp/grace-eval/golden-smoke-live-001/state -name acceptance_report.json -exec cat {} \;
git status --short
git log --oneline -5
find sandbox/golden/live_001 -maxdepth 2 -type f -print
```

Expected:

```text
packet state: merged
changed files only under sandbox/golden/live_001/
no verifier/reviewer logs for this packet
```

---

## 13. Follow-up hardening before self-improvement/admin UI

Before using self-improvement to change the admin UI, do these P1s:

1. Pass `base_ref` into `run_e2e_packet(...)` so worktree base and diff base are identical.
2. Pass base_ref/base_sha into `run_acceptance_pipeline(...)`; remove hardcoded `base_ref="main"`.
3. Update architect prompt to emit `verification: {t0,t1,t2}` and `expected_evidence`.
4. Make `llm_runner` use `GRACE_STATE_ROOT/llm_prompts`.
5. Add merge failure worker regression test.
6. Parse `git worktree list --porcelain` robustly instead of substring matching.

---

## Final verdict

**GO FOR FAST GOLDEN.**

Do not treat this as full readiness for external projects or self-improvement yet. For the current sandbox FAST golden, the pipeline/prompts/roles are aligned enough, provided the run is clean and uses `HEAD` as base.
