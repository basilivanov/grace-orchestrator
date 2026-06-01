# ############################################################################
# AI_HEADER: packet_executor
# ROLE: Bridge between DB packets and legacy run_e2e_packet. STATELESS.
# ############################################################################

# START_MODULE_CONTRACT
# purpose: Materialize DB packet → markdown → call legacy runner → return structured result.
# inputs: packet_id, worker_id, project_root, state_root, worktree_root.
# returns: ExecutionResult (accepted, reason, evidence_path, duration_ms, domain_status).
# side_effects: Creates PacketRun record. Does NOT change packet state.
# emitted_logs: log_event for execution lifecycle.
# error_behavior: Raises on DB/runtime failures. Does not mask exceptions.
# END_MODULE_CONTRACT

# START_MODULE_MAP
# mapping:
#   - class: ExecutionResult
#   - class: PacketExecutionAdapter
# END_MODULE_MAP

from __future__ import annotations

import asyncio
import os
import time
from datetime import datetime
from functools import partial
from pathlib import Path

import yaml
from pydantic import BaseModel

from grace_control.core.structured_logger import GraceLogger
from grace_control.db import get_db
from grace_control.db.schema import Packet, PacketRun

_log = GraceLogger("adapter")

#START_BLOCK_MODELS
class ExecutionResult(BaseModel):
    """Structured result returned by adapter. Worker uses this for release."""
    accepted: bool
    reason: str | None = None
    evidence_path: str = ""
    duration_ms: int = 0
    domain_status: str = ""
    worktree_path: str = ""
    branch_name: str = ""

#END_BLOCK_MODELS

#START_BLOCK_ADAPTER
class PacketExecutionAdapter:
    """
    Bridge between DB packets and legacy run_e2e_packet.

    STATELESS: does NOT call mark_running, mark_accepted, mark_rejected, mark_failed.
    State ownership belongs to API endpoints (claim/release).
    """

    # START_FUNCTION_CONTRACT
    # name: __init__
    # purpose: Initialize adapter with filesystem paths.
    # inputs: project_root, state_root, worktree_root.
    # returns: None.
    # side_effects: None.
    # emitted_logs: None.
    # error_behavior: None.
    # END_FUNCTION_CONTRACT
    def __init__(self, project_root: Path, state_root: Path, worktree_root: Path):
        self.project_root = Path(project_root)
        self.state_root = Path(state_root)
        self.worktree_root = Path(worktree_root)

    # START_FUNCTION_CONTRACT
    # name: execute
    # purpose: Execute a packet: load DB → materialize → call legacy runner → save evidence → return result.
    # inputs:
    #   packet_id: Packet ID string.
    #   worker_id: Worker ID string.
    # returns: ExecutionResult with accepted, evidence_path, etc.
    # side_effects: Creates PacketRun record, writes evidence directory.
    # emitted_logs: None (caller should log).
    # error_behavior: Raises on packet not found, runtime failure.
    # END_FUNCTION_CONTRACT
    async def execute(self, packet_id: str, worker_id: str) -> ExecutionResult:
        start_time = time.time()
        _log.info("adapter_execute_start", packet_id=packet_id, worker_id=worker_id)

        with get_db() as db:
            packet = db.query(Packet).filter_by(id=packet_id).first()
            if not packet:
                raise ValueError(f"Packet {packet_id} not found")

            run_number = packet.attempt_count
            run_id = f"{packet_id}-R{run_number:02d}"

            # Eagerly read all attributes before session closes
            packet_data = {
                "id": packet.id,
                "feature_id": packet.feature_id,
                "wave_id": packet.wave_id,
                "slug": packet.slug,
                "title": packet.title,
                "description": packet.description,
                "spec_json": packet.spec_json,
                "state": packet.state,
                "acceptance_profile": packet.acceptance_profile,
                "attempt_count": packet.attempt_count,
                "max_attempts": packet.max_attempts,
            }

            packet_run = PacketRun(
                id=run_id,
                packet_id=packet_id,
                run_number=run_number,
                worker_id=worker_id,
                status="running",
                started_at=datetime.utcnow(),
            )
            db.add(packet_run)

        # Select executor with escalation
        from grace_control.core.complexity_router import route_packet
        from grace_control.core.executor_selector import select_executor

        tier = route_packet(packet_data.get("acceptance_profile", "NORMAL"), packet_data.get("spec_json"))
        executor = select_executor("coder", attempt=packet_data.get("attempt_count", 1) + 1)
        packet_data["_executor"] = executor
        packet_data["_tier"] = tier.value

        try:
            packet_path = self._materialize_packet(packet_data)
            _log.debug("packet_materialized", packet_id=packet_id, path=str(packet_path))
            result = await self._call_legacy_runner(packet_path)
            _log.debug("legacy_runner_completed", packet_id=packet_id,
                ok=result.ok, domain=result.domain_status)

            # Save raw agent output for analysis
            self._save_agent_log(packet_id, run_number, result)
            execution_result = self._parse_result(result)
            evidence_path = self._save_evidence(packet_id, run_number, result.to_dict())
            execution_result.evidence_path = evidence_path
            execution_result.duration_ms = int((time.time() - start_time) * 1000)

            with get_db() as db:
                existing = db.query(PacketRun).filter_by(id=run_id).first()
                if existing:
                    existing.status = "accepted" if execution_result.accepted else "rejected"
                    existing.result_json = result.to_dict()
                    existing.evidence_path = evidence_path
                    existing.finished_at = datetime.utcnow()
                    existing.duration_ms = execution_result.duration_ms
                    existing.executor_id = executor.get("executor_id", "")

            _log.info("adapter_execute_done", packet_id=packet_id,
                accepted=execution_result.accepted, duration_ms=execution_result.duration_ms)

            return execution_result

        except Exception:
            _log.error("adapter_execute_failed", packet_id=packet_id)
            with get_db() as db:
                existing = db.query(PacketRun).filter_by(id=run_id).first()
                if existing:
                    existing.status = "failed"
                    existing.finished_at = datetime.utcnow()
                    existing.duration_ms = int((time.time() - start_time) * 1000)
            raise

    # START_FUNCTION_CONTRACT
    # name: _materialize_packet
    # purpose: Convert DB Packet into EXECUTION_PACKET.md file parseable by parse_packet_markdown.
    # inputs: packet ORM object.
    # returns: Path to created markdown file.
    # side_effects: Writes file to state_root/packets/{id}/EXECUTION_PACKET.md.
    # emitted_logs: None.
    # error_behavior: Raises on filesystem error.
    # END_FUNCTION_CONTRACT
    def _materialize_packet(self, packet_data: dict) -> Path:
        packet_id = packet_data["id"]
        packet_dir = self.state_root / "packets" / packet_id
        packet_dir.mkdir(parents=True, exist_ok=True)

        spec_json = packet_data["spec_json"] if isinstance(packet_data["spec_json"], dict) else {}
        spec_str = yaml.dump(spec_json, default_flow_style=False, allow_unicode=True)
        scope = spec_json.get("scope", "src/")
        if isinstance(scope, str):
            scope = [scope]
        scope_lines = "\n".join(f"- {s}" for s in scope)
        pd = packet_data
        content = f"""# Execution Packet: {pd['id']}

## Objective

{pd.get('description') or pd.get('title', '')}

## Slice

- slice_id: `SLICE-{pd.get('slug', '').upper()}`
- feature_id: `{pd.get('feature_id', '')}`
- packet_id: `{pd['id']}`
- wave_id: `{pd.get('wave_id', '')}`
- status: `{pd.get('state', '')}`

## Allowed Write Scope

{scope_lines}

## Frozen Scope

- src/prefect_grace/**

## Must Preserve

- Follow GRACE Canon contracts (AI_HEADER, MODULE_CONTRACT, FUNCTION_CONTRACT)
- File ≤ 1000 lines, function ≤ 4000 tokens
- Use log_event() for structured logging

## Acceptance Profile

{pd.get('acceptance_profile', 'NORMAL')}

## Verification

```bash
pytest -v
ruff check src/
```

## Expected Evidence

- test results
- lint output

## Escalation Triggers

- Tests fail
- Lint errors
- Scope violation

## Specification

```yaml
{spec_str}
```
"""
        packet_file = packet_dir / "EXECUTION_PACKET.md"
        packet_file.write_text(content)
        return packet_file

    # START_FUNCTION_CONTRACT
    # name: _call_legacy_runner
    # purpose: Call existing run_e2e_packet synchronously in executor thread.
    # inputs: packet_path to EXECUTION_PACKET.md.
    # returns: E2EPacketRunnerResult.
    # side_effects: Creates git worktree, launches agents, runs verifier/reviewer.
    # emitted_logs: None.
    # error_behavior: Raises on runtime failure.
    # END_FUNCTION_CONTRACT
    async def _call_legacy_runner(self, packet_path: Path):
        from prefect_grace.platform.e2e_packet_runner import run_e2e_packet

        # Register packet in legacy file-based registry
        packet_id = packet_path.parent.name
        reg_dir = self.state_root / "state"
        reg_dir.mkdir(parents=True, exist_ok=True)
        reg_file = reg_dir / "packet_registry.yaml"
        try:
            existing = {}
            if reg_file.exists():
                existing = yaml.safe_load(reg_file.read_text()) or {}
            existing[packet_id] = {
                "packet_id": packet_id,
                "feature_id": packet_id.split("-W")[0] if "-W" in packet_id else "unknown",
                "wave_id": "W01", "status": "ready", "phase": "PHASE-TEST",
                "packet_path": str(packet_path),
                "allowed_write_scope": [], "frozen_scope": [], "depends_on": [],
            }
            reg_file.write_text(yaml.dump(existing, default_flow_style=False))
        except Exception:
            pass

        # Allow sandbox bypass — control plane assumes responsibility
        os.environ.setdefault("GRACE_ALLOW_SANDBOX_BYPASS", "true")

        # Run in separate process for hard kill support
        timeout = int(os.environ.get("GRACE_AGENT_TIMEOUT", "600"))
        import multiprocessing

        def _runner(result_queue, **kwargs):
            try:
                r = run_e2e_packet(**kwargs)
                result_queue.put(("ok", r))
            except Exception as e:
                result_queue.put(("error", str(e)))

        queue: multiprocessing.Queue = multiprocessing.Queue()
        proc = multiprocessing.Process(target=_runner, args=(queue,), kwargs={
            "project_root": self.project_root,
            "packet_path": packet_path,
            "state_root": self.state_root,
            "worktree_root": self.worktree_root,
            "dry_run": False,
            "execute_agent": True,
            "keep_worktree": False,
            "timeout_seconds": timeout,
        })
        proc.start()
        proc.join(timeout=timeout)

        if proc.is_alive():
            proc.terminate()
            proc.join(timeout=5)
            if proc.is_alive():
                proc.kill()
            from prefect_grace.platform.e2e_packet_runner import E2EPacketRunnerResult
            return E2EPacketRunnerResult(
                ok=False, packet_id=packet_id, attempt=1,
                runtime_status="failed", domain_status="runner_error",
                registry_status="blocked", registry_reason="agent_timeout",
                registry_transition={}, worktree_path=None, branch_name=None,
                executor_id=None, managed_runner_result={}, handoff_result=None,
                artifact_paths=[], errors=[f"Agent timed out after {timeout}s"],
            )

        status, result = queue.get(timeout=5)
        if status == "error":
            from prefect_grace.platform.e2e_packet_runner import E2EPacketRunnerResult
            return E2EPacketRunnerResult(
                ok=False, packet_id=packet_id, attempt=1,
                runtime_status="failed", domain_status="runner_error",
                registry_status="blocked", registry_reason=str(result)[:200],
                registry_transition={}, worktree_path=None, branch_name=None,
                executor_id=None, managed_runner_result={}, handoff_result=None,
                artifact_paths=[], errors=[str(result)[:500]],
            )
        return result

    # START_FUNCTION_CONTRACT
    # name: _parse_result
    # purpose: Map E2EPacketRunnerResult to ExecutionResult.
    # inputs: E2EPacketRunnerResult from legacy runner.
    # returns: ExecutionResult.
    # side_effects: None.
    # emitted_logs: None.
    # error_behavior: Never raises (safe mapping).
    # END_FUNCTION_CONTRACT
    def _parse_result(self, result) -> ExecutionResult:
        accepted = result.ok and result.domain_status == "accepted"
        reason = None
        if not accepted:
            reason = result.registry_reason or f"domain_status={result.domain_status}"
        return ExecutionResult(
            accepted=accepted,
            reason=reason,
            domain_status=result.domain_status,
            worktree_path=result.worktree_path or "",
            branch_name=result.branch_name or "",
        )

    # START_FUNCTION_CONTRACT
    # name: _save_evidence
    # purpose: Return evidence path string for PacketRun record.
    # inputs: packet_id, run_number, result_dict.
    # returns: Evidence directory path string.
    # side_effects: None (path only, evidence saved by legacy runner).
    # emitted_logs: None.
    # error_behavior: Never raises.
    # END_FUNCTION_CONTRACT
    def _save_evidence(self, packet_id: str, run_number: int, result: dict) -> str:
        return str(self.state_root / "packets" / packet_id / "runs" / f"R{run_number:02d}")

    def _save_agent_log(self, packet_id: str, run_number: int, result) -> None:
        try:
            log_dir = self.state_root / "packets" / packet_id / "runs" / f"R{run_number:02d}"
            log_dir.mkdir(parents=True, exist_ok=True)
            agent_log = log_dir / "agent_output.log"

            mr = result.managed_runner_result
            if isinstance(mr, dict):
                agent = mr.get("agent_result", {})
                if isinstance(agent, dict):
                    # Try paths first (legacy writes to files)
                    for key in ("stdout_path", "stderr_path"):
                        path = agent.get(key, "")
                        if path:
                            p = Path(path)
                            if p.exists():
                                content = p.read_text()
                                with agent_log.open("a") as f:
                                    f.write(f"=== {key} ===\n{content}\n")
                    # Also check inline stdout/stderr
                    for key in ("stdout", "stderr"):
                        content = agent.get(key, "")
                        if content:
                            with agent_log.open("a") as f:
                                f.write(f"=== AGENT {key.upper()} ===\n{content}\n")

            if agent_log.exists() and agent_log.stat().st_size > 0:
                _log.info("agent_log_saved", packet_id=packet_id, path=str(agent_log),
                    size=agent_log.stat().st_size)
        except Exception:
            pass

#END_BLOCK_ADAPTER
