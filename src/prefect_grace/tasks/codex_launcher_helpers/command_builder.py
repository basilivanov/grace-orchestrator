# AI_HEADER: codex_launcher_helpers
# START_MODULE_CONTRACT
# END_MODULE_CONTRACT
# START_MODULE_MAP
# END_MODULE_MAP

from __future__ import annotations

from pathlib import Path
from typing import Any

from prefect_grace.audit import log_sandbox_bypass_attempt
from prefect_grace.policies import SandboxBypassDenied, check_sandbox_bypass_allowed

def _config_override_args(*, reasoning: str, approval: str, sandbox: str | None = None) -> list[str]:
    args = ["-c", f'model_reasoning_effort="{reasoning}"']
    if approval:
        args.extend(["-c", f'approval_policy="{approval}"'])
    if sandbox:
        args.extend(["-c", f'sandbox_mode="{sandbox}"'])
    return args

def _uses_bypass_sandbox(
    sandbox: str,
    approval: str,
    packet_id: str,
    project_config: dict[str, Any] | None = None,
) -> bool:
    """
    Check if sandbox bypass should be used, enforcing policy gate.

    Args:
        sandbox: Sandbox mode
        approval: Approval policy
        packet_id: Packet identifier for audit trail
        project_config: Project configuration dict (optional)

    Returns:
        True if bypass should be used (and is allowed by policy)

    Raises:
        SandboxBypassDenied: If bypass is requested but denied by policy
    """
    if sandbox != "danger-full-access" or approval != "never":
        return False

    # Check policy
    reason = f"sandbox={sandbox}, approval={approval}"
    allowed, policy_reason = check_sandbox_bypass_allowed(
        packet_id=packet_id,
        reason=reason,
        project_config=project_config,
    )

    # Log attempt
    log_sandbox_bypass_attempt(
        packet_id=packet_id,
        allowed=allowed,
        reason=reason,
        policy_reason=policy_reason,
    )

    # Raise if denied
    if not allowed:
        raise SandboxBypassDenied(f"Sandbox bypass denied: {policy_reason}")

    return True

def _build_exec_command(
    *,
    codex_binary: str,
    workdir: str,
    shared_model: str,
    reasoning: str,
    approval: str,
    sandbox: str,
    last_message_path: Path,
    packet_id: str,
    project_config: dict[str, Any] | None = None,
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
    if _uses_bypass_sandbox(sandbox, approval, packet_id, project_config):
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
    packet_id: str,
    project_config: dict[str, Any] | None = None,
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
    if _uses_bypass_sandbox(sandbox, approval, packet_id, project_config):
        command.append("--dangerously-bypass-approvals-and-sandbox")
    command.extend([thread_id, "-"])
    return command
