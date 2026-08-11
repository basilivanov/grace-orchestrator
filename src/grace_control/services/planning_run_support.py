# ############################################################################
# AI_HEADER: planning_run_support — shared planning run configuration helpers
# ROLE: Centralizes planning log paths, target-repository precedence, and the
#       context-disabled feature flag used by planning stages and the facade.
# ############################################################################

# START_MODULE_CONTRACT
# purpose: Resolve shared planning-run configuration without duplicating precedence rules.
# inputs: Feature/run identifiers, optional planning roots, plan specs, settings, and environment.
# returns: Log paths, effective target roots, or a boolean context-disabled flag.
# side_effects: Creates the configured planning log directory and reads environment configuration.
# emitted_logs: None; stage callers own lifecycle logging.
# error_behavior: Uses the current-directory fallback when no target repository is configured.
# END_MODULE_CONTRACT

# START_MODULE_MAP
# mapping:
#   - function: planning_log_paths
#   - function: resolve_planning_workspace_root
#   - function: resolve_plan_target_root
#   - function: context_disabled
# END_MODULE_MAP

from __future__ import annotations

import os
from pathlib import Path

from grace_control.core.structured_logger import GraceLogger

_log = GraceLogger("planning_run_support")


# START_BLOCK_CONFIGURATION
# START_FUNCTION_CONTRACT
# name: planning_log_paths
# purpose: Create and return the standard stdout/stderr paths for a planning run.
# inputs: feature_id — feature identifier; run_id — planning run identifier.
# returns: Tuple of log directory, stdout path, and stderr path.
# side_effects: Creates the feature/run planning log directory.
# emitted_logs: None.
# error_behavior: Propagates filesystem errors when the log directory cannot be created.
# END_FUNCTION_CONTRACT
def planning_log_paths(feature_id: str, run_id: str) -> tuple[Path, str, str]:
    from grace_control.config.settings import settings

    log_dir = Path(settings.planning_logs_root) / feature_id / run_id
    log_dir.mkdir(parents=True, exist_ok=True)
    return log_dir, str(log_dir / "stdout.log"), str(log_dir / "stderr.log")


# START_FUNCTION_CONTRACT
# name: resolve_planning_workspace_root
# purpose: Apply the planning workspace root precedence used by context and architect stages.
# inputs: explicit_root — caller override; context — optional collected context; settings_obj — settings.
# returns: Effective workspace root string, defaulting to the current directory.
# side_effects: None.
# emitted_logs: None.
# error_behavior: Ignores missing/falsey optional values and returns the safe default.
# END_FUNCTION_CONTRACT
def resolve_planning_workspace_root(
    explicit_root: str | None,
    context: dict | None,
    settings_obj: object,
) -> str:
    context_root = context.get("target_repo_root") if isinstance(context, dict) else None
    return (
        explicit_root
        or context_root
        or getattr(settings_obj, "target_repo_root", None)
        or "."
    )


# START_FUNCTION_CONTRACT
# name: resolve_plan_target_root
# purpose: Apply the canonical feature-spec/settings/environment target-root precedence.
# inputs: spec — feature specification; settings_obj — application settings object.
# returns: Effective target repository Path.
# side_effects: Reads GRACE_TARGET_REPO_ROOT when higher-priority values are absent.
# emitted_logs: None.
# error_behavior: Falls back to the current directory for missing or non-string values.
# END_FUNCTION_CONTRACT
def resolve_plan_target_root(spec: dict, settings_obj: object) -> Path:
    target_root = (
        spec.get("target_repo_root")
        or getattr(settings_obj, "target_repo_root", None)
        or os.environ.get("GRACE_TARGET_REPO_ROOT")
        or "."
    )
    return Path(target_root) if isinstance(target_root, str) else Path(".")


# START_FUNCTION_CONTRACT
# name: context_disabled
# purpose: Read the opt-in flag that disables the Architect context execution.
# inputs: None.
# returns: True when GRACE_CONTEXT_DISABLED uses a recognized truthy value.
# side_effects: Reads GRACE_CONTEXT_DISABLED from the process environment.
# emitted_logs: None.
# error_behavior: Returns False when the variable is absent or unrecognized.
# END_FUNCTION_CONTRACT
def context_disabled() -> bool:
    return os.environ.get("GRACE_CONTEXT_DISABLED", "").lower() in {
        "1", "true", "yes", "on",
    }
# END_BLOCK_CONFIGURATION
