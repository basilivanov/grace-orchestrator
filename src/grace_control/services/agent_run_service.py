# AI_HEADER: agent_run_service — orchestrates renderer→env→supervisor→collector
# START_MODULE_CONTRACT
# purpose: Orchestrate a single CLI agent run: resolve profile from agent_profiles,
#          render command template, build env, spawn process, collect artifacts.
#          No hardcoded CLI names (opencode/codex/agy).
# inputs: executor dict (from agent_profiles), request context.
# returns: dict with stdout, stderr, exit_code, duration_ms, timed_out, artifacts.
# side_effects: Spawns subprocess, writes artifact files.
# error_behavior: Never raises; errors encoded in result dict.
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
                  packet_markdown: str, timeout_seconds: int = 600) -> dict[str, Any]:
        ctx = {
            "packet_id": packet_id,
            "model": executor.get("model", ""),
            "effort": executor.get("effort", "medium"),
            "role": executor.get("roles", ["coder"])[0] if isinstance(executor.get("roles"), list) else "coder",
            "worktree_path": str(worktree_path),
            "state_root": str(state_root),
            "attempt": str(executor.get("attempt", 1)),
        }
        command = self._renderer.render(executor.get("command", []), ctx)
        run_dir = state_root / "agents" / packet_id
        raw_env = executor.get("env", {})
        env = self._env_builder.build(raw_env)

        preview_env = self._env_builder.preview(env)
        preview_cmd = " ".join(command)

        result = await self._supervisor.run(command, cwd=worktree_path, env=env, timeout_seconds=timeout_seconds)

        artifacts = self._collector.collect(
            run_dir, stdout=result.stdout, stderr=result.stderr,
            exit_code=result.exit_code, duration_ms=result.duration_ms,
            command_preview=command,
        )

        return {
            "accepted": not result.timed_out,
            "domain_status": "timeout" if result.timed_out else ("completed" if result.exit_code == 0 else "failed"),
            "executor_id": executor.get("executor_id", "unknown"),
            "command_preview": command,
            "exit_code": result.exit_code,
            "stdout": result.stdout,
            "stderr": result.stderr,
            "stdout_path": artifacts.get("stdout_path", ""),
            "stderr_path": artifacts.get("stderr_path", ""),
            "worktree_path": str(worktree_path),
            "duration_ms": result.duration_ms,
            "reason": "" if result.exit_code == 0 else f"exit_code={result.exit_code}",
            "artifacts": list(artifacts.values()),
        }
