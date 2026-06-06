# AI_HEADER: agent_run_service — orchestrates renderer→env→supervisor→collector
# START_MODULE_CONTRACT
# purpose: Orchestrate a single CLI agent run: render command template,
#          build env (inheriting parent), handle stdin/file/none input modes,
#          spawn process with timeout, collect artifacts. No hardcoded CLI names.
# inputs: executor dict (from AgentProfile.to_dict()), context params.
# returns: dict with accepted, domain_status, stdout, stderr, exit_code, etc.
# side_effects: Spawns subprocess, writes artifacts.
# error_behavior: Never raises; errors in result dict.
# END_MODULE_CONTRACT
# START_MODULE_MAP
# mapping:   - class: AgentRunService
# END_MODULE_MAP

from __future__ import annotations
from pathlib import Path
from typing import Any
from grace_control.services.agent_artifact_collector import AgentArtifactCollector
from grace_control.services.agent_env_builder import AgentEnvBuilder
from grace_control.services.command_template_renderer import CommandTemplateRenderer
from grace_control.services.process_supervisor import ProcessSupervisor


class AgentRunService:
    def __init__(self) -> None:
        self._renderer = CommandTemplateRenderer()
        self._env_builder = AgentEnvBuilder()
        self._supervisor = ProcessSupervisor()
        self._collector = AgentArtifactCollector()

    async def run(self, executor: dict, *, packet_id: str, worktree_path: Path, state_root: Path,
                  packet_markdown: str, timeout_seconds: int = 600, run_dir: Path | None = None) -> dict[str, Any]:
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

        # Render env-driven extras (e.g. `--attach $OPENCODE_SERVER_URL`).
        # Rules:
        #   - Each token is scanned for ${VAR} placeholders.
        #   - If a token is a literal flag (starts with `-`) it is buffered as
        #     a "pending flag" and only emitted if a value follows it.
        #   - If the value token is ${VAR} (unset) or resolves to empty,
        #     the pending flag is dropped together with the value.
        #   - Standalone literal flags (no value) are emitted as-is.
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
                resolved = self._env_builder.resolve(token)
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

        raw_env = executor.get("env", {})
        env = self._env_builder.build(raw_env)
        preview_env = self._env_builder.preview(env)

        cwd_template = str(executor.get("cwd", "{worktree_path}"))
        cwd_str = self._renderer.render([cwd_template], ctx)[0]
        cwd = worktree_path if cwd_str == str(worktree_path) else Path(cwd_str)

        result = await self._supervisor.run(
            command, cwd=cwd, env=env, timeout_seconds=timeout_seconds, stdin_text=stdin_text,
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

        return {
            "accepted": accepted,
            "domain_status": domain_status,
            "executor_id": executor.get("executor_id", "unknown"),
            "command_preview": command,
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
        }
