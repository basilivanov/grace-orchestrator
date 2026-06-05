"""W10 — GraceLint checker tests: one per rule."""
from __future__ import annotations

import os
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from grace_control.api.main import app
from grace_control.db import init_db
from grace_control.tools.grace_lint.checker import (
    lint_text,
    lint_file,
    load_allowlist,
    Violation,
)


@pytest.fixture
def client_w10(tmp_path, monkeypatch):
    """Per-test DB + sync TestClient for API tests."""
    os.environ["GRACE_CONTEXT_DISABLED"] = "true"
    db_url = f"sqlite:///{tmp_path}/w10_test.db"
    os.environ["GRACE_DB_URL"] = db_url
    init_db(db_url)
    return TestClient(app)


def _v(text: str, path: str = "<test>") -> list[Violation]:
    """Shorthand to lint a string and return violations."""
    return lint_text(text, path=path)


# ── GRC001 ──────────────────────────────────────────────────────────────


def test_grc001_missing_ai_header():
    vs = _v("x = 1")
    codes = {v.code for v in vs}
    assert "GRC001" in codes


def test_grc001_present():
    vs = _v("# AI_HEADER: something\nx = 1")
    assert not any(v.code == "GRC001" for v in vs)


# ── GRC020 ──────────────────────────────────────────────────────────────


def test_grc020_missing_module_contract():
    vs = _v("x = 1\n")
    assert any(v.code == "GRC020" for v in vs)


def test_grc020_present():
    src = "# START_MODULE_CONTRACT\n# purpose: x\n# END_MODULE_CONTRACT\nx = 1"
    assert not any(v.code == "GRC020" for v in _v(src))


# ── GRC021 ──────────────────────────────────────────────────────────────


def test_grc021_missing_module_map():
    vs = _v("x = 1\n")
    assert any(v.code == "GRC021" for v in vs)


# ── GRC004 ──────────────────────────────────────────────────────────────


def test_grc004_block_mismatch():
    src = "# START_BLOCK_FOO\nx = 1\n# END_BLOCK_BAR\n"
    vs = _v(src)
    assert any(v.code == "GRC004" for v in vs)


def test_grc004_block_balanced():
    src = "# START_BLOCK_FOO\nx = 1\n# END_BLOCK_FOO\n"
    assert not any(v.code == "GRC004" for v in _v(src))


# ── GRC005 ──────────────────────────────────────────────────────────────


def test_grc005_file_too_large():
    big = "\n".join(f"x = {i}" for i in range(1005))
    assert any(v.code == "GRC005" for v in _v(big))


def test_grc005_within_limit():
    small = "\n".join(f"x = {i}" for i in range(500))
    assert not any(v.code == "GRC005" for v in _v(small))


# ── GRC010 ──────────────────────────────────────────────────────────────


def test_grc010_public_function_missing_contract():
    src = "def hello(): pass\n"
    assert any(v.code == "GRC010" for v in _v(src))


def test_grc010_private_function_skipped():
    src = "def _helper(): pass\n"
    assert not any(v.code == "GRC010" for v in _v(src))


# ── GRC012 ──────────────────────────────────────────────────────────────


def test_grc012_function_too_large():
    body = "\n".join(f"    x = {i}" for i in range(10000))
    src = f"def huge():\n{body}\n"
    assert any(v.code == "GRC012" for v in _v(src))


# ── GRC100: os.environ ───────────────────────────────────────────────────


def test_grc100_env_in_runtime():
    src = 'x = os.environ.get("FOO")'
    vs = _v(src, path="src/grace_control/api/routers/foo.py")
    assert any(v.code == "GRC100" for v in vs)


def test_grc100_env_allowed_in_config():
    src = 'x = os.environ.get("FOO")'
    vs = _v(src, path="src/grace_control/config/settings.py")
    assert not any(v.code == "GRC100" for v in vs)


# ── GRC101: subprocess ──────────────────────────────────────────────────


def test_grc101_subprocess_in_runtime():
    src = "import subprocess\nresult = subprocess.run(['git', 'status'])\n"
    vs = _v(src, path="src/grace_control/core/foo.py")
    assert any(v.code == "GRC101" for v in vs)


def test_grc101_subprocess_allowed_in_tests():
    src = "import subprocess\nresult = subprocess.run(['git', 'status'])\n"
    vs = _v(src, path="tests/grace_control/test_foo.py")
    assert not any(v.code == "GRC101" for v in vs)


def test_grc101_subprocess_in_arbitrary_service_fails():
    """GRC101 now catches import subprocess in any service/ not in the allowlist."""
    src = "import subprocess\nresult = subprocess.run(['git', 'status'])\n"
    vs = _v(src, path="src/grace_control/services/foo_service.py")
    assert any(v.code == "GRC101" for v in vs)


# ── GRC102: prefect_grace ────────────────────────────────────────────────


def test_grc102_prefect_grace_in_runtime():
    src = 'from prefect_grace import x'
    vs = _v(src, path="src/grace_control/core/foo.py")
    assert any(v.code == "GRC102" for v in vs)


def test_grc102_prefect_grace_in_archive():
    src = 'from prefect_grace import x'
    vs = _v(src, path="docs/archived/legacy_prefect_grace/foo.py")
    assert not any(v.code == "GRC102" for v in vs)


# ── GRC103: Packet.state mutation ────────────────────────────────────────


def test_grc103_state_mutation_outside_service():
    src = "packet.state = 'ACCEPTED'"
    vs = _v(src, path="src/grace_control/api/routers/bad.py")
    assert any(v.code == "GRC103" for v in vs)


def test_grc103_state_allowed_in_packet_service():
    src = "packet.state = 'ACCEPTED'"
    vs = _v(src, path="src/grace_control/services/packet_service.py")
    assert not any(v.code == "GRC103" for v in vs)


# ── GRC105: hardcoded /tmp ───────────────────────────────────────────────


def test_grc105_hardcoded_tmp():
    src = 'path = "/tmp/grace-eval"'
    vs = _v(src, path="src/grace_control/core/foo.py")
    assert any(v.code == "GRC105" for v in vs)


def test_grc105_tmp_allowed_in_tests():
    src = 'path = "/tmp/grace-eval"'
    vs = _v(src, path="tests/test_foo.py")
    assert not any(v.code == "GRC105" for v in vs)


# ── GRC106: hardcoded main/origin ────────────────────────────────────────


def test_grc106_hardcoded_main():
    src = 'branch = "main"'
    vs = _v(src, path="src/grace_control/core/foo.py")
    assert any(v.code == "GRC106" for v in vs)


def test_grc106_hardcoded_origin():
    src = 'remote = "origin"'
    vs = _v(src, path="src/grace_control/core/foo.py")
    assert any(v.code == "GRC106" for v in vs)


# ── GRC108: module over 300 lines without blocks ─────────────────────────


def test_grc108_big_module_no_blocks():
    lines = "\n".join(f"x = {i}" for i in range(350))
    vs = _v(lines, path="src/grace_control/big.py")
    assert any(v.code == "GRC108" for v in vs)


def test_grc108_small_module_ok():
    lines = "\n".join(f"x = {i}" for i in range(50))
    vs = _v(lines, path="src/grace_control/small.py")
    assert not any(v.code == "GRC108" for v in vs)


# ── Allowlist ─────────────────────────────────────────────────────────────


def test_allowlist_suppresses_violation():
    from grace_control.tools.grace_lint.checker import load_allowlist
    al = load_allowlist(Path(".grace/lint_allowlist.yaml"))
    assert "rules" in al
    assert len(al["rules"]) > 0


# ── API endpoint ─────────────────────────────────────────────────────────

def test_tools_grace_lint_endpoint(client_w10):
    """POST /api/tools/grace-lint/run appears in OpenAPI and returns violations."""
    schema = client_w10.get("/openapi.json").json()
    assert "/api/tools/grace-lint/run" in schema["paths"]


def test_tools_grace_lint_returns_violations(client_w10, tmp_path):
    bad = tmp_path / "bad.py"
    bad.write_text("x = os.environ.get('FOO')\n")
    payload = {"paths": [str(bad)], "strict": True}
    r = client_w10.post("/api/tools/grace-lint/run", json=payload)
    assert r.status_code == 200
    body = r.json()
    assert body["ok"] is False
    codes = {v["code"] for v in body["violations"]}
    assert "GRC100" in codes
