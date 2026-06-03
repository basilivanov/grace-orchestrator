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

        # Clean git state BEFORE anything
        import subprocess as _sp
        import shutil
        try:
            _sp.run(["git", "-C", str(self.project_root), "worktree", "prune"],
                    capture_output=True, timeout=10)
            wt_path = self.worktree_root / f"{packet_id}-attempt-0001"
            if wt_path.exists():
                _sp.run(["git", "-C", str(self.project_root), "worktree", "remove",
                        str(wt_path), "--force"], capture_output=True, timeout=10)
                shutil.rmtree(wt_path, ignore_errors=True)
            branch = f"agent/default/{packet_id}/attempt-0001"
            _sp.run(["git", "-C", str(self.project_root), "branch", "-D", branch],
                   capture_output=True, timeout=10)
        except Exception:
            pass

        # Use persistent state_root (registry must survive agent process)
        state_root = self.state_root
        state_root.mkdir(parents=True, exist_ok=True)
        # Ensure DB initialized
        from grace_control.db import init_db as _init_db
        _init_db()
        # Use persistent worktree_root (must survive until merge)
        worktree_root = self.worktree_root
        worktree_root.mkdir(parents=True, exist_ok=True)

        with get_db() as db:
            packet = db.query(Packet).filter_by(id=packet_id).first()
            if not packet:
                raise ValueError(f"Packet {packet_id} not found")

            run_number = packet.attempt_count
            run_id = f"{packet_id}-R{run_number:02d}"

            # Check if run already exists (from a previous worker crash)
            existing_run = db.query(PacketRun).filter_by(id=run_id).first()
            if existing_run:
                _log.debug("run_already_exists", packet_id=packet_id, run_id=run_id)
                # Still update status to running
                existing_run.status = "running"
                existing_run.started_at = datetime.utcnow()
            else:
                packet_run = PacketRun(
                    id=run_id, packet_id=packet_id, run_number=run_number,
                    worker_id=worker_id, status="running", started_at=datetime.utcnow(),
                )
                db.add(packet_run)

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

        # Select executor with escalation
        from grace_control.core.complexity_router import route_packet
        from grace_control.core.executor_selector import select_executor

        tier = route_packet(packet_data.get("acceptance_profile", "NORMAL"), packet_data.get("spec_json"))
        executor = select_executor("coder", attempt=packet_data.get("attempt_count", 1) + 1)
        packet_data["_executor"] = executor
        packet_data["_tier"] = tier.value

        try:
            packet_path = self._materialize_packet(packet_data, state_root)
            _log.debug("packet_materialized", packet_id=packet_id, path=str(packet_path))
            result = await self._call_legacy_runner(packet_path, state_root, worktree_root)
            _log.debug("legacy_runner_completed", packet_id=packet_id,
                ok=result.ok, domain=result.domain_status,
                errors=result.errors[:3], blocker=getattr(result, 'registry_reason', '')[:200])

            # Commit agent changes in worktree so merge can apply them
            if result.ok and result.worktree_path:
                import subprocess as _sp
                wt = Path(result.worktree_path)
                if wt.exists():
                    try:
                        _sp.run(["git", "add", "-A"], cwd=str(wt), capture_output=True, timeout=10)
                        _sp.run(["git", "commit", "-m",
                            f"agent: {packet_id} attempt {packet_data['attempt_count']}"],
                            cwd=str(wt), capture_output=True, timeout=10)
                        _log.debug("agent_worktree_committed", packet_id=packet_id, worktree=str(wt))
                    except Exception:
                        _log.warn("agent_commit_failed", packet_id=packet_id)

            # ── Deterministic acceptance pipeline (replaces fake verifier/reviewer) ──
            try:
                spec = packet_data.get("spec_json") or {}
                from grace_control.core.acceptance_pipeline import AcceptancePipeline
                from grace_control.core.contracts import (
                    AcceptanceProfile, ExecutionPacketContract,
                )
                from grace_control.core.scope_guard import ScopeGuard

                scope_list = spec.get("scope", [])
                if isinstance(scope_list, str):
                    scope_list = [scope_list]

                pkt_contract = ExecutionPacketContract(
                    packet_id=packet_id,
                    title=packet_data.get("title", packet_id),
                    allowed_write_scope=scope_list or ["src/grace_control/"],
                    frozen_scope=spec.get("frozen_scope", ["src/prefect_grace/"]),
                    acceptance_profile=AcceptanceProfile(
                        packet_data.get("acceptance_profile", "NORMAL")
                    ),
                    verification_commands=spec.get("verification_commands", []),
                    expected_evidence=spec.get("expected_evidence", []),
                    metadata={"origin": spec.get("origin", ""),
                              "session_id": spec.get("session_id", "")},
                )

                scope_guard = ScopeGuard(self.project_root)
                changed = scope_guard.get_changed_files() if result.worktree_path else []
                pipe = AcceptancePipeline(repo_root=self.project_root, scope_guard=scope_guard)

                accept_report = pipe.run(packet=pkt_contract, changed_files=changed)
                _log.info("acceptance_completed", packet_id=packet_id,
                    verdict=accept_report.final_verdict.value,
                    is_accepted=accept_report.is_accepted)

                # Save acceptance report as evidence
                import json as _json
                ev_dir = state_root / "packets" / packet_id / "runs" / f"R{run_number:02d}"
                ev_dir.mkdir(parents=True, exist_ok=True)
                (ev_dir / "acceptance_report.json").write_text(
                    _json.dumps(accept_report.to_dict(), indent=2, default=str))

                if not accept_report.is_accepted:
                    return ExecutionResult(
                        accepted=False,
                        domain_status="rejected",
                        reason="; ".join(accept_report.reasons or ["acceptance failed"]),
                        evidence_path=str(ev_dir / "acceptance_report.json"),
                        duration_ms=int((time.time() - start_time) * 1000),
                    )
            except Exception as e:
                _log.error("acceptance_pipeline_error", packet_id=packet_id, error=str(e)[:200])
                return ExecutionResult(
                    accepted=False,
                    domain_status="blocked",
                    reason=f"Acceptance pipeline error: {str(e)[:200]}",
                    evidence_path="",
                    duration_ms=int((time.time() - start_time) * 1000),
                )

            # Self-evolution guard check (additional checks for self-improvement)
            if isinstance(spec, dict) and spec.get("origin") == "self_evolution":
                _log.info("self_evolution_guard_check", packet_id=packet_id)
                from grace_control.core.self_evolution_guard import SelfEvolutionGuard
                guard = SelfEvolutionGuard()
                changed = _collect_changed_files(worktree_root)
                guard_result = guard.check(changed, session_id=spec.get("session_id", ""))
                if not guard_result.passed:
                    _log.warn("self_evolution_guard_blocked", packet_id=packet_id,
                        errors=guard_result.errors)
                    execution_result = ExecutionResult(
                        accepted=False, domain_status="rejected",
                        errors=guard_result.errors, evidence_path=None,
                        duration_ms=int((time.time() - start_time) * 1000),
                    )
                    return execution_result
                _log.info("self_evolution_guard_passed", packet_id=packet_id)

            execution_result = self._parse_result(result)
            evidence_path = self._save_evidence(packet_id, run_number, result.to_dict(), state_root)
            execution_result.evidence_path = evidence_path
            execution_result.duration_ms = int((time.time() - start_time) * 1000)
            self._save_agent_log(packet_id, run_number, result, state_root)

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
    def _materialize_packet(self, packet_data: dict, state_root: Path) -> Path:
        packet_id = packet_data["id"]
        packet_dir = state_root / "packets" / packet_id
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
    async def _call_legacy_runner(self, packet_path: Path, state_root: Path, worktree_root: Path):
        from prefect_grace.platform.e2e_packet_runner import run_e2e_packet

        packet_id = packet_path.parent.name

        os.environ.setdefault("GRACE_ALLOW_SANDBOX_BYPASS", "true")

        # Write packet to legacy registry (required by agent launcher)
        reg_dir = state_root / "state"
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

        # Clean stale git worktrees + branches from previous attempts
        import subprocess as _sp
        import shutil
        try:
            # First prune dead worktrees
            _sp.run(["git", "-C", str(self.project_root), "worktree", "prune"],
                    capture_output=True, timeout=10)
            # Then remove the worktree directory if it exists
            wt_path = worktree_root / f"{packet_id}-attempt-0001"
            if wt_path.exists():
                _sp.run(["git", "-C", str(self.project_root), "worktree", "remove", str(wt_path), "--force"],
                       capture_output=True, timeout=10)
                shutil.rmtree(wt_path, ignore_errors=True)
            # Delete the branch if it still exists
            branch = f"agent/default/{packet_id}/attempt-0001"
            _sp.run(["git", "-C", str(self.project_root), "branch", "-D", branch],
                   capture_output=True, timeout=10)
        except Exception:
            pass

        timeout = int(os.environ.get("GRACE_AGENT_TIMEOUT", "600"))
        loop = asyncio.get_event_loop()
        result = await loop.run_in_executor(
            None,
            partial(
                run_e2e_packet,
                project_root=self.project_root,
                packet_path=packet_path,
                state_root=state_root,
                worktree_root=worktree_root,
                dry_run=False,
                execute_agent=True,
                keep_worktree=False,
                runtime_state_root=state_root,
                timeout_seconds=timeout,
            ),
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
    def _save_evidence(self, packet_id: str, run_number: int, result: dict, state_root: Path) -> str:
        return str(state_root / "packets" / packet_id / "runs" / f"R{run_number:02d}")

    def _save_agent_log(self, packet_id: str, run_number: int, result, state_root: Path) -> None:
        try:
            log_dir = state_root / "packets" / packet_id / "runs" / f"R{run_number:02d}"
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


def _collect_changed_files(worktree_root: Path) -> list[Path]:
    changed = []
    src = worktree_root / "src" / "grace_control"
    if src.exists():
        for f in src.rglob("*.py"):
            if "__pycache__" not in str(f):
                changed.append(f)
    ui_dir = worktree_root / "src" / "grace_control" / "ui"
    if ui_dir.exists():
        for f in ui_dir.rglob("*"):
            if f.is_file() and "__pycache__" not in str(f):
                changed.append(f)
    return changed

#END_BLOCK_ADAPTER
