# AI_HEADER: agent_artifact_collector — persists subprocess output as evidence
# START_MODULE_CONTRACT
# purpose: Save agent stdout/stderr/summary to a run evidence directory.
#          Best-effort, never raises.
# inputs: run_dir (Path), stdout/stderr/exit_code/duration_ms/command_preview.
# returns: dict{stdout_path, stderr_path, command_log_path}.
# side_effects: Writes files to run_dir.
# error_behavior: Never raises; returns partial paths on failure.
# END_MODULE_CONTRACT
# START_MODULE_MAP
# mapping:   - class: AgentArtifactCollector
# END_MODULE_MAP

from __future__ import annotations
from pathlib import Path


class AgentArtifactCollector:
    def collect(self, run_dir: Path, *, stdout: str, stderr: str, exit_code: int,
                duration_ms: int, command_preview: list[str], env_preview: dict | None = None) -> dict[str, str]:
        paths = {"stdout_path": "", "stderr_path": "", "command_log_path": ""}
        try:
            run_dir.mkdir(parents=True, exist_ok=True)
            so_path = run_dir / "agent_stdout.log"
            so_path.write_text(stdout or "")
            paths["stdout_path"] = str(so_path)
            se_path = run_dir / "agent_stderr.log"
            se_path.write_text(stderr or "")
            paths["stderr_path"] = str(se_path)
            cl_path = run_dir / "agent_command.log"
            cl_text = (f"exit_code={exit_code}\nduration_ms={duration_ms}\n"
                       f"command={' '.join(command_preview)}\n")
            if env_preview:
                for k, v in env_preview.items():
                    cl_text += f"env_{k}={v}\n" if len(v) < 50 else f"env_{k}={v[:50]}...\n"
            cl_path.write_text(cl_text)
            paths["command_log_path"] = str(cl_path)
        except Exception:
            pass
        return paths
