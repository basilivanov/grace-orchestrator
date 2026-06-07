# ############################################################################
# AI_HEADER: admin_aggregation_service
# ROLE: Composes existing services into admin-friendly DTOs for /api/admin/*.
#       Read-only. No mutations. Composes TraceService, EventQueryService,
#       LifecycleRouter patterns. No new SQL aggregation loops.
# ############################################################################

# START_MODULE_CONTRACT
# purpose: Build the read-side DTOs for the admin SPA: overview, packet detail,
#          runs, evidence, artifacts, logs, blocking_decision, sessions,
#          search, system health. Pure composition of existing services.
# inputs: SQLAlchemy Session + entity IDs.
# returns: Plain dicts (DTOs). None when the entity is not found.
# side_effects: None.
# emitted_logs: None.
# error_behavior: Never raises; returns None / empty dict on miss.
# END_MODULE_CONTRACT

# START_MODULE_MAP
# mapping:
#   - class: AdminAggregationService
# END_MODULE_MAP

from __future__ import annotations

import json
import os
import re
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from sqlalchemy import text
from sqlalchemy.orm import Session

from grace_control.db.schema import (
    Event,
    Feature,
    Packet,
    PacketRun,
    Wave,
    Worker,
)


def _iso(dt: datetime | None) -> str | None:
    if dt is None:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.isoformat().replace("+00:00", "Z")


def _now() -> datetime:
    return datetime.now(timezone.utc)


# Packet states where the Blocking decision section should be visible.
_BLOCKING_STATES = frozenset([
    "rejected", "failed", "blocked", "blocked_recoverable", "blocked_final",
])


# Ordered list of packet states for the by_state count.
_PACKET_STATES = [
    "draft", "ready", "running", "accepted", "merged",
    "rejected", "failed", "blocked", "blocked_recoverable", "blocked_final",
    "cancelled",
]


def _elapsed_seconds(started_at: datetime | None, finished_at: datetime | None) -> int | None:
    if started_at is None:
        return None
    end = finished_at or _now()
    if started_at.tzinfo is None:
        started_at = started_at.replace(tzinfo=timezone.utc)
    if end.tzinfo is None:
        end = end.replace(tzinfo=timezone.utc)
    return max(0, int((end - started_at).total_seconds()))


def _is_running(status: str | None, started_at: datetime | None, finished_at: datetime | None) -> bool:
    if status and status not in ("completed", "accepted", "merged", "rejected", "failed", "blocked", "cancelled"):
        return True
    if started_at is not None and finished_at is None and status in (None, "running", ""):
        return True
    return False


def _classify_artifact(name: str) -> str:
    ext = Path(name).suffix.lower()
    if ext in (".png", ".jpg", ".jpeg", ".gif", ".svg", ".webp"):
        return "image"
    if ext in (".log", ".txt", ".md"):
        return "log"
    if ext in (".json",):
        return "json"
    if ext in (".har",):
        return "har"
    return "file"


def _build_artifact_tree(evidence_dir: Path) -> list[dict[str, Any]]:
    """Build a nested tree of files under evidence_dir (size in bytes)."""
    if not evidence_dir.exists():
        return []
    nodes: dict[str, dict[str, Any]] = {}

    def ensure_dir(rel: str) -> dict[str, Any]:
        if rel == "":
            return nodes.setdefault("", {"name": "", "type": "dir", "size": 0, "children": []})
        if rel in nodes:
            return nodes[rel]
        parent_rel = str(Path(rel).parent)
        if parent_rel == ".":
            parent_rel = ""
        parent_node = ensure_dir(parent_rel)
        node = {"name": Path(rel).name, "type": "dir", "size": 0, "children": []}
        parent_node["children"].append(node)
        nodes[rel] = node
        return node

    for f in sorted(evidence_dir.rglob("*")):
        if not f.is_file():
            continue
        rel = f.relative_to(evidence_dir)
        rel_str = str(rel)
        parent_rel = str(rel.parent)
        if parent_rel == ".":
            parent_rel = ""
        parent = ensure_dir(parent_rel)
        node = {
            "name": f.name,
            "type": "file",
            "size": f.stat().st_size,
            "kind": _classify_artifact(f.name),
        }
        parent["children"].append(node)

    return nodes[""]["children"] if "" in nodes else []


class AdminAggregationService:
    """Read-only aggregator for the admin SPA. Composes existing services."""

    # ── overview ─────────────────────────────────────────────────────────

    def get_overview(self, db: Session) -> dict[str, Any]:
        try:
            state_counts: dict[str, int] = {s: 0 for s in _PACKET_STATES}
            for row in db.query(Packet.state, Packet.id).all():
                st = row.state or "draft"
                state_counts[st] = state_counts.get(st, 0) + 1

            total_features = db.query(Feature).count()
            total_waves = db.query(Wave).count()
            total_packets = db.query(Packet).count()

            recent_events_rows = (
                db.query(Event)
                .order_by(Event.timestamp.desc())
                .limit(20)
                .all()
            )
            recent_events = [
                {
                    "id": e.id,
                    "timestamp": _iso(e.timestamp),
                    "event_type": e.event_type,
                    "entity_type": e.entity_type,
                    "entity_id": e.entity_id,
                    "reason": (e.payload_json or {}).get("reason", ""),
                    "trace_id": e.trace_id or "",
                }
                for e in recent_events_rows
            ]

            blocked_rows = (
                db.query(Packet)
                .filter(Packet.state.in_(["blocked", "blocked_recoverable", "blocked_final"]))
                .limit(50)
                .all()
            )
            blocked = [
                {
                    "id": p.id,
                    "title": p.title,
                    "state": p.state,
                    "attempt_count": p.attempt_count,
                    "max_attempts": p.max_attempts,
                    "updated_at": _iso(p.updated_at),
                }
                for p in blocked_rows
            ]

            worker_rows = db.query(Worker).all()
            workers = []
            for w in worker_rows:
                workers.append({
                    "id": w.id,
                    "status": w.status,
                    "current_packet_id": w.current_packet_id,
                    "last_heartbeat": _iso(w.last_heartbeat),
                    "started_at": _iso(w.started_at),
                    "current_elapsed": _elapsed_seconds(w.last_heartbeat, None),
                })

            return {
                "stats": {
                    "features": total_features,
                    "waves": total_waves,
                    "packets": total_packets,
                    "by_state": state_counts,
                    "workers": len([w for w in workers if w["status"] == "active"]),
                },
                "health": self.get_system_health(),
                "recent_events": recent_events,
                "blocked": blocked,
                "workers": workers,
                "fetched_at": _iso(_now()),
            }
        except Exception:
            return {
                "stats": {"by_state": {s: 0 for s in _PACKET_STATES}, "workers": 0},
                "health": self.get_system_health(),
                "recent_events": [],
                "blocked": [],
                "workers": [],
                "fetched_at": _iso(_now()),
            }

    # ── packet detail ────────────────────────────────────────────────────

    def get_packet_detail(self, db: Session, packet_id: str) -> dict[str, Any] | None:
        p = db.query(Packet).filter_by(id=packet_id).first()
        if not p:
            return None

        runs = (
            db.query(PacketRun)
            .filter_by(packet_id=packet_id)
            .order_by(PacketRun.run_number)
            .all()
        )
        last_run = runs[-1] if runs else None
        recommendation = self._recommend(p, last_run)

        sessions_summary = self.get_packet_sessions(db, packet_id)

        runs_summary = [
            {
                "run_id": r.id,
                "run_number": r.run_number,
                "executor_id": r.executor_id or "",
                "status": r.status,
                "duration_ms": r.duration_ms or 0,
                "started_at": _iso(r.started_at),
                "finished_at": _iso(r.finished_at),
            }
            for r in runs
        ]

        return {
            "packet": {
                "id": p.id,
                "feature_id": p.feature_id,
                "wave_id": p.wave_id,
                "slug": p.slug,
                "title": p.title,
                "state": p.state,
                "acceptance_profile": p.acceptance_profile,
                "attempt_count": p.attempt_count,
                "max_attempts": p.max_attempts,
                "created_at": _iso(p.created_at),
                "updated_at": _iso(p.updated_at),
            },
            "worker_id": (last_run.worker_id if last_run else "") or "",
            "model": (last_run.model if last_run else "") or "",
            "started_at": _iso(last_run.started_at) if last_run else None,
            "elapsed_seconds": _elapsed_seconds(last_run.started_at, last_run.finished_at) if last_run else None,
            "is_running": _is_running(last_run.status if last_run else None, last_run.started_at if last_run else None, last_run.finished_at if last_run else None) if last_run else False,
            "recovery": self._recovery_dict(last_run),
            "recommendation": recommendation,
            "sessions_summary": sessions_summary,
            "runs_summary": runs_summary,
            "blocking_decision": self.get_packet_blocking_decision(db, packet_id),
            "state_machine": self._derive_state_machine(db, p, runs),
            "pipeline": self._derive_pipeline(db, p, runs),
        }

    def _derive_pipeline(
        self,
        db: Session,
        p: Packet,
        runs: list[PacketRun],
    ) -> dict[str, Any]:
        """Derive the GRACE operator pipeline view from real data.

        Stages (in order):
          1. Materialized       — packet.created_at
          2. Executor selected  — last_run.executor_id
          3. Coder run          — last_run (started_at → finished_at, or running)
          4. T0 scope/lint      — evidence.stages (T0_SCOPE_AND_LINT)
          5. T1 tests           — evidence.stages (T1_UNIT_TESTS)
          6. T2 smoke/e2e       — evidence.stages (T2_E2E_OR_SMOKE)
          7. Evidence verifier  — STRICT profile / verifier_decision events
          8. Reviewer gate      — release:rejected/accepted events
          9. Merge / finish     — final packet state

        Each stage has: key, label, status (done/running/failed/skipped/pending),
        started_at, finished_at, duration_ms, meta (role/component),
        target_tab (which tab to open for inspection).
        """
        created_at = _iso(p.created_at)
        last_run = runs[-1] if runs else None

        # Load all events for this packet (used for reviewer gate, verifier,
        # coder-run boundaries, etc.)
        events = (
            db.query(Event)
            .filter(Event.entity_id == p.id)
            .order_by(Event.timestamp.asc())
            .all()
        )

        # 1. Materialized
        materialized = {
            "key": "materialized",
            "label": "Materialized",
            "status": "done",
            "started_at": created_at,
            "finished_at": created_at,
            "duration_ms": 0,
            "meta": p.slug or "",
            "target_tab": "spec",
        }

        # 2. Executor selected
        if last_run and last_run.executor_id:
            executor_stage = {
                "key": "executor",
                "label": "Executor selected",
                "status": "done",
                "started_at": _iso(last_run.started_at),
                "finished_at": _iso(last_run.started_at),
                "duration_ms": 0,
                "meta": last_run.executor_id,
                "target_tab": "attempts",
            }
        else:
            # derive from first packet_claimed event
            first_claim = next(
                (e for e in events if e.event_type == "packet_claimed"), None
            )
            if first_claim and first_claim.payload_json:
                executor = (first_claim.payload_json or {}).get("executor_id", "") or "executor"
            else:
                executor = ""
            executor_stage = {
                "key": "executor",
                "label": "Executor selected",
                "status": "done" if executor else "skipped",
                "started_at": _iso(first_claim.timestamp) if first_claim else None,
                "finished_at": _iso(first_claim.timestamp) if first_claim else None,
                "duration_ms": 0,
                "meta": executor,
                "target_tab": "attempts",
            }

        # 3. Coder run — last attempt, derive from claim → next transition
        coder_run_stage = self._stage_coder_run(events, last_run, p)

        # 4-6. T0/T1/T2 — from evidence (if any) or "not in profile"
        evidence = self.get_packet_evidence(db, p.id, run_id=str(last_run.run_number)) if last_run else {"stages": []}
        ev_stages = {st.get("name", "").upper(): st for st in (evidence.get("stages") or [])}
        acceptance_profile = p.acceptance_profile or "NORMAL"
        t_stages = self._stage_acceptance(ev_stages, acceptance_profile)

        # 7. Evidence verifier
        verifier_stage = self._stage_verifier(events, last_run, acceptance_profile, p)

        # 8. Reviewer gate
        reviewer_stage = self._stage_reviewer(events, last_run, p)

        # 9. Merge / finish
        merge_stage = self._stage_merge(events, last_run, p)

        stages = [
            materialized,
            executor_stage,
            coder_run_stage,
            *t_stages,
            verifier_stage,
            reviewer_stage,
            merge_stage,
        ]

        return {
            "stages": stages,
            "has_started": coder_run_stage["status"] != "pending",
            "has_acceptance_data": any(
                s["status"] in ("done", "failed", "running") for s in t_stages
            ),
            "has_reviewer": reviewer_stage["status"] in ("done", "failed", "running"),
        }

    def _stage_coder_run(
        self,
        events: list[Event],
        last_run: PacketRun | None,
        p: Packet,
    ) -> dict[str, Any]:
        """Derive the Coder run stage: time from claim to first transition."""
        # Find the most recent claim → next transition pair
        last_claim_idx: int | None = None
        for i, e in enumerate(events):
            if e.event_type == "packet_claimed":
                last_claim_idx = i
        if last_claim_idx is None:
            # No claim yet
            return {
                "key": "coder_run",
                "label": "Coder run",
                "status": "pending",
                "started_at": None,
                "finished_at": None,
                "duration_ms": 0,
                "meta": "",
                "target_tab": "attempts",
            }
        claim_ev = events[last_claim_idx]
        # Find next transition event (coder finished, going to ready/release/etc.)
        next_ev = None
        for e in events[last_claim_idx + 1:]:  # type: ignore[operator]
            if e.event_type == "packet_transition":
                next_ev = e
                break
        started_at = _iso(claim_ev.timestamp)
        finished_at = _iso(next_ev.timestamp) if next_ev else None
        duration_ms = 0
        if started_at and finished_at:
            try:
                from datetime import datetime as _dt
                t0 = _dt.fromisoformat(started_at.replace("Z", "+00:00"))
                t1 = _dt.fromisoformat(finished_at.replace("Z", "+00:00"))
                duration_ms = max(0, int((t1 - t0).total_seconds() * 1000))
            except (ValueError, AttributeError):
                duration_ms = 0
        elif last_run and last_run.duration_ms and not finished_at:
            duration_ms = last_run.duration_ms

        if not next_ev and p.state == "running":
            status = "running"
        elif p.state in ("rejected", "failed", "blocked", "blocked_recoverable", "blocked_final"):
            status = "failed"
        elif finished_at:
            status = "done"
        else:
            status = "pending"

        meta = ""
        if last_run and last_run.worker_id:
            meta = last_run.worker_id
        elif claim_ev.payload_json:
            meta = (claim_ev.payload_json or {}).get("worker_id", "") or ""
        if not meta:
            meta = f"attempt {p.attempt_count}/{p.max_attempts}"

        return {
            "key": "coder_run",
            "label": "Coder run",
            "status": status,
            "started_at": started_at,
            "finished_at": finished_at,
            "duration_ms": duration_ms,
            "meta": meta,
            "target_tab": "attempts",
        }

    def _stage_acceptance(
        self,
        ev_stages: dict[str, dict[str, Any]],
        acceptance_profile: str,
    ) -> list[dict[str, Any]]:
        """Build T0/T1/T2 stage cards.

        If acceptance_profile is NORMAL/FAST (no separate evidence file), the
        stages are marked as 'skipped' with 'no separate run' meta.
        If STRICT, we look for evidence.stages entries."""
        out: list[dict[str, Any]] = []
        for stage_key, stage_name, label in [
            ("T0_SCOPE_AND_LINT", "t0", "T0 scope/lint"),
            ("T1_UNIT_TESTS", "t1", "T1 tests"),
            ("T2_E2E_OR_SMOKE", "t2", "T2 smoke/e2e"),
        ]:
            ev = ev_stages.get(stage_key)
            if ev is None:
                # No evidence recorded
                if acceptance_profile == "NORMAL" or acceptance_profile == "FAST":
                    status = "skipped"
                    meta = "no separate run (NORMAL profile)"
                else:
                    status = "pending"
                    meta = "no command configured"
                out.append({
                    "key": stage_name,
                    "label": label,
                    "status": status,
                    "started_at": None,
                    "finished_at": None,
                    "duration_ms": 0,
                    "meta": meta,
                    "target_tab": "evidence",
                })
                continue
            # ev has name, status (passed/failed), summary, blocking_issues
            ev_status = (ev.get("status") or "").lower()
            if ev_status == "passed":
                status = "done"
            elif ev_status == "failed":
                status = "failed"
            else:
                status = "running" if ev_status in ("running", "started") else "pending"
            meta_parts: list[str] = []
            if ev.get("summary"):
                meta_parts.append(str(ev["summary"])[:60])
            if ev.get("blocking_issues"):
                meta_parts.append(f"{len(ev['blocking_issues'])} blocking")
            out.append({
                "key": stage_name,
                "label": label,
                "status": status,
                "started_at": None,
                "finished_at": None,
                "duration_ms": 0,
                "meta": " · ".join(meta_parts) if meta_parts else ev_status or "",
                "target_tab": "evidence",
            })
        return out

    def _stage_verifier(
        self,
        events: list[Event],
        last_run: PacketRun | None,
        acceptance_profile: str,
        p: Packet,
    ) -> dict[str, Any]:
        """Evidence verifier stage. Only STRICT profile runs this."""
        if acceptance_profile != "STRICT":
            return {
                "key": "verifier",
                "label": "Evidence verifier",
                "status": "skipped",
                "started_at": None,
                "finished_at": None,
                "duration_ms": 0,
                "meta": f"not in profile ({acceptance_profile})",
                "target_tab": "evidence",
            }
        # Look for verifier events
        verifier_events = [
            e for e in events
            if (e.component or "") == "evidence_service"
            or "verifier" in (e.event_type or "").lower()
        ]
        if not verifier_events:
            return {
                "key": "verifier",
                "label": "Evidence verifier",
                "status": "pending",
                "started_at": None,
                "finished_at": None,
                "duration_ms": 0,
                "meta": "STRICT profile active",
                "target_tab": "evidence",
            }
        last = verifier_events[-1]
        return {
            "key": "verifier",
            "label": "Evidence verifier",
            "status": "done" if p.state != "running" else "running",
            "started_at": _iso(last.timestamp),
            "finished_at": _iso(last.timestamp),
            "duration_ms": 0,
            "meta": last.reason or last.event_type,
            "target_tab": "evidence",
        }

    def _stage_reviewer(
        self,
        events: list[Event],
        last_run: PacketRun | None,
        p: Packet,
    ) -> dict[str, Any]:
        """Reviewer gate stage. Derived from 'release:rejected'/'release:accepted'
        reasons in packet_transition events."""
        review_events = [
            e for e in events
            if e.event_type == "packet_transition"
            and ((e.payload_json or {}).get("reason") or "").startswith("release:")
        ]
        if not review_events:
            if p.state in ("draft", "ready"):
                return {
                    "key": "reviewer",
                    "label": "Reviewer gate",
                    "status": "pending",
                    "started_at": None,
                    "finished_at": None,
                    "duration_ms": 0,
                    "meta": "not started",
                    "target_tab": "events",
                }
            return {
                "key": "reviewer",
                "label": "Reviewer gate",
                "status": "pending",
                "started_at": None,
                "finished_at": None,
                "duration_ms": 0,
                "meta": "",
                "target_tab": "events",
            }
        last = review_events[-1]
        reason = (last.payload_json or {}).get("reason", "") or ""
        decision = reason.split(":", 1)[-1].upper() if ":" in reason else reason.upper()
        if "accepted" in reason or "merged" in reason:
            status = "done"
        elif "rejected" in reason:
            status = "failed"
        else:
            status = "pending"
        return {
            "key": "reviewer",
            "label": "Reviewer gate",
            "status": status,
            "started_at": _iso(last.timestamp),
            "finished_at": _iso(last.timestamp),
            "duration_ms": 0,
            "meta": decision or last.event_type,
            "target_tab": "events",
        }

    def _stage_merge(
        self,
        events: list[Event],
        last_run: PacketRun | None,
        p: Packet,
    ) -> dict[str, Any]:
        """Merge / finish stage. Status derived from packet.state."""
        if p.state in ("merged", "accepted"):
            return {
                "key": "merge",
                "label": "Merge",
                "status": "done",
                "started_at": _iso(p.updated_at),
                "finished_at": _iso(p.updated_at),
                "duration_ms": 0,
                "meta": p.state,
                "target_tab": "attempts",
            }
        if p.state in ("rejected", "failed"):
            return {
                "key": "merge",
                "label": "Merge",
                "status": "skipped",
                "started_at": None,
                "finished_at": None,
                "duration_ms": 0,
                "meta": "not reached",
                "target_tab": "events",
            }
        if p.state in ("blocked", "blocked_recoverable", "blocked_final"):
            return {
                "key": "merge",
                "label": "Merge",
                "status": "skipped",
                "started_at": None,
                "finished_at": None,
                "duration_ms": 0,
                "meta": "blocked",
                "target_tab": "events",
            }
        # draft / ready / running
        return {
            "key": "merge",
            "label": "Merge",
            "status": "pending",
            "started_at": None,
            "finished_at": None,
            "duration_ms": 0,
            "meta": "",
            "target_tab": "events",
        }

    # ── blocking decision ─────────────────────────────────────────────────

    def get_packet_blocking_decision(self, db: Session, packet_id: str) -> dict[str, Any] | None:
        p = db.query(Packet).filter_by(id=packet_id).first()
        if not p or p.state not in _BLOCKING_STATES:
            return None

        last_run = (
            db.query(PacketRun)
            .filter_by(packet_id=packet_id)
            .order_by(PacketRun.run_number.desc())
            .first()
        )
        if last_run is None:
            return {
                "has_blocking": True, "state": p.state,
                "decided_by": None, "action": None, "reason": None, "at": None,
                "last_failure": None,
            }

        rec = (last_run.result_json or {}).get("recovery") or {}
        last_failure = self._last_failure_from_run(last_run)

        decided_by = self._detect_decision_component(db, packet_id, p.state)
        action = rec.get("action", "") or None
        reason = rec.get("reason", "") or last_run.result_json.get("acceptance_report", {}).get("summary", "") if last_run.result_json else None

        return {
            "has_blocking": True,
            "state": p.state,
            "decided_by": decided_by,
            "action": action,
            "reason": reason,
            "at": _iso(last_run.finished_at) or _iso(last_run.started_at),
            "last_failure": last_failure,
        }

    def _detect_decision_component(self, db: Session, packet_id: str, state: str) -> str | None:
        if state not in _BLOCKING_STATES:
            return None
        last_recovery = (
            db.query(Event)
            .filter(Event.entity_id == packet_id, Event.event_type.like("recovery_%"))
            .order_by(Event.timestamp.desc())
            .first()
        )
        if last_recovery:
            et = last_recovery.event_type
            if et in ("recovery_classified", "recovery_decision_made", "recovery_retry_same_coder",
                      "recovery_switch_coder", "recovery_return_to_architect", "recovery_escalate_architect",
                      "recovery_retry_verifier", "recovery_retry_reviewer", "recovery_retry_merge",
                      "recovery_block_feature", "recovery_no_action", "recovery_apply_failed"):
                payload = last_recovery.payload_json or {}
                comp = payload.get("component", "") or payload.get("decided_by", "")
                if comp:
                    return comp
                if et == "recovery_block_feature":
                    return "feature_recovery"
                return "recovery_controller"
        if state in ("rejected", "failed"):
            return "acceptance_pipeline"
        return None

    def _last_failure_from_run(self, run: PacketRun) -> dict[str, Any] | None:
        rj = run.result_json or {}
        acc = rj.get("acceptance_report") or {}
        stages = acc.get("stages", []) or []
        blocking_issues: list[str] = []
        for stage in stages:
            for issue in stage.get("blocking_issues", []) or []:
                blocking_issues.append(issue)
        if not blocking_issues and not acc.get("summary"):
            cmd_failures = []
        else:
            cmd_failures = []
            for stage in stages:
                for cmd in stage.get("commands", []) or []:
                    if (cmd.get("exit_code") or 0) != 0 or cmd.get("timed_out"):
                        cmd_failures.append({
                            "command": cmd.get("command", ""),
                            "exit_code": cmd.get("exit_code", -1),
                            "stderr_tail": self._tail_text(cmd.get("stderr", "") or "", 30),
                            "stdout_tail": self._tail_text(cmd.get("stdout", "") or "", 30),
                        })

        stderr_tail = self._tail_text(rj.get("legacy_result", {}).get("stderr", "") if isinstance(rj.get("legacy_result"), dict) else "", 30)
        command_preview = list(run.command_preview or [])
        prompt = run.prompt or ""

        if not (blocking_issues or acc.get("summary") or stderr_tail or cmd_failures):
            return None

        return {
            "stage": "acceptance" if acc else "executor",
            "summary": acc.get("summary", "") or rj.get("reason", "") if isinstance(rj, dict) else "",
            "blocking_issues": blocking_issues,
            "command_failures": cmd_failures,
            "stderr_tail": stderr_tail,
            "command_preview": command_preview,
            "model": run.model or "",
            "prompt_preview": self._tail_text(prompt, 30),
        }

    @staticmethod
    def _tail_text(s: str, n: int) -> str:
        if not s:
            return ""
        lines = s.splitlines()
        return "\n".join(lines[-n:]) if len(lines) > n else s

    # ── timeline ─────────────────────────────────────────────────────────

    def get_packet_timeline(
        self, db: Session, packet_id: str, limit: int = 200, offset: int = 0
    ) -> dict[str, Any]:
        q = db.query(Event).filter(Event.entity_id == packet_id)
        total = q.count()
        rows = (
            q.order_by(Event.timestamp.desc())
            .offset(offset)
            .limit(limit)
            .all()
        )
        events = [
            {
                "id": e.id,
                "timestamp": _iso(e.timestamp),
                "event_type": e.event_type,
                "entity_type": e.entity_type,
                "entity_id": e.entity_id,
                "component": (e.payload_json or {}).get("component", "") or "",
                "reason": (e.payload_json or {}).get("reason", "") or "",
                "payload": e.payload_json or {},
                "trace_id": e.trace_id or "",
            }
            for e in rows
        ]
        return {"total": total, "limit": limit, "offset": offset, "events": events}

    # ── runs ─────────────────────────────────────────────────────────────

    def get_packet_runs(self, db: Session, packet_id: str) -> dict[str, Any]:
        runs = (
            db.query(PacketRun)
            .filter_by(packet_id=packet_id)
            .order_by(PacketRun.run_number)
            .all()
        )
        out = []
        for r in runs:
            out.append({
                "run_id": r.id,
                "run_number": r.run_number,
                "worker_id": r.worker_id or "",
                "executor_id": r.executor_id or "",
                "model": r.model or "",
                "status": r.status,
                "duration_ms": r.duration_ms or 0,
                "started_at": _iso(r.started_at),
                "finished_at": _iso(r.finished_at),
                "elapsed_seconds": _elapsed_seconds(r.started_at, r.finished_at),
                "is_running": _is_running(r.status, r.started_at, r.finished_at),
            })
        return {"runs": out}

    def get_packet_run(self, db: Session, packet_id: str, run_id: str) -> dict[str, Any] | None:
        r = db.query(PacketRun).filter_by(id=f"{packet_id}-{run_id}").first()
        if not r:
            return None
        ep = Path(r.evidence_path) if r.evidence_path else None
        artifacts_summary = {"total_files": 0, "total_size": 0, "files": []}
        if ep and ep.exists():
            files = []
            total = 0
            for f in sorted(ep.rglob("*")):
                if f.is_file():
                    rel = str(f.relative_to(ep))
                    sz = f.stat().st_size
                    total += sz
                    files.append({
                        "name": rel,
                        "type": _classify_artifact(f.name),
                        "size": sz,
                    })
            artifacts_summary = {"total_files": len(files), "total_size": total, "files": files}
        return {
            "run": {
                "run_id": r.id,
                "run_number": r.run_number,
                "packet_id": r.packet_id,
                "worker_id": r.worker_id or "",
                "executor_id": r.executor_id or "",
                "model": r.model or "",
                "status": r.status,
                "duration_ms": r.duration_ms or 0,
                "started_at": _iso(r.started_at),
                "finished_at": _iso(r.finished_at),
                "evidence_path": r.evidence_path or "",
            },
            "result_json": r.result_json or {},
            "command_preview": list(r.command_preview or []),
            "model": r.model or "",
            "prompt": r.prompt or "",
            "evidence_path": r.evidence_path or "",
            "artifacts_summary": artifacts_summary,
        }

    # ── evidence ────────────────────────────────────────────────────────

    def get_packet_evidence(
        self, db: Session, packet_id: str, run_id: str | None = None
    ) -> dict[str, Any]:
        if run_id is None:
            r = (
                db.query(PacketRun)
                .filter_by(packet_id=packet_id)
                .order_by(PacketRun.run_number.desc())
                .first()
            )
        else:
            r = db.query(PacketRun).filter_by(id=f"{packet_id}-{run_id}").first()
        if not r:
            return {"verdict": "", "summary": "", "stages": [], "screenshots": []}
        acc = (r.result_json or {}).get("acceptance_report", {}) or {}
        stages = []
        for st in acc.get("stages", []) or []:
            cmds = st.get("commands", []) or []
            failed_cmds = [c for c in cmds if (c.get("exit_code") or 0) != 0 or c.get("timed_out")]
            stages.append({
                "name": st.get("name", ""),
                "status": st.get("status", ""),
                "summary": st.get("summary", ""),
                "blocking_issues": st.get("blocking_issues", []) or [],
                "commands_summary": {
                    "passed": len(cmds) - len(failed_cmds),
                    "failed": len(failed_cmds),
                    "total": len(cmds),
                },
            })
        return {
            "verdict": acc.get("final_verdict", ""),
            "summary": acc.get("summary", ""),
            "stages": stages,
            "screenshots": [],
        }

    # ── artifacts ───────────────────────────────────────────────────────

    def get_packet_artifacts(
        self, db: Session, packet_id: str, run_id: str
    ) -> dict[str, Any]:
        r = db.query(PacketRun).filter_by(id=f"{packet_id}-{run_id}").first()
        if not r or not r.evidence_path:
            return {"tree": [], "evidence_path": ""}
        ep = Path(r.evidence_path)
        return {
            "tree": _build_artifact_tree(ep),
            "evidence_path": r.evidence_path,
        }

    def get_artifact_file(
        self, db: Session, packet_id: str, run_id: str, path: str, tail: int = 0
    ) -> tuple[bytes, str] | None:
        r = db.query(PacketRun).filter_by(id=f"{packet_id}-{run_id}").first()
        if not r or not r.evidence_path:
            return None
        evidence_dir = Path(r.evidence_path).resolve()
        target = (evidence_dir / path).resolve()
        if not target.is_file() or evidence_dir not in target.parents:
            return None
        ext = target.suffix.lower()
        if ext in (".png", ".jpg", ".jpeg", ".gif", ".svg", ".webp"):
            ctype = f"image/{'svg+xml' if ext == '.svg' else 'jpeg' if ext in ('.jpg','.jpeg') else 'gif' if ext == '.gif' else ext.lstrip('.')}"
        elif ext == ".json":
            ctype = "application/json"
        elif ext in (".log", ".txt", ".md", ".har"):
            ctype = "text/plain; charset=utf-8"
        else:
            ctype = "application/octet-stream"
        content = target.read_bytes()
        if tail > 0 and ctype.startswith("text/"):
            text_content = content.decode("utf-8", errors="replace")
            lines = text_content.splitlines()
            content = "\n".join(lines[-tail:]).encode("utf-8")
        return content, ctype

    # ── logs ────────────────────────────────────────────────────────────

    def get_packet_logs(
        self,
        db: Session,
        packet_id: str,
        run_id: str,
        stream: str = "stderr",
        tail: int = 200,
        filter_regex: str = "",
    ) -> dict[str, Any]:
        r = db.query(PacketRun).filter_by(id=f"{packet_id}-{run_id}").first()
        if not r:
            return {"lines": [], "total": 0, "truncated": False, "source_file": ""}

        ev_dir = Path(r.evidence_path) if r.evidence_path else None
        candidates: list[Path] = []
        if ev_dir and ev_dir.exists():
            for name in ("agent_output.log", "agent_stderr.log", "agent_stdout.log", "stderr.log", "stdout.log"):
                p = ev_dir / name
                if p.exists():
                    candidates.append(p)
        rj = r.result_json or {}
        if isinstance(rj.get("legacy_result"), dict):
            for key in ("stdout_path", "stderr_path"):
                p = rj["legacy_result"].get(key)
                if p:
                    pp = Path(p)
                    if pp.exists():
                        candidates.append(pp)

        if stream == "stdout":
            chosen = next((c for c in candidates if "stdout" in c.name.lower()), None)
        elif stream == "agent":
            chosen = next((c for c in candidates if c.name == "agent_output.log"), None)
        else:
            chosen = next((c for c in candidates if "stderr" in c.name.lower()), candidates[0] if candidates else None)

        if chosen is None or not chosen.exists():
            return {"lines": [], "total": 0, "truncated": False, "source_file": ""}

        text_content = chosen.read_text(errors="replace")
        lines = text_content.splitlines()
        total = len(lines)
        sliced = lines[-tail:] if tail > 0 else lines
        if filter_regex:
            try:
                rx = re.compile(filter_regex)
                sliced = [ln for ln in sliced if rx.search(ln)]
            except re.error:
                pass
        return {
            "lines": sliced,
            "total": total,
            "truncated": total > len(sliced),
            "source_file": str(chosen),
        }

    # ── sessions (forward-compat) ───────────────────────────────────────

    def get_packet_sessions(self, db: Session, packet_id: str) -> dict[str, Any]:
        try:
            row = db.execute(
                text("SELECT name FROM sqlite_master WHERE type='table' AND name='agent_sessions'")
            ).first()
        except Exception:
            row = None
        if row is None:
            return {"sessions": [], "reason": "table_missing"}
        try:
            rows = db.execute(
                text("SELECT id, external_id, role, executor_id, backend, attempt_number, status, parent_session_id, created_at, finished_at "
                     "FROM agent_sessions WHERE packet_id = :pid ORDER BY created_at"),
                {"pid": packet_id},
            ).all()
            sessions = [
                {
                    "id": r[0], "external_id": r[1] or "", "role": r[2] or "",
                    "executor_id": r[3] or "", "backend": r[4] or "",
                    "attempt_number": r[5] or 0, "status": r[6] or "",
                    "parent_session_id": r[7] or "",
                    "created_at": _iso(r[8]) if r[8] else None,
                    "finished_at": _iso(r[9]) if r[9] else None,
                }
                for r in rows
            ]
            return {"sessions": sessions, "reason": "ok"}
        except Exception:
            return {"sessions": [], "reason": "query_failed"}

    # ── feature summary ─────────────────────────────────────────────────

    def get_feature_summary(self, db: Session, feature_id: str) -> dict[str, Any] | None:
        f = db.query(Feature).filter_by(id=feature_id).first()
        if not f:
            return None
        waves = (
            db.query(Wave)
            .filter_by(feature_id=feature_id)
            .order_by(Wave.order)
            .all()
        )
        packets = db.query(Packet).filter_by(feature_id=feature_id).all()
        packets_by_wave: dict[str, list[dict[str, Any]]] = {w.id: [] for w in waves}
        for p in packets:
            packets_by_wave.setdefault(p.wave_id, []).append({
                "id": p.id, "slug": p.slug, "title": p.title,
                "state": p.state, "attempt_count": p.attempt_count,
            })
        wave_rows: list[dict[str, Any]] = []
        for w in waves:
            wpackets = packets_by_wave.get(w.id, [])
            w_attn = sum(
                1 for p in wpackets
                if p.get("state") in (
                    "rejected", "failed", "blocked",
                    "blocked_recoverable", "blocked_final",
                )
            )
            wave_rows.append({
                "id": w.id, "title": w.title, "order": w.order, "status": w.status,
                "packets": wpackets,
                "total_packets": len(wpackets),
                "attention_count": w_attn,
            })
        return {
            "feature": {
                "id": f.id, "slug": f.slug, "title": f.title,
                "status": f.status, "description": f.description or "",
                "created_at": _iso(f.created_at), "updated_at": _iso(f.updated_at),
            },
            "waves": wave_rows,
        }

    def get_features_tree(self, db: Session) -> dict[str, Any]:
        """Return all features with nested waves → packets. Used by Overview."""
        features = db.query(Feature).order_by(Feature.created_at).all()
        out: list[dict[str, Any]] = []
        for f in features:
            waves = (
                db.query(Wave)
                .filter_by(feature_id=f.id)
                .order_by(Wave.order)
                .all()
            )
            packets = db.query(Packet).filter_by(feature_id=f.id).all()
            packets_by_wave: dict[str, list[dict[str, Any]]] = {w.id: [] for w in waves}
            for p in packets:
                # Per-packet last run for stage + timing
                last_run = (
                    db.query(PacketRun)
                    .filter_by(packet_id=p.id)
                    .order_by(PacketRun.run_number.desc())
                    .first()
                )
                stage = self._derive_packet_stage(p, last_run)
                started_at = (
                    _iso(last_run.started_at)
                    if last_run and last_run.started_at else None
                )
                duration_seconds = (
                    _elapsed_seconds(last_run.started_at, last_run.finished_at)
                    if last_run else None
                )
                packets_by_wave.setdefault(p.wave_id, []).append({
                    "id": p.id, "slug": p.slug, "title": p.title,
                    "state": p.state, "attempt_count": p.attempt_count,
                    "max_attempts": p.max_attempts,
                    "stage": stage,
                    "started_at": started_at,
                    "duration_seconds": duration_seconds,
                })
            # Build wave rows with attention counters
            wave_rows: list[dict[str, Any]] = []
            for w in waves:
                wpackets = packets_by_wave.get(w.id, [])
                w_attn = sum(
                    1 for p in wpackets
                    if p.get("state") in (
                        "rejected", "failed", "blocked",
                        "blocked_recoverable", "blocked_final",
                    )
                )
                wave_rows.append({
                    "id": w.id, "slug": w.slug, "title": w.title,
                    "order": w.order, "status": w.status,
                    "packets": wpackets,
                    "total_packets": len(wpackets),
                    "attention_count": w_attn,
                })
            # Feature-level counters
            all_packets = [pp for wpackets in packets_by_wave.values() for pp in wpackets]
            f_attn = sum(
                1 for p in all_packets
                if p.get("state") in (
                    "rejected", "failed", "blocked",
                    "blocked_recoverable", "blocked_final",
                )
            )
            out.append({
                "id": f.id, "slug": f.slug, "title": f.title,
                "status": f.status, "description": f.description or "",
                "created_at": _iso(f.created_at), "updated_at": _iso(f.updated_at),
                "wave_count": len(wave_rows),
                "total_packets": len(all_packets),
                "attention_count": f_attn,
                "waves": wave_rows,
            })
        return {"features": out}

    def _derive_packet_stage(
        self, p: Packet, last_run: PacketRun | None
    ) -> dict[str, str]:
        """Derive the current pipeline stage for a packet.

        Returns a small dict with `label` (human stage name) and
        `key` (machine name). Used by the timeline and wave details
        to show "what stage is this packet at" without tooltips.

        Heuristic (cheap; avoids the full _derive_pipeline call per packet):
          - no run, draft/ready:        "Materialized"
          - last_run.status == running: "Coder run"
          - last_run.status == accepted
            or state in accepted/merged:"Merge"
          - last_run.status in rejected/failed
            or state in rejected/failed/blocked: "Reviewer gate"
          - default (no run, running):  "Coder run"
        """
        state = (p.state or "draft").lower()
        run_status = (last_run.status if last_run else "").lower() if last_run else ""
        if not last_run:
            if state in ("draft", "ready"):
                return {"key": "materialized", "label": "Materialized"}
            return {"key": "materialized", "label": "Not started"}
        if run_status == "running" or state == "running":
            return {"key": "coder_run", "label": "Coder run"}
        if state in ("accepted", "merged") or run_status == "accepted":
            return {"key": "merge", "label": "Merge"}
        if state in ("rejected", "failed", "blocked", "blocked_recoverable",
                     "blocked_final") or run_status in ("rejected", "failed"):
            return {"key": "reviewer", "label": "Reviewer gate"}
        return {"key": "coder_run", "label": "Coder run"}

    # ── wave detail ────────────────────────────────────────────────────

    def get_wave_detail(
        self, db: Session, feature_id: str, wave_id: str
    ) -> dict[str, Any] | None:
        """Return a single wave with its feature context and packets.

        Used by the right pane when the user clicks a wave (not a packet).
        Returns None if the wave does not exist (or is not in the feature).

        Shape:
          {
            "wave":       {id, title, slug, order, status, feature_id},
            "feature":    {id, title, slug, status},
            "counts":     {all, failed, running, blocked, attention, done},
            "packets":    [{id, title, slug, state, attempt_count, max_attempts,
                            started_at, duration_seconds, severity}, ...]
          }
        """
        feature = db.query(Feature).filter_by(id=feature_id).first()
        if not feature:
            return None
        wave = (
            db.query(Wave)
            .filter_by(id=wave_id, feature_id=feature_id)
            .first()
        )
        if not wave:
            return None

        packets = (
            db.query(Packet)
            .filter_by(wave_id=wave_id, feature_id=feature_id)
            .order_by(Packet.id)
            .all()
        )

        # Per-packet started_at / duration: take from latest run when present.
        packet_rows: list[dict[str, Any]] = []
        for p in packets:
            last_run = (
                db.query(PacketRun)
                .filter_by(packet_id=p.id)
                .order_by(PacketRun.run_number.desc())
                .first()
            )
            started_at = _iso(last_run.started_at) if last_run and last_run.started_at else None
            duration_seconds = (
                _elapsed_seconds(last_run.started_at, last_run.finished_at)
                if last_run else None
            )
            stage = self._derive_packet_stage(p, last_run)
            packet_rows.append({
                "id": p.id,
                "title": p.title,
                "slug": p.slug,
                "state": p.state,
                "attempt_count": p.attempt_count,
                "max_attempts": p.max_attempts,
                "started_at": started_at,
                "duration_seconds": duration_seconds,
                "stage": stage,
            })

        counts = {"all": len(packet_rows), "failed": 0, "running": 0,
                  "blocked": 0, "attention": 0, "done": 0}
        for p in packet_rows:
            s = p["state"]
            if s in ("rejected", "failed"):
                counts["failed"] += 1
                counts["attention"] += 1
            elif s == "running":
                counts["running"] += 1
            elif s in ("blocked", "blocked_recoverable", "blocked_final"):
                counts["blocked"] += 1
                counts["attention"] += 1
            elif s in ("accepted", "merged"):
                counts["done"] += 1

        return {
            "wave": {
                "id": wave.id,
                "title": wave.title,
                "slug": wave.slug,
                "order": wave.order,
                "status": wave.status,
                "feature_id": feature.id,
            },
            "feature": {
                "id": feature.id,
                "title": feature.title,
                "slug": feature.slug,
                "status": feature.status,
            },
            "counts": counts,
            "packets": packet_rows,
            "stage_progress": self._derive_wave_stage_progress(packet_rows),
        }

    def _derive_wave_stage_progress(
        self, packets: list[dict[str, Any]]
    ) -> list[dict[str, Any]]:
        """Aggregate per-stage packet counts for the wave progress block.

        Each entry has:
          - key: machine stage name (e.g. "materialized", "coder_run", ...)
          - label: human name (e.g. "Materialized", "Coder run", ...)
          - reached: count of packets that have reached this stage
          - total: total packets in the wave
          - severity: 'ok' / 'attention' / 'muted' for the progress bar style

        A packet is considered to have "reached" stage X if its current
        stage is X or later in the pipeline order. Pipeline order:
          1. materialized
          2. coder_run
          3. reviewer
          4. merge
        """
        stage_order = [
            ("materialized", "Materialized"),
            ("coder_run", "Coder run"),
            ("reviewer", "Reviewer gate"),
            ("merge", "Merge reached"),
        ]
        total = len(packets)
        if total == 0:
            return [
                {"key": k, "label": l, "reached": 0, "total": 0,
                 "severity": "muted"}
                for k, l in stage_order
            ]
        # Map each packet to its current stage index
        index_for = {k: i for i, (k, _) in enumerate(stage_order)}
        result: list[dict[str, Any]] = []
        for i, (key, label) in enumerate(stage_order):
            # Packets that have reached at least this stage
            reached = sum(
                1 for p in packets
                if index_for.get(p.get("stage", {}).get("key", ""), 0) >= i
            )
            if reached == total:
                severity = "ok"
            elif reached == 0:
                severity = "muted"
            else:
                severity = "attention"
            result.append({
                "key": key,
                "label": label,
                "reached": reached,
                "total": total,
                "severity": severity,
            })
        return result

    # ── search ──────────────────────────────────────────────────────────

    def search(self, db: Session, q: str, limit: int = 50) -> dict[str, Any]:
        if not q:
            return {"results": []}
        like = f"%{q}%"
        out: list[dict[str, Any]] = []
        for p in db.query(Packet).filter((Packet.id.ilike(like)) | (Packet.title.ilike(like))).limit(limit).all():
            out.append({"kind": "packet", "id": p.id, "title": p.title, "state": p.state})
        for f in db.query(Feature).filter(Feature.title.ilike(like)).limit(limit).all():
            out.append({"kind": "feature", "id": f.id, "title": f.title, "status": f.status})
        for r in db.query(PacketRun).filter(PacketRun.executor_id.ilike(like)).limit(limit).all():
            out.append({
                "kind": "run", "id": r.id, "packet_id": r.packet_id,
                "executor_id": r.executor_id or "", "status": r.status,
            })
        return {"results": out[:limit]}

    # ── system health / workers ─────────────────────────────────────────

    def get_system_health(self) -> dict[str, Any]:
        health: dict[str, Any] = {
            "supervisor_alive": False, "api_alive": True, "workers_alive": 0,
            "db_ok": True, "code_sha": "", "version": "0.1.0",
        }
        target = os.environ.get("GRACE_TARGET_DIR", "")
        if target:
            state_path = Path(target) / "supervisor.json"
            if state_path.exists():
                try:
                    st = json.loads(state_path.read_text())
                    health["supervisor_alive"] = True
                    health["workers_alive"] = len(st.get("workers", [])) if isinstance(st.get("workers"), list) else 0
                except Exception:
                    pass
        try:
            sha_proc = subprocess.run(
                ["git", "rev-parse", "--short", "HEAD"],
                capture_output=True, text=True, timeout=2,
            )
            if sha_proc.returncode == 0:
                health["code_sha"] = sha_proc.stdout.strip()
        except Exception:
            pass
        return health

    def get_workers(self, db: Session) -> dict[str, Any]:
        rows = db.query(Worker).all()
        return {
            "workers": [
                {
                    "id": w.id,
                    "status": w.status,
                    "current_packet_id": w.current_packet_id,
                    "last_heartbeat": _iso(w.last_heartbeat),
                    "started_at": _iso(w.started_at),
                    "current_elapsed": _elapsed_seconds(w.last_heartbeat, None),
                }
                for w in rows
            ]
        }

    # ── helpers ─────────────────────────────────────────────────────────

    def _recovery_dict(self, run: PacketRun | None) -> dict[str, Any] | None:
        if run is None or run.result_json is None:
            return None
        rec = run.result_json.get("recovery") or {}
        if not rec:
            return None
        return {
            "failure_class": rec.get("failure_class", ""),
            "action": rec.get("action", ""),
            "reason": rec.get("reason", ""),
            "current_executor_id": rec.get("current_executor_id", ""),
            "next_executor_hint": rec.get("next_executor_hint", ""),
            "decision_id": rec.get("decision_id", ""),
        }

    @staticmethod
    def _recommend(p: Packet, last_run: PacketRun | None) -> str:
        if p.state == "merged" or p.state == "accepted":
            return "none"
        if last_run is None:
            return "none"
        if last_run.status in ("rejected", "failed", "blocked"):
            if p.attempt_count >= p.max_attempts:
                return "manual"
            return "retry"
        return "none"

    def _derive_state_machine(
        self, db: Session, p: Packet, runs: list[PacketRun]
    ) -> dict[str, Any]:
        """Derive a 4-step lifecycle for the operator console.

        Steps: created → claimed → reviewed → result
        - created: packet.created_at
        - claimed: first run.started_at, or first packet_claimed event
        - reviewed: last run.finished_at, or last packet_transition event
        - result: current packet state

        Each step has a state (done/current/failed/blocked/pending), time, meta.
        """
        created_at = _iso(p.created_at)
        first_started = None
        last_finished = None
        last_status = None
        worker_id = ""
        for r in runs:
            if first_started is None and r.started_at is not None:
                first_started = _iso(r.started_at)
                worker_id = r.worker_id or ""
            if r.finished_at is not None:
                last_finished = _iso(r.finished_at)
                last_status = r.status

        # If no runs (legacy packets), fall back to events to derive claimed/reviewed.
        if first_started is None or last_finished is None:
            events = (
                db.query(Event)
                .filter(Event.entity_id == p.id)
                .order_by(Event.timestamp.asc())
                .all()
            )
            for ev in events:
                ts = _iso(ev.timestamp)
                pl = ev.payload_json or {}
                if ev.event_type == "packet_claimed" and first_started is None:
                    first_started = ts
                    if not worker_id:
                        worker_id = pl.get("worker_id", "") or ""
                if ev.event_type == "packet_transition":
                    last_finished = ts
                    reason = pl.get("reason", "") or ""
                    if "rejected" in reason:
                        last_status = "rejected"
                    elif "failed" in reason:
                        last_status = "failed"
                    elif "blocked" in reason:
                        last_status = "blocked"
                    elif "accepted" in reason or "merged" in reason:
                        last_status = "accepted"

        steps: list[dict[str, Any]] = []

        # 1. Created
        steps.append({
            "key": "created",
            "label": "Created",
            "state": "done",
            "time": created_at,
            "meta": "",
        })

        # 2. Claimed (by a worker)
        if first_started is not None:
            claimed_state = "current" if p.state == "running" else "done"
            steps.append({
                "key": "claimed",
                "label": "Claimed",
                "state": claimed_state,
                "time": first_started,
                "meta": worker_id or "",
            })
        else:
            steps.append({
                "key": "claimed",
                "label": "Claimed",
                "state": "pending",
                "time": None,
                "meta": "",
            })

        # 3. Reviewed (last run finished)
        if last_finished is not None:
            if last_status in ("rejected", "failed"):
                reviewed_state = "failed"
            elif last_status in ("blocked", "blocked_recoverable", "blocked_final"):
                reviewed_state = "blocked"
            elif p.state == "running":
                reviewed_state = "current"
            else:
                reviewed_state = "done"
            meta = f"{p.attempt_count}/{p.max_attempts} attempts"
            if last_status:
                meta = f"{last_status} · {meta}"
            steps.append({
                "key": "reviewed",
                "label": "Reviewed",
                "state": reviewed_state,
                "time": last_finished,
                "meta": meta,
            })
        elif p.state in ("draft", "ready"):
            steps.append({
                "key": "reviewed",
                "label": "Reviewed",
                "state": "pending",
                "time": None,
                "meta": "",
            })
        else:
            steps.append({
                "key": "reviewed",
                "label": "Reviewed",
                "state": "current",
                "time": None,
                "meta": "in progress",
            })

        # 4. Result
        terminal = p.state in (
            "accepted", "merged", "rejected", "failed",
            "blocked", "blocked_recoverable", "blocked_final", "cancelled",
        )
        if p.state in ("rejected", "failed"):
            result_state = "failed"
        elif p.state in ("blocked", "blocked_recoverable", "blocked_final"):
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
        }.get(p.state, p.state)
        steps.append({
            "key": "result",
            "label": result_label,
            "state": result_state,
            "time": _iso(p.updated_at),
            "meta": p.state,
        })

        return {"steps": steps}
