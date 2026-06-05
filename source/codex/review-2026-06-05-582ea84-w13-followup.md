# Review: `582ea84` W13 follow-up

Date: 2026-06-05
Reviewed commit: `582ea84856865f4283364f0d10974dedf80c3f3c`
Spec: `source/codex/tz-w13-llm-runner-and-test-cleanup.md`

## Verdict

Not fully accepted yet.

The patch closes several important W13 items:

- `.grace/lint_allowlist.yaml` no longer contains `llm_runner.py` entries.
- There are no visible `expires_wave: W12` entries in the allowlist.
- The old `llm_runner.py` direct `asyncio.subprocess` / `os.environ` implementation is gone.
- The pre-existing recovery test was updated to expect `DRAFT` for the blocked-feature wave gate case.
- Reported suite is green: `402 passed, 0 failed`.

However, the new `llm_runner.py` implementation is not yet a valid W13 resolution. It removes hardcoded tool names, but it still constructs an inline command and has a likely runtime bug around `{packet_path}` rendering. This violates the W13 intent: commands must come from `agent_profiles.yaml` / profile config and `run_llm()` should be a thin adapter over the same UniversalCliAgentBackend profile path.

---

## Accepted items

### A1. Allowlist cleanup

Accepted.

Current `.grace/lint_allowlist.yaml` no longer contains `llm_runner.py` exceptions for `GRC101` or `GRC109`. It also has no visible `expires_wave: W12` entries.

### A2. Old direct subprocess/env implementation removed from `llm_runner.py`

Accepted.

The previous implementation imported/used:

```text
asyncio.create_subprocess_exec
os.environ
yaml profile reading
hardcoded opencode/agy command branches
```

Those are gone.

### A3. Pre-existing test fixed

Accepted, assuming the reported suite result is accurate.

The recovery test now documents that when the feature is blocked, W02 does not progress and packet P2 remains `DRAFT`. This matches the post-refactor wave gate semantics.

---

# Remaining blockers

## P0-1. `llm_runner.py` still constructs command inline instead of using agent profiles

Current code builds an executor dict inside `run_llm()`:

```python
executor = {
    "executor_id": f"llm_{role}",
    "command": [cli, "run", "--model", model, "Read the task from {packet_path}. Respond ONLY with valid JSON."],
    "model": model,
    "effort": "high",
    "cwd": "{worktree_path}",
    "timeout_seconds": 600,
    "input_mode": "file",
}
```

This no longer hardcodes `opencode` or `agy`, but it still hardcodes the CLI invocation shape:

```text
<cli> run --model <model> <instruction>
```

That is not universal. `agy`, `codex`, `claude`, and other CLIs may not use this shape. Revised W7/W13 required command shape to come from profiles/config, not from runtime code.

Required fix:

1. Treat `cli` as `executor_id`, not executable name.
2. Resolve an agent profile through `get_agent_profile(cli)` or a role-to-executor mapping.
3. Pass the resolved profile dict into `ExecutionRequest.executor`.
4. Do not build `command` inside `llm_runner.py`.

Example direction:

```python
executor_id = cli or f"llm_{role}"
profile = get_agent_profile(executor_id)
executor = profile.to_dict()
```

If the profile does not exist, fail clearly with a config error.

---

## P0-2. `{packet_path}` is rendered before it is added to context

`AgentRunService.run()` renders command first:

```python
command = self._renderer.render(executor.get("command", []), ctx)
```

Only later, for file mode, it sets:

```python
elif input_mode == "file":
    ctx["packet_path"] = str(cwd / "EXECUTION_PACKET.md")
```

Therefore a command containing `{packet_path}` is rendered while `ctx["packet_path"]` is still missing. `CommandTemplateRenderer` replaces missing keys with `""`, so the command will become something like:

```text
Read the task from . Respond ONLY with valid JSON.
```

or otherwise lose the task path.

This directly affects the new `llm_runner.py`, which injects `{packet_path}` into its inline command.

Required fix:

1. In `AgentRunService`, compute input mode and `packet_path` before rendering command.
2. If `input_mode == "file"`, write `packet_markdown` to the file path, not just set a context key.
3. Add regression test proving `{packet_path}` is substituted and the file exists with packet content before process launch.

Suggested order in `AgentRunService.run()`:

```python
input_mode = executor.get("input_mode", "none")
if input_mode == "file":
    packet_path = effective_run_dir_or_worktree / "EXECUTION_PACKET.md"
    packet_path.write_text(packet_markdown)
    ctx["packet_path"] = str(packet_path)
command = renderer.render(..., ctx)
```

The exact directory can be canonical run dir or worktree root, but it must be documented and tested.

---

## P0-3. `llm_runner.py` writes `prompt_file` but never uses it

Current code writes:

```python
prompt_file = prompt_dir / f"{role}_{uuid.uuid4().hex[:8]}.txt"
prompt_file.write_text(prompt)
```

But the constructed executor command uses `{packet_path}` and `spec={"packet_markdown": prompt}`. The `prompt_file` path is never passed into the backend request or command context.

Impact:

- stale prompt files accumulate under `.grace/llm_prompts`;
- the actual CLI command does not read that file;
- the code suggests file-based execution but does not wire it.

Required fix:

Choose one:

1. Remove `prompt_file` writing entirely and rely on AgentRunService file mode to materialize the packet.
2. Or pass this exact prompt path into `ExecutionRequest.spec` / command context and use it consistently.

Preferred: remove this duplicate prompt file and let `AgentRunService` own materialization.

---

## P1-1. `CommandTemplateRenderer` is imported/instantiated in `llm_runner.py` but unused

Current code:

```python
from grace_control.services.command_template_renderer import CommandTemplateRenderer
...
_renderer = CommandTemplateRenderer()
```

`_renderer` is never used.

This is minor, but it reinforces that the adapter is not cleanly designed yet.

Required fix: remove the unused import/global.

---

## P1-2. No visible regression test for `llm_runner.py` through fake profile/backend

The reported tests are green, but from the reviewed diff, the added tests cover GRC109 and the recovery expectation. I did not see a W13 regression test proving:

```text
run_llm() resolves a profile
run_llm() sends prompt content through file/stdin mode
run_llm() returns stdout
run_llm() fails on non-zero exit
```

Required test:

- create a temporary fake CLI command/script or monkeypatch `UniversalCliAgentBackend` / `AgentRunService`;
- call `run_llm(prompt, role="architect", model="test", cli="fake_llm")`;
- assert it uses resolved profile/config, not inline hardcoded command;
- assert prompt content reaches the backend.

---

## Status against W13 DoD

| W13 item | Status |
|---|---:|
| Remove direct subprocess/env/hardcoded opencode/agy from llm_runner | ✅ |
| Remove llm_runner allowlist entries | ✅ |
| Fix/quarantine pre-existing test | ✅ reported / likely |
| Refactor llm_runner through profile-backed UniversalCliAgentBackend | ❌ not yet |
| Command shape comes from config/profile | ❌ not yet |
| File input mode actually provides packet path/content before command render | ❌ not yet |
| Regression test for run_llm adapter path | ❌ not visible |

---

## Required next patch

Title:

```text
fix(W13): make llm_runner use agent profiles and fix file input rendering
```

Scope:

```text
src/grace_control/core/llm_runner.py
src/grace_control/services/agent_run_service.py
src/grace_control/config/agent_profiles.py
src/grace_control/config/agent_profiles.yaml
tests/grace_control/core/test_llm_runner.py
tests/grace_control/agent/test_agent_run_service.py
```

Acceptance:

1. `llm_runner.py` does not build a `command` list inline.
2. `llm_runner.py` resolves an executor/profile by id or role mapping.
3. `AgentRunService` sets and writes `packet_path` before rendering command.
4. File input mode has a regression test proving command receives a real path and file contains packet content.
5. `run_llm()` has a regression test proving prompt reaches the backend and stdout is returned.
6. No allowlist entries for `llm_runner.py` are reintroduced.
7. Full suite remains green.

After that patch, W13 can be accepted cleanly.
