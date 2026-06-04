# ############################################################################
# AI_HEADER: cli_trace
# ROLE: CLI audit tool for execution timeline by packet/feature/wave.
# TZ-024 §3: grace trace --packet/--feature/--wave.
# ############################################################################

from __future__ import annotations

import json
from pathlib import Path

import click

from grace_control.db import get_db
from grace_control.db.schema import Event, PacketRun


def collect_events(entity_id: str, db) -> list[dict]:
    events = db.query(Event).filter_by(
        entity_id=entity_id
    ).order_by(Event.timestamp).all()
    return [{
        "ts": e.timestamp.isoformat() + "Z" if e.timestamp else "",
        "event_type": e.event_type,
        "payload": e.payload_json or {},
        "trace_id": e.trace_id,
    } for e in events]


def collect_packet_runs(packet_id: str, db) -> list[dict]:
    runs = db.query(PacketRun).filter_by(
        packet_id=packet_id
    ).order_by(PacketRun.run_number).all()
    return [{
        "run_number": r.run_number,
        "status": r.status,
        "duration_ms": r.duration_ms,
        "result": r.result_json or {},
    } for r in runs]


def collect_packets_in_feature(feature_id: str, db) -> list[str]:
    from grace_control.db.schema import Packet
    packets = db.query(Packet).filter_by(feature_id=feature_id).all()
    return [p.id for p in packets]


def collect_packets_in_wave(wave_id: str, db) -> list[str]:
    from grace_control.db.schema import Packet
    packets = db.query(Packet).filter_by(wave_id=wave_id).all()
    return [p.id for p in packets]


def format_timeline(entity_id: str, db, full: bool = False) -> str:
    events = collect_events(entity_id, db)
    runs = collect_packet_runs(entity_id, db)

    lines = [f"Timeline for: {entity_id}", "=" * 60]
    for ev in events:
        ts = ev["ts"][:19]
        etype = ev["event_type"]
        payload = ev["payload"]
        action = payload.get("action", "")
        reason = payload.get("reason", "")[:100]
        lines.append(f"{ts}  {etype:30s}  {action:25s}  {reason}")

    for run in runs:
        rj = run["result"]
        acc = rj.get("acceptance_report", {})
        ev = rj.get("evidence_verifier_report", {})
        rv = rj.get("reviewer_report", {})
        lines.append(f"  Run {run['run_number']}: {run['status']} ({run['duration_ms']}ms)")
        if acc:
            lines.append(f"    acceptance: {acc.get('final_verdict', '?')}")
            for s in acc.get("stages", []):
                lines.append(f"      {s['name']}: {s['status']}")
                for bi in s.get("blocking_issues", []):
                    lines.append(f"        BLOCKER: {bi[:150]}")
            if acc.get("evidence_issues"):
                for ei in acc["evidence_issues"]:
                    lines.append(f"        EVIDENCE: {ei}")
        if ev:
            lines.append(f"    verifier: {ev.get('verdict', '?')} — {ev.get('summary', '')[:100]}")
        if rv:
            lines.append(f"    reviewer: {rv.get('verdict', '?')} — {rv.get('summary', '')[:100]}")
        if rj.get("recovery"):
            rec = rj["recovery"]
            lines.append(f"    recovery: {rec.get('action', '?')} — {rec.get('reason', '')[:100]}")

    return "\n".join(lines)


@click.command("trace")
@click.option("--packet", "packet_id", default=None, help="Packet ID to trace")
@click.option("--feature", "feature_id", default=None, help="Feature ID to trace")
@click.option("--wave", "wave_id", default=None, help="Wave ID to trace")
@click.option("--json", "json_out", is_flag=True, help="JSON output")
@click.option("--full", "full_context", is_flag=True, help="Full context including reports")
def trace(packet_id, feature_id, wave_id, json_out, full_context):
    """Show detailed execution timeline for a packet/feature/wave."""
    entities = []
    if packet_id:
        entities = [packet_id]
    elif feature_id:
        with get_db() as db:
            entities = collect_packets_in_feature(feature_id, db)
    elif wave_id:
        with get_db() as db:
            entities = collect_packets_in_wave(wave_id, db)
    else:
        click.echo("Specify --packet, --feature, or --wave")
        return

    results = {}
    for eid in entities:
        with get_db() as db:
            events = collect_events(eid, db)
            runs = collect_packet_runs(eid, db)
            results[eid] = {"events": events, "runs": runs}

    if json_out:
        click.echo(json.dumps(results, indent=2, default=str))
        return

    for eid in entities:
        with get_db() as db:
            click.echo(format_timeline(eid, db, full=full_context))
        click.echo()
