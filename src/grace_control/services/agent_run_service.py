# AI_HEADER: agent_run_service — orchestrates renderer→env→supervisor→collector
# START_MODULE_CONTRACT
# purpose: Orchestrate a single CLI agent run: render command template,
#          build env (inheriting parent), handle stdin/file/none input modes,
#          spawn process with timeout, collect artifacts. No hardcoded CLI names.
#          Also injects session resume flags (TZ_SESSION_RESUME.md Phase 2)
#          and extracts session_id from agent stdout.
# inputs: executor dict (from AgentProfile.to_dict()), context params.
# returns: dict with accepted, domain_status, stdout, stderr, exit_code, etc.
#          Includes 'session_id' field when extractable from stdout.
# side_effects: Spawns subprocess, writes artifacts.
# error_behavior: Never raises; errors in result dict.
# END_MODULE_CONTRACT
# START_MODULE_MAP
# mapping:   - class: AgentRunService
#             - function: _extract_session_id
# END_MODULE_MAP

from __future__ import annotations
import json
import re
from pathlib import Path
from typing import Any
from grace_control.services.agent_artifact_collector import AgentArtifactCollector
from grace_control.services.agent_env_builder import AgentEnvBuilder
from grace_control.services.command_template_renderer import CommandTemplateRenderer
from grace_control.services.process_supervisor import ProcessSupervisor
from grace_control.core.structured_logger import GraceLogger

_log = GraceLogger("agent_run_service")


# Session ID extraction patterns per backend (TZ_SESSION_RESUME.md Phase 2)
_SESSION_PATTERNS: dict[str, list[re.Pattern]] = {
    "opencode": [
        re.compile(r'"session_id":\s*"(ses_\w+)"'),
        re.compile(r'Session:\s*(ses_\w+)'),
        re.compile(r'Session:\s*(\S+)'),
    ],
    "agy": [
        re.compile(r'Conversation ID:\s*(\S+)'),
    ],
    "cli": [  # fallback for unknown backends
        re.compile(r'"session_id":\s*"(ses_\w+)"'),
        re.compile(r'Session:\s*(ses_\w+)'),
    ],
}


def _extract_session_id(stdout: str, backend: str) -> str | None:
    """Extract the session/external ID from agent stdout.

    Args:
        stdout: Raw stdout from the agent subprocess.
        backend: The backend type from the executor dict
                 (e.g. "opencode", "agy", "cli").

    Returns:
        The session ID string if found, None otherwise.
    """
    patterns = _SESSION_PATTERNS.get(backend, _SESSION_PATTERNS["cli"])
    for pat in patterns:
        m = pat.search(stdout)
        if m:
            sid = m.group(1)
            _log.info("session_id_extracted", backend=backend, session_id=sid)
            return sid
    # Try JSON parse as last resort
    try:
        data = json.loads(stdout)
        if isinstance(data, dict) and "session_id" in data:
            sid = data["session_id"]
            _log.info("session_id_extracted_json", backend=backend, session_id=sid)
            return str(sid)
    except (json.JSONDecodeError, TypeError):
        pass
    return None


def _opencode_session_usable(session_id: str) -> bool:
    """Best-effort check whether an opencode session id is still usable.

    Conservative default: returns False (skip resume) when we cannot
    prove the session is valid. Stale opencode sessions cause
    `Session not found` exit_code=1 — never blindly resume.

    This is intentionally simple and CLI-free. A future iteration may
    inspect `~/.local/share/opencode/storage/session/<id>` or call
    `opencode session list`. For now: trust the format prefix only.
    """
    if not session_id:
        return False
    sid = session_id.strip()
    # opencode session ids look like `ses_<8 hex>` or longer base32.
    if not sid.startswith("ses_"):
        return False
    if len(sid) < 6:
        return False
    return True


class AgentRunService:
    def __init__(self) -> None:
        self._renderer = CommandTemplateRenderer()
        self._env_builder = AgentEnvBuilder()
        self._supervisor = ProcessSupervisor()
        self._collector = AgentArtifactCollector()

    async def run(self, executor: dict, *, packet_id: str, worktree_path: Path, state_root: Path,
                  packet_markdown: str, timeout_seconds: int = 600, run_dir: Path | None = None,
                  resume_session_id: str | None = None,
                  fork: bool = False,
                  stdout_log_path: Path | str | None = None,
                  stderr_log_path: Path | str | None = None) -> dict[str, Any]:
        ctx = {
            "packet_id": packet_id,
            "model": executor.get("model", ""),
            "effort": executor.get("effort", "medium"),
            "role": executor.get("role", "coder"),
            "worktree_path": str(worktree_path),
            "state_root": str(state_root),
            "attempt": "1",
            "packet_markdown": packet_markdown,
        }

        # Input mode must be resolved before command render (P0-2: {packet_path} needs ctx).
        input_mode = executor.get("input_mode", "none")
        input_template = executor.get("input_template", "")
        stdin_text: str | None = None
        if input_mode == "stdin" and input_template:
            stdin_text = self._renderer.render([input_template], ctx)[0]
        elif input_mode == "file":
            effective_run_dir = run_dir or (state_root / "agents" / packet_id)
            packet_path = effective_run_dir / "EXECUTION_PACKET.md"
            packet_path.parent.mkdir(parents=True, exist_ok=True)
            packet_path.write_text(packet_markdown)
            ctx["packet_path"] = str(packet_path)

        # Normalize legacy string command → list
        cmd = executor.get("command", [])
        if isinstance(cmd, str):
            cmd = [cmd, "{packet_markdown}"]
        command = self._renderer.render(cmd, ctx)

        # Inject --dir <worktree_path> for backends that require it (e.g. opencode
        # which connects to a server and would otherwise use the server's cwd).
        # Controlled by the profile field `inject_dir: true` — avoids hardcoding
        # CLI tool names. Legacy fallback: if command[0] basename is "opencode"
        # and the profile has no explicit inject_dir field, still inject (back-compat).
        inject_dir = executor.get("inject_dir")
        if inject_dir is None:
            # Back-compat: auto-detect opencode by binary name
            cmd0 = command[0] if command else ""
            inject_dir = (cmd0 == "opencode" or cmd0.endswith("/opencode"))
        if inject_dir:
            for i, part in enumerate(command):
                if part == "run":
                    command = command[:i + 1] + ["--dir", str(worktree_path)] + command[i + 1:]
                    break

        # Build subprocess env FIRST so extras resolution sees injected vars.
        raw_env = executor.get("env", {})
        env = self._env_builder.build(raw_env)

        # Render env-driven extras (e.g. `--attach $OPENCODE_SERVER_URL`)
        # against the final subprocess env (not just os.environ).
        raw_extras = executor.get("extras", [])
        rendered_extras: list[str] = []
        if isinstance(raw_extras, str):
            raw_extras = [raw_extras]
        if raw_extras:
            pending_flag: str | None = None
            for token in raw_extras:
                if not isinstance(token, str):
                    pending_flag = None
                    continue
                resolved = self._env_builder.resolve(token, env=env)
                value_dropped = ("${" in token and resolved == token) or not resolved.strip()
                if value_dropped:
                    pending_flag = None
                    continue
                if pending_flag is not None:
                    rendered_extras.append(pending_flag)
                    pending_flag = None
                if resolved.startswith("-"):
                    pending_flag = resolved
                else:
                    rendered_extras.append(resolved)
            if pending_flag is not None:
                rendered_extras.append(pending_flag)
        command = command + rendered_extras

        # TZ_SESSION_RESUME.md Phase 2: inject session resume/fork flags.
        # Hardened: never inject stale session id when profile is not
        # explicitly marked safe, when validation is required and not feasible,
        # or when the session id looks empty/invalid.
        resume_mode = executor.get("resume_mode", "never")
        resume_safe = bool(executor.get("resume_safe", False))
        validate_before_use = bool(executor.get("validate_session_before_use", False))
        session_resume_used = False
        session_resume_reason = "disabled_for_profile"
        if resume_session_id and resume_mode != "never":
            # Empty / placeholder session ids are never safe.
            sid = (resume_session_id or "").strip()
            sid_valid = bool(sid) and len(sid) >= 4
            if not sid_valid:
                session_resume_reason = "invalid_or_empty"
            elif not resume_safe:
                session_resume_reason = "profile_not_resume_safe"
            elif validate_before_use and not _opencode_session_usable(sid):
                # Conservative: if we cannot validate, skip resume.
                session_resume_reason = "invalid_or_stale"
            else:
                resume_flag = executor.get("resume_flag", "--session")
                command.append(resume_flag)
                command.append(sid)
                if fork:
                    fork_flag = executor.get("fork_flag")
                    if fork_flag:
                        command.append(fork_flag)
                session_resume_used = True
                session_resume_reason = "injected"
                _log.info("session_resume_injected",
                          packet_id=packet_id,
                          resume_session_id=sid,
                          fork=fork,
                          resume_mode=resume_mode)
            if not session_resume_used:
                _log.warn("session_resume_skipped_invalid",
                          packet_id=packet_id,
                          resume_session_id=resume_session_id,
                          reason=session_resume_reason,
                          resume_mode=resume_mode)

        # Persist resume decision in evidence so admin/debug can see it.
        # We attach it after the run via a side-channel; but for now we add it
        # to the stdin/cmd preview by appending a comment? No — keep cmd clean.
        # Use env or temp file. Simplest: stash on the result via a helper.
        # (Will be attached by caller after run completes.)
        # Stash in a thread-local-like attribute on self.
        self._last_session_resume = {
            "requested": bool(resume_session_id and resume_mode != "never"),
            "session_id": resume_session_id,
            "used": session_resume_used,
            "reason": session_resume_reason,
        }

        preview_env = self._env_builder.preview(env)

        cwd_template = str(executor.get("cwd", "{worktree_path}"))
        cwd_str = self._renderer.render([cwd_template], ctx)[0]
        cwd = worktree_path if cwd_str == str(worktree_path) else Path(cwd_str)
        cwd.mkdir(parents=True, exist_ok=True)

        result = await self._supervisor.run(
            command, cwd=cwd, env=env, timeout_seconds=timeout_seconds, stdin_text=stdin_text,
            stdout_log_path=stdout_log_path, stderr_log_path=stderr_log_path,
        )

        accepted = (not result.timed_out and result.exit_code == 0)
        if result.timed_out:
            domain_status = "timeout"
        elif result.exit_code == 0:
            domain_status = "completed"
        else:
            domain_status = "failed"

        effective_run_dir = run_dir or (state_root / "agents" / packet_id)
        artifacts = self._collector.collect(
            effective_run_dir, stdout=result.stdout, stderr=result.stderr,
            exit_code=result.exit_code, duration_ms=result.duration_ms,
            command_preview=command, env_preview=preview_env,
        )

        # TZ_SESSION_RESUME.md Phase 2: extract session_id from stdout
        backend = executor.get("backend", "cli")
        # When backend=cli (universal backend), derive the actual CLI kind
        # from command[0] so session extraction uses the right patterns
        # (e.g. AGY needs Conversation ID, opencode needs Session: ses_...).
        if backend == "cli":
            cmd = executor.get("command", [])
            if isinstance(cmd, list) and cmd:
                first = str(cmd[0]).lower()
                if first in ("agy", "opencode", "codex"):
                    backend = first
        result_session_id = _extract_session_id(result.stdout, backend)

        return {
            "accepted": accepted,
            "domain_status": domain_status,
            "executor_id": executor.get("executor_id", "unknown"),
            "command_preview": command,
            "model": executor.get("model", ""),
            "prompt": stdin_text or packet_markdown or "",
            "exit_code": result.exit_code,
            "stdout": result.stdout,
            "stderr": result.stderr,
            "stdout_path": artifacts.get("stdout_path", ""),
            "stderr_path": artifacts.get("stderr_path", ""),
            "cwd": str(cwd),
            "worktree_path": str(worktree_path),
            "duration_ms": result.duration_ms,
            "reason": "" if result.exit_code == 0 else f"exit_code={result.exit_code}",
            "artifacts": list(artifacts.values()),
            "session_id": result_session_id,
        }
