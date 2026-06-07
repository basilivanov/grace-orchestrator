# ############################################################################
# AI_HEADER: size_calculator
# ROLE: Compute disk sizes for runs, packets, waves, and aggregate dirs.
#       Implements TZ_RETENTION_POLICY.md Phase 2.
# ############################################################################

# START_MODULE_CONTRACT
# purpose: Recursive directory size in bytes, formatted in human-readable
#          units. Read-only — never modifies the filesystem.
# inputs: Path, optional packet_id / run_id filters.
# returns: int (bytes) for raw methods; dicts for structured snapshots.
# side_effects: filesystem read (os.walk / Path.rglob).
# emitted_logs: None (callee logs).
# error_behavior: Returns 0 for missing paths; never raises.
# END_MODULE_CONTRACT

# START_MODULE_MAP
# mapping:
#   - dataclass: RunSizeInfo
#   - dataclass: PacketSizeInfo
#   - dataclass: DiskSnapshot
#   - class: SizeCalculator
# END_MODULE_MAP

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


def fmt_size(num_bytes: int | float | None) -> str:
    """Format a byte count as a human-readable string (B/KB/MB/GB/TB/PB).

    Examples:
        >>> fmt_size(0)
        '0 B'
        >>> fmt_size(512)
        '512 B'
        >>> fmt_size(1024)
        '1.0 KB'
        >>> fmt_size(1572864)
        '1.5 MB'
        >>> fmt_size(2 * 1024**3)
        '2.0 GB'
        >>> fmt_size(None)
        '0 B'
    """
    if num_bytes is None:
        return "0 B"
    n = float(num_bytes)
    if n == 0:
        return "0 B"
    sign = "-" if n < 0 else ""
    n = abs(n)
    if n < 1024:
        return f"{sign}{int(n) if n == int(n) else n} B"
    original = n
    for unit, divisor in (("KB", 1024), ("MB", 1024**2), ("GB", 1024**3), ("TB", 1024**4)):
        n = original / divisor
        if n < 1024:
            return f"{sign}{n:.1f} {unit}"
    n = original / 1024**5
    return f"{sign}{n:.1f} PB"


@dataclass
class RunSizeInfo:
    """Size info for a single run (R0X) directory."""
    run_id: str           # e.g. "R01"
    path: str             # absolute path
    size_bytes: int

    @property
    def size_human(self) -> str:
        return fmt_size(self.size_bytes)

    def to_dict(self) -> dict[str, Any]:
        return {
            "run_id": self.run_id,
            "path": self.path,
            "size_bytes": self.size_bytes,
            "size_human": self.size_human,
        }


@dataclass
class PacketSizeInfo:
    """Size info for a single packet (sum of all runs)."""
    packet_id: str
    runs: list[RunSizeInfo] = field(default_factory=list)

    @property
    def size_bytes(self) -> int:
        return sum(r.size_bytes for r in self.runs)

    @property
    def size_human(self) -> str:
        return fmt_size(self.size_bytes)

    @property
    def run_count(self) -> int:
        return len(self.runs)

    def to_dict(self) -> dict[str, Any]:
        return {
            "packet_id": self.packet_id,
            "size_bytes": self.size_bytes,
            "size_human": self.size_human,
            "run_count": self.run_count,
            "runs": [r.to_dict() for r in self.runs],
        }


@dataclass
class DiskSnapshot:
    """Top-level snapshot of disk usage for the maintenance tab."""
    worktrees_total_bytes: int = 0
    worktree_count: int = 0
    state_total_bytes: int = 0
    packet_count: int = 0
    run_count: int = 0
    branch_count: int = 0
    agent_branch_count: int = 0

    @property
    def worktrees_total_human(self) -> str:
        return fmt_size(self.worktrees_total_bytes)

    @property
    def state_total_human(self) -> str:
        return fmt_size(self.state_total_bytes)

    def to_dict(self) -> dict[str, Any]:
        return {
            "worktrees_total_bytes": self.worktrees_total_bytes,
            "worktrees_total_human": self.worktrees_total_human,
            "worktree_count": self.worktree_count,
            "state_total_bytes": self.state_total_bytes,
            "state_total_human": self.state_total_human,
            "packet_count": self.packet_count,
            "run_count": self.run_count,
            "branch_count": self.branch_count,
            "agent_branch_count": self.agent_branch_count,
        }


class SizeCalculator:
    """Read-only size calculations for admin UI.

    All methods are safe to call on missing paths (return 0). All sizes are
    in bytes; use `fmt_size()` for human-readable display.
    """

    def __init__(self, state_root: Path | str | None = None,
                 worktree_root: Path | str | None = None):
        self.state_root = Path(state_root) if state_root is not None else None
        self.worktree_root = Path(worktree_root) if worktree_root is not None else None

    def du(self, path: Path | str) -> int:
        """Recursively compute total size in bytes for `path`.

        Returns 0 if path doesn't exist or is not a directory.
        """
        p = Path(path)
        if not p.exists():
            return 0
        if p.is_file():
            try:
                return p.stat().st_size
            except (OSError, PermissionError):
                return 0
        total = 0
        try:
            for entry in p.rglob("*"):
                if entry.is_file() and not entry.is_symlink():
                    try:
                        total += entry.stat().st_size
                    except (OSError, PermissionError):
                        continue
        except (OSError, PermissionError):
            return total
        return total

    def packet_runs_size(self, packet_id: str) -> int:
        """Total size of all R0X/ runs for `packet_id` in state_root."""
        if self.state_root is None:
            return 0
        runs_dir = self.state_root / "packets" / packet_id / "runs"
        if not runs_dir.exists():
            return 0
        return self.du(runs_dir)

    def packet_runs_breakdown(self, packet_id: str) -> PacketSizeInfo:
        """Per-run size breakdown for `packet_id`."""
        info = PacketSizeInfo(packet_id=packet_id)
        if self.state_root is None:
            return info
        runs_dir = self.state_root / "packets" / packet_id / "runs"
        if not runs_dir.exists():
            return info
        for run_dir in sorted(runs_dir.iterdir()):
            if not run_dir.is_dir():
                continue
            info.runs.append(RunSizeInfo(
                run_id=run_dir.name,
                path=str(run_dir.resolve()),
                size_bytes=self.du(run_dir),
            ))
        return info

    def worktree_size(self, slug: str) -> int:
        """Size of `.grace/worktrees/<slug>/`."""
        if self.worktree_root is None:
            return 0
        return self.du(self.worktree_root / slug)

    def all_worktrees_total(self) -> int:
        """Total size of all worktree dirs."""
        if self.worktree_root is None:
            return 0
        return self.du(self.worktree_root)

    def all_state_total(self) -> int:
        """Total size of `.grace/state/`."""
        if self.state_root is None:
            return 0
        return self.du(self.state_root)

    def list_worktree_slugs(self) -> list[str]:
        """List all worktree dir names (slugs)."""
        if self.worktree_root is None or not self.worktree_root.exists():
            return []
        return sorted(p.name for p in self.worktree_root.iterdir() if p.is_dir())

    def state_packet_count(self) -> int:
        """Count of packet dirs in `.grace/state/packets/`."""
        if self.state_root is None:
            return 0
        packets_dir = self.state_root / "packets"
        if not packets_dir.exists():
            return 0
        return sum(1 for p in packets_dir.iterdir() if p.is_dir())

    def state_run_count(self) -> int:
        """Total count of R0X dirs across all packets."""
        if self.state_root is None:
            return 0
        packets_dir = self.state_root / "packets"
        if not packets_dir.exists():
            return 0
        count = 0
        for packet_dir in packets_dir.iterdir():
            runs_dir = packet_dir / "runs"
            if runs_dir.is_dir():
                count += sum(1 for r in runs_dir.iterdir() if r.is_dir())
        return count

    def disk_snapshot(self) -> DiskSnapshot:
        """Build a top-level snapshot for the maintenance tab."""
        snap = DiskSnapshot(
            worktrees_total_bytes=self.all_worktrees_total(),
            worktree_count=len(self.list_worktree_slugs()),
            state_total_bytes=self.all_state_total(),
            packet_count=self.state_packet_count(),
            run_count=self.state_run_count(),
        )
        return snap
