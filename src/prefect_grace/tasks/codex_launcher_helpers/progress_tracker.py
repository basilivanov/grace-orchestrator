# AI_HEADER: codex_launcher_helpers
# START_MODULE_CONTRACT
# END_MODULE_CONTRACT
# START_MODULE_MAP
# END_MODULE_MAP

from __future__ import annotations

import hashlib
import json
import logging
import os
import subprocess
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from prefect_grace.tasks.agent_output_parser import (
    ARCHITECT_ARTIFACT_PLAN_END,
    PACKET_DECISION_END,
    PLANNER_WAVE_PLAN_END,
    VERIFIER_EVIDENCE_END,
    WAVE_DECISION_END,
)

DEFAULT_HEARTBEAT_INTERVAL_SECONDS = 15.0
DEFAULT_STALL_TIMEOUT_SECONDS = 900.0
DEFAULT_FINAL_OUTPUT_GRACE_SECONDS = 60.0
DEFAULT_POST_TURN_COMPLETION_GRACE_SECONDS = 30.0
FINAL_OUTPUT_MARKERS = (
    ARCHITECT_ARTIFACT_PLAN_END,
    PLANNER_WAVE_PLAN_END,
    VERIFIER_EVIDENCE_END,
    PACKET_DECISION_END,
    WAVE_DECISION_END,
)
SEMANTIC_ITEM_TYPES = {"agent_message", "file_change", "command_execution"}

def _extract_thread_id(stdout_path: Path) -> str | None:
    if not stdout_path.exists():
        return None
    with stdout_path.open("r", encoding="utf-8", errors="replace") as handle:
        for line in handle:
            stripped = line.strip()
            if not stripped:
                continue
            try:
                payload = json.loads(stripped)
            except json.JSONDecodeError:
                continue
            if not isinstance(payload, dict):
                continue
            if str(payload.get("type") or "").strip() != "thread.started":
                continue
            thread_id = str(payload.get("thread_id") or "").strip()
            if thread_id:
                return thread_id
    return None

def _extract_last_stdout_event(stdout_path: Path, *, max_bytes: int = 16384) -> dict[str, str] | None:
    if not stdout_path.exists() or stdout_path.stat().st_size == 0:
        return None
    with stdout_path.open("rb") as handle:
        size = handle.seek(0, os.SEEK_END)
        read_size = min(size, max_bytes)
        handle.seek(-read_size, os.SEEK_END)
        tail = handle.read(read_size).decode("utf-8", errors="replace")
    lines = [line.strip() for line in tail.splitlines() if line.strip()]
    for line in reversed(lines):
        try:
            payload = json.loads(line)
        except json.JSONDecodeError:
            continue
        if not isinstance(payload, dict):
            continue
        event_type = str(payload.get("type") or "").strip()
        item = payload.get("item") if isinstance(payload.get("item"), dict) else {}
        status = str(item.get("status") or "").strip()
        if event_type or status:
            return {
                "event_type": event_type or "unknown",
                "status": status or "unknown",
            }
    return None

def _run_progress_class(stdout_path: Path) -> str:
    progress = _extract_stdout_progress(stdout_path)
    if progress.get("turn_completed_signature"):
        return "completed_turn"
    semantic_reason = str(progress.get("semantic_reason") or "")
    if semantic_reason.startswith("item."):
        return "semantic_progress"
    if semantic_reason == "thread.started" or progress.get("event_type") in {"turn.started", "thread.started"}:
        return "startup_only"
    return "no_output"

def _text_signature(text: str) -> str:
    return hashlib.sha1(text.encode("utf-8")).hexdigest()[:12]

def _iter_stdout_payloads(stdout_path: Path, *, max_bytes: int = 262144) -> list[dict[str, Any]]:
    if not stdout_path.exists() or stdout_path.stat().st_size == 0:
        return []
    with stdout_path.open("rb") as handle:
        size = handle.seek(0, os.SEEK_END)
        read_size = min(size, max_bytes)
        handle.seek(-read_size, os.SEEK_END)
        tail = handle.read(read_size).decode("utf-8", errors="replace")
    payloads: list[dict[str, Any]] = []
    for line in tail.splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            payload = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(payload, dict):
            payloads.append(payload)
    return payloads

def _payload_text(payload: dict[str, Any]) -> str:
    item = payload.get("item") if isinstance(payload.get("item"), dict) else {}
    for value in (item.get("text"), payload.get("text"), item.get("message"), payload.get("message")):
        if isinstance(value, str) and value.strip():
            return value.strip()
    return ""

def _detect_final_marker(text: str) -> str | None:
    for marker in FINAL_OUTPUT_MARKERS:
        if marker in text:
            return marker
    return None

def _semantic_signature_from_payload(payload: dict[str, Any]) -> tuple[str | None, str | None]:
    event_type = str(payload.get("type") or "").strip()
    if event_type == "thread.started":
        thread_id = str(payload.get("thread_id") or "").strip()
        if thread_id:
            return (f"thread.started:{thread_id}", "thread.started")
        return ("thread.started", "thread.started")

    item = payload.get("item") if isinstance(payload.get("item"), dict) else {}
    item_type = str(item.get("type") or "").strip()
    if item_type not in SEMANTIC_ITEM_TYPES:
        return (None, None)
    item_id = str(item.get("id") or "").strip()
    status = str(item.get("status") or "").strip()
    if item_type == "agent_message":
        text = _payload_text(payload)
        if not text:
            return (None, None)
        return (
            f"{event_type}:{item_type}:{item_id}:{_text_signature(text)}",
            f"{event_type}:{item_type}",
        )
    exit_code = item.get("exit_code")
    exit_code_part = f":{exit_code}" if exit_code is not None else ""
    return (
        f"{event_type}:{item_type}:{item_id}:{status}{exit_code_part}",
        f"{event_type}:{item_type}",
    )

def _extract_stdout_progress(stdout_path: Path, *, max_bytes: int = 262144) -> dict[str, Any]:
    payloads = _iter_stdout_payloads(stdout_path, max_bytes=max_bytes)
    latest_event: dict[str, Any] = {
        "event_type": "none",
        "status": "none",
        "item_type": "none",
        "semantic_signature": None,
        "semantic_reason": None,
        "final_signature": None,
        "final_marker": None,
        "turn_completed_signature": None,
    }
    for payload in reversed(payloads):
        if latest_event["event_type"] == "none":
            event_type = str(payload.get("type") or "").strip()
            item = payload.get("item") if isinstance(payload.get("item"), dict) else {}
            status = str(item.get("status") or "").strip()
            item_type = str(item.get("type") or "").strip()
            if event_type or status or item_type:
                latest_event["event_type"] = event_type or "unknown"
                latest_event["status"] = status or "unknown"
                latest_event["item_type"] = item_type or "unknown"
        if latest_event["semantic_signature"] is None:
            semantic_signature, semantic_reason = _semantic_signature_from_payload(payload)
            if semantic_signature is not None:
                latest_event["semantic_signature"] = semantic_signature
                latest_event["semantic_reason"] = semantic_reason
        if latest_event["final_signature"] is None:
            item = payload.get("item") if isinstance(payload.get("item"), dict) else {}
            item_type = str(item.get("type") or "").strip()
            if item_type == "agent_message":
                text = _payload_text(payload)
                marker = _detect_final_marker(text)
                if marker:
                    item_id = str(item.get("id") or "").strip()
                    latest_event["final_signature"] = f"agent_message:{item_id}:{marker}:{_text_signature(text)}"
                    latest_event["final_marker"] = marker
        if latest_event["turn_completed_signature"] is None and str(payload.get("type") or "").strip() == "turn.completed":
            usage = payload.get("usage") if isinstance(payload.get("usage"), dict) else {}
            latest_event["turn_completed_signature"] = (
                f"turn.completed:{usage.get('input_tokens')}:{usage.get('output_tokens')}:{usage.get('reasoning_tokens')}"
            )
        if (
            latest_event["semantic_signature"] is not None
            and latest_event["final_signature"] is not None
            and latest_event["turn_completed_signature"] is not None
        ):
            break
    return latest_event

def _last_message_progress(last_message_path: Path | None) -> dict[str, Any]:
    if last_message_path is None or not last_message_path.exists():
        return {
            "last_message_bytes": 0,
            "last_message_signature": None,
            "final_signature": None,
            "final_marker": None,
        }
    text = last_message_path.read_text(encoding="utf-8").strip()
    if not text:
        return {
            "last_message_bytes": 0,
            "last_message_signature": None,
            "final_signature": None,
            "final_marker": None,
        }
    marker = _detect_final_marker(text)
    signature = f"last_message:{_text_signature(text)}"
    return {
        "last_message_bytes": len(text.encode("utf-8")),
        "last_message_signature": signature,
        "final_signature": f"{signature}:{marker}" if marker else None,
        "final_marker": marker,
    }

def _heartbeat_payload(
    *,
    run_dir: Path,
    stdout_path: Path,
    process: subprocess.Popen[str],
    last_message_path: Path | None = None,
) -> dict[str, Any]:
    progress = _extract_stdout_progress(stdout_path)
    last_message = _last_message_progress(last_message_path)
    stdout_bytes = stdout_path.stat().st_size if stdout_path.exists() else 0
    semantic_signature = last_message["last_message_signature"] or progress["semantic_signature"]
    semantic_reason = "last_message" if last_message["last_message_signature"] else progress["semantic_reason"]
    final_signature = last_message["final_signature"] or progress["final_signature"]
    final_marker = last_message["final_marker"] or progress["final_marker"]
    return {
        "run_dir": str(run_dir),
        "stdout_path": str(stdout_path),
        "stdout_bytes": stdout_bytes,
        "pid": process.pid,
        "event_type": progress.get("event_type", "none"),
        "event_status": progress.get("status", "none"),
        "event_item_type": progress.get("item_type", "none"),
        "semantic_signature": semantic_signature,
        "semantic_reason": semantic_reason or "none",
        "final_signature": final_signature,
        "final_marker": final_marker or "none",
        "last_message_bytes": last_message["last_message_bytes"],
        "last_message_path": str(last_message_path) if last_message_path else "",
    }

def _format_heartbeat_message(packet_id: str, payload: dict[str, Any]) -> str:
    return (
        "Codex heartbeat packet=%s pid=%s run_dir=%s stdout_bytes=%s last_event=%s/%s/%s last_semantic=%s final=%s stdout=%s last_message=%s"
        % (
            packet_id,
            payload.get("pid"),
            payload.get("run_dir"),
            payload.get("stdout_bytes"),
            payload.get("event_type"),
            payload.get("event_status"),
            payload.get("event_item_type"),
            payload.get("semantic_reason"),
            payload.get("final_marker"),
            payload.get("stdout_path"),
            payload.get("last_message_path"),
        )
    )

def _heartbeat_loop(
    process: subprocess.Popen[str],
    *,
    packet_id: str,
    run_dir: Path,
    stdout_path: Path,
    logger: logging.Logger,
    interval_seconds: float,
    stop_event: threading.Event,
    stall_state: dict[str, Any] | None = None,
    stall_timeout_seconds: float | None = DEFAULT_STALL_TIMEOUT_SECONDS,
    last_message_path: Path | None = None,
    final_output_grace_seconds: float = DEFAULT_FINAL_OUTPUT_GRACE_SECONDS,
    post_turn_completion_grace_seconds: float = DEFAULT_POST_TURN_COMPLETION_GRACE_SECONDS,
) -> None:
    last_progress_at = datetime.now(timezone.utc)
    payload = _heartbeat_payload(
        run_dir=run_dir,
        stdout_path=stdout_path,
        process=process,
        last_message_path=last_message_path,
    )
    last_semantic_signature = payload.get("semantic_signature")
    last_final_signature = payload.get("final_signature")
    final_seen_at = datetime.now(timezone.utc) if last_final_signature else None
    last_turn_completed_signature = payload.get("turn_completed_signature")
    turn_completed_seen_at = datetime.now(timezone.utc) if last_turn_completed_signature else None
    while not stop_event.wait(interval_seconds):
        if process.poll() is not None:
            break
        payload = _heartbeat_payload(
            run_dir=run_dir,
            stdout_path=stdout_path,
            process=process,
            last_message_path=last_message_path,
        )
        semantic_signature = payload.get("semantic_signature")
        if semantic_signature and semantic_signature != last_semantic_signature:
            last_semantic_signature = semantic_signature
            last_progress_at = datetime.now(timezone.utc)
        final_signature = payload.get("final_signature")
        if final_signature:
            if final_signature != last_final_signature:
                last_final_signature = final_signature
                final_seen_at = datetime.now(timezone.utc)
        else:
            last_final_signature = None
            final_seen_at = None
        turn_completed_signature = payload.get("turn_completed_signature")
        if turn_completed_signature:
            if turn_completed_signature != last_turn_completed_signature:
                last_turn_completed_signature = turn_completed_signature
                turn_completed_seen_at = datetime.now(timezone.utc)
        else:
            last_turn_completed_signature = None
            turn_completed_seen_at = None
        idle_seconds = max(0.0, (datetime.now(timezone.utc) - last_progress_at).total_seconds())
        logger.info("%s idle_seconds=%.1f", _format_heartbeat_message(packet_id, payload), idle_seconds)
        if (
            final_seen_at is not None
            and final_output_grace_seconds > 0
            and (datetime.now(timezone.utc) - final_seen_at).total_seconds() >= final_output_grace_seconds
            and process.poll() is None
        ):
            if stall_state is not None:
                stall_state["final_output_collected"] = True
                stall_state["final_marker"] = payload.get("final_marker")
                stall_state["idle_seconds"] = idle_seconds
            logger.warning(
                "Codex final output collected packet=%s pid=%s final_marker=%s run_dir=%s stdout=%s; terminating hung process",
                packet_id,
                process.pid,
                payload.get("final_marker"),
                run_dir,
                stdout_path,
            )
            process.kill()
            break
        if (
            turn_completed_seen_at is not None
            and post_turn_completion_grace_seconds > 0
            and (datetime.now(timezone.utc) - turn_completed_seen_at).total_seconds() >= post_turn_completion_grace_seconds
            and process.poll() is None
        ):
            if stall_state is not None:
                stall_state["post_turn_completion_collected"] = True
                stall_state["turn_completed_signature"] = last_turn_completed_signature
                stall_state["idle_seconds"] = idle_seconds
            logger.warning(
                "Codex post-turn completion collected packet=%s pid=%s run_dir=%s stdout=%s; terminating hung process after completed turn",
                packet_id,
                process.pid,
                run_dir,
                stdout_path,
            )
            process.kill()
            break
        if stall_timeout_seconds and idle_seconds >= stall_timeout_seconds and process.poll() is None:
            if stall_state is not None:
                stall_state["detected"] = True
                stall_state["idle_seconds"] = idle_seconds
            logger.warning(
                "Codex stall detected packet=%s pid=%s idle_seconds=%.1f run_dir=%s stdout=%s; terminating process",
                packet_id,
                process.pid,
                idle_seconds,
                run_dir,
                stdout_path,
            )
            process.kill()
            break
