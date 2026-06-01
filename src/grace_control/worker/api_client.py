# ############################################################################
# AI_HEADER: api_client
# ROLE: HTTP client for worker to communicate with GRACE Control Plane API.
# ############################################################################

# START_MODULE_CONTRACT
# purpose: Provide async HTTP methods for worker operations (register, heartbeat, claim, release).
# inputs: base_url, worker_id, packet_id, status, result.
# returns: JSON responses or None (no packets available).
# side_effects: HTTP requests to API server.
# emitted_logs: None.
# error_behavior: httpx.HTTPStatusError propagates to caller.
# END_MODULE_CONTRACT

from __future__ import annotations

import httpx
from pydantic import BaseModel


class PacketClaim(BaseModel):
    packet_id: str
    spec: dict
    lease_id: int
    expires_at: str


class WorkerAPIClient:
    def __init__(self, base_url: str = "http://localhost:8042"):
        self.client = httpx.AsyncClient(base_url=base_url, timeout=30.0)

    async def register(self, worker_id: str) -> dict:
        r = await self.client.post("/api/workers/register", json={"worker_id": worker_id})
        r.raise_for_status()
        return r.json()

    async def heartbeat(self, worker_id: str) -> dict:
        r = await self.client.post("/api/workers/heartbeat", json={"worker_id": worker_id})
        r.raise_for_status()
        return r.json()

    async def claim_packet(self, worker_id: str) -> PacketClaim | None:
        try:
            r = await self.client.post("/api/packets/claim", json={"worker_id": worker_id})
            r.raise_for_status()
            return PacketClaim(**r.json()["data"])
        except httpx.HTTPStatusError as e:
            if e.response.status_code == 404:
                return None
            raise

    async def release_packet(self, packet_id: str, worker_id: str, status: str, result: dict) -> dict:
        r = await self.client.post(f"/api/packets/{packet_id}/release", json={
            "worker_id": worker_id, "status": status, "result": result,
        })
        r.raise_for_status()
        return r.json()

    async def close(self):
        await self.client.aclose()

    async def merge_packet(self, packet_id: str, commit_sha: str = "", worktree_path: str = "", branch_name: str = "") -> dict:
        r = await self.client.post(f"/api/packets/{packet_id}/merge", json={
            "commit_sha": commit_sha, "worktree_path": worktree_path, "branch_name": branch_name,
        })
        r.raise_for_status()
        return r.json()
