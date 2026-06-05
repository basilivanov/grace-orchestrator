# Review: `7db766c` W7 UniversalCliAgentBackend follow-up

Date: 2026-06-05
Reviewed commit: `7db766cd8b8275726c017be86c9101c1c935b494`
Previous review: `source/codex/review-2026-06-05-36cb236-w7-universal-cli.md`

## Verdict

Accepted with one non-blocking follow-up.

The P0/P1 issues from the previous W7 review are materially fixed:

- `/api/agents/run` now resolves from top-level `agents:` profiles via `get_agent_profile()`.
- String `command` is rejected by `AgentProfile._validate()`.
- `worktree_path` is required by the API route and passed into `ExecutionRequest`.
- The route is now `async` and awaits backend execution instead of calling `asyncio.run()`.
- `UniversalCliAgentBackend` explicitly implements `ExecutionBackend`.
- `AgentRunService` marks success only when `not timed_out and exit_code == 0`.
- `stdin` mode is implemented through `ProcessSupervisor.run(..., stdin_text=...)`.
- Parent environment is inherited via `os.environ.copy()` and profile env overlays it.
- `cwd` is rendered from profile config.
- Env preview is redacted and written into command metadata.

This is sufficient to mark W7 as accepted for the revised UniversalCliAgentBackend direction.

---

## Checked items

### 1. Profile lookup uses `agents:`

Accepted.

`src/grace_control/config/agent_profiles.py` loads top-level `agents:` and exposes:

```python
load_agent_profiles()
get_agent_profile(executor_id)
```

`src/grace_control/api/routers/agents.py` now calls:

```python
profile = get_agent_profile(req.executor_id)
```

This fixes the previous incorrect lookup through `codex.executors`.

### 2. Command validation rejects string commands

Accepted.

`AgentProfile._validate()` rejects:

```yaml
command: opencode
```

and requires:

```yaml
command:
  - opencode
```

This removes the previous character-splitting failure mode.

### 3. Worktree path is passed through

Accepted.

The API route now rejects missing `worktree_path` and builds:

```python
ExecutionRequest(worktree_path=Path(req.worktree_path), ...)
```

This prevents accidental execution in the control-plane repo root.

### 4. Non-zero exit code is not accepted

Accepted.

`AgentRunService` now uses:

```python
accepted = (not result.timed_out and result.exit_code == 0)
```

and maps non-zero exits to `domain_status = "failed"`.

### 5. Stdin mode exists

Accepted.

`AgentRunService` computes `stdin_text` for `input_mode == "stdin"`, and `ProcessSupervisor` passes it to:

```python
proc.communicate(input=in_data)
```

### 6. Env inheritance and redaction exist

Accepted.

`AgentEnvBuilder.build()` starts from `os.environ.copy()` and overlays expanded profile env. `preview()` redacts secret-like keys.

### 7. CWD template is rendered

Accepted.

`AgentRunService` renders:

```python
cwd_template = executor.get("cwd", "{worktree_path}")
cwd_str = renderer.render([cwd_template], ctx)[0]
```

and passes the resulting cwd to the supervisor.

### 8. Async route fixed

Accepted.

`/api/agents/run` is now `async def` and awaits backend execution.

---

## Remaining non-blocking follow-up

### F1. Evidence run directory is supported in `AgentRunService`, but not passed through `UniversalCliAgentBackend`

`AgentRunService.run()` now accepts:

```python
run_dir: Path | None = None
```

and writes artifacts to that directory when provided. Good.

However, `UniversalCliAgentBackend.run()` does not pass a `run_dir` from `ExecutionRequest` or `request.spec`. It calls:

```python
out = await self._run_service.run(...)
```

without `run_dir=...`, so artifacts still fall back to:

```python
state_root / "agents" / packet_id
```

This is acceptable for W7 MVP because artifacts are still persisted and returned in `ExecutionResult.evidence`, but it is not yet fully unified with packet-run evidence directories.

Recommended follow-up:

```text
W7.2/W12: pass evidence_dir/run_dir through ExecutionRequest.spec and write CLI stdout/stderr into the canonical packet run evidence directory.
```

Acceptance for that follow-up:

- `PacketExecutionAdapter` passes current run evidence directory into backend request.
- `UniversalCliAgentBackend` forwards it to `AgentRunService`.
- `/api/packets/{id}/runs/{run_id}/artifacts` can show CLI stdout/stderr artifacts without a separate path convention.

---

## Status

W7 revised is accepted.

Overall W0-W11 can now be considered complete, with the following future cleanup items moved out of the blocker path:

1. W7.2/W12 — unify UniversalCliAgentBackend artifact directory with packet-run evidence directory.
2. W12 — finish readability/service-boundary cleanup for `packet_executor.py` and `evidence_service.py`.
3. W12 — remove or resolve remaining temporary GraceLint allowlist entries.
4. Optional — move WorktreeCleanupService git shelling into GitService for a single git boundary.
