# ############################################################################
# AI_HEADER: worker
# ROLE: Worker loop — claim→execute→release with heartbeat and full observability.
# ############################################################################

from __future__ import annotations

import asyncio
import os
import uuid
import traceback
from pathlib import Path

from grace_control.adapters.packet_executor import PacketExecutionAdapter, ExecutionResult
from grace_control.core.git_context import resolve_git_execution_context, GitExecutionContext
from grace_control.core.structured_logger import GraceLogger, trace_context
from grace_control.worker.api_client import WorkerAPIClient


def release_status_from_result(result: ExecutionResult) -> str:
    if result.accepted:
        return "accepted"
    if result.domain_status == "blocked":
        return "blocked"
    return "rejected"


class Worker:
    def __init__(
        self,
        worker_id: str | None = None,
        api_url: str | None = None,
        heartbeat_interval: int = 30,
        project_root: Path | None = None,
        state_root: Path | None = None,
        worktree_root: Path | None = None,
        git_context: GitExecutionContext | None = None,
    ):
        from grace_control.config.settings import settings as _settings
        self.worker_id = worker_id or f"worker-{uuid.uuid4().hex[:8]}"
        self.api = WorkerAPIClient(api_url or _settings.api_url)
        self.heartbeat_interval = heartbeat_interval
        self.running = False
        self.log = GraceLogger("worker")

        self._git_context = git_context or resolve_git_execution_context(
            control_plane_root=project_root,
            target_repo_root=project_root,
            runtime_state_root=state_root,
            worktree_root=worktree_root,
        )
        self.log.info("git_context",
            target_repo_root=str(self._git_context.target_repo_root),
            runtime_state_root=str(self._git_context.runtime_state_root),
            worktree_root=str(self._git_context.worktree_root),
            base_ref=self._git_context.base_ref)

        self.executor = PacketExecutionAdapter(
            project_root=self._git_context.target_repo_root,
            state_root=self._git_context.runtime_state_root,
            worktree_root=self._git_context.worktree_root,
        )

    async def start(self):
        self.log.info("worker_starting", worker_id=self.worker_id)
        await self.api.register(self.worker_id)
        self.log.info("worker_registered", worker_id=self.worker_id)
        self.running = True

        heartbeat_task = asyncio.create_task(self._heartbeat_loop())
        try:
            await self._main_loop()
        finally:
            self.running = False
            heartbeat_task.cancel()
            try:
                await heartbeat_task
            except asyncio.CancelledError:
                pass
            await self.api.close()
            self.log.info("worker_stopped", worker_id=self.worker_id)

    async def _main_loop(self):
        from grace_control.config.settings import settings
        agent_timeout = int(os.environ.get(
            "GRACE_AGENT_TIMEOUT", str(settings.agent_timeout_seconds)))
        while self.running:
            claim = None
            try:
                claim = await self.api.claim_packet(self.worker_id)
                if not claim:
                    self.log.debug("no_packets_available", worker_id=self.worker_id)
                    await asyncio.sleep(5)
                    continue

                packet_id = claim.packet_id
                self.log.info("packet_claimed", worker_id=self.worker_id, packet_id=packet_id)

                with trace_context(packet_id):
                    try:
                        self.log.info("execution_started", packet_id=packet_id, timeout_s=agent_timeout)
                        result = await asyncio.wait_for(
                            self.executor.execute(packet_id, self.worker_id),
                            timeout=agent_timeout,
                        )
                        self.log.info("execution_completed",
                            packet_id=packet_id, accepted=result.accepted,
                            domain_status=result.domain_status,
                            duration_ms=result.duration_ms)

                        status = release_status_from_result(result)
                        await self.api.release_packet(packet_id, self.worker_id, status, result.model_dump())
                        self.log.info("packet_released", packet_id=packet_id, status=status)

                        if status == "accepted":
                            target_repo = str(self._git_context.target_repo_root)
                            self.log.info("merging", packet_id=packet_id,
                                worktree=result.worktree_path, branch=result.branch_name,
                                target_repo=target_repo, sha=result.commit_sha[:12])
                            try:
                                await self.api.merge_packet(packet_id,
                                    target_repo_root=target_repo,
                                    worktree_path=result.worktree_path,
                                    branch_name=result.branch_name,
                                    commit_sha=result.commit_sha)
                                self.log.info("merged", packet_id=packet_id)
                            except Exception:
                                self.log.warn("merge_failed_keep_accepted", packet_id=packet_id,
                                    error=traceback.format_exc()[:200])

                        if status == "rejected":
                            self.log.warn("packet_rejected", packet_id=packet_id, reason=result.reason)
                            await self._handle_rejection(packet_id)
                        elif status == "blocked":
                            self.log.warn("packet_blocked", packet_id=packet_id, reason=result.reason)
                            await self._maybe_apply_recovery(packet_id)

                    except asyncio.TimeoutError:
                        self.log.error("execution_timed_out", packet_id=packet_id,
                            timeout_s=agent_timeout)
                        try:
                            await self.api.release_packet(packet_id, self.worker_id, "failed", {"accepted": False, "reason": "timeout"})
                        except Exception:
                            pass
                    except Exception:
                        self.log.error("execution_failed", packet_id=packet_id,
                            error=traceback.format_exc()[:5000])
                        try:
                            already_released = status not in ("", "running")
                        except UnboundLocalError:
                            already_released = False
                        if not already_released:
                            try:
                                await self.api.release_packet(packet_id, self.worker_id, "failed", {"accepted": False})
                                self.log.info("released_as_failed", packet_id=packet_id)
                            except Exception:
                                pass
                    except Exception:
                            self.log.error("release_failed_on_error", packet_id=packet_id)

            except Exception:
                self.log.error("main_loop_error", worker_id=self.worker_id,
                    error=traceback.format_exc()[:500])
                await asyncio.sleep(10)

    async def _handle_rejection(self, packet_id: str):
        from grace_control.services.packet_service import PacketService
        from grace_control.core.state_machine import StateTransitionError
        try:
            await PacketService().retry(packet_id)
            self.log.info("packet_retried", packet_id=packet_id)
        except StateTransitionError as e:
            self.log.warn("max_retries_reached", packet_id=packet_id, error=str(e)[:200])

    async def _maybe_apply_recovery(self, packet_id: str):
        from grace_control.config.settings import settings
        controller_enabled = os.environ.get(
            "GRACE_RECOVERY_CONTROLLER_ENABLED",
            "true" if settings.recovery_controller_enabled else "false",
        ) == "true"
        self.log.info("recovery_check",
            packet_id=packet_id,
            controller_enabled=controller_enabled,
        )
        if not controller_enabled:
            return
        from grace_control.core.recovery_controller import RecoveryController
        ctrl = RecoveryController()
        try:
            decision = await asyncio.wait_for(
                ctrl.evaluate(packet_id, allow_apply=True),
                timeout=30,
            )
            self.log.info("recovery_applied",
                packet_id=packet_id,
                action=decision.action.value,
                reason=decision.reason,
            )
        except Exception as e:
            self.log.error("recovery_apply_failed",
                packet_id=packet_id,
                error=str(e)[:500],
            )

    async def _heartbeat_loop(self):
        while self.running:
            try:
                await self.api.heartbeat(self.worker_id)
                self.log.debug("heartbeat_sent", worker_id=self.worker_id)
            except Exception:
                self.log.warn("heartbeat_failed", worker_id=self.worker_id)
            await asyncio.sleep(self.heartbeat_interval)


async def main():
    worker = Worker()
    await worker.start()


if __name__ == "__main__":
    asyncio.run(main())
