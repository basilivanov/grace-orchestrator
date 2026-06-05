# Review: `a3eff49` follow-up approval

Date: 2026-06-05
Reviewed commit: `a3eff49a5ea2f63af28ff9e5b98974abd200bacf`
Previous review: `source/codex/review-2026-06-05-8dabbaa-followup.md`

## Verdict

Approved for the W0-W11 audit blocker closure.

The previously open P0/P1 findings from `8dabbaa` are now addressed in code:

- resolved executor profile is forwarded into the backend request;
- `GraceSettings.execution_backend` default is no longer `legacy`;
- `packet_registry.yaml` write was removed from `packet_executor.py`;
- branch/worktree naming now has canonical helpers;
- self-evolution list/get/cancel DB operations moved into `SelfEvolutionService`;
- stale `GRC100` allowlist entry for `packet_executor.py` was removed;
- `packet_executor.py` no longer imports `os`, `subprocess`, `shutil`, or `yaml`.

This closes the blocker chain from the W0-W11 completion audit.

---

## Checked items

### 1. Executor profile forwarded to backend

Accepted.

`PacketExecutionAdapter.execute()` now passes the resolved executor into `_call_executor()`:

```python
executor = self._resolve_executor(packet_data)
...
result = await self._call_executor(..., executor)
```

`_call_executor()` then forwards it into `ExecutionRequest`:

```python
req = ExecutionRequest(..., executor=executor, ...)
```

This fixes the previous issue where the request was hardcoded to:

```python
{"executor_id": "api", "model": ""}
```

and could silently fall back to mock provider.

### 2. Default backend no longer `legacy`

Accepted.

`GraceSettings` now declares:

```python
execution_backend: str = "api"  # "api" | "mock"
```

This is consistent with W8 legacy removal.

### 3. `packet_registry.yaml` write removed

Accepted.

`packet_executor.py` no longer imports `yaml` and no longer writes `state/packet_registry.yaml` in `_call_executor()`.

### 4. Canonical branch/worktree naming

Accepted.

`packet_executor.py` now has:

```python
def _attempt_slug(packet_id: str, attempt: int) -> str:
    return f"{packet_id}-attempt-{attempt:04d}"


def _attempt_branch(packet_id: str, attempt: int) -> str:
    return f"agent/{_attempt_slug(packet_id, attempt)}"
```

`_load_packet()` and `_call_executor()` both use the same slug helper. `ExecutionRequest.branch_name` now includes packet id via `_attempt_branch(...)`.

### 5. Self-evolution router delegates DB work to service

Accepted.

The router no longer imports `get_db` or `SelfEvolutionSession`. It delegates:

```python
_svc.list_sessions(...)
_svc.get_session(...)
_svc.cancel_session(...)
```

`SelfEvolutionService` now owns list/get/cancel DB operations.

### 6. Stale GRC100 allowlist removed

Accepted.

`.grace/lint_allowlist.yaml` no longer contains the `GRC100` entry for `src/grace_control/adapters/packet_executor.py`.

---

## Minor notes / not blockers

### M1. `packet_executor.py` is still dense

The blocker is closed, but the file remains compressed and service boundaries are still not as clean as the target architecture. This should become a quality follow-up, not a W0-W11 blocker.

Suggested future cleanup:

```text
PacketLoader
AcceptanceService
VerifierService
ReviewerService
RunResultWriter
```

### M2. ApiAgentBackend real-provider support remains W7.1

The executor now forwards provider/model correctly, but `AgentGatewayService` still only implements `mock` and returns unsupported for real providers. This was already understood as an MVP limitation.

Create a separate follow-up:

```text
W7.1: implement first real ApiAgentBackend provider adapter
```

### M3. Worktree cleanup still shells out by design

This is acceptable because it is now isolated in `WorktreeCleanupService` and explicitly allowed by GRC101. Longer term, it could be folded into `GitService` for a single git command boundary, but this is not a blocker.

### M4. Remaining W12 allowlist entries should be tracked

Remaining W12 entries:

```text
GRC101 core/llm_runner.py
GRC103 packet_executor.py
GRC108 packet_executor.py
GRC108 evidence_service.py
```

These should be handled in the next cleanup wave, but they no longer block this review.

---

## Status

The W0-W11 blocker chain can now be considered closed.

Recommended next work:

1. W7.1 — implement one real API provider adapter.
2. W12 — readability/service-boundary cleanup for `packet_executor.py` and `evidence_service.py`.
3. Tighten GraceLint expiry handling for W12 allowlist entries.
4. Optional: move `WorktreeCleanupService` git shelling into `GitService` for a single git boundary.
