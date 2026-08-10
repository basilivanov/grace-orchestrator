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
    attempt: int
    claimed_attempt: int  # W01: fencing token — required, no default
    feature_id: str = ""
    wave_id: str = ""
    slug: str = ""
    title: str = ""
    description: str = ""
    acceptance_profile: str = ""
    max_attempts: int = 0
    parallel_lease_id: str | None = None
    parallel_expires_at: str | None = None


class WorkerAPIClient:
    def __init__(self, base_url: str = "http://localhost:8042"):
        self.client = httpx.AsyncClient(base_url=base_url, timeout=30.0)
        self._last_lease_error = ""

    @property
    def last_lease_error(self) -> str:
        """Return the typed fencing reason from the latest renewal failure."""
        return self._last_lease_error

    async def register(self, worker_id: str, pid: int | None = None) -> dict:
        payload = {"worker_id": worker_id}
        if pid:
            payload["pid"] = pid
        r = await self.client.post("/api/workers/register", json=payload)
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

    async def retry_packet(self, packet_id: str, worker_id: str) -> dict:
        r = await self.client.post(f"/api/packets/{packet_id}/retry", json={"worker_id": worker_id})
        r.raise_for_status()
        return r.json()

    async def release_packet(
        self,
        packet_id: str,
        worker_id: str,
        status: str,
        result: dict,
        *,
        lease_id: int | None = None,
        claimed_attempt: int | None = None,
    ) -> dict:
        """W01: Release packet with lease fencing tokens."""
        payload = {
            "worker_id": worker_id,
            "status": status,
            "result": result,
        }
        if lease_id is not None:
            payload["lease_id"] = lease_id
        if claimed_attempt is not None:
            payload["claimed_attempt"] = claimed_attempt
        r = await self.client.post(f"/api/packets/{packet_id}/release", json=payload)
        r.raise_for_status()
        return r.json()

    async def renew_lease(
        self,
        packet_id: str,
        worker_id: str,
        lease_id: int,
    ) -> dict | None:
        """W01: Renew active lease. Returns new expires_at or None on failure."""
        self._last_lease_error = ""
        try:
            r = await self.client.post(
                f"/api/packets/{packet_id}/renew-lease",
                json={"worker_id": worker_id, "lease_id": lease_id},
            )
            r.raise_for_status()
            return r.json()
        except httpx.HTTPStatusError as error:
            self._last_lease_error = self._lease_error_from_response(error)
            return None

    # START_FUNCTION_CONTRACT
    # name: renew_parallel_lease
    # purpose: Renew a parallel resource lease retained while an accepted
    #          packet waits for serialized merge.
    # inputs: packet_id, worker_id, parallel_lease_id, claimed_attempt.
    # returns: API response dictionary or None for a rejected renewal.
    # side_effects: HTTP POST to the parallel lease renewal endpoint.
    # emitted_logs: None.
    # error_behavior: Returns None and records a typed fencing reason on HTTP
    #                 409; other HTTP errors propagate.
    # END_FUNCTION_CONTRACT
    async def renew_parallel_lease(
        self,
        packet_id: str,
        worker_id: str,
        parallel_lease_id: str,
        claimed_attempt: int,
    ) -> dict | None:
        self._last_lease_error = ""
        try:
            r = await self.client.post(
                f"/api/packets/{packet_id}/renew-parallel-lease",
                json={
                    "worker_id": worker_id,
                    "parallel_lease_id": parallel_lease_id,
                    "claimed_attempt": claimed_attempt,
                },
            )
            r.raise_for_status()
            return r.json()
        except httpx.HTTPStatusError as error:
            self._last_lease_error = self._lease_error_from_response(error)
            return None

    # START_FUNCTION_CONTRACT
    # name: _lease_error_from_response
    # purpose: Convert an HTTP lease rejection into a stable worker failure
    #          reason without exposing transport-specific text.
    # inputs: error — HTTP status error from the lease endpoint.
    # returns: parallel_lease_lost, stale_lease, or an empty string.
    # side_effects: None.
    # emitted_logs: None.
    # error_behavior: Returns an empty string for non-fencing responses.
    # END_FUNCTION_CONTRACT
    @staticmethod
    def _lease_error_from_response(error: httpx.HTTPStatusError) -> str:
        if error.response.status_code != 409:
            return ""
        try:
            payload = error.response.json()
        except ValueError:
            payload = {}
        detail = payload.get("detail", {}) if isinstance(payload, dict) else {}
        if isinstance(detail, dict) and detail.get("parallel_lease_lost"):
            return "parallel_lease_lost"
        return "stale_lease"

    async def close(self):
        await self.client.aclose()

    # START_FUNCTION_CONTRACT
    # name: merge_packet
    # purpose: Request serialized merge of an accepted packet through the API.
    # inputs: packet_id, target/branch/worker merge metadata, and optional
    #         parallel lease fencing identity.
    # returns: API response dictionary.
    # side_effects: HTTP POST to the packet merge endpoint.
    # emitted_logs: None.
    # error_behavior: Raises the HTTP client's request error for non-success.
    # END_FUNCTION_CONTRACT
    async def merge_packet(
        self,
        packet_id: str,
        *,
        target_repo_root: str = "",
        commit_sha: str = "",
        worktree_path: str = "",
        branch_name: str = "",
        worker_id: str = "",
        parallel_lease_id: str | None = None,
        claimed_attempt: int | None = None,
    ) -> dict:
        r = await self.client.post(f"/api/packets/{packet_id}/merge", json={
            "target_repo_root": target_repo_root,
            "commit_sha": commit_sha,
            "worktree_path": worktree_path,
            "branch_name": branch_name,
            "worker_id": worker_id,
            "parallel_lease_id": parallel_lease_id,
            "claimed_attempt": claimed_attempt,
        })
        r.raise_for_status()
        return r.json()
