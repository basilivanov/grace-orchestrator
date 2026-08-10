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

import os
import shutil
import signal
import subprocess
import time
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
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
        """Return True when cleanup cannot prove a worktree is orphaned.

        Packet does not persist a worktree column. Active packet/run evidence
        is matched when available; without it, retaining the registered
        worktree is the only safe choice for a live worker.
        """
        try:
            from grace_control.db import get_db
            from grace_control.db.schema import Packet, PacketRun, PacketState
        except Exception:
            return True  # DB unavailable — keep registered worktree
        try:
            with get_db() as db:
                active_states = {PacketState.RUNNING.value, PacketState.ACCEPTED.value}
                active_packets = [
                    p for p in db.query(Packet).all() if p.state in active_states
                ]
                for packet in active_packets:
                    packet_matches_slug = packet.id in slug or bool(
                        packet.slug and slug.startswith(packet.slug)
                    )
                    runs = (
                        db.query(PacketRun)
                        .filter_by(packet_id=packet.id)
                        .order_by(PacketRun.run_number.desc())
                        .all()
                    )
                    known_paths: list[str] = []
                    for run in runs:
                        result = run.result_json if isinstance(run.result_json, dict) else {}
                        worktree_path = result.get("worktree_path")
                        if worktree_path:
                            known_paths.append(str(worktree_path))
                        evidence = result.get("evidence")
                        if isinstance(evidence, dict):
                            evidence_path = evidence.get("worktree_path")
                            if evidence_path:
                                known_paths.append(str(evidence_path))
                    if any(slug in path for path in known_paths if path):
                        return True
                    if packet_matches_slug and not known_paths:
                        return True
        except RuntimeError:
            # DB not initialized — be conservative
            return True
        except Exception as e:
            _log.warn("worktree_active_check_failed", error=str(e)[:200])
            return True
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
        cutoff = datetime.now(UTC).replace(tzinfo=None) - timedelta(minutes=older_than_minutes)
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
                        PacketState.RUNNING.value,
                        "claimed",
                    ):
                        packet.state = PacketState.FAILED.value
                        db.add(packet)
                        from grace_control.services.parallel_lease_service import ParallelLeaseService
                        ParallelLeaseService().release_for_terminal_state(
                            db,
                            packet.id,
                            PacketState.FAILED.value,
                        )
                        report.stale_leases_released += 1
                        _log.info(
                            "stale_lease_released",
                            packet_id=lease.packet_id,
                            worker_id=lease.worker_id,
                        )
                    db.delete(lease)
                self._recover_expired_merge_leases(db, report, cutoff=cutoff)
                self._reclaim_expired_accepted_parallel_leases(db, report, cutoff=cutoff)
                from grace_control.services.parallel_lease_service import ParallelLeaseService
                ParallelLeaseService().expire(db)
        except RuntimeError as e:
            # DB not initialized — skip silently. This is normal during
            # early boot or in unit tests with no DB.
            _log.info("lease_cleanup_skipped", reason=str(e)[:120])
        except Exception as e:
            msg = f"stale leases: {e!s}"[:200]
            report.errors.append(msg)
            _log.warn("lease_cleanup_failed", error=str(e)[:200])

    # START_FUNCTION_CONTRACT
    # name: _recover_expired_merge_leases
    # purpose: Reclaim expired merge leases only after target-repository sanity
    #          confirms there is no live or interrupted mutation.
    # inputs: db — cleanup transaction; report — mutable cleanup report;
    #         cutoff — UTC-naive expiry boundary.
    # returns: None.
    # side_effects: Deletes safely reclaimable merge_leases rows only.
    # emitted_logs: merge_lease_recovered, merge_lease_recovery_deferred.
    # error_behavior: Keeps unsafe leases and records an error.
    # END_FUNCTION_CONTRACT
    def _recover_expired_merge_leases(
        self,
        db,
        report: CleanupReport,
        *,
        cutoff: datetime,
    ) -> None:
        from grace_control.db.schema import MergeLease
        from grace_control.services.merge_coordinator_service import MergeCoordinatorService

        coordinator = MergeCoordinatorService()
        expired = db.query(MergeLease).filter(MergeLease.expires_at < cutoff).all()
        for lease in expired:
            sanity = coordinator.check_repo_sanity(
                lease.target_repo_key,
                expected_target_repo_key=lease.target_repo_key,
            )
            if not sanity.ok:
                message = f"merge lease {lease.target_repo_key}: {sanity.error}"[:200]
                report.errors.append(message)
                _log.warn(
                    "merge_lease_recovery_deferred",
                    target_repo_key=lease.target_repo_key,
                    reason=sanity.error[:200],
                )
                continue
            db.delete(lease)
            _log.info(
                "merge_lease_recovered",
                target_repo_key=lease.target_repo_key,
                packet_id=lease.packet_id,
            )

    # START_FUNCTION_CONTRACT
    # name: _reclaim_expired_accepted_parallel_leases
    # purpose: Recover an ACCEPTED packet whose worker died after releasing its
    #          ordinary lease but before serialized merge ownership existed.
    # inputs: db — cleanup transaction; report — mutable cleanup report;
    #         cutoff — UTC-naive expiry boundary.
    # returns: None.
    # side_effects: Moves abandoned ACCEPTED packets to BLOCKED_RECOVERABLE,
    #               releases their parallel lease, and clears worker linkage.
    # emitted_logs: accepted_parallel_lease_recovered,
    #               accepted_parallel_lease_deferred.
    # error_behavior: Leaves the lease untouched when a merge lease is still
    #                 present, so an in-flight target mutation is not fenced
    #                 by cleanup.
    # END_FUNCTION_CONTRACT
    @staticmethod
    def _reclaim_expired_accepted_parallel_leases(
        db,
        report: CleanupReport,
        *,
        cutoff: datetime,
    ) -> None:
        from grace_control.db.schema import Event, MergeLease, Packet, PacketState, ParallelLease, Worker

        expired = db.query(ParallelLease).filter(ParallelLease.expires_at < cutoff).all()
        for lease in expired:
            packet = db.query(Packet).filter_by(id=lease.packet_id).first()
            if packet is None or packet.state != PacketState.ACCEPTED.value:
                continue
            merge_lease = db.query(MergeLease).filter_by(packet_id=packet.id).first()
            if merge_lease is not None:
                _log.info(
                    "accepted_parallel_lease_deferred",
                    packet_id=packet.id,
                    reason="merge_lease_present",
                )
                continue
            packet.state = PacketState.BLOCKED_RECOVERABLE.value
            db.add(Event(
                event_type="packet_transition",
                entity_type="packet",
                entity_id=packet.id,
                payload_json={
                    "from": PacketState.ACCEPTED.value,
                    "to": PacketState.BLOCKED_RECOVERABLE.value,
                    "reason": "parallel_lease_expired_recovery",
                },
                timestamp=datetime.now(UTC),
            ))
            worker = db.query(Worker).filter_by(current_packet_id=packet.id).first()
            if worker is not None:
                worker.current_packet_id = None
            db.delete(lease)
            report.stale_leases_released += 1
            _log.warn(
                "accepted_parallel_lease_recovered",
                packet_id=packet.id,
                worker_id=lease.worker_id,
                reason="worker_crash_before_merge",
            )

    @staticmethod
    def _kill_frontend_processes(report: CleanupReport) -> None:
        """Kill leftover dev-server and ngrok processes scoped to this project.

        TZ_FRONTEND_ACCEPTANCE P3 — uses cwd pattern matching instead of
        broad pgrep -f which could kill unrelated user processes.
        Only kills processes whose cwd matches our worktree or who have
        a GRACE worker environment marker.
        """
        # Kill via /proc — check cwd for worktree paths, not global patterns
        try:
            for proc_dir in Path("/proc").iterdir():
                if not proc_dir.name.isdigit():
                    continue
                try:
                    cmdline = (proc_dir / "cmdline").read_text().replace("\0", " ")
                    cwd_link = proc_dir / "cwd"
                    cwd = cwd_link.resolve() if cwd_link.is_symlink() else None
                except (OSError, PermissionError):
                    continue
                # Only kill processes running in our worktree
                is_dev = any(kw in cmdline for kw in ("npm run dev", "vite", "next dev", "ngrok http"))
                is_ours = cwd and (".grace" in str(cwd) or "grace-live-wt" in str(cwd))
                if is_dev and is_ours:
                    try:
                        pid = int(proc_dir.name)
                        os.kill(pid, signal.SIGTERM)
                        report.errors.append(f"killed frontend process {cmdline[:50]} (pid={pid})")
                    except (OSError, ValueError):
                        pass
        except Exception:
            pass
