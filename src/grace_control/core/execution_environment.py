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
    # The command runner uses /bin/sh (subprocess with shell=True),
    # NOT the user's login shell ($SHELL). So we probe /bin/sh.
    shell_path = "/bin/sh"
    shell_is_bash = False  # Ubuntu /bin/sh is dash; even if symlinked to bash,
                           # bash runs in POSIX mode as sh and lacks 'source'.
    shell_supports_source = False

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
