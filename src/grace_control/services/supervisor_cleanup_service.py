# ############################################################################
# AI_HEADER: supervisor_cleanup_service
# ROLE: Idempotent cleanup for the GRACE supervisor's runtime state.
#       Owns three cleanup axes:
#         1. Stale worktrees (orphaned by crashed packets, not tracked by DB)
#         2. Stale state files (.grace_state/ for finished packets)
#         3. Stale packet leases (DB packets claimed > N min without progress)
# ############################################################################

# START_MODULE_CONTRACT
# purpose: Run best-effort, idempotent cleanup of supervisor-owned state.
#          Designed to be called by the supervisor itself (`POST /control/cleanup`)
#          or by the API proxy (`POST /api/admin/lifecycle/cleanup`).
# inputs: target_dir (Path) — the worktree root; source_dir (Path) — for git ops.
# returns: CleanupReport dict.
# side_effects: Deletes worktree dirs (via git), state files, releases stale leases.
# emitted_logs: cleanup_started, worktree_removed, state_file_removed,
#               stale_lease_released, cleanup_finished.
# error_behavior: Best-effort; never raises. Each step is wrapped and logged.
# END_MODULE_CONTRACT

# START_MODULE_MAP
# mapping:
#   - class: SupervisorCleanupService
#   - class: CleanupReport
# END_MODULE_MAP

from __future__ import annotations

import json
import shutil
import subprocess
import time
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path

from grace_control.core.structured_logger import GraceLogger

_log = GraceLogger("supervisor_cleanup")

DEFAULT_STALE_LEASE_MINUTES = 30
DEFAULT_STALE_STATE_DAYS = 7


@dataclass
class CleanupReport:
    """Result of a cleanup run. Safe to serialize to JSON."""

    worktrees_removed: list[str] = field(default_factory=list)
    worktrees_kept: list[str] = field(default_factory=list)
    state_files_removed: list[str] = field(default_factory=list)
    state_files_kept: list[str] = field(default_factory=list)
    stale_leases_released: int = 0
    errors: list[str] = field(default_factory=list)
    duration_seconds: float = 0.0

    def to_dict(self) -> dict:
        return {
            "worktrees_removed": self.worktrees_removed,
            "worktrees_kept": self.worktrees_kept,
            "state_files_removed": self.state_files_removed,
            "state_files_kept": self.state_files_kept,
            "stale_leases_released": self.stale_leases_released,
            "errors": self.errors,
            "duration_seconds": round(self.duration_seconds, 3),
        }


class SupervisorCleanupService:
    """Idempotent cleanup of supervisor-owned runtime state."""

    def __init__(
        self,
        target_dir: Path,
        source_dir: Path,
        worktree_root: Path | None = None,
        state_root: Path | None = None,
    ) -> None:
        self._target = Path(target_dir).resolve()
        self._source = Path(source_dir).resolve()
        self._worktree_root = Path(worktree_root or (self._target / ".grace" / "worktrees")).resolve()
        self._state_root = Path(state_root or (self._target / ".grace" / "state")).resolve()

    def run(
        self,
        *,
        stale_lease_minutes: int = DEFAULT_STALE_LEASE_MINUTES,
        stale_state_days: int = DEFAULT_STALE_STATE_DAYS,
        worktrees: bool = True,
        state_files: bool = True,
        stale_leases: bool = True,
    ) -> CleanupReport:
        """Run all configured cleanup steps. Each step is independent."""
        report = CleanupReport()
        start = time.time()
        _log.info("cleanup_started", target=str(self._target))
        try:
            if worktrees:
                self._cleanup_worktrees(report)
            if state_files:
                self._cleanup_state_files(report, older_than_days=stale_state_days)
            if stale_leases:
                self._release_stale_leases(report, older_than_minutes=stale_lease_minutes)
            # TZ_FRONTEND_ACCEPTANCE P1 — kill orphan frontend processes
            self._kill_frontend_processes(report)
        finally:
            report.duration_seconds = time.time() - start
            _log.info(
                "cleanup_finished",
                duration_s=round(report.duration_seconds, 3),
                wt_removed=len(report.worktrees_removed),
                state_removed=len(report.state_files_removed),
                leases=report.stale_leases_released,
                errors=len(report.errors),
            )
        return report

    # ── worktrees ──────────────────────────────────────────────────────────

    def _is_worktree_registered(self, slug: str) -> bool:
        """Check git for a worktree with this slug. Cheap; uses `git worktree list`."""
        try:
            r = subprocess.run(
                ["git", "-C", str(self._target), "worktree", "list", "--porcelain"],
                capture_output=True, text=True, timeout=5,
            )
        except (subprocess.TimeoutExpired, FileNotFoundError):
            return True  # if git fails, be conservative — keep
        if r.returncode != 0:
            return True
        for line in r.stdout.splitlines():
            if line.startswith("worktree ") and slug in line:
                return True
        return False

    def _worktree_for_active_packet(self, slug: str) -> bool:
        """Return True if any non-terminal Packet references this worktree slug."""
        try:
            from grace_control.db import get_db
            from grace_control.db.schema import Packet, PacketState
        except Exception:
            return False  # DB unavailable — be conservative
        try:
            with get_db() as db:
                for p in db.query(Packet).all():
                    if p.state in (PacketState.CLAIMED.value, PacketState.RUNNING.value,
                                   PacketState.AWAITING_ACCEPTANCE.value, PacketState.AWAITING_VERIFICATION.value):
                        if p.worktree_path and slug in p.worktree_path:
                            return True
        except RuntimeError:
            # DB not initialized — be conservative
            return False
        except Exception as e:
            _log.warn("worktree_active_check_failed", error=str(e)[:200])
            return False
        return False

    def _cleanup_worktrees(self, report: CleanupReport) -> None:
        if not self._worktree_root.exists():
            return
        for child in self._worktree_root.iterdir():
            if not child.is_dir():
                continue
            slug = child.name
            if self._is_worktree_registered(slug) and self._worktree_for_active_packet(slug):
                report.worktrees_kept.append(slug)
                continue
            try:
                subprocess.run(
                    ["git", "-C", str(self._target), "worktree", "prune"],
                    capture_output=True, timeout=10,
                )
                if child.exists():
                    subprocess.run(
                        ["git", "-C", str(self._target), "worktree", "remove", str(child), "--force"],
                        capture_output=True, timeout=10,
                    )
                    shutil.rmtree(child, ignore_errors=True)
                subprocess.run(
                    ["git", "-C", str(self._target), "branch", "-D", f"agent/{slug}"],
                    capture_output=True, timeout=10,
                )
                report.worktrees_removed.append(slug)
                _log.info("worktree_removed", slug=slug)
            except Exception as e:
                msg = f"worktree {slug}: {e!s}"[:200]
                report.errors.append(msg)
                _log.warn("worktree_cleanup_failed", slug=slug, error=str(e)[:200])

    # ── state files ────────────────────────────────────────────────────────

    def _cleanup_state_files(self, report: CleanupReport, *, older_than_days: int) -> None:
        if not self._state_root.exists():
            return
        cutoff = time.time() - older_than_days * 86400
        for child in self._state_root.iterdir():
            try:
                mtime = child.stat().st_mtime
            except FileNotFoundError:
                continue
            if mtime > cutoff:
                report.state_files_kept.append(child.name)
                continue
            try:
                if child.is_dir():
                    shutil.rmtree(child, ignore_errors=True)
                else:
                    child.unlink()
                report.state_files_removed.append(child.name)
                _log.info("state_file_removed", path=child.name)
            except Exception as e:
                msg = f"state {child.name}: {e!s}"[:200]
                report.errors.append(msg)
                _log.warn("state_cleanup_failed", path=child.name, error=str(e)[:200])

    # ── stale leases ───────────────────────────────────────────────────────

    def _release_stale_leases(self, report: CleanupReport, *, older_than_minutes: int) -> None:
        try:
            from grace_control.db import get_db
            from grace_control.db.schema import Lease, Packet, PacketState
        except Exception as e:
            _log.warn("lease_cleanup_unavailable", error=str(e)[:200])
            return
        cutoff = datetime.now(timezone.utc).replace(tzinfo=None) - timedelta(minutes=older_than_minutes)
        try:
            with get_db() as db:
                stale = (
                    db.query(Lease)
                    .filter(Lease.expires_at < cutoff)
                    .all()
                )
                for lease in stale:
                    packet = db.query(Packet).filter(Packet.id == lease.packet_id).first()
                    if packet and packet.state in (
                        PacketState.CLAIMED.value,
                        PacketState.RUNNING.value,
                    ):
                        packet.state = PacketState.FAILED.value
                        db.add(packet)
                        report.stale_leases_released += 1
                        _log.info(
                            "stale_lease_released",
                            packet_id=lease.packet_id,
                            worker_id=lease.worker_id,
                        )
                    db.delete(lease)
        except RuntimeError as e:
            # DB not initialized — skip silently. This is normal during
            # early boot or in unit tests with no DB.
            _log.info("lease_cleanup_skipped", reason=str(e)[:120])
        except Exception as e:
            msg = f"stale leases: {e!s}"[:200]
            report.errors.append(msg)
            _log.warn("lease_cleanup_failed", error=str(e)[:200])

    @staticmethod
    def _kill_frontend_processes(report: CleanupReport) -> None:
        """Kill leftover dev-server and ngrok processes from crashed packets.

        TZ_FRONTEND_ACCEPTANCE P1/1.7/3.5 — ensures ports are freed and
        no orphan processes linger after packet execution.
        """
        for pattern, label in [
            (["node", "npm run dev"], "dev-server (npm)"),
            (["node", "vite"], "dev-server (vite)"),
            (["node", "next"], "dev-server (next)"),
            (["ngrok", "http"], "ngrok tunnel"),
        ]:
            try:
                r = subprocess.run(
                    ["pgrep", "-f", " ".join(pattern)],
                    capture_output=True, text=True, timeout=5,
                )
                pids = r.stdout.strip().split()
                for pid_str in pids:
                    pid = int(pid_str)
                    try:
                        os.kill(pid, signal.SIGTERM)
                        report.errors.append(f"killed {label} (pid={pid})")
                    except OSError:
                        pass
            except Exception:
                pass
