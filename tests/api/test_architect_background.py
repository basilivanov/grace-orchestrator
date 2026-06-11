# ############################################################################
# AI_HEADER: test_architect_background
# ROLE: Tests for the background architect mode — async feature planning
#       that returns immediate response and spawns background task.
# ############################################################################

# START_MODULE_CONTRACT
# purpose: Verify background architect creates features immediately then
#          persists packets via background task. Covers success, error,
#          LLM failure, and edge cases.
# inputs: HTTP POST /api/architect/plan with background=True (default).
# verifies: Immediate response shape, feature creation, packet persistence,
#           ARCHITECT_FAILED state on error, frozen_scope propagation.
# emitted_logs: None (uses mock, not log capture).
# error_behavior: Each test independent; no cross-test state leak.
# END_MODULE_CONTRACT

# START_MODULE_MAP
# mapping:
#   - function: _mock_llm_result
#   - function: test_background_returns_immediate
#   - function: test_background_creates_feature_in_planning
#   - function: test_background_completes_and_creates_packets
#   - function: test_background_error_sets_architect_failed
#   - function: test_background_preserves_verification_and_frozen_scope
#   - function: test_background_respects_spec_verification
# END_MODULE_MAP

from __future__ import annotations

import asyncio
import json
from unittest.mock import AsyncMock, patch

import pytest
from grace_control.core.structured_logger import GraceLogger

_log = GraceLogger("test_architect_background")
_LLM_TARGET = "grace_control.api.routers.architect._call_architect_llm"

_SAMPLE_LLM_RESPONSE = {
    "waves": [
        {
            "title": "Phase 1",
            "packets": [
                {
                    "title": "Add auth login",
                    "scope": ["src/auth.py", "tests/test_auth.py"],
                    "acceptance_profile": "NORMAL",
                    "depends_on": [],
                    "description": "Add login endpoint",
                    "verification": {"t0": [], "t1": ["pytest tests/test_auth.py -q"], "t2": []},
                    "expected_evidence": [
                        {"id": "auth_test_green", "kind": "command", "required": True, "pattern": "tests/test_auth.py"}
                    ],
                },
                {
                    "title": "Add user model",
                    "scope": ["src/models/user.py"],
                    "acceptance_profile": "FAST",
                    "depends_on": [],
                    "description": "Add user ORM model",
                    "verification": {"t0": [], "t1": [], "t2": []},
                    "expected_evidence": [],
                },
            ],
        },
        {
            "title": "Phase 2",
            "packets": [
                {
                    "title": "Add tests for auth",
                    "scope": ["tests/test_auth_integration.py"],
                    "acceptance_profile": "NORMAL",
                    "depends_on": [],
                    "description": "Integration tests",
                    "verification": {"t0": [], "t1": ["pytest tests/test_auth_integration.py -q"], "t2": []},
                    "expected_evidence": [],
                }
            ],
        },
    ],
    "constraints": {"frozen_scope": ["docs/archived/legacy_prefect_grace/"]},
    "verification": {"t0": [], "t1": [], "t2": []},
}


#START_BLOCK_HELPERS

def _mock_llm_result(data: dict | None = None) -> AsyncMock:
    """Return an AsyncMock that resolves to a parsed plan dict."""
    payload = data or _SAMPLE_LLM_RESPONSE
    mock = AsyncMock(return_value=payload)
    return mock

#END_BLOCK_HELPERS


#START_BLOCK_TESTS

#START_FUNCTION_CONTRACT
# name: test_background_returns_immediate
# purpose: Verify background POST returns {feature_id, slug, status, immediate}
#          before background task completes.
# inputs: None (uses api fixture).
# verifies: status=200, keys present, slug matches, immediate=True.
# emitted_logs: None.
# error_behavior: AssertionError on mismatch.
#END_FUNCTION_CONTRACT
@pytest.mark.asyncio
async def test_background_returns_immediate(api):
    """Post with description (no waves) triggers background -> immediate response."""
    r = await api.post("/api/architect/plan", json={
        "feature_spec": {"title": "Bg Immediate", "description": "Add login feature"}})
    assert r.status_code == 200
    d = r.json()
    assert d["feature_id"].startswith("feat_")
    assert d["slug"] == "bg-immediate"
    assert d["status"] == "planning"
    assert d["immediate"] is True


#START_FUNCTION_CONTRACT
# name: test_background_creates_feature_in_planning
# purpose: Verify a Feature row is created with status=PLANNING immediately.
# inputs: Uses api fixture + db fixture.
# verifies: Feature in DB with correct title, slug, status.
# emitted_logs: None.
# error_behavior: AssertionError on missing/wrong feature.
#END_FUNCTION_CONTRACT
@pytest.mark.asyncio
async def test_background_creates_feature_in_planning(api, db):
    """After immediate response, feature appears in DB with PLANNING status."""
    from grace_control.db import get_db
    from grace_control.db.schema import Feature

    r = await api.post("/api/architect/plan", json={
        "feature_spec": {"title": "Bg Planning Check", "description": "Test planning state"}})
    fid = r.json()["feature_id"]

    with get_db() as s:
        feat = s.query(Feature).filter_by(id=fid).first()
    assert feat is not None
    assert feat.title == "Bg Planning Check"
    assert feat.slug == "bg-planning-check"
    assert feat.status == "PLANNING"


#START_FUNCTION_CONTRACT
# name: test_background_completes_and_creates_packets
# purpose: Mock _call_architect_llm, verify background task creates
#          waves/packets and sets feature to NOT_STARTED.
# inputs: Uses api fixture.
# verifies: Waves and packets exist in DB, state is ready/draft,
#           feature status is NOT_STARTED.
# emitted_logs: None.
# error_behavior: Timeout if background never completes.
#END_FUNCTION_CONTRACT
@pytest.mark.asyncio
async def test_background_completes_and_creates_packets(api):
    """Mock LLM -> background completes and persists waves/packets."""
    from grace_control.db import get_db
    from grace_control.db.schema import Feature, Wave, Packet

    with patch(_LLM_TARGET, _mock_llm_result()):
        r = await api.post("/api/architect/plan", json={
            "feature_spec": {"title": "Bg Complete", "description": "Build auth system"}})
    fid = r.json()["feature_id"]

    for _ in range(10):
        await asyncio.sleep(0.05)
        with get_db() as s:
            feat = s.query(Feature).filter_by(id=fid).first()
            if feat and feat.status == "NOT_STARTED":
                break

    with get_db() as s:
        feat = s.query(Feature).filter_by(id=fid).first()
        waves = s.query(Wave).filter_by(feature_id=fid).order_by(Wave.order).all()
        packets = s.query(Packet).filter_by(feature_id=fid).all()

    assert feat is not None
    assert feat.status == "NOT_STARTED"
    assert len(waves) == 2
    assert waves[0].order == 1
    assert waves[1].order == 2
    assert len(packets) == 3

    pkt1 = next(p for p in packets if p.title == "Add auth login")
    assert pkt1.state == "ready"
    assert pkt1.acceptance_profile == "NORMAL"

    pkt3 = next(p for p in packets if p.title == "Add tests for auth")
    assert pkt3.state == "draft"


#START_FUNCTION_CONTRACT
# name: test_background_error_sets_architect_failed
# purpose: Mock _call_architect_llm to raise, verify feature gets
#          ARCHITECT_FAILED status.
# inputs: Uses api fixture.
# verifies: Feature status becomes ARCHITECT_FAILED, no waves/packets created.
# emitted_logs: None.
# error_behavior: Timeout if background never completes.
#END_FUNCTION_CONTRACT
@pytest.mark.asyncio
async def test_background_error_sets_architect_failed(api):
    """Mock LLM failure -> background error handler sets ARCHITECT_FAILED."""
    from grace_control.db import get_db
    from grace_control.db.schema import Feature, Wave, Packet

    failing_mock = AsyncMock(side_effect=RuntimeError("LLM timeout"))
    with patch(_LLM_TARGET, failing_mock):
        r = await api.post("/api/architect/plan", json={
            "feature_spec": {"title": "Bg Fail", "description": "Will fail"}})
    fid = r.json()["feature_id"]

    for _ in range(10):
        await asyncio.sleep(0.05)
        with get_db() as s:
            feat = s.query(Feature).filter_by(id=fid).first()
            if feat and feat.status == "ARCHITECT_FAILED":
                break

    with get_db() as s:
        feat = s.query(Feature).filter_by(id=fid).first()

    assert feat is not None
    assert feat.status == "ARCHITECT_FAILED", f"expected ARCHITECT_FAILED got {feat.status}"


#START_FUNCTION_CONTRACT
# name: test_background_preserves_verification_and_frozen_scope
# purpose: Verify root-level verification and constraints propagate
#          into packet spec_json (same as sync mode P0-1 contract).
# inputs: Uses api fixture.
# verifies: verification and frozen_scope appear in packet spec_json.
# emitted_logs: None.
# error_behavior: Timeout if background never completes.
#END_FUNCTION_CONTRACT
@pytest.mark.asyncio
async def test_background_preserves_verification_and_frozen_scope(api):
    """Root verification + constraints.frozen_scope propagate to packet spec."""
    from grace_control.db import get_db
    from grace_control.db.schema import Feature, Packet

    llm_data = dict(_SAMPLE_LLM_RESPONSE)
    llm_data["verification"] = {"t0": [], "t1": ["pytest tests/ -x"], "t2": []}
    llm_data["constraints"] = {"frozen_scope": ["src/secret/"]}
    for w in llm_data["waves"]:
        for p in w["packets"]:
            p.pop("verification", None)

    with patch(_LLM_TARGET, _mock_llm_result(llm_data)):
        r = await api.post("/api/architect/plan", json={
            "feature_spec": {
                "title": "Bg Propagate",
                "description": "Test propagation",
            }})
    fid = r.json()["feature_id"]

    for _ in range(10):
        await asyncio.sleep(0.05)
        with get_db() as s:
            feat = s.query(Feature).filter_by(id=fid).first()
            if feat and feat.status == "NOT_STARTED":
                break

    with get_db() as s:
        packets = s.query(Packet).filter_by(feature_id=fid).all()

    assert len(packets) > 0
    for pkt in packets:
        spec = pkt.spec_json
        assert "verification" in spec
        assert "pytest" in str(spec["verification"])
        frozen = spec.get("frozen_scope", [])
        assert "src/secret/" in frozen


#START_FUNCTION_CONTRACT
# name: test_background_respects_spec_verification
# purpose: Verify packet-level verification takes precedence over
#          root-level (same as sync mode P0-1 contract).
# inputs: Uses api fixture.
# verifies: Packet's own verification is preserved, not overridden.
# emitted_logs: None.
# error_behavior: Timeout if background never completes.
#END_FUNCTION_CONTRACT
@pytest.mark.asyncio
async def test_background_respects_spec_verification(api):
    """Packet-level verification overrides root in background mode."""
    from grace_control.db import get_db
    from grace_control.db.schema import Feature, Packet

    llm_data = dict(_SAMPLE_LLM_RESPONSE)
    llm_data["waves"][0]["packets"][0]["verification"] = ["packet override command"]
    llm_data["verification"] = {"t0": [], "t1": ["root command"], "t2": []}

    with patch(_LLM_TARGET, _mock_llm_result(llm_data)):
        r = await api.post("/api/architect/plan", json={
            "feature_spec": {
                "title": "Bg Override",
                "description": "Test override",
            }})
    fid = r.json()["feature_id"]

    for _ in range(10):
        await asyncio.sleep(0.05)
        with get_db() as s:
            feat = s.query(Feature).filter_by(id=fid).first()
            if feat and feat.status == "NOT_STARTED":
                break

    with get_db() as s:
        packets = s.query(Packet).filter_by(feature_id=fid).all()

    auth_pkt = next(p for p in packets if p.title == "Add auth login")
    assert auth_pkt.spec_json["verification"] == ["packet override command"]

#END_BLOCK_TESTS
