# Review: `8dabbaa` follow-up

Date: 2026-06-05
Reviewed commit: `8dabbaa1ffddf0040a69f825c24d63efe9d38f1b`
Previous review: `source/codex/review-2026-06-05-w0-w11-followup-still-open.md`

## Verdict

Partially accepted, but not done.

`8dabbaa` correctly removes direct `subprocess` / `shutil` from `packet_executor.py` and narrows `GRC101` subprocess allowlist. That closes part of the previous review.

However, several important blockers remain, and one new execution correctness issue is visible: selected executor/profile is lost before `ApiAgentBackend`, so execution can silently fall back to mock.

---

## Fixed in this commit

### 1. Direct subprocess removed from `packet_executor.py`

Accepted.

`packet_executor.py` no longer contains direct `import subprocess`, `subprocess.run`, or `import shutil`. Git worktree cleanup moved to `WorktreeCleanupService`.

### 2. `GRC101` allowlist narrowed

Accepted.

Current allowlist:

```python
ALLOWED_SUBPROCESS = {
    "services/git_service.py",
    "services/worktree_cleanup_service.py",
    "scripts/",
    "tests/",
}
```

This is much better than allowing all `services/`.

### 3. `GRC101` now catches import-only subprocess usage

Accepted.

`_check_subprocess()` now flags any line containing `subprocess`, including `import subprocess`, outside explicit allowlist.

### 4. Self-evolution direct subprocess removed

Accepted for the specific previous finding.

`_build_rollback()` now uses `WorktreeInspector().base_sha(project_root)` instead of direct `subprocess.run(["git", "rev-parse", "HEAD"])`.

### 5. pyproject Prefect metadata/deps improved

Accepted.

Project description no longer says “with Prefect”, and `typer` / `rich` are no longer in runtime dependencies.

---

## Still open / new blockers

### P0-1. Selected executor/profile is lost before ApiAgentBackend

Current `_resolve_executor()` computes an `executor`, but `_call_executor()` does not receive/use it. Instead it hardcodes:

```python
executor={"executor_id":"api","model":""}
```

Then `ApiAgentBackend.run()` does:

```python
provider = executor.get("provider", "mock")
model = executor.get("model", "")
```

Result: unless another path injects provider/model, packet execution silently defaults to `mock`, regardless of the selected executor/profile.

Impact:

- W7 API-agent path is not actually using configured agent profiles.
- Real execution may be bypassed by mock.
- Tests can pass while the production path does not call a real provider.

Required fix:

1. Pass resolved `executor` into `_call_executor()`:

```python
result = await self._call_executor(..., executor=executor)
```

2. Use it in `ExecutionRequest`:

```python
executor=executor
```

3. Ensure profile carries at least:

```text
provider
model
executor_id
role
```

4. Add regression test:

- given selected executor `{provider: "anthropic", model: "claude-test", executor_id: "coder-x"}`;
- `ApiAgentBackend` / fake gateway receives provider/model exactly;
- no implicit mock fallback occurs unless config explicitly selects mock.

---

### P0-2. Runtime default still advertises `legacy` in `GraceSettings`

Current `settings.py` still declares:

```python
execution_backend: str = "legacy"
```

`ProjectConfig.ExecutionSection` defaults to `api`, and `_apply_project_fallbacks()` likely overwrites the effective runtime value when no env is set. So this may not break runtime anymore in practice.

But it is still wrong and confusing after W8:

- class-level default says legacy is valid;
- inline comment says `"legacy" | "api" | "mock"`;
- tests that inspect class defaults may misread the true default;
- env `GRACE_EXECUTION_BACKEND=legacy` still reaches `select_backend` and fails.

Required fix:

```python
execution_backend: str = "api"
```

and update the comment to:

```python
# "api" | "mock" — legacy removed in W8
```

Add tests:

- `GraceSettings.model_fields["execution_backend"].default != "legacy"`;
- effective `settings.execution_backend != "legacy"` in clean env;
- `select_backend("legacy")` still raises clear W8 removal error.

---

### P1-1. `packet_executor.py` still writes legacy-style `packet_registry.yaml`

Current `_call_executor()` still writes:

```python
reg = self.state_root / "state"
rf = reg / "packet_registry.yaml"
...
rf.write_text(yaml.dump(ex, default_flow_style=False))
```

This was part of the legacy runner shape. After W8 / API-first execution, `packet_registry.yaml` should not be maintained from the executor unless a current non-legacy consumer is documented and tested.

Required fix:

- remove registry writing from `packet_executor.py`, or
- move it behind a clearly named compatibility service with tests and an explicit sunset note.

Preferred: remove it from the API backend path.

---

### P1-2. Branch/worktree identity is inconsistent

`WorktreeCleanupService.cleanup_attempt()` receives slug like:

```python
f"{pid}-{slug}"
```

and deletes branch:

```python
branch = f"agent/{slug}"
```

So cleanup branch becomes `agent/<packet_id>-attempt-0001`.

But `ExecutionRequest` currently gets:

```python
branch_name=f"agent/{slug}"
```

where `slug = "attempt-0001"`, so execution branch is `agent/attempt-0001`, missing packet id.

Impact:

- branch names can collide across packets;
- cleanup and execution branch names disagree;
- merge path may receive a branch name that is not the one cleanup expects.

Required fix:

Create one canonical branch/worktree naming helper, e.g.:

```python
def attempt_slug(packet_id: str, attempt: int) -> str: ...
def attempt_branch(packet_id: str, attempt: int) -> str: ...
def attempt_worktree_dir(packet_id: str, attempt: int) -> str: ...
```

Use it in both executor and cleanup service.

Regression tests:

- two different packets at attempt 1 produce different branches;
- cleanup branch equals request branch;
- no hardcoded `agent/attempt-` branch remains.

---

### P1-3. Self-evolution router still owns DB query/mutation logic

Previous review also noted that `self_evolution.py` router directly queries and mutates DB:

```python
sessions = db.query(SelfEvolutionSession)....all()
s = db.query(SelfEvolutionSession).filter_by(id=session_id).first()
s.status = "cancelled"
```

This remains open.

Required fix:

Move these into `SelfEvolutionService`:

```text
list_sessions(limit, offset)
get_session(session_id)
cancel_session(session_id)
```

Router should translate service result/errors only.

Tests:

- router cancel calls service;
- service owns session status mutation;
- `GRC104` or a new rule catches router DB queries/mutations for self-evolution.

---

### P1-4. GraceLint allowlist still has avoidable W12 exceptions

`packet_executor.py` no longer needs GRC101, good. But allowlist still keeps:

```yaml
GRC100 path: src/grace_control/adapters/packet_executor.py expires_wave: W12
GRC103 path: src/grace_control/adapters/packet_executor.py expires_wave: W12
GRC108 path: src/grace_control/adapters/packet_executor.py expires_wave: W12
```

Given the file has no `os.environ`, the GRC100 allowlist entry should be removed now. GRC103/GRC108 may stay temporarily if intentional, but should have precise reasons and tests.

Required fix:

- remove stale GRC100 packet_executor allowlist entry;
- ensure W12 exceptions are tracked explicitly in a new cleanup ticket/doc.

---

## P2 / follow-up

### ApiAgentBackend is still mock-only for real providers

This was already noted. It can remain as an explicit W7.1 follow-up if documented honestly. But with the new P0-1 issue, make sure configured provider/model is at least passed through to the gateway.

---

## Required next patch

Title:

```text
fix: pass executor profile through API backend and finish W8/W11 cleanup
```

Scope:

```text
src/grace_control/adapters/packet_executor.py
src/grace_control/config/settings.py
src/grace_control/services/worktree_cleanup_service.py
src/grace_control/services/self_evolution_service.py
src/grace_control/api/routers/self_evolution.py
.grace/lint_allowlist.yaml
tests/grace_control/*
```

Acceptance:

1. `_call_executor()` receives and forwards the resolved executor/profile.
2. ApiAgentBackend fake gateway receives configured provider/model, not implicit mock.
3. `GraceSettings` class default for execution backend is not `legacy`.
4. No `packet_registry.yaml` write in normal API backend execution path, or it is isolated behind explicit compatibility service.
5. Branch naming is canonical and includes packet id; cleanup branch equals request branch.
6. Self-evolution router no longer directly queries/mutates `SelfEvolutionSession`.
7. Remove stale `GRC100` allowlist for packet_executor.

Do not submit another patch that only proves `packet_executor.py` has no subprocess. That part is already accepted.
