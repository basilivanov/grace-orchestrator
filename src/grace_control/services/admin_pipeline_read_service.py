# ############################################################################
# AI_HEADER: admin_pipeline_read_service — packet pipeline projections
# ROLE: Derives packet stage cards, recovery chains, lifecycle state and wave
#       progress from persisted read models. The service is intentionally
#       read-only and receives artifact evidence through a collaborator.
# ############################################################################

# START_MODULE_CONTRACT
# purpose: Build the admin pipeline and lifecycle projections formerly owned
#          by AdminAggregationService.
# inputs: SQLAlchemy Session, Packet/PacketRun rows and an artifact reader.
# returns: Plain dictionaries/lists used by existing admin DTOs.
# side_effects: Reads ORM rows and persisted evidence JSON only.
# emitted_logs: None.
# error_behavior: Missing optional data produces pending/skipped projections;
#                 no mutation is performed.
# END_MODULE_CONTRACT

# START_MODULE_MAP
# mapping:
#   - class: AdminPipelineReadService
#     methods:
#       - derive_pipeline
#       - derive_stages
#       - derive_state_machine
#       - derive_simple_pipeline
#       - derive_packet_stage
# END_MODULE_MAP

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from sqlalchemy.orm import Session

from grace_control.core.structured_logger import GraceLogger
from grace_control.db.schema import Event, Packet, PacketRun
from grace_control.services.admin_overview_read_service import _iso, _packet_state

_log = GraceLogger("admin_pipeline_read")


# START_BLOCK_SERVICE
class AdminPipelineReadService:
    """Read-only owner for pipeline and lifecycle projections."""

    # START_FUNCTION_CONTRACT
    # name: __init__
    # purpose: Configure the optional artifact evidence collaborator.
    # inputs: artifact_service — object exposing get_packet_evidence.
    # returns: None.
    # side_effects: None.
    # error_behavior: Missing collaborator is tolerated until evidence is
    #                 requested by a pipeline projection.
    # END_FUNCTION_CONTRACT
    def __init__(self, artifact_service: Any | None = None) -> None:
        self._artifact_service = artifact_service

    # START_FUNCTION_CONTRACT
    # name: derive_pipeline
    # purpose: Derive the eleven-stage operator pipeline from packet, run,
    #          planning, event and evidence data.
    # inputs: db, packet row and ordered PacketRun rows.
    # returns: Pipeline DTO with stages and capability flags.
    # side_effects: Reads ORM and persisted evidence data.
    # emitted_logs: None.
    # error_behavior: Missing optional records become pending/skipped stages.
    # END_FUNCTION_CONTRACT
    def derive_pipeline(
        self,
        db: Session,
        packet: Packet,
        runs: list[PacketRun],
    ) -> dict[str, Any]:
        created_at = _iso(packet.created_at)
        last_run = runs[-1] if runs else None
        run_started = _iso(last_run.started_at) if last_run else None
        has_run = last_run is not None
        events = (
            db.query(Event)
            .filter(Event.entity_id == packet.id)
            .order_by(Event.timestamp.asc())
            .all()
        )
        from grace_control.db.schema import FeaturePlanningRun
        planning_runs = db.query(FeaturePlanningRun).filter(
            FeaturePlanningRun.feature_id == packet.feature_id,
            FeaturePlanningRun.stage.in_(["architect", "context_builder"]),
        ).all()
        architect_run = next((run for run in planning_runs if run.stage == "architect"), None)
        context_run = next((run for run in planning_runs if run.stage == "context_builder"), None)

        architect_live = self._planning_run_is_live(architect_run)
        architect_duration = (architect_run.duration_ms or 0) if architect_run else 0
        architect_start = _iso(architect_run.started_at) if architect_run and architect_run.started_at else created_at
        architect_finish = _iso(architect_run.finished_at) if architect_run and architect_run.finished_at else created_at
        architect_status = "running" if architect_live else (architect_run.status if architect_run else "done")
        architect_stage = {
            "key": "architect",
            "label": "Architect",
            "status": architect_status,
            "started_at": architect_start,
            "finished_at": architect_finish,
            "duration_ms": architect_duration,
            "meta": "🟢 LIVE" if architect_live else "",
            "target_tab": "spec",
        }
        context_live = self._planning_run_is_live(context_run)
        context_duration = (context_run.duration_ms or 0) if context_run else 0
        context_start = _iso(context_run.started_at) if context_run and context_run.started_at else created_at
        context_finish = _iso(context_run.finished_at) if context_run and context_run.finished_at else (run_started or created_at)
        context_status = "running" if context_live else (context_run.status if context_run else ("done" if has_run else "pending"))
        context_stage = {
            "key": "context_builder",
            "label": "Context Builder",
            "status": context_status,
            "started_at": context_start,
            "finished_at": context_finish,
            "duration_ms": context_duration,
            "meta": "🟢 LIVE" if context_live else "",
            "target_tab": "spec",
        }
        materialized_stage = {
            "key": "materialized",
            "label": "Materialize",
            "status": "done",
            "started_at": created_at,
            "finished_at": created_at,
            "duration_ms": 0,
            "meta": packet.slug or "",
            "target_tab": "spec",
        }
        if last_run and last_run.executor_id:
            executor_stage = {
                "key": "executor",
                "label": "Executor",
                "status": "done",
                "started_at": run_started,
                "finished_at": run_started,
                "duration_ms": 0,
                "meta": last_run.executor_id,
                "target_tab": "runs",
            }
        else:
            first_claim = next((event for event in events if event.event_type == "packet_claimed"), None)
            executor = (
                (first_claim.payload_json or {}).get("executor_id", "")
                if first_claim and first_claim.payload_json
                else ""
            )
            executor_stage = {
                "key": "executor",
                "label": "Executor",
                "status": "done" if executor else "skipped",
                "started_at": _iso(first_claim.timestamp) if first_claim else None,
                "finished_at": _iso(first_claim.timestamp) if first_claim else None,
                "duration_ms": 0,
                "meta": executor,
                "target_tab": "runs",
            }
        coder_stage = self._stage_coder_run(events, last_run, packet)
        coder_stage["target_tab"] = "runs"
        evidence = (
            self._artifact_service.get_packet_evidence(db, packet.id, run_id=str(last_run.run_number))
            if last_run and self._artifact_service
            else {"stages": []}
        )
        evidence_stages = {
            stage.get("name", "").upper(): stage
            for stage in (evidence.get("stages") or [])
        }
        acceptance_stages = self._stage_acceptance(
            evidence_stages,
            packet.acceptance_profile or "NORMAL",
        )
        verifier_stage = self._stage_verifier(
            events,
            last_run,
            packet.acceptance_profile or "NORMAL",
            packet,
        )
        reviewer_stage = self._stage_reviewer(events, last_run, packet)
        merge_stage = self._stage_merge(events, last_run, packet)
        stages = [context_stage, architect_stage, materialized_stage, executor_stage, coder_stage]
        stages += acceptance_stages + [verifier_stage, reviewer_stage, merge_stage]
        return {
            "stages": stages,
            "has_started": coder_stage["status"] != "pending",
            "has_acceptance_data": any(
                stage["status"] in ("done", "failed", "running")
                for stage in acceptance_stages
            ),
            "has_reviewer": reviewer_stage["status"] in ("done", "failed", "running"),
        }

    # START_FUNCTION_CONTRACT
    # name: derive_stages
    # purpose: Serialize StageRun telemetry for a packet plus any planning
    #          stages stored against its feature plan packet.
    # inputs: db and packet ORM row.
    # returns: Ordered StageRun DTO list.
    # side_effects: Reads StageRun rows only.
    # emitted_logs: None.
    # error_behavior: Missing planning rows are ignored.
    # END_FUNCTION_CONTRACT
    def derive_stages(self, db: Session, packet: Packet) -> list[dict[str, Any]]:
        from grace_control.db.schema import StageRun
        stage_runs = db.query(StageRun).filter_by(packet_id=packet.id).order_by(StageRun.started_at).all()
        plan_packet_id = f"plan_{packet.feature_id}"
        if plan_packet_id != packet.id:
            plan_runs = db.query(StageRun).filter_by(packet_id=plan_packet_id).order_by(StageRun.started_at).all()
            existing_keys = {(stage.stage_key, stage.loop_round) for stage in stage_runs}
            stage_runs.extend(
                stage for stage in plan_runs
                if (stage.stage_key, stage.loop_round) not in existing_keys
            )
        stage_runs.sort(key=lambda stage: (
            stage.started_at or datetime.max.replace(tzinfo=None),
            stage.created_at,
        ))
        return [
            {
                "id": stage.id,
                "stage_key": stage.stage_key,
                "status": stage.status,
                "started_at": _iso(stage.started_at),
                "finished_at": _iso(stage.finished_at),
                "duration_ms": stage.duration_ms,
                "loop_round": stage.loop_round,
                "attempt_number": stage.attempt_number,
                "parent_stage_run_id": stage.parent_stage_run_id,
                "error": stage.error,
                "executor_id": stage.executor_id,
                "worker_id": stage.worker_id,
                "model": stage.model,
                "tokens_in": stage.tokens_in,
                "tokens_out": stage.tokens_out,
                "cost_usd": float(stage.cost_usd) if stage.cost_usd else None,
                "stdout_path": stage.stdout_path,
                "stderr_path": stage.stderr_path,
                "artifacts_dir": stage.artifacts_dir,
                "result_path": stage.result_path,
                "trace_id": stage.trace_id,
                "recovery_reason": stage.recovery_reason,
            }
            for stage in stage_runs
        ]

    # START_FUNCTION_CONTRACT
    # name: derive_state_machine
    # purpose: Build the created/claimed/reviewed/result lifecycle DTO.
    # inputs: db, packet row and ordered runs.
    # returns: Dictionary containing four lifecycle steps.
    # side_effects: Reads packet events when run data is incomplete.
    # emitted_logs: None.
    # error_behavior: Legacy packets fall back to event-derived timestamps.
    # END_FUNCTION_CONTRACT
    def derive_state_machine(
        self,
        db: Session,
        packet: Packet,
        runs: list[PacketRun],
    ) -> dict[str, Any]:
        created_at = _iso(packet.created_at)
        first_started = None
        last_finished = None
        last_status = None
        worker_id = ""
        for run in runs:
            if first_started is None and run.started_at is not None:
                first_started = _iso(run.started_at)
                worker_id = run.worker_id or ""
            if run.finished_at is not None:
                last_finished = _iso(run.finished_at)
                last_status = run.status
        if first_started is None or last_finished is None:
            events = (
                db.query(Event)
                .filter(Event.entity_id == packet.id)
                .order_by(Event.timestamp.asc())
                .all()
            )
            for event in events:
                timestamp = _iso(event.timestamp)
                payload = event.payload_json or {}
                if event.event_type == "packet_claimed" and first_started is None:
                    first_started = timestamp
                    if not worker_id:
                        worker_id = payload.get("worker_id", "") or ""
                if event.event_type == "packet_transition":
                    last_finished = timestamp
                    reason = payload.get("reason", "") or ""
                    if "rejected" in reason:
                        last_status = "rejected"
                    elif "failed" in reason:
                        last_status = "failed"
                    elif "blocked" in reason:
                        last_status = "blocked"
                    elif "accepted" in reason or "merged" in reason:
                        last_status = "accepted"
        steps: list[dict[str, Any]] = [{
            "key": "created", "label": "Created", "state": "done",
            "time": created_at, "meta": "",
        }]
        if first_started is not None:
            claimed_state = "current" if _packet_state(packet) == "running" else "done"
            steps.append({
                "key": "claimed", "label": "Claimed", "state": claimed_state,
                "time": first_started, "meta": worker_id or "",
            })
        else:
            steps.append({
                "key": "claimed", "label": "Claimed", "state": "pending",
                "time": None, "meta": "",
            })
        if last_finished is not None:
            if last_status in ("rejected", "failed"):
                reviewed_state = "failed"
            elif last_status in ("blocked", "blocked_recoverable", "blocked_final"):
                reviewed_state = "blocked"
            elif _packet_state(packet) == "running":
                reviewed_state = "current"
            else:
                reviewed_state = "done"
            meta = f"{packet.attempt_count}/{packet.max_attempts} attempts"
            if last_status:
                meta = f"{last_status} · {meta}"
            steps.append({
                "key": "reviewed", "label": "Reviewed", "state": reviewed_state,
                "time": last_finished, "meta": meta,
            })
        elif _packet_state(packet) in ("draft", "ready"):
            steps.append({
                "key": "reviewed", "label": "Reviewed", "state": "pending",
                "time": None, "meta": "",
            })
        else:
            steps.append({
                "key": "reviewed", "label": "Reviewed", "state": "current",
                "time": None, "meta": "in progress",
            })
        terminal = _packet_state(packet) in (
            "accepted", "merged", "rejected", "failed", "blocked",
            "blocked_recoverable", "blocked_final", "cancelled",
        )
        if _packet_state(packet) in ("rejected", "failed"):
            result_state = "failed"
        elif _packet_state(packet) in ("blocked", "blocked_recoverable", "blocked_final"):
            result_state = "blocked"
        elif terminal:
            result_state = "done"
        else:
            result_state = "current"
        result_label = {
            "accepted": "Accepted", "merged": "Merged",
            "rejected": "Rejected", "failed": "Failed",
            "blocked": "Blocked", "blocked_recoverable": "Blocked (recoverable)",
            "blocked_final": "Blocked (final)", "cancelled": "Cancelled",
            "running": "Running", "ready": "Ready", "draft": "Draft",
        }.get(_packet_state(packet), _packet_state(packet))
        steps.append({
            "key": "result", "label": result_label, "state": result_state,
            "time": _iso(packet.updated_at), "meta": _packet_state(packet),
        })
        return {"steps": steps}

    # START_FUNCTION_CONTRACT
    # name: derive_simple_pipeline
    # purpose: Build the cheap feature-tree pipeline preview without events or
    #          evidence command loops.
    # inputs: packet, latest run, feature status and optional db session.
    # returns: Eleven-stage compact pipeline DTO.
    # side_effects: Optionally reads planning run metadata.
    # emitted_logs: None.
    # error_behavior: Missing planning rows become pending/default stages.
    # END_FUNCTION_CONTRACT
    def derive_simple_pipeline(
        self,
        packet: Packet,
        last_run: PacketRun | None,
        feature_status: str = "",
        db: Session | None = None,
    ) -> dict[str, Any]:
        state = (_packet_state(packet) or "draft").lower()
        profile = packet.acceptance_profile or "NORMAL"
        created_iso = _iso(packet.created_at)
        updated_iso = _iso(packet.updated_at)
        run_started = _iso(last_run.started_at) if last_run else None
        run_finished = _iso(last_run.finished_at) if last_run else None
        run_duration = last_run.duration_ms if last_run else 0
        run_status = (last_run.status or "").lower() if last_run else ""
        executor = (last_run.executor_id or "") if last_run else ""
        has_run = last_run is not None
        is_planning = feature_status == "PLANNING"
        stages: list[dict[str, Any]] = []
        from grace_control.db.schema import FeaturePlanningRun
        architect_duration = 0
        context_duration = 0
        architect_start = created_iso
        architect_finish = created_iso
        context_start = created_iso
        context_finish = created_iso
        architect_live = False
        context_live = False
        architect_status = None
        context_status = None
        if db is not None:
            planning_runs = db.query(FeaturePlanningRun).filter(
                FeaturePlanningRun.feature_id == packet.feature_id,
                FeaturePlanningRun.stage.in_(["architect", "context_builder"]),
            ).all()
            context_run = next((run for run in planning_runs if run.stage == "context_builder"), None)
            if context_run:
                context_duration = context_run.duration_ms or 0
                context_start = _iso(context_run.started_at) if context_run.started_at else created_iso
                context_finish = _iso(context_run.finished_at) if context_run.finished_at else created_iso
                context_live = self._planning_run_is_live(context_run)
                context_status = "running" if context_live else context_run.status
            architect_run = next((run for run in planning_runs if run.stage == "architect"), None)
            if architect_run:
                architect_duration = architect_run.duration_ms or 0
                architect_start = _iso(architect_run.started_at) if architect_run.started_at else created_iso
                architect_finish = _iso(architect_run.finished_at) if architect_run.finished_at else created_iso
                architect_live = self._planning_run_is_live(architect_run)
                architect_status = "running" if architect_live else architect_run.status
        stages.append({
            "key": "context_builder", "label": "Context Builder",
            "status": context_status or ("pending" if is_planning else ("done" if has_run else "pending")),
            "started_at": context_start, "finished_at": context_finish,
            "duration_ms": context_duration, "meta": "🟢 LIVE" if context_live else "",
            "target_tab": "spec",
        })
        stages.append({
            "key": "architect", "label": "Architect",
            "status": architect_status or ("running" if is_planning else "done"),
            "started_at": architect_start, "finished_at": architect_finish,
            "duration_ms": architect_duration, "meta": "🟢 LIVE" if architect_live else "",
            "target_tab": "spec",
        })
        stages.extend([
            {"key": "materialized", "label": "Materialize", "status": "done", "started_at": created_iso, "finished_at": created_iso, "duration_ms": 0, "meta": packet.slug or "", "target_tab": "spec"},
            {"key": "executor", "label": "Executor", "status": "done" if executor else "skipped", "started_at": run_started, "finished_at": run_started, "duration_ms": 0, "meta": executor, "target_tab": "runs"},
        ])
        if not has_run:
            coder_status = "pending"
        elif run_status == "running" or state == "running":
            coder_status = "running"
        elif state in ("rejected", "failed", "blocked", "blocked_recoverable", "blocked_final"):
            coder_status = "failed"
        elif run_status in ("accepted", "completed") or state in ("accepted", "merged"):
            coder_status = "done"
        else:
            coder_status = "pending"
        stages.append({
            "key": "coder_run", "label": "Coder", "status": coder_status,
            "started_at": run_started, "finished_at": run_finished,
            "duration_ms": run_duration if coder_status in ("done", "failed", "running") else 0,
            "meta": (last_run.worker_id or "") if last_run else "", "target_tab": "runs",
        })
        stages.extend([
            {"key": key, "label": label, "status": "skipped" if profile in ("FAST", "NORMAL") else "pending", "started_at": None, "finished_at": None, "duration_ms": 0, "meta": "", "target_tab": "evidence"}
            for key, label in (("t0", "T0 Lint"), ("t1", "T1 Tests"), ("t2", "T2 E2E"))
        ])
        if profile == "STRICT":
            verifier_status = "running" if state == "running" else ("done" if state in ("accepted", "merged") else "pending")
            stages.append({"key": "verifier", "label": "Verifier", "status": verifier_status, "started_at": None, "finished_at": None, "duration_ms": 0, "meta": "STRICT profile active", "target_tab": "evidence"})
        else:
            stages.append({"key": "verifier", "label": "Verifier", "status": "skipped", "started_at": None, "finished_at": None, "duration_ms": 0, "meta": "", "target_tab": "evidence"})
        reviewer_status = "done" if state in ("merged", "accepted") else ("failed" if state in ("rejected", "failed", "blocked", "blocked_recoverable", "blocked_final") else "pending")
        stages.append({"key": "reviewer", "label": "Reviewer", "status": reviewer_status, "started_at": run_finished, "finished_at": run_finished, "duration_ms": 0, "meta": "", "target_tab": "events"})
        merge_status = "done" if state in ("merged", "accepted") else ("skipped" if state in ("rejected", "failed", "blocked", "blocked_recoverable", "blocked_final") else "pending")
        stages.append({"key": "merge", "label": "Merge", "status": merge_status, "started_at": updated_iso if merge_status == "done" else None, "finished_at": updated_iso if merge_status == "done" else None, "duration_ms": 0, "meta": _packet_state(packet) if merge_status == "done" else "", "target_tab": "events"})
        return {
            "stages": stages,
            "has_started": has_run,
            "has_acceptance_data": False,
            "has_reviewer": reviewer_status in ("done", "failed", "running"),
        }

    # START_FUNCTION_CONTRACT
    # name: derive_packet_stage
    # purpose: Return the compact current stage label/key for a packet.
    # inputs: packet and latest PacketRun or None.
    # returns: Dictionary with machine key and human label.
    # side_effects: None.
    # emitted_logs: None.
    # error_behavior: Unknown/nonterminal states default to coder_run.
    # END_FUNCTION_CONTRACT
    def derive_packet_stage(
        self,
        packet: Packet,
        last_run: PacketRun | None,
    ) -> dict[str, str]:
        state = (_packet_state(packet) or "draft").lower()
        run_status = (last_run.status if last_run else "").lower() if last_run else ""
        if not last_run:
            if state in ("draft", "ready"):
                return {"key": "materialized", "label": "Materialized"}
            return {"key": "materialized", "label": "Not started"}
        if run_status == "running" or state == "running":
            return {"key": "coder_run", "label": "Coder run"}
        if state in ("accepted", "merged") or run_status == "accepted":
            return {"key": "merge", "label": "Merge"}
        if state in ("rejected", "failed", "blocked", "blocked_recoverable", "blocked_final") or run_status in ("rejected", "failed"):
            return {"key": "reviewer", "label": "Reviewer gate"}
        return {"key": "coder_run", "label": "Coder run"}

    # START_FUNCTION_CONTRACT
    # name: derive_recovery_chain
    # purpose: Link child StageRun recovery transitions to their parent runs.
    # inputs: db and packet row.
    # returns: Recovery transition DTO list.
    # side_effects: Reads StageRun rows.
    # emitted_logs: None.
    # error_behavior: Missing parents are skipped.
    # END_FUNCTION_CONTRACT
    def derive_recovery_chain(self, db: Session, packet: Packet) -> list[dict[str, Any]]:
        from grace_control.db.schema import StageRun
        chain: list[dict[str, Any]] = []
        seen: set[str] = set()
        stage_runs = db.query(StageRun).filter_by(packet_id=packet.id).order_by(StageRun.started_at).all()
        for stage in stage_runs:
            if stage.parent_stage_run_id and stage.parent_stage_run_id not in seen:
                seen.add(stage.parent_stage_run_id)
                parent = db.query(StageRun).filter_by(id=stage.parent_stage_run_id).first()
                if parent:
                    chain.append({
                        "from": parent.stage_key,
                        "to": stage.stage_key,
                        "reason": stage.recovery_reason or "",
                        "decision": f"recovery_return_to_{stage.stage_key}",
                        "at": _iso(stage.created_at),
                        "loop_round": stage.loop_round,
                    })
        return chain

    # START_FUNCTION_CONTRACT
    # name: derive_totals
    # purpose: Aggregate duration, token, cost and loop counters for a packet.
    # inputs: db and packet row.
    # returns: Totals DTO dictionary.
    # side_effects: Reads StageRun rows.
    # emitted_logs: None.
    # error_behavior: Empty stage data returns zero totals.
    # END_FUNCTION_CONTRACT
    def derive_totals(self, db: Session, packet: Packet) -> dict[str, Any]:
        from grace_control.db.schema import StageRun
        stage_runs = db.query(StageRun).filter_by(packet_id=packet.id).all()
        return {
            "duration_ms": sum(stage.duration_ms or 0 for stage in stage_runs),
            "tokens_in": sum(stage.tokens_in or 0 for stage in stage_runs),
            "tokens_out": sum(stage.tokens_out or 0 for stage in stage_runs),
            "cost_usd": round(sum(float(stage.cost_usd or 0) for stage in stage_runs), 6),
            "loop_count": sum(1 for stage in stage_runs if stage.parent_stage_run_id is not None),
        }

    # END_BLOCK_SERVICE

    # START_BLOCK_STAGE_HELPERS
    @staticmethod
    def _planning_run_is_live(run: Any | None) -> bool:
        if not run or run.status != "running":
            return False
        if run.last_heartbeat:
            return (datetime.now(UTC) - run.last_heartbeat).total_seconds() < 30
        return True

    def _stage_coder_run(
        self,
        events: list[Event],
        last_run: PacketRun | None,
        packet: Packet,
    ) -> dict[str, Any]:
        last_claim_index: int | None = None
        for index, event in enumerate(events):
            if event.event_type == "packet_claimed":
                last_claim_index = index
        if last_claim_index is None:
            return {
                "key": "coder_run", "label": "Coder run", "status": "pending",
                "started_at": None, "finished_at": None, "duration_ms": 0,
                "meta": "", "target_tab": "runs",
            }
        claim_event = events[last_claim_index]
        next_event = next(
            (
                event for event in events[last_claim_index + 1:]
                if event.event_type == "packet_transition"
            ),
            None,
        )
        started_at = _iso(claim_event.timestamp)
        finished_at = _iso(next_event.timestamp) if next_event else None
        duration_ms = 0
        if started_at and finished_at:
            try:
                start = datetime.fromisoformat(started_at.replace("Z", "+00:00"))
                finish = datetime.fromisoformat(finished_at.replace("Z", "+00:00"))
                duration_ms = max(0, int((finish - start).total_seconds() * 1000))
            except (ValueError, AttributeError):
                duration_ms = 0
        elif last_run and last_run.duration_ms and not finished_at:
            duration_ms = last_run.duration_ms
        if not next_event and _packet_state(packet) == "running":
            status = "running"
        elif _packet_state(packet) in ("rejected", "failed", "blocked", "blocked_recoverable", "blocked_final"):
            status = "failed"
        elif finished_at:
            status = "done"
        else:
            status = "pending"
        meta = (last_run.worker_id if last_run and last_run.worker_id else "")
        if not meta and claim_event.payload_json:
            meta = (claim_event.payload_json or {}).get("worker_id", "") or ""
        if not meta:
            meta = f"attempt {packet.attempt_count}/{packet.max_attempts}"
        return {
            "key": "coder_run", "label": "Coder run", "status": status,
            "started_at": started_at, "finished_at": finished_at,
            "duration_ms": duration_ms, "meta": meta, "target_tab": "runs",
        }

    def _stage_acceptance(
        self,
        evidence_stages: dict[str, dict[str, Any]],
        acceptance_profile: str,
    ) -> list[dict[str, Any]]:
        output: list[dict[str, Any]] = []
        for stage_key, stage_name, label in (
            ("T0_SCOPE_AND_LINT", "t0", "T0 scope/lint"),
            ("T1_UNIT_TESTS", "t1", "T1 tests"),
            ("T2_E2E_OR_SMOKE", "t2", "T2 smoke/e2e"),
        ):
            evidence = evidence_stages.get(stage_key)
            if evidence is None:
                if acceptance_profile in ("NORMAL", "FAST"):
                    status, meta = "skipped", "no separate run (NORMAL profile)"
                else:
                    status, meta = "pending", "no command configured"
                output.append({
                    "key": stage_name, "label": label, "status": status,
                    "started_at": None, "finished_at": None, "duration_ms": 0,
                    "meta": meta, "target_tab": "evidence",
                })
                continue
            evidence_status = (evidence.get("status") or "").lower()
            if evidence_status == "passed":
                status = "done"
            elif evidence_status == "failed":
                status = "failed"
            else:
                status = "running" if evidence_status in ("running", "started") else "pending"
            meta_parts: list[str] = []
            if evidence.get("summary"):
                meta_parts.append(str(evidence["summary"])[:60])
            if evidence.get("blocking_issues"):
                meta_parts.append(f"{len(evidence['blocking_issues'])} blocking")
            output.append({
                "key": stage_name, "label": label, "status": status,
                "started_at": None, "finished_at": None, "duration_ms": 0,
                "meta": " · ".join(meta_parts) if meta_parts else evidence_status or "",
                "target_tab": "evidence",
            })
        return output

    def _stage_verifier(
        self,
        events: list[Event],
        last_run: PacketRun | None,
        acceptance_profile: str,
        packet: Packet,
    ) -> dict[str, Any]:
        if acceptance_profile != "STRICT":
            return {
                "key": "verifier", "label": "Evidence verifier", "status": "skipped",
                "started_at": None, "finished_at": None, "duration_ms": 0,
                "meta": f"not in profile ({acceptance_profile})", "target_tab": "evidence",
            }
        verifier_events = [
            event for event in events
            if (event.payload_json or {}).get("component", "") == "evidence_service"
            or "verifier" in (event.event_type or "").lower()
        ]
        if not verifier_events:
            return {
                "key": "verifier", "label": "Evidence verifier", "status": "pending",
                "started_at": None, "finished_at": None, "duration_ms": 0,
                "meta": "STRICT profile active", "target_tab": "evidence",
            }
        last_event = verifier_events[-1]
        return {
            "key": "verifier", "label": "Evidence verifier",
            "status": "done" if _packet_state(packet) != "running" else "running",
            "started_at": _iso(last_event.timestamp), "finished_at": _iso(last_event.timestamp),
            "duration_ms": 0,
            "meta": (last_event.payload_json or {}).get("reason", "") or last_event.event_type,
            "target_tab": "evidence",
        }

    def _stage_reviewer(
        self,
        events: list[Event],
        last_run: PacketRun | None,
        packet: Packet,
    ) -> dict[str, Any]:
        review_events = [
            event for event in events
            if event.event_type == "packet_transition"
            and ((event.payload_json or {}).get("reason") or "").startswith("release:")
        ]
        if not review_events:
            meta = "not started" if _packet_state(packet) in ("draft", "ready") else ""
            return {
                "key": "reviewer", "label": "Reviewer gate", "status": "pending",
                "started_at": None, "finished_at": None, "duration_ms": 0,
                "meta": meta, "target_tab": "events",
            }
        last_event = review_events[-1]
        reason = (last_event.payload_json or {}).get("reason", "") or ""
        decision = reason.split(":", 1)[-1].upper() if ":" in reason else reason.upper()
        if "accepted" in reason or "merged" in reason:
            status = "done"
        elif "rejected" in reason:
            status = "failed"
        else:
            status = "pending"
        return {
            "key": "reviewer", "label": "Reviewer gate", "status": status,
            "started_at": _iso(last_event.timestamp), "finished_at": _iso(last_event.timestamp),
            "duration_ms": 0, "meta": decision or last_event.event_type, "target_tab": "events",
        }

    def _stage_merge(
        self,
        events: list[Event],
        last_run: PacketRun | None,
        packet: Packet,
    ) -> dict[str, Any]:
        if _packet_state(packet) in ("merged", "accepted"):
            return {
                "key": "merge", "label": "Merge", "status": "done",
                "started_at": _iso(packet.updated_at), "finished_at": _iso(packet.updated_at),
                "duration_ms": 0, "meta": _packet_state(packet), "target_tab": "runs",
            }
        if _packet_state(packet) in ("rejected", "failed"):
            return {
                "key": "merge", "label": "Merge", "status": "skipped",
                "started_at": None, "finished_at": None, "duration_ms": 0,
                "meta": "not reached", "target_tab": "events",
            }
        if _packet_state(packet) in ("blocked", "blocked_recoverable", "blocked_final"):
            return {
                "key": "merge", "label": "Merge", "status": "skipped",
                "started_at": None, "finished_at": None, "duration_ms": 0,
                "meta": "blocked", "target_tab": "events",
            }
        return {
            "key": "merge", "label": "Merge", "status": "pending",
            "started_at": None, "finished_at": None, "duration_ms": 0,
            "meta": "", "target_tab": "events",
        }


# END_BLOCK_STAGE_HELPERS
