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
                packets_by_wave.setdefault(p.wave_id, []).append({
                    "id": p.id, "slug": p.slug, "title": p.title,
                    "state": p.state, "attempt_count": p.attempt_count,
                    "max_attempts": p.max_attempts,
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
