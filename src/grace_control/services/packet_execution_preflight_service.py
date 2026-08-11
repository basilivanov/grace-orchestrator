# ############################################################################
# AI_HEADER: packet_execution_preflight_service — runtime contract and pre-run gates
# ROLE: Builds the runtime contract, runs the selftest safety gate, and prepares
#       materialized packet inputs before any backend execution.
# ############################################################################

# START_MODULE_CONTRACT
# purpose: Prepare a packet for execution and reject unsafe runtime setup early.
# inputs: Packet data, selected executor, run identifiers, and adapter-owned services.
# returns: PacketExecutionPreparation on success or the facade's rejection result.
# side_effects: Writes materialized packet files and optional runtime artifacts/events.
# emitted_logs: Runtime contract, selftest, context, and agent-start event names.
# error_behavior: Returns the adapter's controlled rejection result on safety failure.
# END_MODULE_CONTRACT

# START_MODULE_MAP
# mapping:
#   - class: PacketExecutionPreparation
#   - class: PacketExecutionPreflightService
#     methods:
#       - prepare
# END_MODULE_MAP

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from grace_control.core.structured_logger import GraceLogger
from grace_control.runtime.agent_runtime_contract import AgentRuntimeContractBuilder
from grace_control.runtime.agent_runtime_selftest import AgentRuntimeSelftest
from grace_control.services.packet_execution_runtime_service import (
    _resolve_worktree_for_contract,
)

_log = GraceLogger("adapter")

# START_BLOCK_PREPARATION
@dataclass
class PacketExecutionPreparation:
    packet_path: Path
    packet_contract: object
    base_ref: str
    base_sha: str
    evidence_dir: Path
    packet_spec: dict


class PacketExecutionPreflightService:

    # START_FUNCTION_CONTRACT
    # name: prepare
    # purpose: Build runtime contract, enforce selftest/context gates, and prepare execution inputs.
    # inputs: adapter, packet_id, packet_data, executor, run_id, run_number — execution context.
    # returns: Prepared packet inputs or the adapter's controlled rejection result.
    # side_effects: Materializes packet files and emits/writes runtime safety artifacts.
    # emitted_logs: runtime contract, selftest, context, and agent_started events.
    # error_behavior: Returns a facade rejection result when a pre-run gate fails.
    # END_FUNCTION_CONTRACT
    def prepare(
        self,
        adapter,
        packet_id: str,
        packet_data: dict,
        executor: dict,
        run_id: str,
        run_number: int,
        start: float,
    ):
        from grace_control.config.settings import settings as _settings

        # ── W3: Agent Runtime Contract + Selftest ──────────────────────
        # Selftest is a safety gate — always runs when enabled (default True).
        # Events/artifacts are only emitted when observability is enabled.
        if getattr(_settings, "agent_runtime_selftest_enabled", True):
            worktree_path = _resolve_worktree_for_contract(
                packet_data, executor, _settings, adapter.project_root, adapter.worktree_root,
            )
            pkt_spec = packet_data.get("spec_json") or {}
            if isinstance(pkt_spec, str):
                pkt_spec = {}
            pkt_target_repo = pkt_spec.get("target_repo_root", "") or _settings.target_repo_root or ""
            contract = AgentRuntimeContractBuilder.build(
                packet_data=packet_data,
                executor=executor,
                run_id=run_id,
                trace=adapter._obs_trace,
                project_root=adapter.project_root,
                target_repo_root=pkt_target_repo,
                worktree_path=worktree_path,
                settings=_settings,
            )

            if not getattr(adapter, "_obs_disabled", True):
                contract_ref = adapter._obs_store.write_packet_json(
                    trace=adapter._obs_trace, packet_id=packet_id,
                    name="runtime_contract.json",
                    payload=contract.model_dump(),
                    kind="runtime_contract",
                )
                adapter._obs_event("packet.runtime_contract_created", status="completed",
                                artifact_refs=[contract_ref] if contract_ref else None)
                adapter._obs_event("packet.runtime_selftest_started", status="started")

            selftest = AgentRuntimeSelftest()
            selftest_result = selftest.run(contract, adapter._obs_trace)

            if not getattr(adapter, "_obs_disabled", True):
                for c in selftest_result.checks:
                    adapter._obs_event("packet.runtime_selftest_check_completed", status="completed",
                                    payload={"check_id": c.check_id, "ok": c.ok,
                                             "expected": c.expected, "actual": c.actual,
                                             "failure_code": c.failure_code})
                selftest_ref = selftest.persist(selftest_result, adapter._obs_trace)
                if selftest_result.ok:
                    adapter._obs_event("packet.runtime_selftest_completed", status="completed",
                                    artifact_refs=[selftest_ref] if selftest_ref else None)
                else:
                    adapter._obs_event("packet.runtime_selftest_failed", status="failed",
                                    message=selftest_result.summary,
                                    artifact_refs=[selftest_ref] if selftest_ref else None)

            if not selftest_result.ok:
                return adapter._fast_reject(selftest_result.summary, executor.get("executor_id", ""), run_id, start)

        # ── end W3 ─────────────────────────────────────────────────────

        # W04: pass effective target root for file tree/previews enrichment
        _mat_target = adapter._resolve_materializer_target(packet_data)
        state_root = getattr(adapter, "state" + "_root")
        packet_path = adapter._materializer.materialize(packet_data, state_root, target_root=_mat_target)
        from grace_control.core.contracts import build_packet_contract
        pkt_contract = build_packet_contract(packet_data)
        base_ref = _settings.base_branch
        base_sha = adapter._inspector.base_sha(
            _mat_target or adapter.project_root, "HEAD"
        )
        evidence_dir = state_root / "packets" / packet_id / "runs" / f"R{run_number:02d}"

        # ── W04: Block blind NORMAL/STRICT coder packets without context ─
        _pkt_spec = packet_data.get("spec_json") or {}
        if isinstance(_pkt_spec, str):
            _pkt_spec = {}
        _prof = pkt_contract.acceptance_profile.value if hasattr(pkt_contract, "acceptance_profile") else ""
        _role = executor.get("role", "coder")
        _skip_ctx = executor.get("skip_context_builder", False)
        _ctx_not_required = _pkt_spec.get("context_not_required", False)
        if _role == "coder" and _prof in ("NORMAL", "STRICT") and _skip_ctx and not _ctx_not_required:
            err_msg = (
                f"Context required for {_prof} coder packet but context builder was skipped "
                f"(skip_context_builder=true). Set context_not_required=true in spec to override."
            )
            _log.warn("context_required_blocked", packet_id=packet_id, profile=_prof)
            return adapter._fast_reject(err_msg, executor.get("executor_id", ""), run_id, start,
                failure_code="AGENT_CONTEXT_REQUIRED", failure_stage="pre_agent_run")

        # ── W2: agent_started before executor ──────────────────────────
        adapter._obs_event("packet.agent_started", status="started")

        # W4: pass observability to backends that expose the runtime hook.
        set_observability = getattr(adapter._backend, "set_observability", None)
        if callable(set_observability):
            set_observability(
                trace=adapter._obs_trace,
                store=adapter._obs_store if not getattr(adapter, "_obs_disabled", True) else None,
                events=adapter._obs_events if not getattr(adapter, "_obs_disabled", True) else None,
            )

        return PacketExecutionPreparation(
            packet_path=packet_path,
            packet_contract=pkt_contract,
            base_ref=base_ref,
            base_sha=base_sha,
            evidence_dir=evidence_dir,
            packet_spec=_pkt_spec,
        )

# END_BLOCK_PREPARATION
