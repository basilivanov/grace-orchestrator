# TZ: Minimal worktree safety polish after `ec47e41`

Date: 2026-06-10
Status: ready for coder
Priority: P0 safety follow-up for fixture minimal mode
Scope: scoped_copy workspace safety + evidence visibility
Related:
- `docs/work/TZ_MINIMAL_WORKTREE_AND_CONTEXT_BUILDER.md`
- `docs/work/REVIEW_MINIMAL_WORKTREE_356097A.md`
- `docs/work/REVIEW_MINIMAL_WORKTREE_EC47E41.md`

## 1. Current state

`ec47e41` is a good foundation:

```text
AgentWorkspaceBuilder added
scoped_copy mode exists
relative paths are preserved
minimal repo gets its own base_sha
copied_files mapping exists
main coder-opencode profile is safe again
coder-opencode-fixture has minimal_repo: true
basic builder tests exist
```

But the implementation is not yet safe enough for broad use. It is acceptable only as a controlled fixture experiment after the safety issues below are fixed.

## 2. Goal

Polish the minimal worktree implementation so fixture runs can safely use `coder-opencode-fixture` without leaking outside `target_root`, without producing invisible workspace behavior, and without pretending scoped-copy commits are target-repo commits.

This is not the full context-builder project yet. This is the **safety/polish patch** for the workspace-builder foundation.

## 3. Non-goals

Do not implement the full context builder in this patch.
Do not implement Solar Sage support in this patch.
Do not implement apply-back/merge-to-target in this patch.
Do not turn `minimal_repo` on for the default `coder-opencode` profile.
Do not change packet lifecycle semantics.
Do not change health/watchdog.
Do not rewrite executor architecture beyond the minimal safety fixes.

## 4. Required fixes

### 4.1 Block paths outside `target_root`

Current risk:

```python
src = Path(sp)
if not src.is_absolute():
    src = self._target_root / sp
try:
    rel = src.relative_to(self._target_root)
except ValueError:
    rel = Path(sp)
dst = wt_path / rel
```

If `sp` is an absolute path outside `target_root`, fallback may produce an unsafe absolute destination.

Required behavior:

- Resolve both `target_root` and `src` with `.resolve()`.
- If `src` is outside `target_root`, do not copy it.
- Add it to `omitted_files` with a reason.
- Never use an absolute path as workspace-relative `rel`.
- Never allow `..` traversal in `rel.parts`.

Suggested implementation:

```python
resolved_target = self._target_root.resolve()
resolved_src = src.resolve()
try:
    rel = resolved_src.relative_to(resolved_target)
except ValueError:
    omitted.append(f"outside_target_root:{sp}")
    continue
if rel.is_absolute() or ".." in rel.parts:
    omitted.append(f"unsafe_relative_path:{sp}")
    continue
```

Acceptance:

```text
absolute path outside target_root is omitted
workspace does not contain that file
no file is written outside workspace
omitted_files records reason
```

### 4.2 Make empty workspace behavior explicit

Current risk: if no scope files and no config files are copied, `git commit -m init` may fail and `base_sha` may be empty.

Choose one behavior and test it.

Preferred behavior:

```text
fail fast with ValueError("no files copied into scoped workspace")
```

Acceptable alternative:

```text
create .grace-workspace marker file and include it in copied_files/omitted report
```

Preferred for now: **fail fast**. Empty workspaces usually mean the packet scope or target_root is wrong.

Acceptance:

```text
scope_paths=[] and missing config_allowlist -> clear ValueError
all missing scope paths -> clear ValueError
```

### 4.3 Persist workspace report in run evidence/dev replay

`WorkspaceResult.to_dict()` exists, but it is not yet visible in evidence.

Required:

When minimal mode is used, store workspace report in run result evidence/dev replay.

At minimum include:

```json
{
  "workspace": {
    "workspace_mode": "scoped_copy",
    "workspace_path": "...",
    "target_repo_root": "...",
    "copied_files": [...],
    "omitted_files": [...],
    "base_sha": "..."
  }
}
```

Places to consider:

```text
ExecutionResult.evidence
PacketRun.result_json via evidence update
Dev replay metadata
agent log / admin evidence display if already automatic
```

Acceptance:

- After a minimal run, `result.evidence["workspace"]` or equivalent persisted result JSON contains `workspace_mode=scoped_copy`.
- Admin/evidence can show or at least inspect it.

### 4.4 Mark scoped_copy commit semantics clearly

Minimal repo commit SHA is not a target repo commit.

Required:

- In evidence/dev replay, label it clearly:

```text
workspace_base_sha = minimal repo init commit
agent_commit_sha = minimal repo commit, not target repo commit
target_commit_sha = empty / not_applicable
```

- Do not present minimal repo commit as mergeable into the target repository.
- If existing `commit_sha` field must still be filled, add a companion field:

```json
"commit_scope": "workspace_only"
```

or:

```json
"commit_semantics": "minimal_workspace_patch_only"
```

Acceptance:

- Reviewer can tell from result/evidence that this was scoped-copy workspace-only output.

### 4.5 Keep fixture profile only

Do not enable `minimal_repo` on normal `coder-opencode`.

Required state:

```text
coder-opencode: minimal_repo absent/false
coder-opencode-fixture: minimal_repo true, skip_context_builder true
```

Add a test or snapshot assertion if a profile test file exists.

### 4.6 Add targeted tests

Add tests for:

1. absolute outside-target path is omitted;
2. `..` traversal is rejected/omitted;
3. no files copied -> clear failure;
4. workspace report appears in execution result/evidence for minimal mode;
5. default `coder-opencode` does not have `minimal_repo: true`;
6. `coder-opencode-fixture` does have `minimal_repo: true`.

Keep existing tests.

## 5. Files likely involved

```text
src/grace_control/services/agent_workspace_builder.py
src/grace_control/adapters/packet_executor.py
src/grace_control/config/agent_profiles.yaml
tests/grace_control/services/test_agent_workspace_builder.py
tests/grace_control/adapters/test_packet_executor*.py
tests/grace_control/config/test_agent_profiles*.py
```

Use actual existing test file names.

## 6. Acceptance criteria for this patch

Accepted when:

1. `AgentWorkspaceBuilder` cannot copy files outside `target_root`.
2. `AgentWorkspaceBuilder` cannot write outside `workspace_path`.
3. Empty scoped workspace fails clearly.
4. Minimal workspace report is persisted in run evidence/dev replay.
5. Minimal workspace commit semantics are marked as workspace-only / patch-only.
6. `minimal_repo` remains off for normal `coder-opencode`.
7. `coder-opencode-fixture` remains the only minimal profile.
8. Tests cover the new safety cases.
9. Existing test suite passes.

## 7. What remains from the original big TZ

This patch does **not** finish the whole `TZ_MINIMAL_WORKTREE_AND_CONTEXT_BUILDER.md`.

Still remaining after this safety polish:

### 7.1 Runtime handling for `skip_context_builder`

Current state: profile flag exists.

Still needed:

```text
Wherever context collector is invoked, honor executor.skip_context_builder=true.
Add test proving context collector is not called for coder-opencode-fixture.
```

### 7.2 Bounded context builder

Still needed:

```text
src/grace_control/services/agent_context_builder.py
max_total_context_bytes
max_file_snippet_bytes
max_files_indexed
AI_HEADER / CONTRACT / MAP / BLOCK-first scanning
selected snippets
omitted reasons
budget_report
```

### 7.3 GRACE Canon digest instead of huge prompt duplication

Still needed:

```text
docs/grace/grace-canon-digest.md
runtime prompt uses digest, not full repeated Canon template
coder profile no huge duplicated canon block
EXECUTION_PACKET includes digest reference / short rules
```

### 7.4 Project profile support

Still needed for Solar Sage:

```text
project_profile_path
project-specific rules
verification commands
allowed project configs
frontend/Next/Vitest/Playwright config allowlist
```

### 7.5 `target_repo_worktree` mode

Still needed for real projects before scoped-copy apply-back is ready:

```text
git worktree from target repo root, not GRACE repo
agent sees full Solar Sage, but not GRACE
safer than scoped_copy for first real project pilot
```

### 7.6 Scoped-copy apply-back / patch semantics

Still needed before using scoped_copy on real repos:

```text
map workspace changes back to target-relative files
apply patch to target repo worktree
commit in target repo
or explicitly keep scoped_copy as patch-only/no-merge mode
```

### 7.7 Evidence/admin visibility

Still needed:

```text
show workspace_mode, copied_files count, omitted_files in admin/evidence
show context budget report when context builder exists
```

## 8. Suggested next order

Do in this order:

```text
1. This safety polish TZ
2. Run live fixture with coder-opencode-fixture
3. Add runtime skip_context_builder handling
4. Add target_repo_worktree mode for Solar Sage pilot
5. Only then build bounded context builder / canon digest cleanup
6. Later: scoped_copy apply-back for real repos
```

## 9. Suggested verification

Unit:

```bash
pytest tests/grace_control/services/test_agent_workspace_builder.py -q
pytest tests/grace_control/adapters -q
pytest tests/grace_control/config -q
```

Full:

```bash
pytest -q
```

Manual fixture smoke after safety polish:

```bash
GRACE_TARGET_REPO_ROOT=/tmp/grace-live-test/backend_fastapi_todo \
GRACE_WORKSPACE_MODE=scoped_copy \
# use coder-opencode-fixture profile in scenario/config
python3 -u tests_live/runner/wave_resume_runner.py ...
```

Expected evidence:

```text
workspace_mode=scoped_copy
workspace path under configured worktree_root
copied_files does not include GRACE repo files
omitted_files records unsafe/missing paths
```
