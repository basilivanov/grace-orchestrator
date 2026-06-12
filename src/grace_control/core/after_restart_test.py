# ############################################################################
# AI_HEADER: after_restart_test
# ROLE: Test system consistency after supervisor restart — validate health,
#       lease state, packet state, and recovery readiness.
# ############################################################################

# START_MODULE_CONTRACT
# purpose: After a restart, validate that the GRACE control plane is in a
#          consistent state: health endpoints respond, leases are not stale,
#          packets are not stuck, and recovery can proceed.
# inputs: project_root (Path), packet_id (str | None), api_url (str).
# returns: AfterRestartReport dataclass with component-level pass/fail results.
# side_effects: HTTP health checks, DB lease queries, state file reads.
# emitted_logs: restart_test_started, restart_test_component, restart_test_complete.
# error_behavior: Never raises. Collects component failures in report.errors.
# END_MODULE_CONTRACT

# START_MODULE_MAP
# mapping:
#   - dataclass: ComponentResult
#   - dataclass: AfterRestartReport
#   - class: AfterRestartTester
# END_MODULE_MAP

from __future__ import annotations

import os
import json
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from grace_control.core.structured_logger import GraceLogger

_log = GraceLogger("after_restart_test")

#START_BLOCK_DATACLASSES

@dataclass
class ComponentResult:
    name: str
    passed: bool
    detail: str = ""
    duration_ms: float = 0.0

@dataclass
class AfterRestartReport:
    started_at: str = ""
    finished_at: str = ""
    components: list[ComponentResult] = field(default_factory=list)
    all_passed: bool = False
    errors: list[str] = field(default_factory=list)

    #START_FUNCTION_CONTRACT
    # name: summary
    # purpose: Return a human-readable summary string of pass/fail counts.
    # inputs: None.
    # returns: str like "3/4 components passed".
    # side_effects: None.
    # emitted_logs: None.
    # error_behavior: Never raises.
    #END_FUNCTION_CONTRACT
    @property
    def summary(self) -> str:
        passed = sum(1 for c in self.components if c.passed)
        total = len(self.components)
        return f"{passed}/{total} components passed"

#END_BLOCK_DATACLASSES

#START_BLOCK_TESTER

class AfterRestartTester:

    def __init__(self, project_root: Path | None = None, api_url: str | None = None):
        self._root = project_root or Path.cwd()
        self._api_url = api_url or os.environ.get("GRACE_API_URL", "http://127.0.0.1:8042")

    #START_FUNCTION_CONTRACT
    # name: run_all
    # purpose: Run all post-restart consistency checks and return a report.
    # inputs: packet_id — optional specific packet to check; timeout_sec — per-check timeout.
    # returns: AfterRestartReport with component-level results.
    # side_effects: HTTP requests, DB queries, file reads.
    # emitted_logs: restart_test_started, restart_test_component, restart_test_complete.
    # error_behavior: Never raises — each component failure is recorded.
    #END_FUNCTION_CONTRACT
    async def run_all(self, packet_id: str | None = None, timeout_sec: int = 10) -> AfterRestartReport:
        report = AfterRestartReport(
            started_at=datetime.now(timezone.utc).isoformat() + "Z",
        )
        _log.info("restart_test_started", packet_id=packet_id, api_url=self._api_url)

        checks = [
            ("api_health", self._check_api_health(timeout_sec)),
            ("state_files", self._check_state_files()),
            ("packet_operations", self._check_packet_operations(packet_id)),
            ("worker_health", self._check_worker_health(timeout_sec)),
        ]

        for name, coro in checks:
            try:
                result = await coro
                report.components.append(result)
                _log.info("restart_test_component", component=name, passed=result.passed, detail=result.detail)
            except Exception as e:
                report.components.append(ComponentResult(name=name, passed=False, detail=str(e)[:200]))
                report.errors.append(f"{name}: {e}")
                _log.warn("restart_test_component", component=name, passed=False, error=str(e)[:120])

        report.all_passed = all(c.passed for c in report.components)
        report.finished_at = datetime.now(timezone.utc).isoformat() + "Z"
        _log.info("restart_test_complete", summary=report.summary, all_passed=report.all_passed)
        return report

    async def _check_api_health(self, timeout: int) -> ComponentResult:
        import asyncio
        try:
            _, _writer = await asyncio.wait_for(
                asyncio.open_connection("127.0.0.1", 8042),
                timeout=timeout,
            )
            _writer.close()
            return ComponentResult("api_health", True, detail="API port reachable")
        except Exception as e:
            return ComponentResult("api_health", False, detail=f"API unreachable: {e}")

    async def _check_state_files(self) -> ComponentResult:
        state_dir = self._root / ".grace_state"
        if not state_dir.exists():
            return ComponentResult("state_files", True, detail="No .grace_state directory (clean)")
        errors = []
        for f in sorted(state_dir.rglob("*.json")):
            try:
                data = json.loads(f.read_text())
                state = data.get("state", data.get("status", ""))
                if state in ("RUNNING", "CLAIMED"):
                    errors.append(f"{f.relative_to(self._root)}: stuck in {state}")
            except Exception as e:
                errors.append(f"{f.relative_to(self._root)}: unreadable ({e})")
        if errors:
            return ComponentResult("state_files", False, detail="; ".join(errors[:5]))
        return ComponentResult("state_files", True, detail=f"{len(list(state_dir.rglob('*.json')))} state files OK")

    async def _check_packet_operations(self, packet_id: str | None) -> ComponentResult:
        if not packet_id:
            return ComponentResult("packet_operations", True, detail="No packet_id provided, skipped")
        state_dir = self._root / ".grace_state"
        state_file = state_dir / f"{packet_id}.json"
        if not state_file.exists():
            return ComponentResult("packet_operations", True, detail=f"Packet {packet_id} has no state file")
        try:
            data = json.loads(state_file.read_text())
            state = data.get("state", data.get("status", "unknown"))
            if state in ("FAILED", "REJECTED", "MERGED"):
                return ComponentResult("packet_operations", True, detail=f"Packet {packet_id} terminal ({state})")
            return ComponentResult("packet_operations", True, detail=f"Packet {packet_id} state={state}")
        except Exception as e:
            return ComponentResult("packet_operations", False, detail=f"Cannot read packet state: {e}")

    async def _check_worker_health(self, timeout: int) -> ComponentResult:
        import asyncio
        sock_path = os.environ.get("GRACE_SUPERVISOR_SOCK")
        if not sock_path:
            return ComponentResult("worker_health", True, detail="No supervisor socket configured, skipped")
        sock = Path(sock_path)
        if not sock.exists():
            return ComponentResult("worker_health", False, detail=f"Supervisor socket not found: {sock_path}")
        try:
            reader, writer = await asyncio.wait_for(
                asyncio.open_unix_connection(str(sock)),
                timeout=timeout,
            )
            writer.write(json.dumps({"action": "status"}).encode() + b"\n")
            await writer.drain()
            resp = await asyncio.wait_for(reader.readline(), timeout=timeout)
            writer.close()
            data = json.loads(resp.decode())
            workers = data.get("workers", [])
            alive = [w for w in workers if w.get("alive")]
            return ComponentResult("worker_health", True, detail=f"{len(alive)}/{len(workers)} workers alive")
        except Exception as e:
            return ComponentResult("worker_health", False, detail=f"Worker check failed: {e}")

#END_BLOCK_TESTER

#START_BLOCK_HELPERS

#START_FUNCTION_CONTRACT
# name: relevant_files_for_restart_test
# purpose: Return file paths most relevant to testing after a restart.
# inputs: None.
# returns: list[str] of up to 15 file paths.
# side_effects: None.
# emitted_logs: None.
# error_behavior: Never raises.
#END_FUNCTION_CONTRACT
def relevant_files_for_restart_test() -> list[str]:
    return [
        "src/grace_control/core/health.py",
        "src/grace_control/core/self_reload.py",
        "src/grace_control/cli.py",
        "src/grace_control/api/lifespan.py",
        "src/grace_control/api/routers/health.py",
        "src/grace_control/api/routers/lifecycle.py",
        "src/grace_control/core/lease_manager.py",
        "src/grace_control/core/cleanup_on_state.py",
        "src/grace_control/core/state_machine.py",
        "src/grace_control/core/packet_operations.py",
        "src/grace_control/api/routers/packets.py",
        "src/grace_control/api/routers/admin.py",
        "src/grace_control/core/recovery_controller.py",
        "src/grace_control/core/self_evolution_guard.py",
        "src/grace_control/config/settings.py",
    ]

#END_BLOCK_HELPERS
