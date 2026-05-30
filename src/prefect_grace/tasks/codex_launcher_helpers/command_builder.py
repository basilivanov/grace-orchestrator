# AI_HEADER: codex_launcher_helpers
# START_MODULE_CONTRACT
# END_MODULE_CONTRACT
# START_MODULE_MAP
# END_MODULE_MAP

from __future__ import annotations

from pathlib import Path

def _config_override_args(*, reasoning: str, approval: str, sandbox: str | None = None) -> list[str]:
    args = ["-c", f'model_reasoning_effort="{reasoning}"']
    if approval:
        args.extend(["-c", f'approval_policy="{approval}"'])
    if sandbox:
        args.extend(["-c", f'sandbox_mode="{sandbox}"'])
    return args

def _uses_bypass_sandbox(sandbox: str, approval: str) -> bool:
    return sandbox == "danger-full-access" and approval == "never"

def _build_exec_command(
    *,
    codex_binary: str,
    workdir: str,
    shared_model: str,
    reasoning: str,
    approval: str,
    sandbox: str,
    last_message_path: Path,
) -> list[str]:
    command = [
        codex_binary,
        "exec",
        "-C",
        workdir,
        "-m",
        shared_model,
        "--json",
        "--output-last-message",
        str(last_message_path),
        *_config_override_args(reasoning=reasoning, approval=approval),
    ]
    if _uses_bypass_sandbox(sandbox, approval):
        command.append("--dangerously-bypass-approvals-and-sandbox")
    else:
        command.extend(["--sandbox", sandbox])
    command.append("-")
    return command

def _build_resume_command(
    *,
    codex_binary: str,
    workdir: str,
    shared_model: str,
    reasoning: str,
    approval: str,
    sandbox: str,
    thread_id: str,
    last_message_path: Path,
) -> list[str]:
    command = [
        codex_binary,
        "exec",
        "-C",
        workdir,
        "resume",
        "--json",
        "--output-last-message",
        str(last_message_path),
        "-m",
        shared_model,
        *_config_override_args(reasoning=reasoning, approval=approval, sandbox=sandbox),
    ]
    if _uses_bypass_sandbox(sandbox, approval):
        command.append("--dangerously-bypass-approvals-and-sandbox")
    command.extend([thread_id, "-"])
    return command
