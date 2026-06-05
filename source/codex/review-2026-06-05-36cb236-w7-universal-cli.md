# Review: `36cb236` W7 UniversalCliAgentBackend

Date: 2026-06-05
Reviewed commit: `36cb2361f917ee9e0d092d5c920a6d38fe40a15a`
Spec: revised W7 in `source/codex/tz-api-first-cleanup-waves-w0-w11.md`

## Verdict

Not accepted yet.

The commit adds the right pieces for the revised W7 direction:

- `UniversalCliAgentBackend`
- `AgentRunService`
- `CommandTemplateRenderer`
- `AgentEnvBuilder`
- `ProcessSupervisor`
- `AgentArtifactCollector`
- declarative `agents:` profiles in `agent_profiles.yaml`
- `execution_backend = "cli"`

However, the current implementation has several runtime blockers. In the current state, `/api/agents/run` is likely to use the wrong profile section and fail or silently run in the wrong directory. The core idea is correct, but the wiring is not yet reliable.

---

## P0 blockers

### P0-1. `/api/agents/run` looks up the old `codex.executors`, not the new `agents:` profiles

The revised W7 spec says UniversalCliAgentBackend should be driven by declarative profiles under `agents:`.

But `src/grace_control/api/routers/agents.py` currently does:

```python
profiles = load_profiles()
executors = profiles.get("codex", {}).get("executors", [])
matching = [e for e in executors if e.get("executor_id") == req.executor_id]
```

The new config has the actual CLI profiles here:

```yaml
agents:
  coder_opencode:
    backend: cli
    command:
      - opencode
      - run
      - "--model"
      - "{model}"
      - "--effort"
      - "{effort}"
```

Impact:

- default request uses `executor_id="coder_opencode"`;
- `coder_opencode` exists under `agents:`, not under `codex.executors`;
- endpoint returns 400 `unknown executor_id: coder_opencode`;
- if using an old `codex.executors` id, the shape is wrong for UniversalCliAgentBackend.

Required fix:

1. Add an agent profile loader dedicated to W7, e.g.:

```text
src/grace_control/config/agent_profiles.py
```

with:

```python
load_agent_profiles() -> dict[str, AgentProfile]
get_agent_profile(executor_id: str) -> AgentProfile
```

2. `/api/agents/run` must resolve from `profiles["agents"]`, not `profiles["codex"]["executors"]`.

3. `PacketExecutionAdapter._resolve_executor()` should also return the W7 profile shape for CLI execution, or there must be an explicit compatibility normalization layer.

Required tests:

- `GET/POST /api/agents/run` with default `executor_id="coder_opencode"` finds the `agents.coder_opencode` profile.
- unknown executor id returns 400.
- old `codex.executors` shape is not accidentally passed directly into `UniversalCliAgentBackend` unless normalized.

---

### P0-2. Old executor profile has `command: opencode` string; renderer expects `list[str]`

`CommandTemplateRenderer.render()` expects:

```python
render(command: list[str], ctx: dict) -> list[str]
```

But old `codex.executors` entries have:

```yaml
command: opencode
```

If `/api/agents/run` resolves one of those old entries and passes it to `AgentRunService`, then:

```python
command = self._renderer.render(executor.get("command", []), ctx)
```

will iterate characters of the string `opencode`, producing a broken command like:

```python
["o", "p", "e", "n", "c", "o", "d", "e"]
```

or it will fail at subprocess startup.

Required fix:

- enforce `command` is `list[str]` at config validation time;
- reject string command with a clear validation error;
- use only the new `agents:` profile shape for W7.

Required tests:

- string command fails validation with clear error;
- list command renders correctly;
- no character-splitting behavior is possible.

---

### P0-3. `/api/agents/run` ignores `req.worktree_path`

`RunRequest` has:

```python
worktree_path: str = ""
```

But the router builds:

```python
ExecutionRequest(
    ...
    worktree_path=None,
    branch_name="",
    ...
)
```

Then `UniversalCliAgentBackend` falls back to:

```python
worktree_path=Path(request.worktree_path) if request.worktree_path else Path(".")
```

Impact:

- direct `/api/agents/run` executes in `.` instead of the requested worktree;
- this can mutate the control-plane repo instead of the target worktree;
- `cwd: "{worktree_path}"` in the profile becomes meaningless for this endpoint.

Required fix:

- pass `worktree_path=Path(req.worktree_path) if req.worktree_path else Path(".")` into `ExecutionRequest`;
- preferably require `worktree_path` for real CLI execution unless using a test/mock profile;
- return 400 if path is missing or does not exist in non-test mode.

Required tests:

- `/api/agents/run` with `worktree_path=/tmp/x` passes that path into backend/supervisor;
- missing worktree path returns clear 400 or uses an explicitly documented test default;
- command runs with cwd equal to worktree_path.

---

### P0-4. `AgentRunService` marks non-zero exit as accepted

Current code:

```python
"accepted": not result.timed_out,
"domain_status": "timeout" if result.timed_out else ("completed" if result.exit_code == 0 else "failed"),
```

If the process exits with code `1`, `accepted=True` and `domain_status="failed"`.

This is contradictory and dangerous. `PacketExecutionAdapter` uses `result.accepted` as a success-like signal before acceptance checks. A failed CLI process should not be accepted.

Required fix:

```python
accepted = (not result.timed_out and result.exit_code == 0)
```

Required tests:

- exit code 0 => accepted true, completed.
- exit code 1 => accepted false, failed.
- timeout => accepted false, timeout.

---

## P1 high priority

### P1-1. `stdin` / `file` / `none` input modes are not implemented

Spec requires input modes:

```text
stdin — send packet markdown to process stdin
file — pass path to materialized packet file
none — command reads repo/context itself
```

Current `ProcessSupervisor.run()` calls `proc.communicate()` without input. `AgentRunService` receives `packet_markdown` but never sends it to subprocess stdin and does not render `{packet_markdown}` or `{packet_path}` into command context.

Required fix:

1. Extend `ProcessSupervisor.run(..., stdin_text: str | None = None)` and call:

```python
proc.communicate(stdin_text.encode() if stdin_text else None)
```

with `stdin=asyncio.subprocess.PIPE` when needed.

2. Add input mode handling in `AgentRunService`:

```python
input_cfg = executor.get("input", {})
mode = input_cfg.get("mode", "none")
```

3. For `stdin`, render template and pass to supervisor stdin.
4. For `file`, include materialized packet path in command context.
5. For `none`, pass no stdin.

Required tests:

- stdin mode sends packet markdown to a fake command that echoes stdin.
- file mode renders `{packet_path}` or equivalent.
- none mode sends no stdin.

---

### P1-2. Env builder discards parent process environment

Current `AgentEnvBuilder.build()` returns only the configured env keys:

```python
result = {}
for k, v in merged.items():
    result[k] = self._expand(v)
return result
```

Passing that to subprocess means the CLI may lose `PATH`, `HOME`, locale, and other required environment variables. On many systems this can make `opencode`, `codex`, `agy`, etc. fail even if installed.

Required fix:

- Start from `os.environ.copy()` and overlay profile env / overrides:

```python
env = os.environ.copy()
env.update(expanded_profile_env)
```

- Keep preview redaction.
- Allow explicit `inherit_env: false` only if needed later.

Required tests:

- PATH is present by default.
- profile env overrides parent env.
- secrets are redacted in preview.

---

### P1-3. `cwd` profile field is ignored

Profiles define:

```yaml
cwd: "{worktree_path}"
```

But `AgentRunService` always runs:

```python
self._supervisor.run(command, cwd=worktree_path, ...)
```

For MVP this is equivalent, but if profile declares a different cwd template, it is ignored.

Required fix:

- render `executor.get("cwd", "{worktree_path}")` through the same template renderer;
- validate that cwd exists;
- pass rendered cwd to supervisor.

Required tests:

- cwd template is rendered.
- missing cwd returns structured failure.

---

### P1-4. `command_preview` is not redacted and `preview_env` is unused

`AgentRunService` computes:

```python
preview_env = self._env_builder.preview(env)
preview_cmd = " ".join(command)
```

but neither is used. `AgentArtifactCollector` writes command preview to disk. If a command template ever includes secrets, they can leak into artifacts/logs.

Required fix:

- remove unused variables or use them properly;
- implement command redaction for secret-like tokens if secrets may appear in command;
- store redacted env preview in command metadata, not raw env.

Required tests:

- env preview redacts `API_KEY`, `TOKEN`, `SECRET`.
- command log does not contain secret values from env expansion.

---

### P1-5. Artifact paths are not in packet run evidence directory

`AgentRunService` writes artifacts to:

```python
run_dir = state_root / "agents" / packet_id
```

The rest of the packet evidence path usually uses packet/run-specific directories such as:

```text
state_root / packets / packet_id / runs / Rxx
```

Impact:

- artifacts may not show up under existing `/api/packets/{id}/runs/{run_id}/artifacts` flows;
- trace/evidence may be split across incompatible directories.

Required fix:

- pass run_id or evidence_dir into `ExecutionRequest.spec` or service call;
- write agent stdout/stderr into the same run evidence directory used by `EvidenceService`.

MVP alternative:

- explicitly document `/state/agents/{packet_id}` and expose it through artifacts API.

Preferred: unify evidence paths.

---

## P2 / cleanup

### P2-1. `/api/agents/run` uses `asyncio.run()` inside sync FastAPI route

This can fail if the route is ever executed inside an existing event loop. Better to make the route `async def` and `await backend.run(er)`.

Required fix:

```python
@router.post("/run")
async def run_agent(...):
    result = await backend.run(er)
```

### P2-2. `UniversalCliAgentBackend` does not explicitly inherit `ExecutionBackend`

It imports `ExecutionBackend` but class is declared as:

```python
class UniversalCliAgentBackend:
```

If `ExecutionBackend` is a Protocol this may be OK structurally, but for clarity and type checks use:

```python
class UniversalCliAgentBackend(ExecutionBackend):
```

### P2-3. `changed_files` always empty

`UniversalCliAgentBackend` returns `changed_files=[]` regardless of actual worktree changes. Later acceptance pipeline can compute changed files, but backend result should ideally include what it can discover or leave it explicitly documented as intentionally empty.

---

## Positive findings

### The direction is correct

The architecture now matches the user's intended model:

```text
GRACE API/OpenAPI = control plane
UniversalCliAgentBackend = local CLI agent execution adapter
opencode/codex/agy/etc. = config, not hardcoded in orchestration code
```

### Backend selection supports `cli`

`select_backend("cli")` returns `UniversalCliAgentBackend`, `legacy` is still rejected, and `execution_backend` defaults to `cli`.

### Process group timeout exists

`ProcessSupervisor` uses `preexec_fn=os.setsid` and kills process group with `os.killpg(...)` on timeout.

### Config contains declarative CLI examples

`agent_profiles.yaml` now has `agents.coder_opencode` and `agents.coder_agy` with command lists, model, effort, env, and input config.

---

## Required next patch

Title:

```text
fix(W7): make UniversalCliAgentBackend profiles executable end-to-end
```

Scope:

```text
src/grace_control/api/routers/agents.py
src/grace_control/config/agent_profiles.py
src/grace_control/services/agent_run_service.py
src/grace_control/services/agent_env_builder.py
src/grace_control/services/process_supervisor.py
src/grace_control/services/agent_artifact_collector.py
src/grace_control/services/command_template_renderer.py
src/grace_control/agent/universal_cli_backend.py
tests/grace_control/agent/
tests/grace_control/api/test_agents_api.py
```

Acceptance criteria:

1. `/api/agents/run` resolves `executor_id` from top-level `agents:` profiles, not old `codex.executors`.
2. Config validation rejects string `command`; requires `list[str]`.
3. `req.worktree_path` is passed through and used as process cwd by default.
4. exit code `!= 0` returns `accepted=false`.
5. `stdin` input mode sends packet markdown to subprocess.
6. `file` input mode has a tested behavior or returns clear “not implemented” error; no silent ignore.
7. env inherits `PATH`/parent env by default and overlays profile env.
8. command/env previews are redacted where secrets are involved.
9. stdout/stderr artifacts are written into a packet-run evidence directory or exposed consistently through artifacts API.
10. `/api/agents/run` is async and does not use `asyncio.run()`.
11. Tests include a fake local command that proves end-to-end CLI execution through the API without Prefect.

Do not mark W7 complete until this end-to-end fake local command path passes.
