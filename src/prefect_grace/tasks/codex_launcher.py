# AI_HEADER: codex_launcher
# ROLE: Launches Codex agent sessions for packet execution with resume control.
# START_MODULE_CONTRACT
# END_MODULE_CONTRACT
# START_MODULE_MAP
# END_MODULE_MAP

from __future__ import annotations

import json
import logging
import os
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import yaml

from prefect_grace.models import ReasoningProfile
from prefect_grace.platform.executor_registry import select_executor_for_packet
from prefect_grace.platform.project_adapter import load_project_adapter
from prefect_grace.platform.state_store import PacketRegistryStore, ExecutorHistoryStore
from prefect_grace.tasks.agent_output_parser import read_agent_message
from prefect_grace.tasks.codex_launcher_helpers import process_runner as _process_runner
from prefect_grace.tasks.codex_launcher_helpers import progress_tracker as _progress_tracker
from prefect_grace.tasks.codex_launcher_helpers import prompt_builder as _prompt_builder
from prefect_grace.tasks.codex_launcher_helpers import resume_policy as _resume_policy
from prefect_grace.tasks.codex_launcher_helpers import session_manager as _session_manager
from prefect_grace.tasks.codex_launcher_helpers.command_builder import _build_exec_command, _build_resume_command
from prefect_grace.tasks.codex_launcher_helpers.command_builder import _config_override_args, _uses_bypass_sandbox
from prefect_grace.tasks.codex_launcher_helpers.process_runner import CodexLaunchResult, CodexProcessResult
from prefect_grace.tasks.codex_launcher_helpers.progress_tracker import _extract_thread_id
from prefect_grace.tasks.codex_launcher_helpers.prompt_builder import _read_text
from prefect_grace.tasks.state_store import find_record, update_record
from prefect_grace.tasks.workdir import resolve_execution_workdir

CONFIG_PATH = Path(__file__).resolve().parents[1] / "agent_profiles.yaml"
RUNS_DIR = Path(__file__).resolve().parents[1] / "state" / "runs"
FEATURES_DIR = Path(__file__).resolve().parents[1] / "packets"
STATE_ROOT = Path(__file__).resolve().parents[1] / "state"
DEFAULT_HEARTBEAT_INTERVAL_SECONDS = 15.0
DEFAULT_STALL_TIMEOUT_SECONDS = 900.0
DEFAULT_FINAL_OUTPUT_GRACE_SECONDS = 60.0
DEFAULT_POST_TURN_COMPLETION_GRACE_SECONDS = 30.0
DEFAULT_MAX_AUTO_RESUME_ATTEMPTS = 1
AUTO_RESUME_TERMINATION_REASONS = {"stall_killed", "timeout"}

def _load_agent_config() -> dict[str, Any]:
    return yaml.safe_load(CONFIG_PATH.read_text(encoding="utf-8")) or {}
load_agent_config = _load_agent_config

def _role_defaults(config: dict[str, Any], role: str) -> dict[str, Any]:
    return dict(config.get("codex", {}).get("roles", {}).get(role, {}))

def _sanitize_filename(value: str) -> str:
    cleaned = re.sub(r"[^A-Za-z0-9_.-]+", "-", value.strip())
    return cleaned.strip("-") or "packet"

def _sync_prompt_builder() -> None:
    _prompt_builder.FEATURES_DIR = FEATURES_DIR
    _prompt_builder.find_record = find_record
    _prompt_builder.read_agent_message = read_agent_message

def _build_packet_prompt_public(packet_path: Path, role_prompt: str) -> str:
    _sync_prompt_builder(); return _prompt_builder.build_packet_prompt(packet_path, role_prompt)
build_packet_prompt = _build_packet_prompt_public

def _role_prompt_for_public(role: str) -> str:
    _sync_prompt_builder(); return _prompt_builder.role_prompt_for(role)
role_prompt_for = _role_prompt_for_public

def _sync_progress_tracker() -> None:
    _progress_tracker.datetime = datetime
    _progress_tracker.DEFAULT_HEARTBEAT_INTERVAL_SECONDS = DEFAULT_HEARTBEAT_INTERVAL_SECONDS
    _progress_tracker.DEFAULT_STALL_TIMEOUT_SECONDS = DEFAULT_STALL_TIMEOUT_SECONDS
    _progress_tracker.DEFAULT_FINAL_OUTPUT_GRACE_SECONDS = DEFAULT_FINAL_OUTPUT_GRACE_SECONDS
    _progress_tracker.DEFAULT_POST_TURN_COMPLETION_GRACE_SECONDS = DEFAULT_POST_TURN_COMPLETION_GRACE_SECONDS

def _progress_call(name: str, *args: Any, **kwargs: Any) -> Any:
    _sync_progress_tracker(); return getattr(_progress_tracker, name)(*args, **kwargs)
def _extract_last_stdout_event(*args: Any, **kwargs: Any) -> Any: return _progress_call("_extract_last_stdout_event", *args, **kwargs)
def _run_progress_class(*args: Any, **kwargs: Any) -> Any: return _progress_call("_run_progress_class", *args, **kwargs)
def _extract_stdout_progress(*args: Any, **kwargs: Any) -> Any: return _progress_call("_extract_stdout_progress", *args, **kwargs)
def _heartbeat_payload(*args: Any, **kwargs: Any) -> Any: return _progress_call("_heartbeat_payload", *args, **kwargs)
def _format_heartbeat_message(*args: Any, **kwargs: Any) -> Any: return _progress_call("_format_heartbeat_message", *args, **kwargs)
def _heartbeat_loop(*args: Any, **kwargs: Any) -> Any: return _progress_call("_heartbeat_loop", *args, **kwargs)

def _sync_process_runner() -> None:
    _sync_progress_tracker()
    _process_runner._heartbeat_loop = _heartbeat_loop
    _process_runner.DEFAULT_HEARTBEAT_INTERVAL_SECONDS = DEFAULT_HEARTBEAT_INTERVAL_SECONDS
    _process_runner.DEFAULT_STALL_TIMEOUT_SECONDS = DEFAULT_STALL_TIMEOUT_SECONDS

def _run_codex_process(*args: Any, **kwargs: Any) -> CodexProcessResult:
    _sync_process_runner(); return _process_runner._run_codex_process(*args, **kwargs)

def _sync_session_manager() -> None:
    _session_manager.find_record = find_record
    _session_manager.update_record = update_record
    _session_manager.datetime = datetime
    _session_manager.STATE_ROOT = STATE_ROOT

def _session_call(name: str, *args: Any, **kwargs: Any) -> Any:
    _sync_session_manager(); return getattr(_session_manager, name)(*args, **kwargs)
def _feature_role_session(*args: Any, **kwargs: Any) -> Any: return _session_call("_feature_role_session", *args, **kwargs)
def _packet_parent_session(*args: Any, **kwargs: Any) -> Any: return _session_call("_packet_parent_session", *args, **kwargs)
def _store_feature_role_session(*args: Any, **kwargs: Any) -> Any: return _session_call("_store_feature_role_session", *args, **kwargs)

def _sync_resume_policy() -> None:
    _resume_policy.PacketRegistryStore = PacketRegistryStore
    _resume_policy.STATE_ROOT = STATE_ROOT
    _resume_policy.DEFAULT_STALL_TIMEOUT_SECONDS = DEFAULT_STALL_TIMEOUT_SECONDS
    _resume_policy.DEFAULT_MAX_AUTO_RESUME_ATTEMPTS = DEFAULT_MAX_AUTO_RESUME_ATTEMPTS
_normalize_resume_strategy = _resume_policy._normalize_resume_strategy
_normalize_non_negative_int = _resume_policy._normalize_non_negative_int
_normalize_positive_float = _resume_policy._normalize_positive_float

def _resume_call(name: str, *args: Any, **kwargs: Any) -> Any:
    _sync_resume_policy(); return getattr(_resume_policy, name)(*args, **kwargs)
def _check_resume_allowed(*args: Any, **kwargs: Any) -> Any: return _resume_call("_check_resume_allowed", *args, **kwargs)
def _resolve_resume_strategy(*args: Any, **kwargs: Any) -> Any: return _resume_call("_resolve_resume_strategy", *args, **kwargs)
def _resolve_stall_timeout_seconds(*args: Any, **kwargs: Any) -> Any: return _resume_call("_resolve_stall_timeout_seconds", *args, **kwargs)
def _resolve_max_auto_resume_attempts(*args: Any, **kwargs: Any) -> Any: return _resume_call("_resolve_max_auto_resume_attempts", *args, **kwargs)

def _launch_codex_for_packet(
    packet_id: str,
    *,
    dry_run: bool = False,
    timeout_seconds: int = 3600,
    logger: logging.Logger | None = None,
    heartbeat_interval_seconds: float = DEFAULT_HEARTBEAT_INTERVAL_SECONDS,
    stall_timeout_seconds: float | None = None,
    workdir_override: str | Path | None = None,
    runtime_state_root: str | Path | None = None,
    project_root: str | Path | None = None,
) -> dict[str, Any]:
    config = load_agent_config()
    # Use new registry format with fallback to old
    from prefect_grace.tasks.state_store import find_packet_from_registry
    registry_project_root = Path(project_root).resolve() if project_root is not None else Path.cwd()
    packet = find_packet_from_registry(packet_id, runtime_state_root, project_root=registry_project_root)
    # Add project_root to packet dict for path normalization in prompt builder
    packet["project_root"] = str(registry_project_root)
    role = str(packet.get("role") or "coder")
    role_defaults = _role_defaults(config, role)
    execution_hints = dict(packet.get("execution_hints") or {})
    reasoning = str(packet.get("reasoning") or role_defaults.get("reasoning") or ReasoningProfile.HIGH.value)
    sandbox = str(execution_hints.get("sandbox") or role_defaults.get("sandbox") or "workspace-write")
    approval = str(role_defaults.get("approval") or "never")
    resume_strategy = _resolve_resume_strategy(packet, role_defaults)
    effective_stall_timeout_seconds = _resolve_stall_timeout_seconds(packet, role_defaults, stall_timeout_seconds)
    max_auto_resume_attempts = _resolve_max_auto_resume_attempts(packet, role_defaults)
    codex_binary = str(config.get("codex", {}).get("binary") or "codex1")

    # Load project config for policy checks
    project_config = None
    try:
        project_adapter = load_project_adapter(
            config_path=registry_project_root,
            overrides=None
        )
        project_config = project_adapter.to_dict()
    except Exception as e:
        if logger:
            logger.warning("Failed to load project config for policy checks: %s", e)
        project_config = None

    # Try executor registry first
    requested_executor = execution_hints.get("requested_executor") if execution_hints else None

    # Load executor history for rotation logic
    history = None
    try:
        resolved_state_root = Path(runtime_state_root) if runtime_state_root else STATE_ROOT
        history_store = ExecutorHistoryStore(state_root=resolved_state_root)
        history = history_store.list_executions()

        if logger:
            logger.info("EXECUTOR_HISTORY_LOADED", extra={
                "packet_id": packet_id,
                "role": role,
                "total_history_count": len(history)
            })
    except Exception as e:
        # Fallback to None on any error
        if logger:
            logger.warning("EXECUTOR_HISTORY_LOAD_FAILED", extra={
                "packet_id": packet_id,
                "role": role,
                "error": str(e)
            })
        history = None

    executor_selection = select_executor_for_packet(
        project=config,
        packet=packet,
        history=history,
        requested_executor=requested_executor
    )

    if executor_selection.ok and executor_selection.selected and executor_selection.selected.model:
        shared_model = executor_selection.selected.model
        logger.info("EXECUTOR_SELECTED", extra={
            "executor_id": executor_selection.selected.executor_id,
            "model": shared_model,
            "packet_id": packet.get("id"),
            "role": role
        })
    else:
        # Fallback to shared_model from config or default executor
        config_model = config.get("codex", {}).get("shared_model")
        if not config_model:
            # Get default model from agent profiles
            default_executor = next(
                (e for e in config.get("executors", []) if e.get("priority") == 1),
                None
            )
            config_model = default_executor.get("model") if default_executor else "gemini-3.5-flash"

        shared_model = str(config_model)
        logger.warning("EXECUTOR_FALLBACK", extra={
            "reason": executor_selection.reason if not executor_selection.ok else "no model specified",
            "fallback_model": shared_model,
            "packet_id": packet.get("id")
        })

    # Resolve working directory: workdir_override wins over packet hints and config
    if workdir_override is not None:
        workdir_path = Path(workdir_override).resolve()
        if not workdir_path.exists():
            error_msg = f"workdir_override does not exist: {workdir_path}"
            if logger:
                logger.error(error_msg)
            return CodexLaunchResult(
                packet_id=packet_id,
                returncode=1,
                launcher="codex",
                command="",
                session_mode="exec",
                resume_strategy=resume_strategy,
                thread_id="",
                resumed_from_thread_id=None,
                stdout_path="",
                stderr_path="",
                last_message_path="",
                started_at=datetime.now(timezone.utc).isoformat(),
                finished_at=datetime.now(timezone.utc).isoformat(),
                termination_reason="workdir_override_not_found",
                attempt=0,
                attempt_count=0,
                attempts=[],
            ).to_dict()
        if not workdir_path.is_dir():
            error_msg = f"workdir_override is not a directory: {workdir_path}"
            if logger:
                logger.error(error_msg)
            return CodexLaunchResult(
                packet_id=packet_id,
                returncode=1,
                launcher="codex",
                command="",
                session_mode="exec",
                resume_strategy=resume_strategy,
                thread_id="",
                resumed_from_thread_id=None,
                stdout_path="",
                stderr_path="",
                last_message_path="",
                started_at=datetime.now(timezone.utc).isoformat(),
                finished_at=datetime.now(timezone.utc).isoformat(),
                termination_reason="workdir_override_not_directory",
                attempt=0,
                attempt_count=0,
                attempts=[],
            ).to_dict()
        workdir = str(workdir_path)
    else:
        configured_workdir = str(execution_hints.get("workdir") or config.get("codex", {}).get("workdir") or registry_project_root)
        workdir = str(resolve_execution_workdir(configured_workdir, project_root=registry_project_root))

    role_prompt = role_prompt_for(role)
    prompt = build_packet_prompt(packet, role_prompt)

    # Add verification phase context if specified
    verification_phase = packet.get("verification_phase")
    if verification_phase and verification_phase != "full":
        phase_instructions = {
            "code": "VERIFICATION PHASE: code\nWrite code only. Do not run tests or linting. Focus on implementation.",
            "lint": "VERIFICATION PHASE: lint\nRun linting and formatting checks only. Fix any issues found. Do not write new code or run tests.",
            "test": "VERIFICATION PHASE: test\nRun tests only. Fix any test failures. Do not write new code or run linting."
        }
        phase_suffix = phase_instructions.get(verification_phase, "")
        if phase_suffix:
            prompt = f"{prompt}\n\n{phase_suffix}"
            if logger:
                logger.info("VERIFICATION_PHASE_CONTEXT", extra={
                    "packet_id": packet_id,
                    "verification_phase": verification_phase
                })

    # Check if resume is allowed based on source hash gate
    resume_allowed = _check_resume_allowed(packet_id, resume_strategy, logger)

    resolved_state_root = Path(runtime_state_root) if runtime_state_root else STATE_ROOT
    if resume_strategy == "feature_role" and resume_allowed:
        existing_session = _feature_role_session(str(packet.get("feature_id")), role, state_root=resolved_state_root)
    elif resume_strategy == "packet_parent" and resume_allowed:
        existing_session = _packet_parent_session(packet, state_root=resolved_state_root)
    else:
        existing_session = None
    env = os.environ.copy()
    env.pop("CODEX_FORCE_PROFILE_MODEL_PREFIX", None)

    attempts: list[dict[str, Any]] = []
    resume_thread_id = (
        str(existing_session.get("thread_id") or "").strip()
        if existing_session and str(existing_session.get("thread_id") or "").strip()
        else None
    )
    attempt = 0
    while True:
        attempt += 1
        run_id = (
            f"{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')}"
            f"-{_sanitize_filename(packet_id)}-try{attempt}"
        )
        run_dir = RUNS_DIR / run_id
        run_dir.mkdir(parents=True, exist_ok=True)
        prompt_path = run_dir / "prompt.md"
        stdout_path = run_dir / "stdout.jsonl"
        stderr_path = run_dir / "stderr.log"
        last_message_path = run_dir / "last-message.md"
        prompt_path.write_text(prompt, encoding="utf-8")

        resumed_from_thread_id = resume_thread_id or None
        session_mode = "resume" if resumed_from_thread_id else "exec"
        if resumed_from_thread_id:
            command = _build_resume_command(
                codex_binary=codex_binary,
                workdir=workdir,
                shared_model=shared_model,
                reasoning=reasoning,
                approval=approval,
                sandbox=sandbox,
                thread_id=resumed_from_thread_id,
                last_message_path=last_message_path,
                packet_id=packet_id,
                project_config=project_config,
            )
        else:
            command = _build_exec_command(
                codex_binary=codex_binary,
                workdir=workdir,
                shared_model=shared_model,
                reasoning=reasoning,
                approval=approval,
                sandbox=sandbox,
                last_message_path=last_message_path,
                packet_id=packet_id,
                project_config=project_config,
            )

        started_at = datetime.now(timezone.utc).isoformat()
        termination_reason = "dry_run"
        if dry_run:
            stdout_path.write_text(
                json.dumps(
                    {"dry_run": True, "command": command, "launcher": codex_binary, "routing": "cliproxy-via-wrapper"}
                )
                + "\n",
                encoding="utf-8",
            )
            stderr_path.write_text("", encoding="utf-8")
            last_message_path.write_text("DRY RUN: Codex was not launched.\n", encoding="utf-8")
            returncode = 0
            if logger is not None:
                logger.info(
                    "Codex dry-run packet=%s attempt=%s run_dir=%s stdout=%s stderr=%s last_message=%s",
                    packet_id,
                    attempt,
                    run_dir,
                    stdout_path,
                    stderr_path,
                    last_message_path,
                )
            thread_id = resumed_from_thread_id
        else:
            process_result = _run_codex_process(
                command,
                packet_id=packet_id,
                prompt=prompt,
                workdir=workdir,
                env=env,
                timeout_seconds=timeout_seconds,
                stdout_path=stdout_path,
                stderr_path=stderr_path,
                run_dir=run_dir,
                logger=logger,
                heartbeat_interval_seconds=heartbeat_interval_seconds,
                stall_timeout_seconds=effective_stall_timeout_seconds,
            )
            if isinstance(process_result, CodexProcessResult):
                returncode = process_result.returncode
                termination_reason = process_result.termination_reason
            else:
                returncode = int(process_result)
                termination_reason = "timeout" if returncode == 124 else ("completed" if returncode == 0 else "nonzero_exit")
            thread_id = _extract_thread_id(stdout_path) or resumed_from_thread_id
        finished_at = datetime.now(timezone.utc).isoformat()

        # Classify API failure if returncode != 0
        api_failure_category = None
        api_failure_retryable = None
        api_failure_reason = None

        if returncode != 0:
            from prefect_grace.platform.agent_failure_classifier import classify_agent_failure

            stderr_text = _read_text(stderr_path)
            stdout_text = _read_text(stdout_path)

            classification = classify_agent_failure(
                stdout_text=stdout_text,
                stderr_text=stderr_text,
                exit_code=returncode,
                termination_reason=termination_reason,
            )

            if classification.category != "none":
                api_failure_category = classification.category
                api_failure_retryable = classification.retryable
                api_failure_reason = classification.reason

        if resume_strategy == "feature_role" and thread_id:
            _store_feature_role_session(
                feature_id=str(packet.get("feature_id")),
                role=role,
                thread_id=thread_id,
                launcher=codex_binary,
                packet_id=packet_id,
                reasoning=reasoning,
                sandbox=sandbox,
                approval=approval,
                model=shared_model,
                session_mode=session_mode,
                run_dir=run_dir,
                resumed_from_thread_id=resumed_from_thread_id,
                state_root=resolved_state_root,
            )

        attempt_result = CodexLaunchResult(
            packet_id=packet_id,
            returncode=returncode,
            launcher=codex_binary,
            command=command,
            session_mode=session_mode,
            resume_strategy=resume_strategy,
            thread_id=thread_id,
            resumed_from_thread_id=resumed_from_thread_id,
            stdout_path=str(stdout_path),
            stderr_path=str(stderr_path),
            last_message_path=str(last_message_path),
            started_at=started_at,
            finished_at=finished_at,
            termination_reason=termination_reason,
            attempt=attempt,
            attempt_count=attempt,
            attempts=[],
            api_failure_category=api_failure_category,
            api_failure_retryable=api_failure_retryable,
            api_failure_reason=api_failure_reason,
        ).to_dict()
        attempts.append(attempt_result)

        progress_class = _run_progress_class(stdout_path)

        should_auto_resume = (
            not dry_run
            and returncode != 0
            and bool(thread_id)
            and termination_reason in AUTO_RESUME_TERMINATION_REASONS
            and progress_class not in {"startup_only", "no_output"}
            and attempt <= max_auto_resume_attempts
        )
        if should_auto_resume:
            resume_thread_id = str(thread_id)
            if logger is not None:
                logger.warning(
                    "Codex packet=%s attempt=%s rc=%s reason=%s thread=%s; scheduling automatic resume",
                    packet_id,
                    attempt,
                    returncode,
                    termination_reason,
                    resume_thread_id,
                )
            continue

        should_retry_fresh = (
            not dry_run
            and returncode != 0
            and termination_reason in AUTO_RESUME_TERMINATION_REASONS
            and attempt <= max_auto_resume_attempts
            and progress_class in {"startup_only", "no_output"}
        )
        if should_retry_fresh:
            resume_thread_id = None
            if logger is not None:
                logger.warning(
                    "Codex packet=%s attempt=%s rc=%s reason=%s progress=%s; retrying with fresh exec instead of resume",
                    packet_id,
                    attempt,
                    returncode,
                    termination_reason,
                    progress_class,
                )
            continue

        result = CodexLaunchResult(
            packet_id=packet_id,
            returncode=returncode,
            launcher=codex_binary,
            command=command,
            session_mode=session_mode,
            resume_strategy=resume_strategy,
            thread_id=thread_id,
            resumed_from_thread_id=resumed_from_thread_id,
            stdout_path=str(stdout_path),
            stderr_path=str(stderr_path),
            last_message_path=str(last_message_path),
            started_at=started_at,
            finished_at=finished_at,
            termination_reason=termination_reason,
            attempt=attempt,
            attempt_count=len(attempts),
            attempts=attempts,
        ).to_dict()
        break
    # Try to update old format state store (optional, may not exist in new registry format)
    try:
        update_record(
            "packets",
            "packets",
            "packet_id",
            packet_id,
            {
                "last_codex_run": result,
                "last_execution_run": result,
                "last_thread_id": thread_id,
                "last_session_mode": session_mode,
                "last_resume_strategy": resume_strategy,
                "status": "review" if returncode == 0 else "blocked",
            },
            state_root=resolved_state_root,
        )
    except KeyError:
        # Packet not in old format state store, skip update (new registry format)
        pass

    # Update registry with execution state for resume decision tracking
    if role == "coder" and thread_id:
        try:
            registry_state_root = Path(runtime_state_root) / "state" if runtime_state_root else STATE_ROOT
            registry = PacketRegistryStore(registry_state_root)
            packet_record = registry.load_packet(packet_id)
            if packet_record is not None:
                current_source_hash = packet_record.get("source_hash")
                registry.update_resume_state(
                    packet_id=packet_id,
                    last_executed_source_hash=current_source_hash,
                    latest_coder_session_id=thread_id,
                )
        except Exception as e:
            if logger is not None:
                logger.warning(
                    "Failed to update registry resume state for packet=%s error=%s",
                    packet_id,
                    str(e),
                )

    return result
launch_codex_for_packet = _launch_codex_for_packet
