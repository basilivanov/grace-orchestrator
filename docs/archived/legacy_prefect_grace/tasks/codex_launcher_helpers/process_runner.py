# AI_HEADER: codex_launcher_helpers
# START_MODULE_CONTRACT
# END_MODULE_CONTRACT
# START_MODULE_MAP
# END_MODULE_MAP

from __future__ import annotations

import logging
import subprocess
import threading
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, TextIO

from prefect_grace.tasks.codex_launcher_helpers.progress_tracker import _heartbeat_loop

DEFAULT_HEARTBEAT_INTERVAL_SECONDS = 15.0
DEFAULT_STALL_TIMEOUT_SECONDS = 900.0

@dataclass(frozen=True)
class CodexLaunchResult:
    packet_id: str
    returncode: int
    launcher: str
    command: list[str]
    session_mode: str
    resume_strategy: str
    thread_id: str | None
    resumed_from_thread_id: str | None
    stdout_path: str
    stderr_path: str
    last_message_path: str
    started_at: str
    finished_at: str
    termination_reason: str | None = None
    attempt: int = 1
    attempt_count: int = 1
    attempts: list[dict[str, Any]] = field(default_factory=list)
    # API failure classification metadata
    api_failure_category: str | None = None
    api_failure_retryable: bool | None = None
    api_failure_reason: str | None = None

    # START_FUNCTION_CONTRACT
    # name: to_dict
    # purpose: Convert CodexLaunchResult to dictionary for serialization.
    # inputs: None (instance method)
    # returns: dict[str, Any] - Dictionary with all result fields.
    # side_effects: None
    # emitted_logs: None
    # error_behavior: None
    # END_FUNCTION_CONTRACT
    def to_dict(self) -> dict[str, Any]:
        result = {
            "packet_id": self.packet_id,
            "returncode": self.returncode,
            "launcher": self.launcher,
            "command": self.command,
            "session_mode": self.session_mode,
            "resume_strategy": self.resume_strategy,
            "thread_id": self.thread_id,
            "resumed_from_thread_id": self.resumed_from_thread_id,
            "stdout_path": self.stdout_path,
            "stderr_path": self.stderr_path,
            "last_message_path": self.last_message_path,
            "started_at": self.started_at,
            "finished_at": self.finished_at,
            "termination_reason": self.termination_reason,
            "attempt": self.attempt,
            "attempt_count": self.attempt_count,
            "attempts": list(self.attempts),
        }

        # Add API failure metadata if present
        if self.api_failure_category is not None:
            result["api_failure_category"] = self.api_failure_category
            result["api_failure_retryable"] = self.api_failure_retryable
            result["api_failure_reason"] = self.api_failure_reason

        return result

@dataclass(frozen=True)
class CodexProcessResult:
    returncode: int
    termination_reason: str

def _pump_stream(stream: TextIO | None, sink_path: Path) -> None:
    if stream is None:
        sink_path.write_text("", encoding="utf-8")
        return
    with sink_path.open("w", encoding="utf-8") as sink:
        for chunk in iter(stream.readline, ""):
            sink.write(chunk)
            sink.flush()

def _run_codex_process(
    command: list[str],
    *,
    packet_id: str,
    prompt: str,
    workdir: str,
    env: dict[str, str],
    timeout_seconds: int,
    stdout_path: Path,
    stderr_path: Path,
    run_dir: Path,
    logger: logging.Logger | None = None,
    heartbeat_interval_seconds: float = DEFAULT_HEARTBEAT_INTERVAL_SECONDS,
    stall_timeout_seconds: float | None = DEFAULT_STALL_TIMEOUT_SECONDS,
) -> CodexProcessResult:
    process = subprocess.Popen(
        command,
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        cwd=workdir,
        env=env,
        bufsize=1,
    )
    stdout_thread = threading.Thread(target=_pump_stream, args=(process.stdout, stdout_path), daemon=True)
    stderr_thread = threading.Thread(target=_pump_stream, args=(process.stderr, stderr_path), daemon=True)
    stdout_thread.start()
    stderr_thread.start()
    heartbeat_stop = threading.Event()
    heartbeat_thread: threading.Thread | None = None
    stall_state: dict[str, Any] = {
        "detected": False,
        "idle_seconds": 0.0,
        "final_output_collected": False,
        "post_turn_completion_collected": False,
    }
    returncode = -1
    heartbeat_logger = logger or (logging.getLogger(__name__) if stall_timeout_seconds else None)
    last_message_path = run_dir / "last-message.md"
    if heartbeat_logger is not None:
        heartbeat_logger.info(
            "Launching Codex packet=%s pid=%s run_dir=%s stdout=%s stderr=%s",
            packet_id,
            process.pid,
            run_dir,
            stdout_path,
            stderr_path,
        )
        heartbeat_thread = threading.Thread(
            target=_heartbeat_loop,
            args=(process,),
            kwargs={
                "packet_id": packet_id,
                "run_dir": run_dir,
                "stdout_path": stdout_path,
                "logger": heartbeat_logger,
                "interval_seconds": heartbeat_interval_seconds,
                "stop_event": heartbeat_stop,
                "stall_state": stall_state,
                "stall_timeout_seconds": stall_timeout_seconds,
                "last_message_path": last_message_path,
            },
            daemon=True,
        )
        heartbeat_thread.start()
    try:
        assert process.stdin is not None
        process.stdin.write(prompt)
        process.stdin.close()
        returncode = process.wait(timeout=timeout_seconds)
    except subprocess.TimeoutExpired:
        process.kill()
        process.wait(timeout=10)
        returncode = 124
        with stderr_path.open("a", encoding="utf-8") as sink:
            sink.write(f"\nTimed out after {timeout_seconds} seconds.\n")
            sink.flush()
    finally:
        termination_reason = "completed"
        if stall_state.get("final_output_collected"):
            returncode = 0
            termination_reason = "final_output_collected"
            with stderr_path.open("a", encoding="utf-8") as sink:
                sink.write(
                    f"\nCodex final output collected ({stall_state.get('final_marker') or 'unknown-marker'})"
                    f" after {float(stall_state.get('idle_seconds') or 0.0):.1f} idle seconds; process terminated.\n"
                )
                sink.flush()
        elif stall_state.get("post_turn_completion_collected"):
            returncode = 0
            termination_reason = "post_turn_hung_killed"
            with stderr_path.open("a", encoding="utf-8") as sink:
                sink.write(
                    f"\nCodex post-turn completion collected after {float(stall_state.get('idle_seconds') or 0.0):.1f} idle seconds; process terminated after completed turn.\n"
                )
                sink.flush()
        elif stall_state.get("detected"):
            termination_reason = "stall_killed"
            with stderr_path.open("a", encoding="utf-8") as sink:
                sink.write(
                    f"\nCodex stall detected after {float(stall_state.get('idle_seconds') or 0.0):.1f} idle seconds.\n"
                )
                sink.flush()
        elif returncode == 124:
            termination_reason = "timeout"
        elif returncode != 0:
            termination_reason = "nonzero_exit"
        heartbeat_stop.set()
        if heartbeat_thread is not None:
            heartbeat_thread.join(timeout=5)
        stdout_thread.join(timeout=5)
        stderr_thread.join(timeout=5)
        if process.stdout is not None:
            process.stdout.close()
        if process.stderr is not None:
            process.stderr.close()
        if logger is not None:
            logger.info(
                "Codex finished packet=%s pid=%s rc=%s reason=%s stdout_bytes=%s run_dir=%s last_message=%s",
                packet_id,
                process.pid,
                returncode,
                termination_reason,
                stdout_path.stat().st_size if stdout_path.exists() else 0,
                run_dir,
                run_dir / "last-message.md",
            )
    return CodexProcessResult(returncode=returncode, termination_reason=termination_reason)
