"""Tests for pipeline stage instrumentation."""
from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, patch
import pytest

from grace_control.core.stage_instrumentation import stage, create_for_return
from grace_control.db import get_db, init_db
from grace_control.db.schema import StageRun, Packet, PacketState, Base


@pytest.fixture(autouse=True)
def setup_test_db():
    init_db("sqlite:///:memory:")
    from grace_control.db import engine
    Base.metadata.create_all(engine)


@pytest.mark.anyio
async def test_decorator_instruments_async_success():
    with get_db() as db:
        pkt = Packet(
            id="pkt_test1",
            feature_id="feat_test1",
            wave_id="wave_test1",
            slug="test-packet",
            title="Test Packet",
            state=PacketState.DRAFT.value,
            attempt_count=1,
            spec_json={}
        )
        db.add(pkt)
        db.commit()

    @stage("coder", llm=True)
    async def dummy_coder_stage(packet_id: str, model: str):
        return {
            "tokens_in": 100,
            "tokens_out": 200,
            "model": model,
            "trace_id": "trc_123",
            "stdout_path": "/tmp/stdout",
            "stderr_path": "/tmp/stderr",
        }

    with patch("grace_control.core.stage_instrumentation.broadcast_event", new_callable=AsyncMock) as mock_broadcast:
        res = await dummy_coder_stage(packet_id="pkt_test1", model="deepseek/deepseek-v4-flash")
        assert res["tokens_in"] == 100

        assert mock_broadcast.call_count == 2
        started_call = mock_broadcast.call_args_list[0]
        assert started_call[0][0] == "stage_started"
        assert started_call[0][1]["stage_key"] == "coder"
        
        finished_call = mock_broadcast.call_args_list[1]
        assert finished_call[0][0] == "stage_finished"
        assert finished_call[0][1]["status"] == "done"
        assert finished_call[0][1]["tokens_in"] == 100
        assert finished_call[0][1]["tokens_out"] == 200

    with get_db() as db:
        runs = db.query(StageRun).filter_by(packet_id="pkt_test1").all()
        assert len(runs) == 1
        run = runs[0]
        assert run.stage_key == "coder"
        assert run.status == "done"
        assert run.tokens_in == 100
        assert run.tokens_out == 200
        assert run.cost_usd > 0
        assert run.trace_id == "trc_123"


@pytest.mark.anyio
async def test_decorator_instruments_async_failure():
    with get_db() as db:
        pkt = Packet(
            id="pkt_test2",
            feature_id="feat_test2",
            wave_id="wave_test2",
            slug="test-packet-2",
            title="Test Packet 2",
            state=PacketState.DRAFT.value,
            attempt_count=1,
            spec_json={}
        )
        db.add(pkt)
        db.commit()

    @stage("verifier")
    async def failing_stage(packet_id: str):
        raise ValueError("failing verifier")

    with patch("grace_control.core.stage_instrumentation.broadcast_event", new_callable=AsyncMock) as mock_broadcast:
        with pytest.raises(ValueError, match="failing verifier"):
            await failing_stage(packet_id="pkt_test2")

        assert mock_broadcast.call_count == 2
        finished_call = mock_broadcast.call_args_list[1]
        assert finished_call[0][0] == "stage_finished"
        assert finished_call[0][1]["status"] == "failed"
        assert "ValueError" in finished_call[0][1]["error"]

    with get_db() as db:
        runs = db.query(StageRun).filter_by(packet_id="pkt_test2").all()
        assert len(runs) == 1
        assert runs[0].status == "failed"
        assert "ValueError" in runs[0].error


@pytest.mark.anyio
async def test_create_for_return():
    with get_db() as db:
        pkt = Packet(
            id="pkt_test3",
            feature_id="feat_test3",
            wave_id="wave_test3",
            slug="test-packet-3",
            title="Test Packet 3",
            state=PacketState.DRAFT.value,
            attempt_count=1,
            spec_json={}
        )
        db.add(pkt)
        
        parent = StageRun(
            id="srun_parent",
            packet_id="pkt_test3",
            feature_id="feat_test3",
            wave_id="wave_test3",
            stage_key="verifier",
            status="failed",
            trace_id="trc_parent"
        )
        db.add(parent)
        db.commit()

    with patch("grace_control.core.stage_instrumentation.broadcast_event", new_callable=AsyncMock) as mock_broadcast:
        srun = create_for_return(
            packet_id="pkt_test3",
            from_stage="verifier",
            to_stage="coder",
            reason="evidence missing T1",
            trace_id="trc_parent"
        )
        assert srun is not None
        assert srun.loop_round == 1
        assert srun.parent_stage_run_id == "srun_parent"
        assert srun.recovery_reason == "evidence missing T1"
        assert srun.trace_id == "trc_parent"

        assert mock_broadcast.call_count == 1
        assert mock_broadcast.call_args[0][0] == "stage_returned"
        assert mock_broadcast.call_args[0][1]["loop_round"] == 1
        assert mock_broadcast.call_args[0][1]["parent_stage_run_id"] == "srun_parent"
