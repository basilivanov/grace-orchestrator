from __future__ import annotations

import asyncio
import hashlib
import json
import os
import signal
import time
from pathlib import Path
from typing import Any, Callable

from grace_control.agent.backend import ExecutionBackend, ExecutionRequest, ExecutionResult
from grace_control.config.settings import settings
from grace_control.core.runtime_artifacts import RuntimeArtifactRef, RuntimeArtifactStore
from grace_control.core.runtime_events import RuntimeEventLogger
from grace_control.core.runtime_redaction import RuntimeRedactor
from grace_control.core.runtime_trace import RuntimeTraceContext
from grace_control.core.structured_logger import GraceLogger
from grace_control.runtime.agent_execution_adapter import (
    AgentExecutionAdapter,
    AgentExecutionAdapterResult,
)
from grace_control.runtime.agent_runtime_contract import (
    AgentRuntimeContract,
    AgentRuntimeFailureCode,
)
from grace_control.runtime.opencode_attach_command_builder import OpenCodeAttachCommandBuilder
from grace_control.runtime.opencode_command_builder import OpenCodeCommandBuilder
from grace_control.runtime.opencode_event_collector import OpenCodeEventCollector
from grace_control.runtime.opencode_failure_classifier import OpenCodeFailureClassifier
from grace_control.runtime.opencode_server_manager import OpenCodeServerManager
from grace_control.runtime.opencode_server_state import OpenCodeServerStatus

_log = GraceLogger("opencode_runtime_adapter")

ProcessRunner = Callable[..., asyncio.subprocess.Process]


def _real_process_runner(*args, **kwargs) -> asyncio.subprocess.Process:
    return asyncio.create_subprocess_exec(*args, **kwargs)


class OpenCodeRuntimeAdapter(AgentExecutionAdapter):

    def __init__(
        self,
        command_builder: OpenCodeCommandBuilder | None = None,
        attach_command_builder: OpenCodeAttachCommandBuilder | None = None,
        server_manager: OpenCodeServerManager | None = None,
        event_collector: OpenCodeEventCollector | None = None,
        failure_classifier: OpenCodeFailureClassifier | None = None,
        process_runner: ProcessRunner | None = None,
        store: RuntimeArtifactStore | None = None,
        redactor: RuntimeRedactor | None = None,
    ):
        self._cmd_builder = command_builder or OpenCodeCommandBuilder()
        self._attach_cmd_builder = attach_command_builder or OpenCodeAttachCommandBuilder()
        self._server_manager = server_manager
        self._collector = event_collector
        self._classifier = failure_classifier or OpenCodeFailureClassifier()
        self._process_runner = process_runner or _real_process_runner
        self._store = store or RuntimeArtifactStore()
        self._redactor = redactor or RuntimeRedactor()

    async def run(self, contract: AgentRuntimeContract, prompt: str, cmd: list[str] | None = None) -> AgentExecutionAdapterResult:
        start = time.time()
        try:
            if cmd is not None:
                pass
            else:
                mode = getattr(settings, "opencode_runtime_mode", "direct")
                if mode == "serve_attach":
                    from grace_control.runtime.opencode_server_manager import OpenCodeServerManager
                    sm = self._server_manager or OpenCodeServerManager()
                    server_state = await sm.ensure_running()
                    if server_state.status == OpenCodeServerStatus.FAILED:
                        return AgentExecutionAdapterResult(
                            ok=False,
                            adapter="opencode",
                            command=[],
                            cwd=contract.worktree_root,
                            duration_ms=int((time.time() - start) * 1000),
                            failure_code=server_state.failure_code or AgentRuntimeFailureCode.AGENT_OPENCODE_SERVER_NOT_RUNNING,
                            failure_summary=server_state.failure_summary or "server not running",
                        )
                    cmd = self._attach_cmd_builder.build(contract, server_state.url)
                else:
                    cmd = self._cmd_builder.build(contract)
        except ValueError as e:
            return AgentExecutionAdapterResult(
                ok=False,
                adapter="opencode",
                command=[],
                cwd=contract.worktree_root,
                duration_ms=int((time.time() - start) * 1000),
                failure_code="AGENT_RUNTIME_CONTRACT_INVALID",
                failure_summary=str(e),
            )

        cwd = contract.worktree_root

        proc = await self._process_runner(
            *cmd,
            cwd=cwd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            stdin=asyncio.subprocess.PIPE,
            start_new_session=True,
        )

        timeout_s = settings.opencode_direct_timeout_seconds
        grace_s = settings.opencode_process_kill_grace_seconds
        collected_stdout: list[str] = []
        collected_stderr: list[str] = []
        collector = self._collector or OpenCodeEventCollector(
            require_json_events=getattr(settings, "opencode_json_events_required", True),
        )
        collector.reset()

        async def _read_stream(stream, dest: list[str], is_stdout: bool):
            while True:
                line_bytes = await stream.readline()
                if not line_bytes:
                    break
                line = line_bytes.decode("utf-8", errors="replace")
                dest.append(line)
                if is_stdout:
                    collector.feed_line(line)

        async def _feed_stdin(proc_stdin):
            if prompt:
                try:
                    proc_stdin.write(prompt.encode("utf-8"))
                    await proc_stdin.drain()
                except Exception:
                    pass
            try:
                proc_stdin.close()
            except Exception:
                pass

        try:
            async with asyncio.timeout(timeout_s):
                await asyncio.gather(
                    _read_stream(proc.stdout, collected_stdout, is_stdout=True),
                    _read_stream(proc.stderr, collected_stderr, is_stdout=False),
                    _feed_stdin(proc.stdin),
                )
                exit_code = await proc.wait()
        except asyncio.TimeoutError:
            # Kill the entire process group, not just the parent
            try:
                pgid = os.getpgid(proc.pid)
                os.killpg(pgid, signal.SIGTERM)
            except Exception:
                try:
                    proc.terminate()
                except Exception:
                    pass
            try:
                await asyncio.wait_for(proc.wait(), timeout=grace_s)
            except asyncio.TimeoutError:
                try:
                    pgid = os.getpgid(proc.pid)
                    os.killpg(pgid, signal.SIGKILL)
                except Exception:
                    try:
                        proc.kill()
                    except Exception:
                        pass
                try:
                    await asyncio.wait_for(proc.wait(), timeout=grace_s)
                except Exception:
                    pass
            except Exception:
                pass
            exit_code = None

        duration_ms = int((time.time() - start) * 1000)
        stdout_text = "".join(collected_stdout)
        stderr_text = "".join(collected_stderr)
        raw_events = collector.raw_events
        event_count = len(raw_events)

        bypass_no_event = collector.has_meaningful_output()
        failure_code, failure_summary = self._classifier.classify(
            exit_code=exit_code,
            stdout=stdout_text,
            stderr=stderr_text,
            duration_ms=duration_ms,
            timeout_seconds=timeout_s,
            event_count=event_count,
            no_event_bypassed=bypass_no_event,
        )

        # In serve_attach mode, override generic failures to ATTACH_FAILED
        if getattr(settings, "opencode_runtime_mode", None) == "serve_attach":
            if failure_code in (None, AgentRuntimeFailureCode.AGENT_PROCESS_CRASHED,
                                AgentRuntimeFailureCode.AGENT_NO_EVENT_OUTPUT):
                failure_code = AgentRuntimeFailureCode.AGENT_OPENCODE_ATTACH_FAILED
                failure_summary = failure_summary or f"attach run failed (exit {exit_code})"

        session_id = None
        if raw_events:
            for ev in raw_events:
                sid = ev.get("session_id") or ev.get("session", {}).get("id")
                if sid:
                    session_id = sid
                    break

        prompt_sha = hashlib.sha256((prompt or "").encode("utf-8")).hexdigest()

        return AgentExecutionAdapterResult(
            ok=(failure_code is None),
            accepted=(failure_code is None and exit_code == 0) if exit_code is not None else False,
            adapter="opencode",
            command=cmd,
            cwd=cwd,
            stdout=stdout_text,
            stderr=stderr_text,
            raw_events=raw_events,
            exit_code=exit_code,
            duration_ms=duration_ms,
            failure_code=failure_code,
            failure_stage="opencode_run" if failure_code else None,
            failure_summary=failure_summary,
            session_id=session_id,
            model=contract.model,
            agent_name=contract.agent_name,
            prompt_sha256=prompt_sha,
        )

    async def run_with_artifacts(
        self,
        contract: AgentRuntimeContract,
        prompt: str,
        trace: RuntimeTraceContext,
        packet_id: str,
    ) -> tuple[AgentExecutionAdapterResult, list[RuntimeArtifactRef]]:
        result = await self.run(contract, prompt)
        refs = await self._write_opencode_artifacts(result, prompt, trace, packet_id)
        return result, refs

    async def _write_opencode_artifacts(
        self,
        result: AgentExecutionAdapterResult,
        prompt: str,
        trace: RuntimeTraceContext,
        packet_id: str,
    ) -> list[RuntimeArtifactRef]:
        refs: list[RuntimeArtifactRef] = []

        try:
            redacted_cmd = self._redactor.redact_string(" ".join(result.command))
            r = self._store.write_packet_text(
                trace=trace, packet_id=packet_id,
                name="command.txt", content=redacted_cmd, kind="opencode_command",
            )
            if r:
                refs.append(r)
        except Exception:
            _log.warn("write_command_txt_failed")

        try:
            redacted_prompt = self._redactor.redact_string(prompt)
            r = self._store.write_packet_text(
                trace=trace, packet_id=packet_id,
                name="prompt.txt", content=redacted_prompt, kind="opencode_prompt",
            )
            if r:
                refs.append(r)
        except Exception:
            _log.warn("write_prompt_txt_failed")

        if result.stdout:
            try:
                redacted_stdout = self._redactor.redact_string(result.stdout)
                r = self._store.write_packet_text(
                    trace=trace, packet_id=packet_id,
                    name="agent_stdout.txt", content=redacted_stdout, kind="opencode_stdout",
                )
                if r:
                    refs.append(r)
            except Exception:
                _log.warn("write_stdout_failed")

        if result.stderr:
            try:
                redacted_stderr = self._redactor.redact_string(result.stderr)
                r = self._store.write_packet_text(
                    trace=trace, packet_id=packet_id,
                    name="agent_stderr.txt", content=redacted_stderr, kind="opencode_stderr",
                )
                if r:
                    refs.append(r)
            except Exception:
                _log.warn("write_stderr_failed")

        if result.raw_events:
            try:
                lines = "\n".join(
                    json.dumps(self._redactor.redact_payload(ev), ensure_ascii=False)
                    for ev in result.raw_events
                )
                r = self._store.write_packet_text(
                    trace=trace, packet_id=packet_id,
                    name="raw_opencode_events.jsonl", content=lines, kind="opencode_events",
                )
                if r:
                    refs.append(r)
            except Exception:
                _log.warn("write_events_failed")

        try:
            redacted_result = self._redactor.redact_payload(result.model_dump())
            r = self._store.write_packet_json(
                trace=trace, packet_id=packet_id,
                name="adapter_result.json", payload=redacted_result, kind="opencode_result",
            )
            if r:
                refs.append(r)
        except Exception:
            _log.warn("write_result_failed")

        return refs


class OpenCodeExecutionBackend:
    """Implements ExecutionBackend Protocol — wraps OpenCodeRuntimeAdapter.

    Builds AgentRuntimeContract from ExecutionRequest, builds the full prompt
    from the materialized packet file, writes all W4 artifacts via the
    RuntimeArtifactStore, and emits packet.opencode_* events.
    """

    def __init__(self, adapter: OpenCodeRuntimeAdapter | None = None):
        self._adapter = adapter or OpenCodeRuntimeAdapter()
        self._trace: RuntimeTraceContext | None = None
        self._store: RuntimeArtifactStore | None = None
        self._events: RuntimeEventLogger | None = None

    def set_observability(
        self,
        trace: RuntimeTraceContext,
        store: RuntimeArtifactStore | None = None,
        events: RuntimeEventLogger | None = None,
    ) -> None:
        self._trace = trace
        self._store = store
        self._events = events

    async def run(self, request: ExecutionRequest) -> ExecutionResult:
        executor = request.executor or {}
        contract = AgentRuntimeContract(
            runtime_run_id="",
            feature_id="",
            packet_id=request.packet_id,
            role=executor.get("role", "coder"),
            adapter="opencode",
            target_repo_root="",
            orchestrator_repo_root="",
            worktree_root=str(request.worktree_path),
            cwd=str(request.worktree_path),
            executor_id=executor.get("executor_id", ""),
            agent_name=executor.get("agent_name", ""),
            provider=executor.get("provider", ""),
            model=executor.get("model", ""),
            runtime_artifacts_dir="",
            timeout_seconds=request.timeout_s or 1800,
        )

        prompt = _build_full_prompt(request)
        package_id = request.packet_id
        trace = self._trace
        store = self._store
        events = self._events
        all_refs: list[RuntimeArtifactRef] = []
        run_cmd: list[str] | None = None
        mode = getattr(settings, "opencode_runtime_mode", "direct")

        # ── 1. Serve/attach server management (mode == "serve_attach") ──
        if mode == "serve_attach":
            sm = self._adapter._server_manager or OpenCodeServerManager()
            binary = getattr(settings, "opencode_binary", "opencode")
            host = getattr(settings, "opencode_server_host", "127.0.0.1")
            port = getattr(settings, "opencode_server_port", 4096)
            server_url = f"http://{host}:{port}"
            server_cmd_str = f"{binary} serve --hostname {host} --port {port}"

            # Server command artifact
            server_cmd_ref = None
            if trace and store:
                try:
                    server_cmd_ref = store.write_packet_text(
                        trace=trace, packet_id=package_id,
                        name="opencode_server_command.txt",
                        content=self._adapter._redactor.redact_string(server_cmd_str),
                        kind="opencode_server_command",
                    )
                    if server_cmd_ref:
                        all_refs.append(server_cmd_ref)
                except Exception:
                    pass

            if events and trace:
                events.emit(trace=trace, event="packet.opencode_server_start_started",
                            stage="opencode_run", component="opencode_adapter",
                            status="started",
                            artifact_refs=[server_cmd_ref] if server_cmd_ref else None)

            server_state = await sm.ensure_running()

            # Early return on failure — no artifacts, only failure event
            if server_state.status == OpenCodeServerStatus.FAILED:
                if events and trace:
                    events.emit(trace=trace, event="packet.opencode_server_start_failed",
                                stage="opencode_run", component="opencode_adapter",
                                status="failed",
                                message=server_state.failure_summary or "server start failed")
                return _map_adapter_result(
                    _make_failed_result(contract, early_failure_code=server_state.failure_code or
                                        AgentRuntimeFailureCode.AGENT_OPENCODE_SERVER_NOT_RUNNING,
                                        early_failure_summary=server_state.failure_summary or "server not running"),
                    request,
                )
            if server_state.status == OpenCodeServerStatus.UNHEALTHY:
                if events and trace:
                    events.emit(trace=trace, event="packet.opencode_server_start_failed",
                                stage="opencode_run", component="opencode_adapter",
                                status="failed",
                                message=server_state.failure_summary or "server unhealthy")
                return _map_adapter_result(
                    _make_failed_result(contract, early_failure_code=AgentRuntimeFailureCode.AGENT_OPENCODE_SERVER_UNHEALTHY,
                                        early_failure_summary=server_state.failure_summary or "server unhealthy"),
                    request,
                )

            # Server state artifact
            state_ref = None
            if trace and store:
                try:
                    state_ref = store.write_packet_json(
                        trace=trace, packet_id=package_id,
                        name="opencode_server_state.json",
                        payload=self._adapter._redactor.redact_payload(server_state.model_dump()),
                        kind="opencode_server_state",
                    )
                    if state_ref:
                        all_refs.append(state_ref)
                except Exception:
                    pass

            # Healthcheck + artifact
            if events and trace:
                events.emit(trace=trace, event="packet.opencode_server_healthcheck_started",
                            stage="opencode_run", component="opencode_adapter",
                            status="started")
            health = await sm.healthcheck()
            if events and trace:
                events.emit(trace=trace, event="packet.opencode_server_healthcheck_completed",
                            stage="opencode_run", component="opencode_adapter",
                            status="completed",
                            payload={"ok": health.ok, "latency_ms": health.latency_ms})

            health_ref = None
            if trace and store:
                try:
                    health_ref = store.write_packet_json(
                        trace=trace, packet_id=package_id,
                        name="opencode_server_health.json",
                        payload=self._adapter._redactor.redact_payload(health.model_dump()),
                        kind="opencode_server_health",
                    )
                    if health_ref:
                        all_refs.append(health_ref)
                except Exception:
                    pass

            # Server log tail artifact
            log_tail_ref = None
            if trace and store:
                try:
                    log_path = Path(getattr(settings, "opencode_server_log_path", ".grace/opencode-server.log"))
                    if log_path.exists():
                        tail_lines = log_path.read_text(encoding="utf-8").split("\n")[-50:]
                        log_content = "\n".join(tail_lines)
                        log_tail_ref = store.write_packet_text(
                            trace=trace, packet_id=package_id,
                            name="opencode_server_log_tail.txt",
                            content=self._adapter._redactor.redact_string(log_content),
                            kind="opencode_server_log_tail",
                        )
                        if log_tail_ref:
                            all_refs.append(log_tail_ref)
                except Exception:
                    pass

            # Server event: reused or start_completed
            if events and trace:
                if server_state.reused:
                    events.emit(trace=trace, event="packet.opencode_server_reused",
                                stage="opencode_run", component="opencode_adapter",
                                status="completed",
                                artifact_refs=[r for r in (state_ref, health_ref, log_tail_ref) if r] or None)
                else:
                    events.emit(trace=trace, event="packet.opencode_server_start_completed",
                                stage="opencode_run", component="opencode_adapter",
                                status="completed",
                                artifact_refs=[r for r in (state_ref, health_ref, log_tail_ref) if r] or None)

            # Attach command
            run_cmd = self._adapter._attach_cmd_builder.build(contract, server_url)
            if events and trace:
                events.emit(trace=trace, event="packet.opencode_attach_command_built",
                            stage="opencode_run", component="opencode_adapter",
                            status="completed")

        # ── 2. Write command.txt before the process ────────────────────
        cmd_ref = None
        if trace and store:
            try:
                if run_cmd is None:
                    run_cmd = self._adapter._cmd_builder.build(contract)
                raw_cmd = " ".join(run_cmd)
                redacted_cmd = self._adapter._redactor.redact_string(raw_cmd)
                cmd_ref = store.write_packet_text(
                    trace=trace, packet_id=package_id,
                    name="command.txt", content=redacted_cmd, kind="opencode_command",
                )
                if cmd_ref:
                    all_refs.append(cmd_ref)
            except Exception:
                pass

        # ── 3. Emit lifecycle: command built + process started ─────────
        if events and trace:
            events.emit(trace=trace, event="packet.opencode_command_built",
                        stage="opencode_run", component="opencode_adapter",
                        status="completed",
                        artifact_refs=[cmd_ref] if cmd_ref else None)
            events.emit(trace=trace, event="packet.opencode_process_started",
                        stage="opencode_run", component="opencode_adapter",
                        status="started")

        # ── 4. Run the adapter (pass prebuilt cmd if serve_attach) ─────
        if run_cmd is not None:
            adapter_result = await self._adapter.run(contract, prompt, cmd=run_cmd)
        else:
            adapter_result = await self._adapter.run(contract, prompt)

        # ── 5. Write remaining artifacts after the process ─────────────
        stdout_ref = None
        stderr_ref = None
        events_ref = None
        result_ref = None

        if trace and store:
            try:
                redacted_prompt = self._adapter._redactor.redact_string(prompt)
                r = store.write_packet_text(
                    trace=trace, packet_id=package_id,
                    name="prompt.txt", content=redacted_prompt, kind="opencode_prompt",
                )
                if r:
                    all_refs.append(r)
            except Exception:
                _log.warn("write_prompt_failed")

            if adapter_result.stdout:
                try:
                    redacted = self._adapter._redactor.redact_string(adapter_result.stdout)
                    r = store.write_packet_text(
                        trace=trace, packet_id=package_id,
                        name="agent_stdout.txt", content=redacted, kind="opencode_stdout",
                    )
                    if r:
                        all_refs.append(r)
                        stdout_ref = r
                except Exception:
                    _log.warn("write_stdout_failed")

            if adapter_result.stderr:
                try:
                    redacted = self._adapter._redactor.redact_string(adapter_result.stderr)
                    r = store.write_packet_text(
                        trace=trace, packet_id=package_id,
                        name="agent_stderr.txt", content=redacted, kind="opencode_stderr",
                    )
                    if r:
                        all_refs.append(r)
                        stderr_ref = r
                except Exception:
                    _log.warn("write_stderr_failed")

            if adapter_result.raw_events:
                try:
                    lines = "\n".join(
                        json.dumps(self._adapter._redactor.redact_payload(ev), ensure_ascii=False)
                        for ev in adapter_result.raw_events
                    )
                    r = store.write_packet_text(
                        trace=trace, packet_id=package_id,
                        name="raw_opencode_events.jsonl", content=lines, kind="opencode_events",
                    )
                    if r:
                        all_refs.append(r)
                        events_ref = r
                except Exception:
                    _log.warn("write_events_failed")

            try:
                redacted = self._adapter._redactor.redact_payload(adapter_result.model_dump())
                r = store.write_packet_json(
                    trace=trace, packet_id=package_id,
                    name="adapter_result.json", payload=redacted, kind="opencode_result",
                )
                if r:
                    all_refs.append(r)
                    result_ref = r
            except Exception:
                _log.warn("write_result_failed")

        # ── 7. Emit per-artifact lifecycle events ──────────────────────
        if events and trace:
            if stdout_ref:
                events.emit(trace=trace, event="packet.opencode_stdout_captured",
                            stage="opencode_run", component="opencode_adapter",
                            status="completed",
                            artifact_refs=[stdout_ref])
            if stderr_ref:
                events.emit(trace=trace, event="packet.opencode_stderr_captured",
                            stage="opencode_run", component="opencode_adapter",
                            status="completed",
                            artifact_refs=[stderr_ref])

            if events_ref:
                events.emit(trace=trace, event="packet.opencode_event_received",
                            stage="opencode_run", component="opencode_adapter",
                            status="completed",
                            payload={"event_count": len(adapter_result.raw_events)})

            if result_ref:
                events.emit(trace=trace, event="packet.opencode_adapter_result_mapped",
                            stage="opencode_run", component="opencode_adapter",
                            status="completed",
                            artifact_refs=[result_ref])

            # ── 8. Final lifecycle event ──────────────────────────────
            if adapter_result.ok:
                events.emit(trace=trace, event="packet.opencode_process_completed",
                            stage="opencode_run", component="opencode_adapter",
                            status="completed", duration_ms=adapter_result.duration_ms,
                            artifact_refs=all_refs if all_refs else None)
            else:
                events.emit(trace=trace, event="packet.opencode_process_failed",
                            stage="opencode_run", component="opencode_adapter",
                            status="failed", message=adapter_result.failure_summary or "",
                            duration_ms=adapter_result.duration_ms,
                            artifact_refs=all_refs if all_refs else None)

        return _map_adapter_result(adapter_result, request)

    async def cancel(self, request: ExecutionRequest) -> None:
        pass


def _build_full_prompt(request: ExecutionRequest) -> str:
    """Build prompt from materialized packet file + scope/frozen skeleton."""
    prompts: list[str] = []

    session_dir = request.session_dir
    if session_dir:
        packet_file = Path(session_dir) / "packets" / request.packet_id / "EXECUTION_PACKET.md"
        if packet_file.exists():
            try:
                prompts.append(packet_file.read_text(encoding="utf-8"))
            except Exception:
                pass

    spec = request.spec or {}
    scope = spec.get("allowed_write_scope") or request.scope_paths or []
    frozen = spec.get("frozen_scope") or []
    if scope or frozen:
        lines = []
        if not prompts:
            lines.append(f"# Packet: {request.packet_id}")
            lines.append("")
        if scope:
            lines.append("## Allowed scope")
            for s in scope:
                lines.append(f"- {s}")
        if frozen:
            lines.append("## Frozen scope — do NOT modify")
            for s in frozen:
                lines.append(f"- {s}")
        if lines:
            prompts.append("\n".join(lines))

    if not prompts:
        return f"# Packet: {request.packet_id}\n\nExecute the required changes."

    return "\n\n".join(prompts)


def _make_failed_result(contract: AgentRuntimeContract,
                         early_failure_code: str,
                         early_failure_summary: str) -> AgentExecutionAdapterResult:
    return AgentExecutionAdapterResult(
        ok=False, adapter="opencode", command=[],
        cwd=contract.worktree_root, duration_ms=0,
        failure_code=early_failure_code,
        failure_stage="opencode_server_setup",
        failure_summary=early_failure_summary,
    )


def _map_adapter_result(ar: AgentExecutionAdapterResult, request: ExecutionRequest) -> ExecutionResult:
    evidence: dict = {}
    if ar.failure_code:
        evidence["failure_code"] = ar.failure_code
        evidence["failure_stage"] = ar.failure_stage or "opencode_run"
        evidence["failure_summary"] = ar.failure_summary or ""
    if ar.session_id:
        evidence["session_id"] = ar.session_id
    if ar.raw_events:
        evidence["opencode_events"] = ar.raw_events

    errors = []
    if ar.failure_summary:
        errors.append(ar.failure_summary)

    return ExecutionResult(
        accepted=ar.accepted,
        domain_status="accepted" if ar.accepted else "failed",
        worktree_path=Path(request.worktree_path) if request.worktree_path else Path(ar.cwd),
        branch_name=request.branch_name or "",
        commit_sha="",
        stdout=ar.stdout or "",
        stderr=ar.stderr or "",
        duration_ms=ar.duration_ms,
        evidence=evidence,
        reason=ar.failure_summary or "",
        errors=errors,
        model=ar.model or request.executor.get("model", "") if request.executor else "",
        command_preview=list(ar.command) if ar.command else [],
        prompt="",
    )
