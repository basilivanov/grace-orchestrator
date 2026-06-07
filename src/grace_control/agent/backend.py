# ############################################################################
# AI_HEADER: backend
# ROLE: ExecutionBackend Protocol — only file declaring the agent execution contract.
# ############################################################################

# START_MODULE_CONTRACT
# purpose: Define the abstract contract for executing a packet. The packet_executor
#          adapter depends only on this Protocol — never on legacy code directly.
# inputs: ExecutionRequest with packet spec, scope, executor selection.
# returns: ExecutionResult with accepted, worktree, commit, stdout, stderr.
# side_effects: None at this layer (impls spawn processes).
# emitted_logs: None.
# error_behavior: Implementations must never raise; failures encoded in result.
# END_MODULE_CONTRACT

# START_MODULE_MAP
# mapping:
#   - dataclass: ExecutionRequest
#   - dataclass: ExecutionResult
#   - class: ExecutionBackend (Protocol)
# END_MODULE_MAP

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Protocol


@dataclass
class ExecutionRequest:
    """Inputs to an execution backend."""
    packet_id: str
    spec: dict
    worktree_path: Path
    branch_name: str
    scope_paths: list[str] = field(default_factory=list)
    executor: dict = field(default_factory=dict)
    timeout_s: int = 600
    session_dir: Path | None = None
    trace_id: str = ""
    evidence_dir: Path | None = None  # canonical run evidence path (W12)


@dataclass
class ExecutionResult:
    """Outputs from an execution backend. accepted=True only for full success."""
    accepted: bool
    domain_status: str
    worktree_path: Path
    branch_name: str
    commit_sha: str
    stdout: str
    stderr: str
    duration_ms: int
    changed_files: list[str] = field(default_factory=list)
    evidence: dict = field(default_factory=dict)
    reason: str = ""
    errors: list[str] = field(default_factory=list)
    registry_reason: str = ""
    # Admin v2: which model/command/prompt was used. Optional — legacy
    # backends may not populate them. Default-empty is safe.
    model: str = ""
    command_preview: list[str] = field(default_factory=list)
    prompt: str = ""

    @property
    def ok(self) -> bool:
        """Legacy alias for accepted; kept for adapter back-compat."""
        return self.accepted

    def to_dict(self) -> dict[str, Any]:
        return {
            "accepted": self.accepted,
            "ok": self.accepted,
            "domain_status": self.domain_status,
            "worktree_path": str(self.worktree_path),
            "branch_name": self.branch_name,
            "commit_sha": self.commit_sha,
            "stdout": self.stdout,
            "stderr": self.stderr,
            "duration_ms": self.duration_ms,
            "changed_files": list(self.changed_files),
            "evidence": dict(self.evidence),
            "reason": self.reason,
            "errors": list(self.errors),
            "registry_reason": self.registry_reason,
            "model": self.model,
            "command_preview": list(self.command_preview),
            "prompt": self.prompt,
        }


class ExecutionBackend(Protocol):
    """Protocol for packet execution backends. Implementations: LegacyPrefectBackend, etc."""

    async def run(self, request: ExecutionRequest) -> ExecutionResult: ...

    async def cancel(self, request: ExecutionRequest) -> None: ...
