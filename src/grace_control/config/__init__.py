# ############################################################################
# AI_HEADER: config_init
# ROLE: Re-export canonical settings for grace_control.config namespace.
#       The single source of truth is config/settings.py (GraceSettings).
#       This file previously contained a duplicate GraceSettings class with
#       stale defaults (/tmp/grace-eval, execution_backend="legacy") —
#       removed in TZ_WORKTREE_ISOLATION_FIX P0/3.1.
# ############################################################################

# Import the submodules so that `from grace_control.config import settings`
# gives the *module* (not the singleton instance), matching test expectations.
from grace_control.config import settings  # noqa: F401
from grace_control.config import project_config  # noqa: F401
from grace_control.config.settings import GraceSettings  # noqa: F401
from grace_control.config.project_config import ProjectConfig, get_project_config  # noqa: F401

__all__ = [
    "GraceSettings",
    "settings",
    "project_config",
    "ProjectConfig",
    "get_project_config",
]
