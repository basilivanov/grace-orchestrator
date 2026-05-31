# ############################################################################
# AI_HEADER: worker
# ROLE: Worker loop — claim→execute→release with heartbeat.
# ############################################################################

from __future__ import annotations

import asyncio
import uuid
from pathlib import Path

from grace_control.adapters.packet_executor import PacketExecutionAdapter
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

        self.executor = PacketExecutionAdapter(
            project_root=project_root or Path.cwd(),
            state_root=state_root or Path.cwd() / ".grace",
            worktree_root=worktree_root or Path.cwd() / ".grace/worktrees",
        )

    async def start(self):
        await self.api.register(self.worker_id)
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

    async def _main_loop(self):
        while self.running:
            try:
                claim = await self.api.claim_packet(self.worker_id)
                if not claim:
                    await asyncio.sleep(5)
                    continue

                result = await self.executor.execute(claim.packet_id, self.worker_id)
                status = "accepted" if result.accepted else "rejected"
                await self.api.release_packet(claim.packet_id, self.worker_id, status, result.model_dump())

            except Exception:
                await asyncio.sleep(10)

    async def _heartbeat_loop(self):
        while self.running:
            try:
                await self.api.heartbeat(self.worker_id)
            except Exception:
                pass
            await asyncio.sleep(self.heartbeat_interval)


async def main():
    worker = Worker()
    await worker.start()


if __name__ == "__main__":
    asyncio.run(main())
