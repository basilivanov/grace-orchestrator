# TZ: Minimal worktree and context builder for real agent runs

Date: 2026-06-10
Status: ready for architect/coder
Priority: P0 real-run stability / OOM prevention
Scope: execution workspace + prompt/context minimization

## 1. Problem

`gemini-3-flash-agent` works in a minimal repository with a small test suite, but GRACE live workflow OOMs when it runs inside a full GRACE worktree.

Current likely chain:

```text
packet execution
→ PacketExecutionAdapter creates a full git worktree from the GRACE project root
→ opencode run receives --dir <full worktree>
→ opencode scans/sees thousands of files
→ process memory grows
→ host gets unstable / OOM risk
```

This is not primarily a model problem. It is a workspace/context problem.

The current code explicitly creates a full checkout:

```python
# Create the worktree on a fresh branch from base_ref so the agent has
# a full checkout (scripts/, src/, tests/) to work in.
add_result = git.worktree_add(self.project_root, wt_path, branch, base_ref=base_ref)
```

`AgentRunService` then injects:

```text
opencode run --dir <worktree_path>
```

so the agent sees the full checkout.

In addition, prompt/context is heavier than needed:

- GRACE Canon is embedded in `PacketMaterializer`.
- GRACE Canon is also embedded in `coder-deepseek-flash` profile.
- `context-collector-flash` runs inside the same `{worktree_path}` and can inspect too much.
- Current prompts are GRACE-specific and should become project-independent with project profile injection.

## 2. Goal

Make real agent runs operate on a **minimal task repository/workspace**, not on the full GRACE orchestrator repository.

Make prompts and context builder project-independent and intentionally small.

The minimum viable target:

```text
agent gets only:
- task packet
- allowed write scope files
- relevant config/test files
- short GRACE Canon digest
- project-specific instructions if configured
- grep/header-derived map of nearby files, not full file contents
```

## 3. Non-goals

Do not rewrite the whole orchestrator.
Do not change packet lifecycle semantics.
Do not change reviewer/verifier semantics except context limits.
Do not add Docker/systemd/cgroup hardening in this task.
Do not optimize UI/admin in this task.
Do not switch away from opencode/gemini yet.
Do not make Solar Sage-specific hardcoding in core runtime.

## 4. Required architecture changes

### 4.1 Separate control-plane repo from target project repo

GRACE must support this as a first-class mode:

```text
GRACE_PROJECT_ROOT      = control-plane / orchestrator root
GRACE_TARGET_REPO_ROOT  = project being modified, e.g. Solar Sage Astro or fixture app
GRACE_WORKTREE_ROOT     = small worktree root for attempts
```

Existing config already has:

```text
execution.target_repo_root
execution.worktree_root
```

Use these correctly:

- `project_root` for agent execution must be the target project repo, not the GRACE orchestrator repo, unless self-evolution mode is explicitly enabled.
- For live fixture scenarios, target project repo should be the fixture/minimal repo under `/tmp/grace-live-test/...`, not `/tmp/grace-orchestrator-export`.
- GRACE source code may be used to run the orchestrator, but it must not be the default agent workspace for non-GRACE tasks.

### 4.2 Add explicit execution workspace mode

Add config:

```yaml
execution:
  workspace_mode: scoped_copy   # full_git_worktree | scoped_copy | target_repo_worktree
  target_repo_root: /path/to/project
  worktree_root: /tmp/grace-agent-worktrees
```

Modes:

#### `full_git_worktree`

Current behavior. Keep for self-evolution / GRACE modifying itself only.

#### `target_repo_worktree`

Create a git worktree from the target repo root, not the orchestrator repo.

Use for real projects like Solar Sage Astro if the full target repo is acceptable.

#### `scoped_copy` — preferred P0 mode

Create a tiny workspace containing only:

- files from `allowed_write_scope`;
- files explicitly referenced by verification commands;
- minimal project config files needed to run tests;
- optional test files directly in scope;
- `.grace/AGENT_CONTEXT.md` or `EXECUTION_PACKET.md`;
- no `.git` unless required.

For fixtures, this should copy only the fixture app, not the full GRACE repository.

P0 can implement only `target_repo_worktree` + a simple `scoped_copy` for fixture/live-run. `full_git_worktree` remains as fallback.

### 4.3 Do not hand full repo context to opencode by default

`opencode run --dir` should point at the minimal task workspace.

Acceptance commands should run in that same minimal workspace unless they explicitly need the full target repo.

The agent must not be able to discover/read the entire orchestrator repo during ordinary project tasks.

## 5. Context builder changes

### 5.1 Add a bounded context builder

Create or update a context builder service with a hard budget.

Suggested service:

```text
src/grace_control/services/agent_context_builder.py
```

Inputs:

```text
packet spec
allowed_write_scope
frozen_scope
target_repo_root
workspace_path
project profile
budget limits
```

Output:

```text
AgentContextBundle
- canon_digest
- project_digest
- file_index
- selected_snippets
- omitted_reason
- budget_report
```

### 5.2 Use header/contract/index-first scanning

The context builder should not read full files by default.

It should first collect only:

```text
AI_HEADER
ROLE
START_MODULE_CONTRACT / END_MODULE_CONTRACT
START_MODULE_MAP / END_MODULE_MAP
START_BLOCK_* / END_BLOCK_*
START_FUNCTION_CONTRACT / END_FUNCTION_CONTRACT
```

Implementation guidance:

- Use grep/ripgrep-style line scanning.
- Read only matched blocks plus small line windows around them.
- Do not include full file contents unless the file is inside `allowed_write_scope` and is small enough.
- Enforce max bytes per file and max total bytes.

Suggested defaults:

```text
max_total_context_bytes = 80_000
max_file_snippet_bytes = 8_000
max_files_indexed = 80
max_full_files = 5
```

### 5.3 Project-independent prompts

Prompts must not assume the project is GRACE.

Instead, prompt should receive:

```text
- role instructions
- task packet
- short GRACE process/canon digest
- project profile digest
- selected context bundle
```

For Solar Sage Astro, project profile should provide project-specific rules separately.

Example:

```yaml
project:
  name: Solar Sage Astro
  key: solarsage-astro
execution:
  target_repo_root: /opt/solarsage-astro
context:
  project_profile_path: docs/grace/project-profile.md
  canon_digest_path: docs/grace/grace-canon-digest.md
```

### 5.4 Canon digest instead of full repeated template

Do not paste the full GRACE Canon template into every profile and every packet.

Create one short canonical digest, for example:

```text
docs/grace/grace-canon-digest.md
```

It should state only the essentials:

```text
- Every new/changed source file needs AI_HEADER + ROLE.
- Module contract required near top.
- Module map required near top.
- Public functions/methods need START_FUNCTION_CONTRACT / END_FUNCTION_CONTRACT.
- Group large sections with START_BLOCK / END_BLOCK.
- Use structured logging where side effects, state transitions, subprocesses, network, DB, or lifecycle decisions happen.
- Do not add logging noise for trivial pure helpers.
```

Full template can remain in docs, but the runtime prompt should use digest only.

### 5.5 Context collector should return references, not full context

`context-collector-flash` should not explore the whole repo.

Change its prompt to:

```text
You are a bounded context collector.
Do not read full files unless explicitly in scope.
Use file headers/contracts/maps first.
Return JSON only:
{
  "relevant_files": [
    {"path": "...", "reason": "...", "needed_blocks": ["AI_HEADER", "function:foo"]}
  ],
  "summary": "...",
  "budget": {"files_scanned": 0, "bytes_read": 0}
}
```

It should run against the minimal target workspace, not the full GRACE repo.

## 6. Prompt/profile changes

### 6.1 Coder prompt

Reduce `coder-deepseek-flash` and `coder-opencode` prompts.

Current `coder-deepseek-flash` embeds the full GRACE Canon template. Replace with:

```text
Read the task packet and implement only the requested change inside the current workspace.
Use the provided context bundle and allowed write scope.
Do not scan the whole repository.
Do not read unrelated files.
Follow the GRACE Canon digest in the packet/context.
Run only the verification commands listed in the packet.
Return a short summary and evidence.
```

### 6.2 Architect prompt

Architect should produce project-independent packets:

```text
- clear objective
- allowed_write_scope
- frozen_scope
- verification commands
- expected evidence
- context hints / relevant files
- project profile references
```

Architect should not assume files live in GRACE unless `project.key == grace-orchestrator` or `origin == self_evolution`.

### 6.3 Verifier/reviewer prompts

Verifier/reviewer should use evidence paths and diffs, not full repo scanning.

They should read:

```text
- task packet
- acceptance report
- changed files list
- relevant snippets if needed
- screenshots/logs if provided
```

They should not inspect the whole workspace unless explicit fallback is enabled.

## 7. Workspace builder changes

Add service:

```text
src/grace_control/services/agent_workspace_builder.py
```

Responsibilities:

1. Determine target root:

```text
if self_evolution or project.key == grace-orchestrator:
    target_repo_root = GRACE_PROJECT_ROOT
else:
    target_repo_root = settings.target_repo_root or project.execution.target_repo_root
```

2. Build workspace based on mode:

```text
full_git_worktree      -> current git worktree behavior
target_repo_worktree   -> git worktree from target repo
scoped_copy            -> copy only scoped files and minimal configs
```

3. Return:

```text
workspace_path
workspace_mode
target_repo_root
copied_files
omitted_files
budget_report
```

4. Store the report in run evidence.

### 7.1 Minimal copy allowlist

For JS/TS frontend projects, minimal copy may include:

```text
package.json
pnpm-lock.yaml
package-lock.json
yarn.lock
tsconfig.json
next.config.*
vite.config.*
playwright.config.*
vitest.config.*
postcss.config.*
tailwind.config.*
app/** or src/** files in allowed scope
tests/** files in allowed scope
```

For Python fixtures, minimal copy may include:

```text
pyproject.toml
requirements*.txt
pytest.ini
src/** files in allowed scope
tests/** files in allowed scope
```

Keep this simple for P0.

## 8. Tests required

### 8.1 Unit tests: workspace target root

Verify non-self-evolution packets use `settings.target_repo_root`, not orchestrator cwd.

### 8.2 Unit tests: scoped workspace excludes orchestrator files

Create a fake repo:

```text
orchestrator_root/huge_file.py
target_repo/app/main.py
target_repo/tests/test_main.py
```

Run workspace builder in `scoped_copy` mode.

Assert:

```text
workspace contains app/main.py\workspace contains tests/test_main.py
workspace does NOT contain orchestrator huge_file.py
workspace file count is small
```

### 8.3 Unit tests: context builder budget

Create many files with large contents and AI_HEADER blocks.

Assert:

```text
context total bytes <= configured budget
full file bodies are not included by default
headers/contracts/maps are included
omitted_reason is populated
```

### 8.4 AgentRunService test

Assert `opencode run --dir` receives the minimal workspace path, not the orchestrator root.

### 8.5 Live fixture regression

Run `backend-1w` fixture and assert evidence contains:

```text
workspace_mode = scoped_copy or target_repo_worktree
workspace_path under /tmp/grace-live-test or configured worktree root
copied_files count below threshold
```

Suggested threshold for fixture:

```text
copied_files <= 80
```

### 8.6 Prompt snapshot tests

Add snapshot-style tests or string assertions:

- coder prompt does not contain full GRACE Canon template block;
- coder prompt contains `GRACE Canon digest` reference;
- prompts mention `allowed_write_scope`;
- prompts warn `do not scan unrelated files`.

## 9. Acceptance criteria

Patch accepted when:

1. Live fixture agent run no longer gets full GRACE repo as `--dir`.
2. Agent workspace is target project/fixture scoped.
3. Context builder has hard file/byte budgets.
4. Context builder uses header/contract/map blocks before full-file reads.
5. Runtime prompts are project-independent.
6. GRACE Canon is provided as a digest, not duplicated as a full template in multiple prompt surfaces.
7. Evidence records workspace mode, workspace path, copied/indexed files, and context budget report.
8. `gemini-3-flash-agent` can run in the minimal fixture workspace without OOM.
9. Existing unit suite passes.

## 10. Suggested verification commands

Unit/API:

```bash
pytest tests/grace_control/services/test_agent_workspace_builder.py -q
pytest tests/grace_control/services/test_agent_context_builder.py -q
pytest tests/grace_control/agent -q
pytest tests/grace_control/adapters -q
```

Live fixture:

```bash
cd /tmp/grace-orchestrator-export
rm -f /tmp/grace-live-test.db
fuser -k 8042/tcp 2>/dev/null || true
sleep 1

setsid env \
  GRACE_DATABASE_URL="sqlite:////tmp/grace-live-test.db" \
  GRACE_DEV_TOOLS_ENABLED=1 \
  GRACE_FAST_FAIL=1 \
  GRACE_WORKSPACE_MODE=scoped_copy \
  python3 scripts/api_watchdog.py > /tmp/grace-watchdog.log 2>&1 &

PYTHONPATH=. GRACE_LIVE_AGENT_TESTS=1 GRACE_DEV_TOOLS_ENABLED=1 GRACE_FAST_FAIL=1 \
  GRACE_WORKSPACE_MODE=scoped_copy \
  python3 -u tests_live/runner/wave_resume_runner.py \
    --scenario backend-1w \
    --api-url http://127.0.0.1:8042 \
    --source-dir . \
    --target-dir /tmp/grace-live-test \
    --timeout 900 \
    --keep-artifacts
```

Diagnostics:

```bash
ps -eo pid,ppid,pgid,sid,user,rss,etime,cmd --sort=-rss | head -60
tail -200 /tmp/grace-watchdog.log
```

## 11. Implementation notes

Start small.

Do not attempt a perfect semantic context engine in the first patch. The P0 target is:

```text
stop giving opencode/gemini the whole GRACE repo
stop duplicating huge canon prompts
make context budgeted and evidence-visible
```

If a later real project needs more context, add explicit context hints to the packet or project profile instead of allowing unbounded repo scanning.
