from __future__ import annotations

from pathlib import Path
import sys

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))

from tests_live import conftest as live_conftest


def test_conftest_skips_without_env(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.delenv("GRACE_LIVE_AGENT_TESTS", raising=False)

    class Item:
        def __init__(self):
            self.keywords = {"live_agent": True}
            self.markers = []

        def add_marker(self, marker):
            self.markers.append(marker)

    item = Item()
    live_conftest.pytest_collection_modifyitems(None, [item])
    assert item.markers


def test_require_live_env_raises(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.delenv("GRACE_LIVE_AGENT_TESTS", raising=False)
    with pytest.raises(pytest.skip.Exception):
        live_conftest.require_live_env()
