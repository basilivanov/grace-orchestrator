"""Service for aggregating logs from 7 sources, filtered by trace_id/level/source."""
from __future__ import annotations

import json
import re
from datetime import datetime
from pathlib import Path

from grace_control.core.structured_logger import GraceLogger
from grace_control.db import get_db
from grace_control.db.schema import Event, StageRun, PacketRun

_log = GraceLogger("aggregated_logs")

AGGREGATED_LOG_SOURCES = frozenset([
    "server", "supervisor", "worker_stdout", "worker_stderr",
    "agent", "recovery", "db_events",
])


class AggregatedLines:
    __slots__ = ("ts", "source", "level", "trace_id", "msg")

    def __init__(self, ts: str, source: str, level: str, trace_id: str | None, msg: str):
        self.ts = ts
        self.source = source
        self.level = level
        self.trace_id = trace_id
        self.msg = msg


def get_aggregated_logs(
    packet_id: str,
    *,
    sources: list[str] | None = None,
    tail: int = 500,
    level: str | None = None,
    trace_id: str | None = None,
    regex: str | None = None,
    since: str | None = None,
    until: str | None = None,
) -> dict:
    if sources is None or "all" in sources:
        sources = list(AGGREGATED_LOG_SOURCES)

    all_lines: list[AggregatedLines] = []
    sources_used: list[str] = []
    time_min: str | None = None
    time_max: str | None = None

    source_set = set(sources)

    parser = re.compile(regex) if regex else None

    # 1. Server logs: /tmp/api*.log
    if "server" in source_set:
        server_lines = _read_server_logs(packet_id, tail)
        all_lines.extend(server_lines)
        if server_lines:
            sources_used.append("server")

    # 2. Supervisor logs: /tmp/supervisor.log
    if "supervisor" in source_set:
        sup_lines = _read_supervisor_logs(packet_id, tail)
        all_lines.extend(sup_lines)
        if sup_lines:
            sources_used.append("supervisor")

    # 3,4. Worker stdout/stderr
    if "worker_stdout" in source_set or "worker_stderr" in source_set:
        worker_lines = _read_worker_logs(packet_id, tail, include_stdout="worker_stdout" in source_set, include_stderr="worker_stderr" in source_set)
        all_lines.extend(worker_lines)
        if worker_lines:
            sources_used.append("worker_stdout") if any(l.source == "worker_out" for l in worker_lines) else None
            sources_used.append("worker_stderr") if any(l.source == "worker_err" for l in worker_lines) else None

    # 5. Agent runtime JSONL
    if "agent" in source_set:
        agent_lines = _read_agent_logs(packet_id, tail)
        all_lines.extend(agent_lines)
        if agent_lines:
            sources_used.append("agent")

    # 6. Recovery events
    if "recovery" in source_set:
        recovery_lines = _read_recovery_events(packet_id, tail)
        all_lines.extend(recovery_lines)
        if recovery_lines:
            sources_used.append("recovery")

    # 7. DB events
    if "db_events" in source_set:
        db_lines = _read_db_events(packet_id, tail)
        all_lines.extend(db_lines)
        if db_lines:
            sources_used.append("db_events")

    # Sort by timestamp
    all_lines.sort(key=lambda x: x.ts)

    # Apply filters
    if level and level != "all":
        all_lines = [l for l in all_lines if l.level == level]
    if trace_id:
        all_lines = [l for l in all_lines if l.trace_id and trace_id in l.trace_id]
    if parser:
        all_lines = [l for l in all_lines if parser.search(l.msg)]

    # Tail
    if len(all_lines) > tail:
        all_lines = all_lines[-tail:]

    if all_lines:
        time_min = all_lines[0].ts
        time_max = all_lines[-1].ts

    truncated = len(all_lines) > tail

    return {
        "lines": [
            {"ts": l.ts, "source": l.source, "level": l.level, "trace_id": l.trace_id, "msg": l.msg}
            for l in all_lines
        ],
        "total": len(all_lines),
        "truncated": truncated,
        "sources_used": sorted(set(sources_used)),
        "time_range": {"min": time_min, "max": time_max} if time_min else None,
    }


def _read_server_logs(packet_id: str, tail: int) -> list[AggregatedLines]:
    lines: list[AggregatedLines] = []
    for log_path in Path("/tmp").glob("api*.log"):
        try:
            text = log_path.read_text(errors="replace")
            for line in text.split("\n")[-tail:]:
                if not line.strip():
                    continue
                if packet_id in line:
                    lines.append(_parse_server_line(line))
        except (OSError, IOError):
            pass
    return lines


def _parse_server_line(line: str) -> AggregatedLines:
    ts = ""
    level = "info"
    trace_id = None
    if line[:19].count("-") >= 2:
        ts = line[:23] if "T" in line[:25] else line[:19]
    level_str = line.lower()
    if "error" in level_str:
        level = "error"
    elif "warn" in level_str:
        level = "warn"
    return AggregatedLines(ts=ts, source="server", level=level, trace_id=trace_id, msg=line.strip())


def _read_supervisor_logs(packet_id: str, tail: int) -> list[AggregatedLines]:
    lines: list[AggregatedLines] = []
    for path in [Path("/tmp/supervisor.log")]:
        try:
            text = path.read_text(errors="replace")
            for line in text.split("\n")[-tail:]:
                if not line.strip():
                    continue
                if packet_id in line:
                    level = "info"
                    if "error" in line.lower():
                        level = "error"
                    elif "warn" in line.lower():
                        level = "warn"
                    lines.append(AggregatedLines(ts="", source="supervisor", level=level, trace_id=None, msg=line.strip()))
        except (OSError, IOError):
            pass
    return lines


def _read_worker_logs(packet_id: str, tail: int, include_stdout: bool, include_stderr: bool) -> list[AggregatedLines]:
    lines: list[AggregatedLines] = []
    with get_db() as db:
        runs = db.query(PacketRun).filter_by(packet_id=packet_id).order_by(PacketRun.run_number.desc()).limit(3).all()
        for run in runs:
            if not run.evidence_path:
                continue
            ev_path = Path(run.evidence_path)
            if include_stdout:
                stdout_file = ev_path / "stdout.log"
                if stdout_file.exists():
                    for line in _tail_file(stdout_file, tail):
                        lines.append(AggregatedLines(ts="", source="worker_out", level="info", trace_id=None, msg=line.strip()))
            if include_stderr:
                stderr_file = ev_path / "stderr.log"
                if stderr_file.exists():
                    for line in _tail_file(stderr_file, tail):
                        level = "info"
                        if "error" in line.lower():
                            level = "error"
                        lines.append(AggregatedLines(ts="", source="worker_err", level=level, trace_id=None, msg=line.strip()))
    return lines


def _read_agent_logs(packet_id: str, tail: int) -> list[AggregatedLines]:
    lines: list[AggregatedLines] = []
    with get_db() as db:
        runs = db.query(PacketRun).filter_by(packet_id=packet_id).order_by(PacketRun.run_number.desc()).limit(3).all()
        for run in runs:
            if not run.evidence_path:
                continue
            ev_path = Path(run.evidence_path)
            agent_file = ev_path / "agent.jsonl"
            if not agent_file.exists():
                agent_file = ev_path / "raw_opencode_events.jsonl"
            if agent_file.exists():
                for line in _tail_file(agent_file, tail):
                    try:
                        ev = json.loads(line)
                        msg = ev.get("message") or ev.get("event", "") or line.strip()[:200]
                        ts = ev.get("ts", ev.get("timestamp", ""))
                        trace = ev.get("trace_id")
                        if isinstance(ts, int):
                            ts = datetime.fromtimestamp(ts).isoformat()
                        level = "info"
                        if "error" in str(ev).lower():
                            level = "error"
                        elif "warn" in str(ev).lower():
                            level = "warn"
                        lines.append(AggregatedLines(ts=str(ts)[:26], source="agent", level=level, trace_id=str(trace) if trace else None, msg=str(msg)[:500]))
                    except json.JSONDecodeError:
                        lines.append(AggregatedLines(ts="", source="agent", level="info", trace_id=None, msg=line.strip()[:200]))
    return lines


def _read_recovery_events(packet_id: str, tail: int) -> list[AggregatedLines]:
    lines: list[AggregatedLines] = []
    with get_db() as db:
        events = db.query(Event).filter(
            Event.entity_id == packet_id,
            Event.event_type.like("recovery_%")
        ).order_by(Event.timestamp.desc()).limit(tail).all()
        for ev in events:
            ts = ev.timestamp.isoformat() if ev.timestamp else ""
            payload = dict(ev.payload_json or {})
            msg = f"{ev.event_type}: {json.dumps(payload, default=str)[:500]}"
            lines.append(AggregatedLines(ts=ts, source="recovery", level="info", trace_id=ev.trace_id, msg=msg))
    return lines


def _read_db_events(packet_id: str, tail: int) -> list[AggregatedLines]:
    lines: list[AggregatedLines] = []
    with get_db() as db:
        events = db.query(Event).filter(
            Event.entity_id == packet_id,
            ~Event.event_type.like("recovery_%")
        ).order_by(Event.timestamp.desc()).limit(tail).all()
        for ev in events:
            ts = ev.timestamp.isoformat() if ev.timestamp else ""
            payload = dict(ev.payload_json or {})
            msg = f"{ev.event_type}: {json.dumps(payload, default=str)[:500]}"
            lines.append(AggregatedLines(ts=ts, source="db_events", level="info", trace_id=ev.trace_id, msg=msg))
    return lines


def _tail_file(path: Path, n: int) -> list[str]:
    try:
        text = path.read_text(errors="replace")
        return text.split("\n")[-n:]
    except (OSError, IOError):
        return []
