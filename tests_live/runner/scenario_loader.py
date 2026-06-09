"""Scenario loader — loads declarative YAML scenario definitions."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

SCENARIOS_DIR = Path(__file__).resolve().parent.parent / "scenarios"


def load_scenario(scenario_id: str) -> dict[str, Any]:
    """Load a scenario YAML file by its id (without .yaml extension).

    Searches tests_live/scenarios/<scenario_id>.yaml.
    """
    yaml_path = SCENARIOS_DIR / f"{scenario_id}.yaml"
    if not yaml_path.exists():
        msg = f"Scenario not found: {scenario_id} (looked at {yaml_path})"
        raise FileNotFoundError(msg)

    try:
        import yaml
    except ImportError:
        raise ImportError("PyYAML is required to load scenario files")

    with open(yaml_path) as f:
        scenario = yaml.safe_load(f)

    _validate_scenario(scenario, scenario_id)
    return scenario


def _validate_scenario(scenario: dict[str, Any], scenario_id: str) -> None:
    """Basic validation of scenario structure."""
    errors: list[str] = []

    if not isinstance(scenario, dict):
        errors.append("scenario must be a mapping")
    else:
        for field in ("id", "fixture_app", "waves"):
            if field not in scenario:
                errors.append(f"missing required field: {field}")

        if scenario.get("id") != scenario_id:
            errors.append(
                f"scenario id mismatch: file={scenario_id}, yaml={scenario.get('id')}"
            )

        waves = scenario.get("waves", [])
        if not isinstance(waves, list) or len(waves) == 0:
            errors.append("must have at least one wave")
        else:
            for wi, wave in enumerate(waves):
                if not isinstance(wave, dict):
                    errors.append(f"wave[{wi}] must be a mapping")
                    continue
                for field in ("id", "title", "packets"):
                    if field not in wave:
                        errors.append(f"wave[{wi}] missing {field}")

                packets = wave.get("packets", [])
                for pi, pkt in enumerate(packets):
                    if not isinstance(pkt, dict):
                        errors.append(f"wave[{wi}].packets[{pi}] must be a mapping")
                        continue
                    for field in ("id", "role", "prompt"):
                        if field not in pkt:
                            errors.append(
                                f"wave[{wi}].packets[{pi}] missing {field}"
                            )

    if errors:
        raise ValueError(
            f"Scenario {scenario_id} validation failed:\n" + "\n".join(errors)
        )


def list_scenarios() -> list[str]:
    """Return list of available scenario ids."""
    return sorted(
        f.stem for f in SCENARIOS_DIR.glob("*.yaml") if not f.stem.startswith("_")
    )


def check_live_agent_env() -> tuple[bool, str]:
    """Check if live agent tests are enabled via env."""
    if os.environ.get("GRACE_LIVE_AGENT_TESTS") != "1":
        return False, "GRACE_LIVE_AGENT_TESTS not set to 1"
    if os.environ.get("GRACE_DEV_TOOLS_ENABLED") != "1":
        return False, "GRACE_DEV_TOOLS_ENABLED not set to 1"
    return True, ""
