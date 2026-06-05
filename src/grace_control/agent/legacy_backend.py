# ############################################################################
# AI_HEADER: legacy_backend
# ROLE: Adapter wrapping prefect_grace — the ONLY file allowed to import it.
# ############################################################################

# START_MODULE_CONTRACT
# purpose: Wrap prefect_grace.platform.e2e_packet_runner.run_e2e_packet behind
#          the ExecutionBackend Protocol so packet_executor does not depend on
#          legacy code directly. This is the boundary of the legacy isolation.
# inputs: ExecutionRequest.
# returns: ExecutionResult with accepted/domain_status from legacy E2E result.
# side_effects: Spawns subprocess via legacy codex_launcher; writes packet_registry.yaml.
# emitted_logs: legacy_run_start, legacy_run_done, legacy_run_failed.
# error_behavior: Never raises; failures encoded in result.accepted=False.
# END_MODULE_CONTRACT

# START_MODULE_MAP
# mapping:
#   - class: LegacyPrefectBackend
# END_MODULE_MAP

from __future__ import annotations

import asyncio
import os
from functools import partial
from pathlib import Path

from grace_control.agent.backend import ExecutionBackend, ExecutionRequest, ExecutionResult
from grace_control.core.structured_logger import GraceLogger

_log = GraceLogger("legacy_backend")

# The single, sanctioned import of legacy code in the entire new control plane.
from prefect_grace.platform.e2e_packet_runner import run_e2e_packet  # noqa: E402


class LegacyPrefectBackend:
    """Wraps the legacy prefect_grace E2E runner behind the new ExecutionBackend protocol.

    Behavior matches the previous _call_legacy_runner implementation:
    1. Set GRACE_ALLOW_SANDBOX_BYPASS=true
    2. Invoke run_e2e_packet via executor
    3. Apply hard wall-clock cap = timeout_s + 30s
    4. Map E2EPacketRunnerResult to ExecutionResult
    """

    HARD_TIMEOUT_BUFFER = 30

    async def run(self, request: ExecutionRequest) -> ExecutionResult:
        os.environ.setdefault("GRACE_ALLOW_SANDBOX_BYPASS", "true")
        _log.info("legacy_run_start", packet_id=request.packet_id,
            executor=request.executor.get("executor_id", "?"),
            timeout_s=request.timeout_s)

        loop = asyncio.get_event_loop()
        hard_timeout = request.timeout_s + self.HARD_TIMEOUT_BUFFER

        try:
            e2e_result = await asyncio.wait_for(
                loop.run_in_executor(
                    None,
                    partial(
                        run_e2e_packet,
                        project_root=Path(request.worktree_path).parent.parent,
                        packet_path=_resolve_packet_path(request),
                        state_root=_resolve_state_root(request),
                        worktree_root=Path(request.worktree_path).parent,
                        dry_run=False,
                        execute_agent=True,
                        attempt=_extract_attempt(request),
                        base_ref="HEAD",
                        keep_worktree=True,
                        runtime_state_root=_resolve_state_root(request),
                        timeout_seconds=request.timeout_s,
                    ),
                ),
                timeout=hard_timeout,
            )
        except asyncio.TimeoutError:
            _log.error("legacy_run_timeout", packet_id=request.packet_id,
                timeout_s=hard_timeout)
            return ExecutionResult(
                accepted=False, domain_status="blocked",
                worktree_path=request.worktree_path, branch_name=request.branch_name,
                commit_sha="", stdout="", stderr="",
                duration_ms=hard_timeout * 1000,
                reason=f"legacy runner exceeded {hard_timeout}s wall-clock timeout",
            )
        except Exception as e:
            _log.error("legacy_run_exception", packet_id=request.packet_id, error=str(e)[:500])
            return ExecutionResult(
                accepted=False, domain_status="failed",
                worktree_path=request.worktree_path, branch_name=request.branch_name,
                commit_sha="", stdout="", stderr="",
                duration_ms=0,
                reason=f"legacy runner exception: {str(e)[:200]}",
            )

        accepted = bool(getattr(e2e_result, "ok", False))
        domain_status = getattr(e2e_result, "domain_status", "unknown")
        worktree_path = Path(getattr(e2e_result, "worktree_path", "") or request.worktree_path)
        branch_name = getattr(e2e_result, "branch_name", "") or request.branch_name
        errors = list(getattr(e2e_result, "errors", []) or [])
        registry_reason = getattr(e2e_result, "registry_reason", "") or ""

        _log.info("legacy_run_done", packet_id=request.packet_id,
            accepted=accepted, domain_status=domain_status)

        return ExecutionResult(
            accepted=accepted,
            domain_status=domain_status,
            worktree_path=worktree_path,
            branch_name=branch_name,
            commit_sha="",
            stdout="",
            stderr="",
            duration_ms=0,
            changed_files=[],
            reason=registry_reason if not accepted else "",
            errors=errors,
            registry_reason=registry_reason,
        )

    async def cancel(self, request: ExecutionRequest) -> None:
        _log.warn("legacy_cancel_noop", packet_id=request.packet_id,
            reason="legacy backend does not support mid-run cancel")


def _resolve_packet_path(request: ExecutionRequest) -> Path:
    """Resolve the EXECUTION_PACKET.md path from session_dir or worktree."""
    if request.session_dir is not None:
        candidate = Path(request.session_dir) / "packets" / request.packet_id / "EXECUTION_PACKET.md"
        if candidate.exists():
            return candidate
    return Path(request.worktree_path) / "EXECUTION_PACKET.md"


def _resolve_state_root(request: ExecutionRequest) -> Path:
    if request.session_dir is not None:
        return Path(request.session_dir)
    return Path(request.worktree_path).parent.parent / "grace_state"


def _extract_attempt(request: ExecutionRequest) -> int:
    return int(request.spec.get("attempt_count", 1))
