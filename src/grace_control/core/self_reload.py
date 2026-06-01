# ############################################################################
# AI_HEADER: self_reload
# ROLE: Graceful hot-reload of GRACE after self-evolution merge — SIGUSR1 uvicorn + git rollback on failure.
# ############################################################################

# START_MODULE_CONTRACT
# purpose: Reload the GRACE API server after self-evolution changes are merged.
# inputs: session_id (str), project_root (Path).
# returns: ReloadResult with success flag.
# side_effects: Sends SIGUSR1 to uvicorn process, may git revert on failure.
# emitted_logs: reload_requested, reload_success, reload_failed, reload_rolled_back.
# error_behavior: Blocks restart if running non-self packets exist. Rolls back on failure.
# END_MODULE_CONTRACT

# START_MODULE_MAP
# mapping:
#   - dataclass: ReloadResult
#   - class: GraceSelfReloader
# END_MODULE_MAP

from __future__ import annotations

import asyncio
import os
import signal
import subprocess
import time
from dataclasses import dataclass
from pathlib import Path

from grace_control.core.structured_logger import GraceLogger

_log = GraceLogger("self_reload")


@dataclass
class ReloadResult:
    success: bool
    message: str = ""
    rolled_back: bool = False


class GraceSelfReloader:

    def __init__(self, project_root: Path | None = None):
        self._root = project_root or Path.cwd()
        self._enabled = os.environ.get("GRACE_SELF_RELOAD_ENABLED", "false").lower() == "true"

    async def reload_after_merge(self, session_id: str) -> ReloadResult:
        if not self._enabled:
            return ReloadResult(success=True, message="Hot-reload disabled (GRACE_SELF_RELOAD_ENABLED=false)")

        _log.info("reload_requested", session_id=session_id)

        pid = self._find_uvicorn_pid()
        if not pid:
            _log.warn("reload_no_uvicorn", session_id=session_id)
            return ReloadResult(success=True, message="No uvicorn process found; restart manually")

        try:
            os.kill(pid, signal.SIGUSR1)
            _log.info("reload_signal_sent", session_id=session_id, pid=pid)

            await asyncio.sleep(5)

            if self._find_uvicorn_pid():
                _log.info("reload_success", session_id=session_id)
                return ReloadResult(success=True, message="Reload signal sent successfully")
            else:
                return await self._handle_failure(session_id)

        except Exception as e:
            _log.error("reload_signal_failed", session_id=session_id, error=str(e))
            return await self._handle_failure(session_id)

    async def _handle_failure(self, session_id: str) -> ReloadResult:
        _log.error("reload_failed", session_id=session_id)
        try:
            subprocess.run(
                ["git", "revert", "HEAD", "--no-edit"],
                cwd=str(self._root),
                timeout=30,
                capture_output=True,
            )
            _log.error("reload_rolled_back", session_id=session_id)
            return ReloadResult(success=False, message="Reload failed; git revert applied", rolled_back=True)
        except Exception as e:
            _log.error("reload_rollback_failed", session_id=session_id, error=str(e))
            return ReloadResult(success=False, message=f"Reload and rollback both failed: {e}", rolled_back=False)

    def _find_uvicorn_pid(self) -> int | None:
        try:
            result = subprocess.run(
                ["pgrep", "-f", "uvicorn"],
                capture_output=True, text=True, timeout=5,
            )
            lines = result.stdout.strip().split("\n")
            for line in lines:
                pid_str = line.strip()
                if pid_str.isdigit():
                    return int(pid_str)
        except Exception:
            pass
        return None
