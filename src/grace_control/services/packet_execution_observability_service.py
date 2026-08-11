# ############################################################################
# AI_HEADER: packet_execution_observability_service — packet runtime events and artifacts
# ROLE: Owns stateless observability orchestration for packet execution while
#       retaining the adapter's trace, event, artifact, and redaction state.
# ############################################################################

# START_MODULE_CONTRACT
# purpose: Emit packet lifecycle events and persist runtime artifacts with stable names and payloads.
# inputs: Adapter observability state plus execution results/reports.
# returns: Artifact references or None; event operations return None.
# side_effects: Writes JSONL events and packet-scoped artifact files.
# emitted_logs: obs_event_failed and artifact capture failure msg names.
# error_behavior: Observability failures are contained and do not fail packet execution.
# END_MODULE_CONTRACT

# START_MODULE_MAP
# mapping:
#   - class: PacketExecutionObservabilityService
#     methods:
#       - initialize
#       - emit
#       - write_artifact
#       - write_json_artifact
#       - capture_prompt
#       - capture_agent_output
#       - capture_test_output
#       - capture_diff_patch
#       - capture_evidence
# END_MODULE_MAP

from __future__ import annotations

import hashlib
from pathlib import Path

from grace_control.core.runtime_artifacts import RuntimeArtifactRef, RuntimeArtifactStore
from grace_control.core.runtime_events import RuntimeEventLogger
from grace_control.core.runtime_redaction import RuntimeRedactor
from grace_control.core.runtime_trace import RuntimeTraceContext, generate_trace_id, set_current_trace
from grace_control.core.structured_logger import GraceLogger

_log = GraceLogger("adapter")


# START_BLOCK_OBSERVABILITY
class PacketExecutionObservabilityService:
    # START_FUNCTION_CONTRACT
    # name: initialize
    # purpose: Initialize packet trace, artifact, event, and redaction state.
    # inputs: adapter, packet_data, run_id — facade state and current run identity.
    # returns: None.
    # side_effects: Creates observability store/logger state and sets current trace.
    # emitted_logs: None.
    # error_behavior: Disables observability when initialization fails.
    # END_FUNCTION_CONTRACT
    def initialize(self, adapter, packet_data: dict, run_id: str) -> None:
        try:
            from grace_control.config.settings import settings as _obs_settings
            adapter._obs_disabled = not _obs_settings.runtime_observability_enabled
            feature_id = packet_data.get("feature_id", "") or ""
            wave_id = packet_data.get("wave_id", "") or ""
            packet_id = packet_data.get("id", "")
            adapter._obs_trace = RuntimeTraceContext(
                trace_id=generate_trace_id(),
                feature_id=feature_id,
                packet_id=packet_id,
                wave_id=wave_id,
                runtime_run_id=run_id,
            )
            set_current_trace(adapter._obs_trace)
            if adapter._obs_disabled:
                return
            adapter._obs_store = RuntimeArtifactStore()
            adapter._obs_events = RuntimeEventLogger(store=adapter._obs_store)
            adapter._obs_redactor = RuntimeRedactor()
            adapter._obs_packet_dir = adapter._obs_store.packet_dir(feature_id, packet_id)
            adapter._obs_redact_enabled = _obs_settings.runtime_redact_secrets
        except Exception:
            adapter._obs_disabled = True

    # START_FUNCTION_CONTRACT
    # name: emit
    # purpose: Emit one canonical packet execution observability event.
    # inputs: adapter, event, status, message, duration_ms, artifact_refs, payload.
    # returns: None.
    # side_effects: Writes one event through RuntimeEventLogger.
    # emitted_logs: obs_event_failed.
    # error_behavior: Swallows event logger failures after logging the failure.
    # END_FUNCTION_CONTRACT
    def emit(self, adapter, event: str, status: str | None = None,
                   message: str | None = None, duration_ms: int | None = None,
                   artifact_refs: list[RuntimeArtifactRef] | None = None,
                   payload: dict | None = None) -> None:
        if getattr(adapter, "_obs_disabled", True):
            return
        try:
            adapter._obs_events.emit(
                trace=adapter._obs_trace,
                event=event,
                stage="packet_execution",
                component="packet_executor",
                status=status,
                message=message,
                duration_ms=duration_ms,
                artifact_refs=artifact_refs,
                payload=payload,
            )
        except Exception as _obs_err:
            _log.warn("obs_event_failed", error=str(_obs_err)[:200])

    # START_FUNCTION_CONTRACT
    # name: write_artifact
    # purpose: Persist one redacted text runtime artifact.
    # inputs: adapter, name, content, kind — artifact identity and content.
    # returns: RuntimeArtifactRef or None.
    # side_effects: Writes a packet-scoped artifact file.
    # emitted_logs: obs_artifact_write_failed.
    # error_behavior: Returns None when observability or writing fails.
    # END_FUNCTION_CONTRACT
    def write_artifact(self, adapter, name: str, content: str, kind: str) -> RuntimeArtifactRef | None:
        if getattr(adapter, "_obs_disabled", True):
            return None
        try:
            redacted = adapter._obs_redactor.redact_string(content) if adapter._obs_redact_enabled else content
            return adapter._obs_store.write_packet_text(
                trace=adapter._obs_trace, packet_id=adapter._obs_trace.packet_id,
                name=name, content=redacted, kind=kind,
            )
        except Exception as _write_err:
            _log.warn("obs_artifact_write_failed", name=name, error=str(_write_err)[:200])
            return None

    # START_FUNCTION_CONTRACT
    # name: write_json_artifact
    # purpose: Persist one redacted JSON runtime artifact.
    # inputs: adapter, name, payload, kind — artifact identity and JSON payload.
    # returns: RuntimeArtifactRef or None.
    # side_effects: Writes a packet-scoped JSON artifact file.
    # emitted_logs: obs_json_artifact_write_failed.
    # error_behavior: Returns None when observability or writing fails.
    # END_FUNCTION_CONTRACT
    def write_json_artifact(self, adapter, name: str, payload: dict | list, kind: str) -> RuntimeArtifactRef | None:
        if getattr(adapter, "_obs_disabled", True):
            return None
        try:
            redacted_payload = adapter._obs_redactor.redact_payload(payload) if adapter._obs_redact_enabled else payload
            return adapter._obs_store.write_packet_json(
                trace=adapter._obs_trace, packet_id=adapter._obs_trace.packet_id,
                name=name, payload=redacted_payload, kind=kind,
            )
        except Exception as _write_err:
            _log.warn("obs_json_artifact_write_failed", name=name, error=str(_write_err)[:200])
            return None

    # START_FUNCTION_CONTRACT
    # name: capture_prompt
    # purpose: Capture the backend prompt as a runtime artifact when present.
    # inputs: adapter, result — backend execution result.
    # returns: RuntimeArtifactRef or None.
    # side_effects: Writes prompt.txt when a prompt exists.
    # emitted_logs: obs_prompt_capture_failed.
    # error_behavior: Returns None on missing prompt or capture failure.
    # END_FUNCTION_CONTRACT
    def capture_prompt(self, adapter, result) -> RuntimeArtifactRef | None:
        try:
            prompt = getattr(result, "prompt", None) or ""
            if prompt:
                return adapter._obs_write_artifact("prompt.txt", prompt, "prompt")
        except Exception as _capture_err:
            _log.warn("obs_prompt_capture_failed", error=str(_capture_err)[:200])
        return None

    # START_FUNCTION_CONTRACT
    # name: capture_agent_output
    # purpose: Capture backend stdout and stderr artifacts.
    # inputs: adapter, result — backend execution result.
    # returns: List of RuntimeArtifactRef values.
    # side_effects: Writes agent output artifact files.
    # emitted_logs: obs_output_capture_failed.
    # error_behavior: Returns an empty list when capture fails.
    # END_FUNCTION_CONTRACT
    def capture_agent_output(self, adapter, result) -> list[RuntimeArtifactRef]:
        refs: list[RuntimeArtifactRef] = []
        try:
            stdout = getattr(result, "stdout", None) or ""
            stderr = getattr(result, "stderr", None) or ""
            if stdout:
                r = adapter._obs_write_artifact("agent_stdout.txt", stdout, "agent_stdout")
                if r:
                    refs.append(r)
            if stderr:
                r = adapter._obs_write_artifact("agent_stderr.txt", stderr, "agent_stderr")
                if r:
                    refs.append(r)
        except Exception as _capture_err:
            _log.warn("obs_output_capture_failed", error=str(_capture_err)[:200])
        return refs

    # START_FUNCTION_CONTRACT
    # name: capture_test_output
    # purpose: Capture the acceptance report as a runtime artifact.
    # inputs: adapter, accept_report — acceptance report value.
    # returns: RuntimeArtifactRef or None.
    # side_effects: Writes test_output.txt JSON content.
    # emitted_logs: obs_test_output_capture_failed.
    # error_behavior: Returns None when no report or capture fails.
    # END_FUNCTION_CONTRACT
    def capture_test_output(self, adapter, accept_report) -> RuntimeArtifactRef | None:
        if accept_report is None:
            return None
        try:
            payload = accept_report.to_dict() if hasattr(accept_report, "to_dict") else {"summary": str(accept_report)}
            return adapter._obs_write_json_artifact("test_output.txt", payload, "test_output")
        except Exception as _capture_err:
            _log.warn("obs_test_output_capture_failed", error=str(_capture_err)[:200])
            return None

    # START_FUNCTION_CONTRACT
    # name: capture_diff_patch
    # purpose: Capture the generated agent patch as a runtime artifact.
    # inputs: adapter, wt_path, run_dir, base_sha — patch context.
    # returns: RuntimeArtifactRef or None.
    # side_effects: Reads agent.patch and writes diff.patch.
    # emitted_logs: obs_diff_patch_capture_failed.
    # error_behavior: Returns None when the patch is unavailable.
    # END_FUNCTION_CONTRACT
    def capture_diff_patch(self, adapter, wt_path, run_dir, base_sha) -> RuntimeArtifactRef | None:
        if getattr(adapter, "_obs_disabled", True):
            return None
        if not run_dir or not base_sha:
            return None
        try:
            patch_src = Path(run_dir) / "agent.patch"
            if patch_src.exists():
                content = patch_src.read_text(encoding="utf-8")
                return adapter._obs_write_artifact("diff.patch", content, "diff")
        except Exception as _capture_err:
            _log.warn("obs_diff_patch_capture_failed", error=str(_capture_err)[:200])
        return None

    # START_FUNCTION_CONTRACT
    # name: capture_evidence
    # purpose: Persist evidence and truthful artifact metadata for a terminal run.
    # inputs: adapter, packet/run identifiers, commit, changed files, reports, result.
    # returns: Tuple of evidence and metadata artifact references.
    # side_effects: Writes evidence.json and metadata.json.
    # emitted_logs: None.
    # error_behavior: Returns a pair of None values when capture fails.
    # END_FUNCTION_CONTRACT
    def capture_evidence(self, adapter, packet_id: str, run_id: str, run_number: int,
                                    commit_sha: str, changed_files, accept_report, evr,
                                    er) -> tuple[RuntimeArtifactRef | None, RuntimeArtifactRef | None]:
        if getattr(adapter, "_obs_disabled", True):
            return None, None
        try:
            ac = accept_report.to_dict() if accept_report and hasattr(accept_report, "to_dict") else {}
            evidence_data = {
                "packet_id": packet_id,
                "run_id": run_id,
                "run_number": run_number,
                "accepted": er.accepted if er else False,
                "domain_status": er.domain_status if er else "unknown",
                "duration_ms": er.duration_ms if er else 0,
                "commit_sha": commit_sha or "",
                "changed_files_count": len(changed_files) if changed_files else 0,
                "acceptance_verdict": ac.get("final_verdict", ""),
                "acceptance_summary": ac.get("summary", ""),
                "evidence_verifier_verdict": evr.verdict if evr and hasattr(evr, "verdict") else "",
            }
            # Write evidence.json first so it appears in metadata.artifacts
            ev_ref = adapter._obs_write_json_artifact("evidence.json", evidence_data, "evidence")
            # Build truthful artifact manifest from the packet dir (includes evidence.json)
            written_refs: dict[str, dict] = {}
            pkt_dir = adapter._obs_packet_dir
            if pkt_dir and pkt_dir.exists():
                for f in pkt_dir.iterdir():
                    if f.is_file() and f.name != "metadata.json":
                        content = f.read_text(encoding="utf-8")
                        written_refs[f.name] = {
                            "sha256": hashlib.sha256(content.encode("utf-8")).hexdigest(),
                            "size_bytes": len(content.encode("utf-8")),
                            "present": True,
                        }
            meta = {
                "packet_id": packet_id,
                "run_id": run_id,
                "run_number": run_number,
                "commit_sha": commit_sha or "",
                "artifacts": written_refs,
            }
            meta_ref = adapter._obs_write_json_artifact("metadata.json", meta, "metadata")
            return ev_ref, meta_ref
        except Exception:
            return None, None

# END_BLOCK_OBSERVABILITY
