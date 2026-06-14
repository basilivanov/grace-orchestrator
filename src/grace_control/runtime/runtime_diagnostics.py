from __future__ import annotations

from typing import Any

from pydantic import BaseModel

from grace_control.core.runtime_artifacts import RuntimeArtifactRef, RuntimeArtifactStore
from grace_control.core.runtime_events import RuntimeEventLogger
from grace_control.core.runtime_redaction import RuntimeRedactor
from grace_control.core.runtime_trace import RuntimeTraceContext
from grace_control.core.structured_logger import GraceLogger

_log = GraceLogger("runtime_diagnostics")


class RuntimeDiagnostics(BaseModel):
    runtime_run_id: str = ""
    packet_id: str = ""
    trace_id: str = ""
    adapter: str = ""
    runtime_mode: str = ""
    agent_name: str = ""
    model: str = ""
    accepted: bool = False
    failure_code: str | None = None
    failure_stage: str | None = None
    duration_ms: int = 0
    changed_files: list[str] = []
    out_of_scope_files: list[str] = []
    frozen_touched_files: list[str] = []
    artifact_refs: list[str] = []
    stdout_tail: str = ""
    stderr_tail: str = ""


class RuntimeFailureReadModel(BaseModel):
    packet_id: str = ""
    status: str = "unknown"
    failure_code: str | None = None
    title: str = ""
    details: str = ""
    changed_files: list[str] = []
    artifact_refs: list[str] = []


class RuntimeDiagnosticsBuilder:

    @staticmethod
    def build(
        runtime_run_id: str = "",
        packet_id: str = "",
        trace_id: str = "",
        adapter: str = "",
        runtime_mode: str = "",
        agent_name: str = "",
        model: str = "",
        accepted: bool = False,
        failure_code: str | None = None,
        failure_stage: str | None = None,
        duration_ms: int = 0,
        changed_files: list[str] | None = None,
        out_of_scope_files: list[str] | None = None,
        frozen_touched_files: list[str] | None = None,
        refs: list[RuntimeArtifactRef] | None = None,
        stdout_tail: str = "",
        stderr_tail: str = "",
    ) -> RuntimeDiagnostics:
        return RuntimeDiagnostics(
            runtime_run_id=runtime_run_id,
            packet_id=packet_id,
            trace_id=trace_id,
            adapter=adapter,
            runtime_mode=runtime_mode,
            agent_name=agent_name,
            model=model,
            accepted=accepted,
            failure_code=failure_code,
            failure_stage=failure_stage,
            duration_ms=duration_ms,
            changed_files=changed_files or [],
            out_of_scope_files=out_of_scope_files or [],
            frozen_touched_files=frozen_touched_files or [],
            artifact_refs=[r.path for r in refs if r.path] if refs else [],
            stdout_tail=stdout_tail[-2000:] if stdout_tail else "",
            stderr_tail=stderr_tail[-2000:] if stderr_tail else "",
        )

    @staticmethod
    def persist(
        diagnostics: RuntimeDiagnostics,
        scope_result: Any,
        diff_result: Any,
        trace: RuntimeTraceContext,
        packet_id: str,
        store: RuntimeArtifactStore,
        redactor: RuntimeRedactor,
    ) -> list[RuntimeArtifactRef]:
        refs: list[RuntimeArtifactRef] = []

        try:
            r = store.write_packet_json(
                trace=trace, packet_id=packet_id,
                name="runtime_diagnostics.json",
                payload=redactor.redact_payload(diagnostics.model_dump()),
                kind="runtime_diagnostics",
            )
            if r:
                refs.append(r)
        except Exception:
            _log.warn("write_runtime_diagnostics_failed")

        try:
            r = store.write_packet_json(
                trace=trace, packet_id=packet_id,
                name="scope_enforcement.json",
                payload=redactor.redact_payload(scope_result.model_dump()),
                kind="scope_enforcement",
            )
            if r:
                refs.append(r)
        except Exception:
            _log.warn("write_scope_enforcement_failed")

        try:
            r = store.write_packet_json(
                trace=trace, packet_id=packet_id,
                name="diff_inspection.json",
                payload=redactor.redact_payload(diff_result.model_dump()),
                kind="diff_inspection",
            )
            if r:
                refs.append(r)
        except Exception:
            _log.warn("write_diff_inspection_failed")

        try:
            r = store.write_packet_json(
                trace=trace, packet_id=packet_id,
                name="changed_files.json",
                payload=redactor.redact_payload({"changed_files": diagnostics.changed_files}),
                kind="changed_files",
            )
            if r:
                refs.append(r)
        except Exception:
            _log.warn("write_changed_files_failed")

        return refs


_FATAL_SCOPE_FAILURES = {
    "AGENT_CHANGED_OUT_OF_SCOPE": "Agent changed files outside allowed scope",
    "AGENT_TOUCHED_FROZEN_SCOPE": "Agent modified frozen scope files",
    "AGENT_SCOPE_ENFORCEMENT_FAILED": "Scope enforcement check failed",
    "AGENT_DIFF_INSPECTION_FAILED": "Diff inspection failed",
    "AGENT_NO_CHANGES_PRODUCED": "Agent produced no changes",
}


def build_read_model(
    packet_id: str,
    diagnostics: RuntimeDiagnostics | None = None,
    scope_enforcement: Any = None,
) -> RuntimeFailureReadModel:
    status = "failed" if diagnostics and not diagnostics.accepted else "unknown"
    fc = diagnostics.failure_code if diagnostics else None
    title = _FATAL_SCOPE_FAILURES.get(fc or "", "Runtime error") if fc else "Success"
    details = ""
    changed = diagnostics.changed_files if diagnostics else []

    if scope_enforcement:
        if hasattr(scope_enforcement, "out_of_scope_files") and scope_enforcement.out_of_scope_files:
            details = f"Files outside scope: {scope_enforcement.out_of_scope_files}"
        elif hasattr(scope_enforcement, "frozen_touched_files") and scope_enforcement.frozen_touched_files:
            details = f"Frozen scope changes: {scope_enforcement.frozen_touched_files}"

    return RuntimeFailureReadModel(
        packet_id=packet_id,
        status=status,
        failure_code=fc,
        title=title,
        details=details,
        changed_files=changed,
        artifact_refs=diagnostics.artifact_refs if diagnostics else [],
    )
