# Review: W12 final approval

Date: 2026-06-05
Reviewed state: current `main` after reported W12 completion.
Previous review: `source/codex/review-2026-06-05-7db766c-w7-final.md`

## Verdict

Approved.

W12 closes the remaining W7.2/W12 follow-up from the previous review: CLI agent stdout/stderr artifacts are now written into the canonical packet-run evidence directory instead of the fallback `state_root/agents/{packet_id}` path.

This means the W0-W12 cleanup program can be considered complete, except for the already reported unrelated pre-existing failing test.

---

## Checked chain

### 1. `ExecutionRequest` carries canonical evidence dir

Accepted.

`src/grace_control/agent/backend.py` now has:

```python
evidence_dir: Path | None = None  # canonical run evidence path (W12)
```

This makes the evidence path part of the backend execution contract rather than an implicit convention.

### 2. `PacketExecutionAdapter` creates canonical packet-run evidence dir

Accepted.

`src/grace_control/adapters/packet_executor.py` now computes:

```python
evidence_dir = self.state_root / "packets" / packet_id / "runs" / f"R{run_number:02d}"
```

and passes it into `_call_executor(...)`.

### 3. `_call_executor()` forwards `evidence_dir` into `ExecutionRequest`

Accepted.

`_call_executor()` now builds:

```python
ExecutionRequest(..., session_dir=self.state_root, evidence_dir=evidence_dir)
```

This closes the previous gap where `AgentRunService.run_dir` existed but was never passed through the backend request.

### 4. `UniversalCliAgentBackend` forwards `request.evidence_dir` to `AgentRunService`

Accepted.

`src/grace_control/agent/universal_cli_backend.py` now calls:

```python
self._run_service.run(..., run_dir=request.evidence_dir)
```

So the UniversalCliAgentBackend no longer falls back to `state_root/agents/{packet_id}` in the normal PacketExecutionAdapter path.

### 5. `AgentRunService` uses provided run dir

Accepted.

`src/grace_control/services/agent_run_service.py` now uses:

```python
effective_run_dir = run_dir or (state_root / "agents" / packet_id)
```

The fallback remains useful for direct `/api/agents/run` or isolated tests, while the packet execution path uses canonical run evidence.

### 6. `AgentArtifactCollector` writes stdout/stderr/command log into that directory

Accepted.

`AgentArtifactCollector.collect(...)` writes:

```text
agent_stdout.log
agent_stderr.log
agent_command.log
```

into the supplied `run_dir`.

### 7. Artifacts are visible to the existing packet-run evidence flow

Accepted.

`PacketExecutionAdapter._route_after()` enumerates files from the same `run_dir`:

```python
art = [str(p.relative_to(run_dir)) for p in run_dir.rglob("*") if p.is_file()]
```

and stores the evidence path through `EvidenceService`. Therefore CLI stdout/stderr are now part of the same canonical packet-run artifact tree as acceptance/reviewer evidence.

---

## Minor notes / not blockers

### M1. Direct `/api/agents/run` still uses fallback artifact path

When `/api/agents/run` is called directly outside a packet run, there may be no canonical `packet_id/Rxx` run directory. In that case the fallback `state_root/agents/{packet_id}` is acceptable for MVP.

Future improvement: allow direct API callers to pass optional `run_id` or `evidence_dir` if they need canonical artifact placement.

### M2. One pre-existing test still fails

The reported test state is:

```text
399 passed, 1 pre-existing fail
```

This review treats that as unrelated to W12. It should still be investigated in a separate small maintenance packet so the suite can become fully green.

### M3. Remaining quality cleanup can move to future work

The architecture is now coherent enough to leave cleanup mode. Future work can be normal product/ops hardening:

```text
- fully green test suite
- API auth / token safety for remote control plane use
- better direct /api/agents/run artifact placement
- further packet_executor readability split if needed
- UI display for active executor/model/stage/artifacts
```

---

## Final status

W0-W12 accepted.

The project now matches the intended control-plane model:

```text
GRACE API/OpenAPI = public control plane
UniversalCliAgentBackend = configurable local CLI execution adapter
Legacy Prefect = removed from runtime package
CLI = not a public GRACE control plane
Trace/artifacts/evidence = visible through API-backed canonical paths
GraceLint/config/docs = guardrails against old technical debt returning
```
