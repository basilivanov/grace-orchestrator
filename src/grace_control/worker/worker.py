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

from grace_control.adapters.packet_executor import PacketExecutionAdapter
from grace_control.core.structured_logger import GraceLogger, trace_context
from grace_control.worker.api_client import WorkerAPIClient


class Worker:
    def __init__(
        self,
        worker_id: str | None = None,
        api_url: str = "http://localhost:8042",
        heartbeat_interval: int = 30,
        project_root: Path | None = None,
        state_root: Path | None = None,
        worktree_root: Path | None = None,
    ):
        self.worker_id = worker_id or f"worker-{uuid.uuid4().hex[:8]}"
        self.api = WorkerAPIClient(api_url)
        self.heartbeat_interval = heartbeat_interval
        self.running = False
        self.log = GraceLogger("worker")

        self.executor = PacketExecutionAdapter(
            project_root=project_root or Path.cwd(),
            state_root=state_root or Path.cwd() / ".grace",
            worktree_root=worktree_root or Path.cwd() / ".grace/worktrees",
        )

    async def start(self):
        from grace_control.db import init_db
        init_db()  # ensure DB session is available in this process
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
        agent_timeout = int(os.environ.get("GRACE_AGENT_TIMEOUT", "600"))
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

                        status = "accepted" if result.accepted else "rejected"
                        await self.api.release_packet(packet_id, self.worker_id, status, result.model_dump())
                        self.log.info("packet_released", packet_id=packet_id, status=status)

                        if status == "accepted":
                            self.log.info("merging", packet_id=packet_id,
                                worktree=result.worktree_path, branch=result.branch_name)
                            await self.api.merge_packet(packet_id,
                                worktree_path=result.worktree_path,
                                branch_name=result.branch_name)
                            self.log.info("merged", packet_id=packet_id)

                        if status == "rejected":
                            self.log.warn("packet_rejected", packet_id=packet_id, reason=result.reason)
                            self._handle_rejection(packet_id)

                    except asyncio.TimeoutError:
                        self.log.error("execution_timed_out", packet_id=packet_id,
                            timeout_s=agent_timeout)
                        try:
                            await self.api.release_packet(packet_id, self.worker_id, "failed", {"accepted": False, "reason": "timeout"})
                        except Exception:
                            pass
                    except Exception:
                        self.log.error("execution_failed", packet_id=packet_id,
                            error=traceback.format_exc()[:500])
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

    def _handle_rejection(self, packet_id: str):
        from grace_control.core.packet_operations import mark_failed, retry_packet
        from grace_control.core.state_machine import StateTransitionError
        try:
            retry_packet(packet_id)
            self.log.info("packet_retried", packet_id=packet_id)
        except StateTransitionError:
            mark_failed(packet_id, "Max retry attempts reached")
            self.log.warn("max_retries_reached", packet_id=packet_id)

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
