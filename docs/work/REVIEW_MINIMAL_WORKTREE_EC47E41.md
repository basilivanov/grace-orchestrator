# Review: Minimal workspace builder patch (`ec47e41`)

Date: 2026-06-10
Reviewer: ChatGPT
Commit reviewed: `ec47e4120d2c5bc420e97182195d220359b09d0c`
Task: `docs/work/TZ_MINIMAL_WORKTREE_AND_CONTEXT_BUILDER.md`
Previous review: `docs/work/REVIEW_MINIMAL_WORKTREE_356097A.md`

## Verdict

**PARTIAL ACCEPT / still needs one safety follow-up before broad use.**

This patch fixes the main structural problems from `356097a`:

- workspace creation is now in `AgentWorkspaceBuilder`;
- target-relative paths are preserved;
- minimal repo gets its own `base_sha`;
- copied file mapping is available in `WorkspaceResult`;
- the default `coder-opencode` profile is safe again;
- minimal mode is isolated into `coder-opencode-fixture`;
- tests were added for path preservation/config/exclusion/base_sha/to_dict/invalid target.

This is a solid improvement and is close enough for controlled fixture experiments.

However, it is **not yet fully accepted for broad project use** because there is one important path safety issue and several remaining architecture gaps from the original P0 TZ.

## Files reviewed

```text
src/grace_control/services/agent_workspace_builder.py
src/grace_control/adapters/packet_executor.py
src/grace_control/config/agent_profiles.yaml
tests/grace_control/services/test_agent_workspace_builder.py
```

## Positive findings

### 1. Dedicated workspace builder service added

The ad-hoc copy logic was removed from `packet_executor` and replaced by:

```text
src/grace_control/services/agent_workspace_builder.py
```

This is the correct direction. The service exposes `WorkspaceResult` with:

```text
workspace_path
workspace_mode
target_repo_root
copied_files
omitted_files
base_sha
```

### 2. Target-relative paths are preserved

The builder now resolves files against `target_root` and copies them under the same relative path:

```python
src = self._target_root / sp
rel = src.relative_to(self._target_root)
dst = wt_path / rel
```

This fixes the previous basename-flattening blocker.

### 3. Minimal repo base SHA is now local to the minimal workspace

The builder initializes a fresh git repo and returns its own initial commit SHA:

```python
sha_result = git._run(["rev-parse", "HEAD"], repo_path)
return sha_result.stdout.strip() or ""
```

`packet_executor` then assigns:

```python
base_sha = ws.base_sha
```

This fixes the previous issue where the original project SHA was used inside an unrelated minimal repo.

### 4. Default `coder-opencode` is safe again

The normal `coder-opencode` profile no longer has `minimal_repo: true`.

A separate profile was added:

```text
coder-opencode-fixture
```

with:

```yaml
minimal_repo: true
skip_context_builder: true
```

This is much safer than enabling minimal mode globally.

### 5. Focused tests were added

The new tests cover:

- path preservation;
- config allowlist;
- exclusion of orchestrator files;
- workspace result serialization;
- minimal repo base SHA;
- invalid target root.

Good coverage for the newly extracted service.

## Blocker before broad use

### BLOCKER 1 — Absolute paths outside `target_root` are not safely rejected

Current builder logic:

```python
src = Path(sp)
if not src.is_absolute():
    src = self._target_root / sp
if not src.exists():
    continue
try:
    rel = src.relative_to(self._target_root)
except ValueError:
    rel = Path(sp)
dst = wt_path / rel
```

If `sp` is an absolute path outside `target_root`, then:

```text
src.relative_to(self._target_root)
```

raises `ValueError`, and the fallback uses:

```python
rel = Path(sp)
```

If `rel` is absolute, then:

```python
dst = wt_path / rel
```

can resolve to the absolute path itself, outside the workspace. This is unsafe and violates the workspace boundary.

Required fix:

- If a scope path resolves outside `target_root`, do not copy it.
- Add it to `omitted_files` with reason.
- Never allow an absolute `rel` to be used as a destination path.
- Add a regression test.

Suggested implementation:

```python
resolved = src.resolve()
try:
    rel = resolved.relative_to(self._target_root)
except ValueError:
    omitted.append(f"outside_target_root:{sp}")
    continue
if rel.is_absolute() or ".." in rel.parts:
    omitted.append(f"unsafe_relative_path:{sp}")
    continue
```

Also use `resolve()` on `self._target_root` and `src` before comparing.

## Major remaining gaps

### MAJOR 1 — Workspace report is not persisted in run evidence

`WorkspaceResult.to_dict()` exists, but I do not see it being stored in `result.evidence` / `PacketRun.result_json` / dev replay.

The original TZ required evidence-visible data:

```text
workspace_mode
workspace_path
target_repo_root
copied_files
omitted_files
base_sha/minimal_base_sha
budget_report
```

Required follow-up:

- Add `workspace_report=ws.to_dict()` to execution evidence/dev replay when minimal mode is used.
- Surface enough of it in admin/logs so we can confirm a run did not use full GRACE repo.

### MAJOR 2 — Patch/apply-back semantics are still not complete

The minimal workspace now produces diffs against its own minimal base SHA, which is good for local `git diff`.

But a commit SHA from the minimal repo is still not a commit in the real target repo.

For fixture experiments this may be acceptable. For Solar Sage or any real repo, we still need either:

```text
1. apply patch back to target repo and commit there; or
2. use target_repo_worktree mode instead of scoped_copy; or
3. explicitly mark scoped_copy as no-merge / patch-only mode until apply-back exists.
```

Required before real project use:

- Decide whether `scoped_copy` is patch-only or apply-back capable.
- Do not treat minimal repo `commit_sha` as a target repo commit.

### MAJOR 3 — `skip_context_builder` runtime handling is explicitly not implemented

The profile has:

```yaml
skip_context_builder: true
```

but the user notes runtime handling will be separate. That is fine, but it means this patch does not implement the context-builder portion of the original P0 TZ.

Remaining work:

```text
src/grace_control/services/agent_context_builder.py
hard file/byte budgets
AI_HEADER / CONTRACT / MAP / BLOCK-first scanning
canon digest instead of huge prompt duplication
budget_report in evidence
runtime handling of skip_context_builder
```

### MAJOR 4 — Config allowlist is too narrow

Current packet executor uses:

```python
config_allowlist=["pyproject.toml"]
```

Good enough for the minimal fixture, but not for typical Python/JS projects.

Before broader use, config allowlist should include at least project-type-specific files:

Python:

```text
pyproject.toml
requirements*.txt
pytest.ini
setup.cfg
setup.py
```

JS/TS:

```text
package.json
pnpm-lock.yaml
package-lock.json
yarn.lock
tsconfig.json
next.config.*
vite.config.*
vitest.config.*
playwright.config.*
```

Do not block fixture testing on this, but do not call this production-ready for Solar Sage.

### MAJOR 5 — Empty workspace / empty commit behavior is not explicit

If no scope files and no config files are copied, `git commit -m init` may fail and `base_sha` may be empty.

Required follow-up:

- If no files are copied, either fail fast with clear error or create a harmless marker file like `.grace-workspace`.
- Add test.

## Acceptance criteria check

| Criterion | Status |
|---|---|
| Dedicated workspace builder service | PASS |
| Preserve target-relative paths | PASS |
| Explicit target_root resolution | PASS, but needs outside-root guard |
| Minimal repo own base SHA | PASS |
| copied_files mapping | PASS |
| default coder-opencode safe | PASS |
| fixture-only minimal profile | PASS |
| tests for builder basics | PASS |
| guard against scope escaping target_root | FAIL |
| workspace report persisted in evidence | FAIL |
| apply-back/target commit semantics | NOT DONE |
| context builder minimization | NOT DONE |

## Recommendation

Accept this patch as a **fixture-only minimal workspace foundation**, after one small safety follow-up:

```text
Guard scope paths so they can never copy/write outside target_root/workspace.
```

Then run the live fixture using `coder-opencode-fixture` and verify memory/process behavior.

Do **not** yet use `scoped_copy` for Solar Sage or real repos until:

```text
workspace report is persisted
patch/apply-back semantics are clear
config allowlist is project-aware
context builder budget/skip logic is implemented
```

## Required follow-up patch

1. Add outside-target-root guard in `AgentWorkspaceBuilder`.
2. Add regression test with an absolute path outside target root.
3. Add no-files-copied behavior test or explicit fail-fast.
4. Store `ws.to_dict()` in run evidence/dev replay for minimal mode.
5. Keep `coder-opencode-fixture` as the only profile with `minimal_repo: true`.

## Final decision

**Partial accept / not blocked for fixture experiments after safety guard.**

This is a major improvement over `356097a`, but it is still not the full P0 context/workspace minimization solution.
