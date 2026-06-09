"""Shared fixtures and guards for tests_live."""

from __future__ import annotations

import os
import shutil
import tempfile
from pathlib import Path

import pytest

from tests_live.runner.scenario_loader import check_live_agent_env, load_scenario


def pytest_configure(config):
    config.addinivalue_line("markers", "live_agent: mark test as requiring real agents")


def pytest_collection_modifyitems(config, items):
    if os.environ.get("GRACE_LIVE_AGENT_TESTS") != "1":
        skip = pytest.mark.skip(reason="GRACE_LIVE_AGENT_TESTS=1 required")
        for item in items:
            if "live_agent" in item.keywords:
                item.add_marker(skip)


@pytest.fixture
def target_dir():
    tmp = tempfile.mkdtemp(prefix="grace-live-")
    yield Path(tmp)
    if not os.environ.get("GRACE_LIVE_TEST_KEEP_ARTIFACTS"):
        shutil.rmtree(tmp, ignore_errors=True)


@pytest.fixture
def api_url():
    return os.environ.get("GRACE_API_URL", "http://127.0.0.1:8042")


@pytest.fixture
def source_dir():
    return Path.cwd()


@pytest.fixture
def scenario(request):
    marker = request.node.get_closest_marker("live_agent")
    if marker:
        scenario_id = marker.kwargs.get("scenario_id", request.node.name)
    else:
        scenario_id = request.node.name
    return load_scenario(scenario_id)


def require_live_env():
    ok, msg = check_live_agent_env()
    if not ok:
        pytest.skip(msg)
