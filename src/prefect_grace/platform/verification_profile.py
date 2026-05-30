# ############################################################################
# AI_HEADER: verification_profile
# ROLE: Loads and validates verification profiles configuration for GRACE.
# ############################################################################

# START_MODULE_CONTRACT
# purpose: Parse policies/verification.yaml and check profile validity.
# inputs: Path to verification profiles yaml (optional).
# returns: dict containing profiles.
# side_effects: Reads verification.yaml from disk.
# emitted_logs: none.
# error_behavior: Raises FileNotFoundError or ValueError if profiles are invalid.
# END_MODULE_CONTRACT

# START_MODULE_MAP
# mapping:
#   - function: load_verification_profiles
# END_MODULE_MAP

from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml

#START_BLOCK_PROFILES_LOADER
REQUIRED_PROFILES = {
    "docs",
    "backend_quick",
    "frontend_quick",
    "read_only_observability",
    "today_week_observability",
    "prefect_grace_unit",
    "full_orchestrator_contract",
}

# START_FUNCTION_CONTRACT
# name: load_verification_profiles
# purpose: Load verification profiles from policies/verification.yaml.
# inputs:
#   config_path: Path | str | None, path to verification.yaml.
# returns: dict mapping profiles to their configurations.
# side_effects: Reads yaml config from disk.
# emitted_logs: none.
# error_behavior: Raises FileNotFoundError if missing, ValueError if invalid.
# END_FUNCTION_CONTRACT
def load_verification_profiles(config_path: Path | str | None = None) -> dict[str, Any]:
    if config_path is None:
        repo_root = Path(__file__).resolve().parents[2]
        grace_profiles = repo_root / "grace" / "policies" / "verification.yaml"
        if grace_profiles.exists():
            config_path = grace_profiles
        else:
            config_path = repo_root / "prefect_grace" / "policies" / "verification.yaml"
    else:
        config_path = Path(config_path)

    if not config_path.exists():
        raise FileNotFoundError(f"Verification profiles configuration file not found at {config_path}")

    with open(config_path, "r", encoding="utf-8") as f:
        data = yaml.safe_load(f) or {}

    profiles = data.get("profiles", {})
    if not isinstance(profiles, dict):
        raise ValueError("Verification profiles should be a dictionary")

    missing = REQUIRED_PROFILES - set(profiles.keys())
    if missing:
        raise ValueError(f"Missing required verification profiles: {sorted(list(missing))}")

    for name, config in profiles.items():
        if not isinstance(config, dict):
            raise ValueError(f"Profile '{name}' configuration must be a dictionary")
        if "description" not in config:
            raise ValueError(f"Profile '{name}' is missing description field")

    return profiles

#END_BLOCK_PROFILES_LOADER
