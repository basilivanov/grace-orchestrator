# ############################################################################
# AI_HEADER: execution_environment
# ROLE: Deterministic probe of the execution environment (shell, venv, paths).
#        Architect and compiler use this to validate commands.
# ############################################################################

from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path

from pydantic import BaseModel


class ExecutionEnvironment(BaseModel):
    shell: str = "/bin/sh"
    shell_is_bash: bool = False
    shell_supports_source: bool = False
    subprocess_shell_default: bool = True
    project_root: str = ""
    target_repo_root: str = ""
    worktree_root: str = ""
    state_root: str = ""
    api_python_path: str | None = None
    has_api_venv: bool = False
    package_manager: str | None = None
    allowed_command_catalog: list[str] = [
        "backend_pytest",
        "backend_pytest_targeted",
        "frontend_typecheck",
        "guardrails_fast",
        "guardrails_normal",
        "guardrails_strict",
        "guardrails_full",
        "contracts_check",
    ]

    model_config = {"frozen": False}


def probe_execution_environment(
    *,
    target_repo_root: Path | None = None,
    project_root: Path | None = None,
    state_root: Path | None = None,
    worktree_root: Path | None = None,
) -> ExecutionEnvironment:
    """Discover execution environment attributes for the compiler."""
    cwd = Path.cwd().resolve()

    # ── Shell detection ────────────────────────────────────────────
    shell_path = os.environ.get("SHELL", "/bin/sh")
    shell_is_bash = "bash" in os.path.basename(shell_path).lower()

    # Check if /bin/sh supports 'source'
    shell_supports_source = False
    try:
        r = subprocess.run(
            ["/bin/sh", "-c", "type source >/dev/null 2>&1"],
            capture_output=True, timeout=3,
        )
        shell_supports_source = r.returncode == 0
    except Exception:
        pass
    # dash falls back to '.' which works everywhere
    if not shell_supports_source:
        try:
            r = subprocess.run(
                ["/bin/sh", "-c", ". /dev/null 2>&1 || true"],
                capture_output=True, timeout=3,
            )
            # '.' exists (though /dev/null isn't a script)
            shell_supports_source = False  # '. exists but not 'source'
        except Exception:
            pass

    # ── Target repo paths ──────────────────────────────────────────
    target = target_repo_root or Path(
        os.environ.get("GRACE_TARGET_REPO_ROOT", str(cwd))
    )
    proj = project_root or cwd
    state = state_root or (target / ".grace" / "state")
    wt = worktree_root or (target / ".grace" / "worktrees")

    # ── Python / venv detection ────────────────────────────────────
    api_python_path: str | None = None
    has_api_venv = False
    venv_python = target / "apps" / "api" / ".venv" / "bin" / "python"
    if venv_python.exists():
        api_python_path = str(venv_python)
        has_api_venv = True
    else:
        # Try system python3
        p3 = shutil.which("python3")
        if p3:
            api_python_path = p3
        else:
            p3 = shutil.which("python")
            if p3:
                api_python_path = p3

    # ── Package manager ────────────────────────────────────────────
    pm: str | None = None
    for mgr in ("pnpm", "npm", "yarn"):
        if shutil.which(mgr):
            pm = mgr
            break

    return ExecutionEnvironment(
        shell=shell_path,
        shell_is_bash=shell_is_bash,
        shell_supports_source=shell_supports_source,
        subprocess_shell_default=True,
        project_root=str(proj.resolve()),
        target_repo_root=str(target.resolve()),
        worktree_root=str(wt.resolve()),
        state_root=str(state.resolve()),
        api_python_path=api_python_path,
        has_api_venv=has_api_venv,
        package_manager=pm,
    )
