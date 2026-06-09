from unittest.mock import MagicMock, patch
import pytest
from pathlib import Path
from grace_control.adapters.packet_executor import PacketExecutionAdapter
from grace_control.config.settings import GraceSettings

@pytest.mark.asyncio
async def test_cleanup_invoked_when_keep_failed_is_false():
    settings = GraceSettings()
    settings.dev_keep_failed_worktrees = False

    adapter = PacketExecutionAdapter(
        project_root=Path("/tmp"),
        state_root=Path("/tmp"),
        worktree_root=Path("/tmp"),
        backend=MagicMock()
    )
    adapter._terminal_cleanup = MagicMock()

    with patch("grace_control.config.settings.settings", settings):
        accept_report = MagicMock(final_verdict=MagicMock(value="rejected"), summary="fail")
        evr = MagicMock(verdict="rework_required", summary="fail")
        rvr = MagicMock(verdict="rework_required", summary="fail")
        
        adapter._persist_run(
            status="rejected",
            run_id="pkt_t-R01",
            executor={},
            safe_data={},
            accept_report=accept_report,
            evr=evr,
            rvr=rvr,
            dur=10,
            ar_path="",
            packet_id="pkt_t",
            start=0
        )
        
        assert adapter._terminal_cleanup.run.called is True

@pytest.mark.asyncio
async def test_cleanup_skipped_when_keep_failed_is_true():
    settings = GraceSettings()
    settings.dev_keep_failed_worktrees = True

    adapter = PacketExecutionAdapter(
        project_root=Path("/tmp"),
        state_root=Path("/tmp"),
        worktree_root=Path("/tmp"),
        backend=MagicMock()
    )
    adapter._terminal_cleanup = MagicMock()

    with patch("grace_control.config.settings.settings", settings):
        accept_report = MagicMock(final_verdict=MagicMock(value="rejected"), summary="fail")
        evr = MagicMock(verdict="rework_required", summary="fail")
        rvr = MagicMock(verdict="rework_required", summary="fail")
        
        adapter._persist_run(
            status="rejected",
            run_id="pkt_t-R01",
            executor={},
            safe_data={},
            accept_report=accept_report,
            evr=evr,
            rvr=rvr,
            dur=10,
            ar_path="",
            packet_id="pkt_t",
            start=0
        )
        
        assert adapter._terminal_cleanup.run.called is False
