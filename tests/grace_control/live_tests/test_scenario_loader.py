from __future__ import annotations

from pathlib import Path
import sys

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))

from tests_live.runner.scenario_loader import (
    check_live_agent_env,
    list_scenarios,
    load_scenario,
)


def test_load_scenario_exists():
    scenario = load_scenario("backend-1w")
    assert isinstance(scenario, dict)
    for key in ("id", "fixture_app", "waves"):
        assert key in scenario


def test_load_scenario_not_found():
    with pytest.raises(FileNotFoundError):
        load_scenario("does-not-exist")


def test_list_scenarios():
    scenarios = list_scenarios()
    assert isinstance(scenarios, list)
    assert scenarios


def test_check_live_env_disabled(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.delenv("GRACE_LIVE_AGENT_TESTS", raising=False)
    ok, msg = check_live_agent_env()
    assert ok is False
    assert msg


def test_validate_missing_fields():
    from tests_live.runner import scenario_loader

    with pytest.raises(ValueError, match="missing required field"):
        scenario_loader._validate_scenario({}, "bad-scenario")


def test_validate_business_feature_no_waves():
    """business_feature: true allows scenario without waves."""
    from tests_live.runner.scenario_loader import load_scenario

    scenario = load_scenario(
        "solarsage-pilot-005-business-feature-full-pipeline-smoke"
    )
    assert scenario.get("business_feature") is True
    assert "business_feature_text" in scenario
    assert isinstance(scenario.get("waves"), list)
