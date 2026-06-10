# Review: Minimal worktree patch (`356097a`)

Date: 2026-06-10
Reviewer: ChatGPT
Commit reviewed: `356097a92d82844ba37866fd811c6b481dad4370`
Task: `docs/work/TZ_MINIMAL_WORKTREE_AND_CONTEXT_BUILDER.md`

## Verdict

**BLOCKED / not accepted as implementation of the P0 minimal-worktree TZ.**

The patch is a useful experiment and may reduce `opencode run` memory in a narrow fixture case, but it is not yet a safe implementation of the requested minimal workspace architecture.

Main reason: the new `minimal_repo` mode creates a separate git repository by copying scope files into a flat directory. That breaks the relationship between:

```text
original target repo paths
allowed_write_scope
changed_files
agent.patch
commit_sha
acceptance pipeline
merge/apply path
```

It can make an agent run small, but the resulting changes may no longer be correctly attributable or applicable back to the real target repository.

## What was changed

Files changed:

```text
src/grace_control/adapters/packet_executor.py
src/grace_control/config/agent_profiles.yaml
tests/grace_control/adapters/test_w6_executor_split.py
```

The profile change enables:

```yaml
minimal_repo: true
skip_context_builder: true
```

for `coder-opencode`.

The executor now branches:

```python
is_minimal = executor.get("minimal_repo", False)

if is_minimal:
    wt_path.mkdir(parents=True, exist_ok=True)
    git._run(["init", "-q"], wt_path)
    ...
    for scope_path in eff:
        src = Path(scope_path)
        if src.exists():
            dst = wt_path / src.name
            shutil.copy2(src, dst)
```

## Positive findings

### 1. The patch attacks the real problem

The known OOM issue comes from handing the full GRACE repo/worktree to the agent. This patch attempts to stop doing that for `coder-opencode` by creating a much smaller workspace.

That direction is correct.

### 2. The change is feature-flagged per executor profile

The new behavior is behind:

```yaml
minimal_repo: true
```

This is better than globally changing all executors at once.

### 3. `coder-opencode` now explicitly avoids context collector in profile

The profile contains:

```yaml
skip_context_builder: true
```

This expresses the intended fast path: do not run context collection before the small live run.

However, see blocker below: I do not see actual runtime handling for this flag in this patch.

## Blockers

### BLOCKER 1 — Relative paths are not preserved

Current minimal repo copy logic uses only `src.name`:

```python
src = Path(scope_path)
dst = wt_path / src.name
shutil.copy2(src, dst)
```

This flattens the file tree.

Example:

```text
allowed_write_scope: src/app/main.py
copied to:          <wt>/main.py
```

Problems:

- package/module imports may break;
- tests may not find files;
- `allowed_write_scope` no longer matches changed files;
- `scope_guard` and changed-file reporting may see `main.py`, not `src/app/main.py`;
- two files with the same basename collide:

```text
src/app/main.py
tests/main.py
```

both become:

```text
<wt>/main.py
```

Required fix:

Preserve paths relative to `target_repo_root` / `project_root`:

```python
rel = src.relative_to(target_root)
dst = wt_path / rel
dst.parent.mkdir(parents=True, exist_ok=True)
shutil.copy2(src, dst)
```

If `allowed_write_scope` is relative, resolve it as:

```python
src = target_root / scope_path
rel = Path(scope_path)
```

Do not use only basename.

### BLOCKER 2 — Source path resolution is ambiguous and likely wrong

The code does:

```python
src = Path(scope_path)
if src.exists():
    ...
```

This resolves relative paths against the Python process current working directory, not explicitly against the target repository root.

The TZ required clear separation:

```text
GRACE_PROJECT_ROOT      = orchestrator root
GRACE_TARGET_REPO_ROOT  = project being modified / fixture app
GRACE_WORKTREE_ROOT     = attempts root
```

This patch does not implement that separation. It still relies on whichever cwd makes `Path(scope_path).exists()` true.

Required fix:

Introduce an explicit target root resolution step:

```python
target_root = settings.target_repo_root or self.project_root
src = Path(scope_path)
if not src.is_absolute():
    src = target_root / scope_path
```

Then preserve relative path under `wt_path`.

### BLOCKER 3 — Minimal repo commit/patch is unrelated to original target repo

The minimal mode initializes a fresh repo:

```python
git init
commit -m init
```

But later code still passes the original `base_sha` from the real project into `_write_agent_patch()`:

```python
git diff <base_sha>
```

inside the minimal repo.

That `base_sha` does not exist in the fresh minimal repo, so patch generation can fail or become meaningless.

Likewise, the `commit_sha` produced by `AgentCommitService` is a commit in the isolated minimal repo, not a commit on the target project branch. It is not directly mergeable into the target repo.

Required fix options:

Option A, preferred for P0 fixture:

- Treat minimal repo as a patch workspace only.
- Generate patch against the minimal repo's own init commit.
- Store `minimal_base_sha` separately.
- Map changed files back to original target-relative paths.
- Apply or validate patch back to target repo explicitly.

Option B:

- Use `target_repo_worktree` from the real target repo for now.
- Defer `scoped_copy` until there is a patch-apply-back service.

Do not report isolated minimal-repo commit SHA as if it were a target repo commit.

### BLOCKER 4 — Acceptance/scope semantics can break

`_run_acceptance()` uses:

```python
wt = Path(result.worktree_path)
cf = get_changed_files(wt, base_ref=base_sha or base_ref)
run_acceptance_pipeline(... project_root=self.project_root, worktree_path=wt, base_sha=base_sha)
```

In minimal mode:

- `wt` is a fresh repo;
- `base_sha` belongs to original repo;
- copied file paths may be flattened;
- minimal repo may lack project config files needed for tests;
- `project_root` still points to `self.project_root`, not an explicit `target_repo_root`.

So acceptance may pass/fail for the wrong reasons or produce changed files that cannot map to original allowed scope.

Required fix:

Minimal workspace must carry evidence fields:

```text
workspace_mode
workspace_path
target_repo_root
minimal_base_sha
copied_files: original_rel -> workspace_rel
changed_files_workspace
changed_files_target_rel
```

Acceptance/scope guard should validate target-relative changed files, not flattened workspace basenames.

### BLOCKER 5 — No workspace builder service / no workspace mode

The TZ asked for explicit workspace mode:

```yaml
execution:
  workspace_mode: scoped_copy | target_repo_worktree | full_git_worktree
```

and suggested a dedicated service:

```text
src/grace_control/services/agent_workspace_builder.py
```

This patch adds ad-hoc logic inside `PacketExecutionAdapter._call_executor()` only.

Required fix:

Extract this into a small deterministic workspace builder service before expanding usage.

At minimum the service should return:

```text
workspace_path
workspace_mode
target_repo_root
copied_files
omitted_files
base_sha/minimal_base_sha
budget_report
```

### BLOCKER 6 — `skip_context_builder` appears to be config-only

The commit adds:

```yaml
skip_context_builder: true
```

but this patch does not show runtime logic that reads and acts on that flag.

I also do not see a bounded `agent_context_builder.py` or a budgeted context bundle implementation.

Required fix:

Either:

- implement the flag where context collection is invoked; or
- remove the claim that context builder skipping is implemented.

For the full TZ, still required:

```text
src/grace_control/services/agent_context_builder.py
hard file/byte budgets
AI_HEADER / CONTRACT / MAP / BLOCK-first scanning
budget_report in evidence
```

### BLOCKER 7 — Missing minimal-workspace tests

The reported test count is green, but the changed test only relaxes a previous import assertion:

```diff
- assert "import shutil" not in src
```

There are no focused tests proving:

- paths are preserved;
- minimal repo does not include full GRACE repo;
- copied file count is bounded;
- changed files map back to target-relative paths;
- duplicate basenames do not collide;
- `opencode run --dir` receives the minimal workspace;
- patch/evidence is usable after the isolated run;
- `skip_context_builder` is actually honored.

Required fix:

Add tests from `TZ_MINIMAL_WORKTREE_AND_CONTEXT_BUILDER.md`, especially:

```text
workspace excludes orchestrator files
workspace preserves target-relative paths
AgentRunService/backend receives minimal workspace path
context builder skip/budget behavior is enforced
```

## Major concerns

### MAJOR 1 — Minimal copy is too minimal for real project tests

The copy logic only copies scope files and `test_*.py` siblings if the scope parent directory is named `tests`.

It does not include common required project files:

```text
pyproject.toml
requirements*.txt
pytest.ini
package.json
pnpm-lock.yaml
tsconfig.json
vite/next/vitest/playwright config
src package __init__.py files
```

For fixture this might work accidentally. For Solar Sage or most real projects, tests/build/typecheck will likely fail.

### MAJOR 2 — No evidence/reporting for workspace minimization

The TZ required evidence-visible reporting:

```text
workspace_mode
workspace_path
copied_files count
omitted_files
context budget report
```

This patch does not add that reporting.

Without that, the admin UI/evidence cannot tell whether an agent run used full repo or minimal workspace.

### MAJOR 3 — Defaulting `coder-opencode` to `minimal_repo: true` may be too broad

Turning this on in the default coder profile affects every `coder-opencode` run.

Given the issues above, this is risky for non-fixture tasks.

Recommended safer approach:

```yaml
coder-opencode-minimal-fixture:
  minimal_repo: true
  skip_context_builder: true

coder-opencode:
  minimal_repo: false
```

or gate by scenario/env:

```text
GRACE_WORKSPACE_MODE=scoped_copy
```

## Acceptance criteria check

| Criterion from TZ | Status |
|---|---|
| Agent no longer gets full GRACE repo in minimal mode | PARTIAL |
| Target project root separated from orchestrator root | FAIL |
| Explicit `workspace_mode` | FAIL |
| `target_repo_worktree` mode | FAIL |
| `scoped_copy` with preserved relative paths | FAIL |
| Context builder hard budget | FAIL |
| AI_HEADER / CONTRACT / MAP-first scanning | FAIL |
| Canon digest instead of duplicated full prompts | NOT ADDRESSED |
| Evidence records workspace/budget report | FAIL |
| Tests prove minimal workspace semantics | FAIL |

## Recommended next patch

Do not throw away the idea. But do not accept this as done.

Implement a smaller safe follow-up:

1. Create `AgentWorkspaceBuilder` service.
2. Resolve `target_root` explicitly.
3. Preserve target-relative paths when copying.
4. Copy minimal config allowlist for fixture/Python projects.
5. Track mapping:

```text
original_rel -> workspace_rel
```

6. Use minimal repo's own base SHA for `git diff`.
7. Store workspace report in run evidence.
8. Add tests for path preservation and no full-GRACE leakage.
9. Keep `minimal_repo` off by default for real projects until patch/apply-back semantics are proven.

## Final decision

**Blocked.**

This is a good proof-of-direction for memory reduction, but it is not safe enough for the GRACE pipeline yet.

The next implementation should focus less on “make opencode see fewer files” and more on the full contract:

```text
small workspace
preserved paths
valid diff
valid changed_files
valid evidence
applicable back to target repo
```
