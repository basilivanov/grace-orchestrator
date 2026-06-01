# ############################################################################
# AI_HEADER: executor_registry
# ROLE: Deterministic executor selection and rotation policy for packet execution.
# ############################################################################

# START_MODULE_CONTRACT
# purpose: Select executors for packet execution based on project config, role compatibility, and failure history.
# inputs: Project config, packet metadata, execution history, requested executor.
# returns: ExecutorSpec selection with rotation logic and execution records.
# side_effects: Appends execution records to ExecutorHistoryStore.
# emitted_logs: None.
# error_behavior: Fails closed on invalid executor specs, returns ok=false when no executor available.
# END_MODULE_CONTRACT

# START_MODULE_MAP
# mapping:
#   - class: ExecutorSpec
#   - class: ExecutorSelection
#   - function: load_executor_specs
#   - function: select_executor_for_packet
#   - function: record_executor_attempt
#   - function: _is_executor_failure
#   - function: _count_consecutive_failures
#   - function: _filter_history_for_packet_role
# END_MODULE_MAP

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Literal

from prefect_grace.platform.status_model import DomainStatus, is_failure_domain_status

from prefect_grace.platform.state_store import ExecutorHistoryStore

#START_BLOCK_DATA_MODELS
@dataclass(frozen=True)
class ExecutorSpec:
    """Executor specification with metadata for selection and execution."""
    executor_id: str
    kind: Literal["codex", "claude", "agy", "mock"]
    command: str
    model: str | None = None
    reasoning: str | None = None
    roles: list[str] = field(default_factory=list)
    enabled: bool = True
    priority: int = 100
    max_consecutive_failures: int = 2
    metadata: dict[str, Any] = field(default_factory=dict)

    # START_FUNCTION_CONTRACT
    # name: to_dict
    # purpose: Convert ExecutorSpec to dictionary for serialization.
    # inputs: None (instance method)
    # returns: dict[str, Any] - Dictionary with all spec fields.
    # side_effects: None
    # emitted_logs: None
    # error_behavior: None
    # END_FUNCTION_CONTRACT
    def to_dict(self) -> dict[str, Any]:
        return {
            "executor_id": self.executor_id,
            "kind": self.kind,
            "command": self.command,
            "model": self.model,
            "reasoning": self.reasoning,
            "roles": list(self.roles),
            "enabled": self.enabled,
            "priority": self.priority,
            "max_consecutive_failures": self.max_consecutive_failures,
            "metadata": dict(self.metadata),
        }


@dataclass(frozen=True)
class ExecutorSelection:
    """Result of executor selection with rotation logic."""
    ok: bool
    packet_id: str
    role: str
    selected: ExecutorSpec | None
    candidate_ids: list[str]
    rotated_from: str | None = None
    reason: str | None = None
    warnings: list[str] = field(default_factory=list)

    # START_FUNCTION_CONTRACT
    # name: to_dict
    # purpose: Convert ExecutorSelection to dictionary for serialization.
    # inputs: None (instance method)
    # returns: dict[str, Any] - Dictionary with all selection fields.
    # side_effects: None
    # emitted_logs: None
    # error_behavior: None
    # END_FUNCTION_CONTRACT
    def to_dict(self) -> dict[str, Any]:
        return {
            "ok": self.ok,
            "packet_id": self.packet_id,
            "role": self.role,
            "selected": self.selected.to_dict() if self.selected else None,
            "candidate_ids": list(self.candidate_ids),
            "rotated_from": self.rotated_from,
            "reason": self.reason,
            "warnings": list(self.warnings),
        }

#END_BLOCK_DATA_MODELS
#START_BLOCK_LOAD_SPECS
# START_FUNCTION_CONTRACT
# name: load_executor_specs
# purpose: Load executor specs from project config with backward compatibility.
# inputs:
#   project: ProjectAdapterConfig instance with agent_executor field.
# returns: list[ExecutorSpec] - List of executor specifications.
# side_effects: None
# emitted_logs: None
# error_behavior: Raises ValueError if enabled executor spec is invalid.
# END_FUNCTION_CONTRACT
def load_executor_specs(project: Any) -> list[ExecutorSpec]:
    """
    Load executor specs from project config with backward compatibility.

    Accepts ProjectAdapterConfig object or dict from project config.
    If project.agent_executor has 'executors' list, parse it.
    Otherwise synthesize single codex-cli spec from default/command.
    Validates each spec, fails closed on invalid enabled executors.
    """
    if project is None:
        return [_default_executor_spec()]

    if isinstance(project, dict):
        agent_executor = project.get("agent_executor", {})
        if isinstance(agent_executor, dict):
            executor_list = agent_executor.get("executors", [])
            default = agent_executor.get("default", "codex-cli")
            command = agent_executor.get("command", "codex1")
        else:
            executor_list = getattr(agent_executor, "executors", None) or []
            default = getattr(agent_executor, "default", "codex-cli")
            command = getattr(agent_executor, "command", "codex1")
    else:
        agent_executor = project.agent_executor
        executor_list = getattr(agent_executor, "executors", None) or []
        default = getattr(agent_executor, "default", "codex-cli")
        command = getattr(agent_executor, "command", "codex1")

    if executor_list:
        specs = []
        for idx, raw_spec in enumerate(executor_list):
            if not isinstance(raw_spec, dict):
                raise ValueError(f"Executor spec at index {idx} must be a dict")

            # Required fields
            executor_id = raw_spec.get("executor_id")
            kind = raw_spec.get("kind")
            command = raw_spec.get("command")

            if not executor_id or not isinstance(executor_id, str):
                raise ValueError(f"Executor spec at index {idx} missing valid executor_id")
            if not kind or kind not in ["codex", "claude", "agy", "mock"]:
                raise ValueError(f"Executor {executor_id} has invalid kind: {kind}")
            if not command or not isinstance(command, str):
                raise ValueError(f"Executor {executor_id} missing valid command")

            # Optional fields
            model = raw_spec.get("model")
            reasoning = raw_spec.get("reasoning")
            roles = raw_spec.get("roles", [])
            enabled = raw_spec.get("enabled", True)
            priority = raw_spec.get("priority", 100)
            max_consecutive_failures = raw_spec.get("max_consecutive_failures", 2)
            metadata = raw_spec.get("metadata", {})

            # Validate types
            if not isinstance(roles, list):
                raise ValueError(f"Executor {executor_id} roles must be a list")
            if not isinstance(enabled, bool):
                raise ValueError(f"Executor {executor_id} enabled must be a boolean")
            if not isinstance(priority, int):
                raise ValueError(f"Executor {executor_id} priority must be an integer")
            if not isinstance(max_consecutive_failures, int) or max_consecutive_failures < 0:
                raise ValueError(f"Executor {executor_id} max_consecutive_failures must be a non-negative integer")
            if not isinstance(metadata, dict):
                raise ValueError(f"Executor {executor_id} metadata must be a dict")

            spec = ExecutorSpec(
                executor_id=executor_id,
                kind=kind,
                command=command,
                model=model,
                reasoning=reasoning,
                roles=list(roles),
                enabled=enabled,
                priority=priority,
                max_consecutive_failures=max_consecutive_failures,
                metadata=dict(metadata),
            )
            specs.append(spec)

        return specs

    # Backward compatibility: synthesize from default/command
    return [
        ExecutorSpec(
            executor_id=default,
            kind="codex",
            command=command,
            model=None,
            reasoning=None,
            roles=[],
            enabled=True,
            priority=100,
            max_consecutive_failures=2,
            metadata={},
        )
    ]

#END_BLOCK_LOAD_SPECS
#START_BLOCK_FAILURE_DETECTION
# START_FUNCTION_CONTRACT
# name: _is_executor_failure
# purpose: Determine if execution record represents executor failure.
# inputs:
#   record: dict[str, Any] - Execution record with returncode, domain_status, termination_reason.
# returns: bool - True if record represents executor failure.
# side_effects: None
# emitted_logs: None
# error_behavior: None
# END_FUNCTION_CONTRACT
def _is_executor_failure(record: dict[str, Any]) -> bool:
    """
    Determine if execution record represents executor failure.

    Failure conditions:
    - returncode != 0
    - domain_status == "agent_failed"
    - termination_reason in ["stall_killed", "timeout", "rate_limit_exceeded", "quota_exceeded", "auth_failed"]

    NOT failures:
    - domain_status == "scope_blocked"
    - status == "skipped"
    """
    # Check status field first
    if record.get("status") == "skipped":
        return False

    # Check returncode
    returncode = record.get("returncode")
    if returncode is not None and returncode != 0:
        return True

    # Check domain_status
    domain_status = record.get("domain_status")
    if domain_status == DomainStatus.AGENT_FAILED.value:
        return True
    if domain_status == DomainStatus.SCOPE_BLOCKED.value:
        return False

    # Check termination_reason
    termination_reason = record.get("termination_reason")
    if termination_reason in ["stall_killed", "timeout", "rate_limit_exceeded", "quota_exceeded", "auth_failed"]:
        return True

    return False


# START_FUNCTION_CONTRACT
# name: _filter_history_for_packet_role
# purpose: Filter execution history to same packet_id and role.
# inputs:
#   history: list[dict[str, Any]] - All execution records.
#   packet_id: str - Packet identifier.
#   role: str - Packet role.
# returns: list[dict[str, Any]] - Filtered records, newest first.
# side_effects: None
# emitted_logs: None
# error_behavior: None
# END_FUNCTION_CONTRACT
def _filter_history_for_packet_role(
    history: list[dict[str, Any]],
    packet_id: str,
    role: str,
) -> list[dict[str, Any]]:
    """Filter history to same packet_id and role, newest first."""
    filtered = [
        record for record in history
        if record.get("packet_id") == packet_id and record.get("role") == role
    ]
    # Sort by recorded_at descending (newest first)
    filtered.sort(key=lambda r: r.get("recorded_at", ""), reverse=True)
    return filtered


# START_FUNCTION_CONTRACT
# name: _count_consecutive_failures
# purpose: Count consecutive failures for executor in filtered history.
# inputs:
#   history: list[dict[str, Any]] - Filtered execution records for packet/role, newest first.
#   executor_id: str - Executor identifier.
#   packet_source_hash: str | None - Packet source hash for filtering.
# returns: int - Count of consecutive failures.
# side_effects: None
# emitted_logs: None
# error_behavior: None
# END_FUNCTION_CONTRACT
def _count_consecutive_failures(
    history: list[dict[str, Any]],
    executor_id: str,
    packet_source_hash: str | None,
) -> int:
    """
    Count consecutive failures for executor in filtered history.

    Rules:
    - Count failures for same executor_id, newest first
    - Stop at first non-failure for same executor
    - If packet has source_hash, only count records with matching source_hash
    - Ignore scope_blocked records; they do not increment or reset the streak
    """
    count = 0
    for record in history:
        if record.get("executor_id") != executor_id:
            continue

        # Source hash filtering
        if packet_source_hash is not None:
            record_source_hash = record.get("source_hash")
            if record_source_hash is not None and record_source_hash != packet_source_hash:
                # Different source hash, skip this record
                continue

        if record.get("domain_status") == DomainStatus.SCOPE_BLOCKED.value:
            continue

        # Check if failure
        if _is_executor_failure(record):
            count += 1
        else:
            # First non-failure for this executor, stop counting
            break

    return count

#END_BLOCK_FAILURE_DETECTION
#START_BLOCK_SELECTION
# START_FUNCTION_CONTRACT
# name: select_executor_for_packet
# purpose: Select executor for packet with deterministic rotation logic.
# inputs:
#   project: ProjectAdapterConfig instance.
#   packet: dict[str, Any] - Packet metadata with packet_id, role, source_hash, requested_executor.
#   history: list[dict[str, Any]] | None - Execution history records.
#   requested_executor: str | None - Explicitly requested executor ID.
# returns: ExecutorSelection - Selection result with ok, selected executor, rotation reason.
# side_effects: None
# emitted_logs: None
# error_behavior: Returns ok=false when no executor available.
# END_FUNCTION_CONTRACT
def select_executor_for_packet(
    *,
    project: Any,
    packet: Any,  # dict[str, Any] or ParsedPacket
    history: list[dict[str, Any]] | None = None,
    requested_executor: str | None = None,
) -> ExecutorSelection:
    """
    Select executor for packet with deterministic rotation logic.

    Selection rules:
    1. If requested_executor provided, select it if enabled and role-compatible
    2. Otherwise filter enabled candidates by role
    3. Sort by (priority, executor_id)
    4. Check history for consecutive failures
    5. Rotate if best candidate has max_consecutive_failures or more
    6. Return ok=false if no candidate remains
    """
    # Handle both dict and ParsedPacket
    if hasattr(packet, "packet_id"):
        # ParsedPacket dataclass
        packet_id = packet.packet_id
        role = "coder"  # Default role, ParsedPacket doesn't have role field
        packet_source_hash = packet.source_hash
    else:
        # dict
        packet_id = packet.get("packet_id", "unknown")
        role = packet.get("role", "coder")
        packet_source_hash = packet.get("source_hash")

    history = history or []

    # Load executor specs
    specs = load_executor_specs(project)

    # Filter history for this packet/role
    filtered_history = _filter_history_for_packet_role(history, packet_id, role)

    # Handle requested executor
    if requested_executor is not None:
        for spec in specs:
            if spec.executor_id == requested_executor:
                if not spec.enabled:
                    return ExecutorSelection(
                        ok=False,
                        packet_id=packet_id,
                        role=role,
                        selected=None,
                        candidate_ids=[],
                        reason=f"requested_executor_disabled:{requested_executor}",
                    )

                # Check role compatibility
                if spec.roles and role not in spec.roles:
                    return ExecutorSelection(
                        ok=False,
                        packet_id=packet_id,
                        role=role,
                        selected=None,
                        candidate_ids=[],
                        reason=f"requested_executor_role_incompatible:{requested_executor}",
                    )

                return ExecutorSelection(
                    ok=True,
                    packet_id=packet_id,
                    role=role,
                    selected=spec,
                    candidate_ids=[spec.executor_id],
                    reason="requested",
                )

        # Requested executor not found
        return ExecutorSelection(
            ok=False,
            packet_id=packet_id,
            role=role,
            selected=None,
            candidate_ids=[],
            reason=f"requested_executor_not_found:{requested_executor}",
        )

    # Filter enabled candidates by role
    candidates = []
    for spec in specs:
        if not spec.enabled:
            continue

        # Role compatibility: empty roles means all roles
        if spec.roles and role not in spec.roles:
            continue

        candidates.append(spec)

    if not candidates:
        return ExecutorSelection(
            ok=False,
            packet_id=packet_id,
            role=role,
            selected=None,
            candidate_ids=[],
            reason="no_executor_available",
        )

    # Filter by complexity if packet has it
    packet_complexity = None
    if hasattr(packet, "complexity"):
        packet_complexity = packet.complexity
    else:
        packet_complexity = packet.get("complexity", "")

    packet_complexity = str(packet_complexity or "").lower()

    if packet_complexity:
        complexity_matched = []
        for spec in candidates:
            spec_complexity = spec.metadata.get("complexity", "")

            # Handle both string and list complexity constraints
            if isinstance(spec_complexity, str):
                spec_complexity = [spec_complexity] if spec_complexity else []
            elif not isinstance(spec_complexity, list):
                spec_complexity = []

            # Match if spec has no complexity constraint or packet complexity matches
            if not spec_complexity or packet_complexity in spec_complexity:
                complexity_matched.append(spec)

        # Only apply complexity filter if we have matches
        if complexity_matched:
            candidates = complexity_matched

    # Sort by (priority, executor_id) for deterministic ordering
    candidates.sort(key=lambda s: (s.priority, s.executor_id))

    candidate_ids = [c.executor_id for c in candidates]

    # Check consecutive failures and rotate if needed
    for candidate in candidates:
        failures = _count_consecutive_failures(filtered_history, candidate.executor_id, packet_source_hash)

        if failures < candidate.max_consecutive_failures:
            # This candidate is good
            return ExecutorSelection(
                ok=True,
                packet_id=packet_id,
                role=role,
                selected=candidate,
                candidate_ids=candidate_ids,
                reason="selected",
            )

        # This candidate has too many failures, try next
        continue

    # All candidates exhausted
    return ExecutorSelection(
        ok=False,
        packet_id=packet_id,
        role=role,
        selected=None,
        candidate_ids=candidate_ids,
        reason="all_executors_failed",
        warnings=[f"All {len(candidates)} candidates exceeded max_consecutive_failures"],
    )

#END_BLOCK_SELECTION
#START_BLOCK_RECORDING
# START_FUNCTION_CONTRACT
# name: record_executor_attempt
# purpose: Record executor attempt to history store.
# inputs:
#   state_root: Path - State root directory.
#   packet_id: str - Packet identifier.
#   role: str - Packet role.
#   executor_id: str - Executor identifier.
#   result: dict[str, Any] - Execution result with returncode, domain_status, termination_reason.
#   attempt: int | None - Attempt number.
# returns: dict[str, Any] - Recorded execution record.
# side_effects: Appends record to ExecutorHistoryStore.
# emitted_logs: None
# error_behavior: None
# END_FUNCTION_CONTRACT
def record_executor_attempt(
    *,
    state_root: Path,
    packet_id: str,
    role: str,
    executor_id: str,
    result: dict[str, Any],
    attempt: int | None = None,
) -> dict[str, Any]:
    """
    Record executor attempt to history store.

    Builds execution record with required fields and appends to ExecutorHistoryStore.
    """
    history_store = ExecutorHistoryStore(state_root)

    # Build execution record
    record = {
        "packet_id": packet_id,
        "feature_id": result.get("feature_id"),
        "wave_id": result.get("wave_id"),
        "source_hash": result.get("source_hash"),
        "role": role,
        "executor_id": executor_id,
        "executor_kind": result.get("executor_kind"),
        "attempt": attempt,
        "status": result.get("status"),
        "returncode": result.get("returncode"),
        "termination_reason": result.get("termination_reason"),
        "domain_status": result.get("domain_status"),
        "selection_reason": result.get("selection_reason"),
        "requested_executor": result.get("requested_executor"),
        "run_dir": result.get("run_dir"),
        "recorded_at": datetime.now(timezone.utc).isoformat(),
    }

    # Append to history
    history_store.append_execution(record)

    return record

#END_BLOCK_RECORDING
