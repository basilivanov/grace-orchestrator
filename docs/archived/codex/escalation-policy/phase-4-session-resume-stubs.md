# Escalation Policy — Phase 4: Session Resume Stubs

Audience: Coder (literal executor).

Depends on: `phase-3-recovery-controller.md` (build_failure_signal must exist).

---

## Goal

Add session resume data models and stub functions. Do NOT implement live LLM session memory or automatic prompt injection. Only prepare the data structures so that Phase 3 controller and Phase 5 admin UI can reference them.

---

## 1. New models in `src/grace_control/core/feature_recovery.py`

### 1.1 RecoverySessionSnapshot

```python
class RecoverySessionSnapshot(BaseModel):
    """Snapshot of a failed session for future resume."""
    session_id: str = ""
    feature_id: str
    wave_id: str = ""
    packet_id: str
    run_id: str = ""
    attempt_number: int = 1
    role: str = "coder"
    executor_id: str = ""
    model: str = ""
    started_at: datetime | None = None
    finished_at: datetime | None = None
    status: str = ""
    summary_human: str = ""
    failure_reason: str = ""
    changed_files: list[str] = Field(default_factory=list)
    artifacts: list[str] = Field(default_factory=list)
    acceptance_report_path: str = ""
    evidence_report_path: str = ""
    reviewer_report_path: str = ""
    recovery_decision_id: str = ""
    previous_attempts_summary: list[str] = Field(default_factory=list)
    full_context_json: dict[str, Any] = Field(default_factory=dict)
```

### 1.2 TaskResumeContext

```python
class TaskResumeContext(BaseModel):
    """Resume context for a specific task/packet retry."""
    task_id: str = ""
    packet_id: str
    feature_id: str
    role: str = "coder"
    previous_attempts: list[RecoverySessionSnapshot] = Field(default_factory=list)
    recovery_decision: dict[str, Any] = Field(default_factory=dict)
    executor_hint: str = ""
    failure_summary: str = ""
    architect_instruction: str = ""
    session_resume_available: bool = False
    build_resume_context: bool = False
```

### 1.3 SessionResumeSummary

```python
class SessionResumeSummary(BaseModel):
    """Human-readable summary of session resume context for admin UI."""
    packet_id: str
    attempt_number: int
    previous_executors: list[str] = Field(default_factory=list)
    failure_reason: str = ""
    action: str = ""
    resume_available: bool = False
    context_size_kb: int = 0
```

---

## 2. Stub functions in `src/grace_control/core/feature_recovery.py`

### 2.1 `build_session_snapshot(packet_run, packet=None)`

```python
def build_session_snapshot(packet_run: Any, packet: Any = None) -> RecoverySessionSnapshot:
    """
    Build RecoverySessionSnapshot from a PacketRun row.
    No LLM calls. No API calls.
    """
    rj = packet_run.result_json or {}
    acc = rj.get("acceptance_report", {})
    rec = rj.get("recovery", {})

    return RecoverySessionSnapshot(
        feature_id=getattr(packet, "feature_id", "") if packet else "",
        packet_id=packet_run.packet_id,
        run_id=packet_run.id,
        attempt_number=packet_run.run_number,
        status=packet_run.status,
        executor_id=rj.get("executor_id", ""),
        model=rj.get("model", ""),
        started_at=packet_run.started_at if hasattr(packet_run, "started_at") else None,
        finished_at=packet_run.finished_at if hasattr(packet_run, "finished_at") else None,
        failure_reason=rj.get("reason", ""),
        acceptance_report_path=rj.get("acceptance_report_path", ""),
        evidence_report_path=rj.get("evidence_verifier_report_path", ""),
        reviewer_report_path=rj.get("reviewer_report_path", ""),
        recovery_decision_id=rec.get("decision_id", ""),
        summary_human=f"Attempt {packet_run.run_number}: {packet_run.status} — {rj.get('reason', '')[:200]}",
    )
```

### 2.2 `build_task_resume_context(packet, decision, history=None)`

```python
def build_task_resume_context(
    packet: Any,
    decision: RecoveryDecision | None = None,
    history: list[RecoverySessionSnapshot] | None = None,
) -> TaskResumeContext:
    """
    Build TaskResumeContext from packet + recovery decision + attempt history.
    No LLM calls. No API calls.
    Returns context with session_resume_available=False (stub, not live).
    """
    return TaskResumeContext(
        packet_id=packet.id if hasattr(packet, "id") else "",
        feature_id=packet.feature_id if hasattr(packet, "feature_id") else "",
        role="coder",
        previous_attempts=history or [],
        recovery_decision=decision.model_dump() if decision else {},
        executor_hint=decision.next_executor_hint if decision else "",
        failure_summary=decision.reason if decision else "",
        architect_instruction=decision.architect_instruction if decision else "",
        session_resume_available=False,  # Stub — not implemented yet
        build_resume_context=False,       # Stub
    )
```

### 2.3 `render_resume_summary(context: TaskResumeContext) -> str`

```python
def render_resume_summary(context: TaskResumeContext) -> str:
    """
    Human-readable resume summary for admin UI.
    """
    parts = [f"Packet {context.packet_id}: {len(context.previous_attempts)} previous attempts"]
    if context.failure_summary:
        parts.append(f"Failure: {context.failure_summary[:200]}")
    if context.executor_hint:
        parts.append(f"Next executor: {context.executor_hint}")
    if context.architect_instruction:
        parts.append(f"Architect: {context.architect_instruction[:200]}")
    return "\\n".join(parts)
```

---

## 3. Required tests

Create `tests/grace_control/core/test_recovery_session.py`:

```text
test_snapshot_contains_run_identity          — snapshot has packet_id, run_id, attempt
test_snapshot_contains_executor_model        — snapshot records executor_id + model
test_snapshot_status_matches_run             — snapshot.status == run.status
test_resume_context_contains_previous        — context.previous_attempts populated
test_resume_context_contains_decision        — context.recovery_decision matches
test_resume_summary_is_human_readable        — render_resume_summary returns non-empty str
test_packet_missing_fields_does_not_crash    — missing packet → empty fields, no exception
test_resume_context_default_disabled         — session_resume_available=False (stub)
test_artifact_paths_preserved_in_snapshot    — report paths copied
```

**No LLM calls, no automatic prompt injection, no live session memory.**

---

## 4. Acceptance criteria

```text
1. RecoverySessionSnapshot model exists with all required fields.
2. TaskResumeContext model exists with all required fields.
3. build_session_snapshot() returns snapshot from PacketRun.
4. build_task_resume_context() returns context without LLM calls.
5. render_resume_summary() returns human-readable string.
6. session_resume_available=False (stub — not implemented).
7. All 9+ tests pass without real LLMs/git/API.
8. Existing recovery tests still pass.
```
