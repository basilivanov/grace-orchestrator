import json
import pytest
from pathlib import Path
from unittest.mock import MagicMock, patch
from grace_control.adapters.packet_executor import PacketExecutionAdapter
from grace_control.core.contracts import ExecutionPacketContract, AcceptanceProfile, AcceptanceReport, StageResult, StageName, StageStatus, FinalVerdict
from grace_control.db.schema import PacketRun

class FakeQuery:
    def __init__(self, result):
        self.result = result
    def filter_by(self, **kwargs):
        return self
    def first(self):
        return self.result

class FakeDB:
    def __init__(self, result):
        self.result = result
    def __enter__(self):
        return self
    def __exit__(self, exc_type, exc_val, exc_tb):
        pass
    def query(self, model):
        return FakeQuery(self.result)
    def commit(self):
        pass

@pytest.mark.asyncio
async def test_acceptance_failure_persists_metadata(tmp_path: Path):
    adapter = PacketExecutionAdapter(
        project_root=tmp_path,
        state_root=tmp_path / "state",
        worktree_root=tmp_path / "wt",
        backend=MagicMock()
    )
    
    # Setup mock worktree and run directory
    wt_path = tmp_path / "wt" / "pkt_t-attempt-0001"
    wt_path.mkdir(parents=True, exist_ok=True)
    run_dir = tmp_path / "state" / "packets" / "pkt_t" / "runs" / "R01"
    run_dir.mkdir(parents=True, exist_ok=True)
    
    # Initialize a mock git repo in wt_path for git diff to run successfully
    import subprocess
    subprocess.run(["git", "init"], cwd=str(wt_path), capture_output=True)
    subprocess.run(["git", "config", "user.name", "Test"], cwd=str(wt_path), capture_output=True)
    subprocess.run(["git", "config", "user.email", "test@test.com"], cwd=str(wt_path), capture_output=True)
    (wt_path / "test.txt").write_text("hello")
    subprocess.run(["git", "add", "test.txt"], cwd=str(wt_path), capture_output=True)
    subprocess.run(["git", "commit", "-m", "initial"], cwd=str(wt_path), capture_output=True)
    # Add a change so diff is non-empty
    (wt_path / "test.txt").write_text("hello world")
    
    # Fake DB factory for unittest
    mock_run = PacketRun(id="pkt_t-R01", packet_id="pkt_t", run_number=1, status="running")
    fake_db = FakeDB(mock_run)
    
    adapter._db = lambda: fake_db
    adapter._evidence._db = lambda: fake_db
    
    # Build a failed acceptance report
    stage = StageResult(name=StageName.T0_SCOPE_AND_LINT, status=StageStatus.FAILED, summary="invalid contract")
    accept_report = AcceptanceReport(
        packet_id="pkt_t", final_verdict=FinalVerdict.REWORK_REQUIRED, profile=AcceptanceProfile.NORMAL,
        stages=[stage], summary="invalid contract"
    )
    
    evr = MagicMock(verdict="rework_required", summary="fail")
    rvr = MagicMock(verdict="rework_required", summary="fail")
    
    adapter._persist_run(
        status="rejected",
        run_id="pkt_t-R01",
        executor={"executor_id": "coder-mini-swe"},
        safe_data={"branch_name": "agent/pkt_t-attempt-0001"},
        accept_report=accept_report,
        evr=evr,
        rvr=rvr,
        dur=10,
        ar_path=str(run_dir / "acceptance_report.json"),
        packet_id="pkt_t",
        start=0,
        commit_sha="agent_commit_sha_123",
        wt_path=wt_path,
        run_dir=run_dir,
        changed_files=["test.txt"],
        base_ref="main",
        base_sha="HEAD"  # git diff should run against HEAD
    )
    
    # Verify result_json has the dev_replay metadata
    assert mock_run.result_json is not None
    assert mock_run.result_json["agent_commit_sha"] == "agent_commit_sha_123"
    
    dev_rep = mock_run.result_json["dev_replay"]
    assert dev_rep["replayable"] is True
    assert dev_rep["packet_id"] == "pkt_t"
    assert dev_rep["run_id"] == "pkt_t-R01"
    assert dev_rep["worktree_path"] == str(wt_path)
    assert dev_rep["branch_name"] == "agent/pkt_t-attempt-0001"
    assert dev_rep["agent_commit_sha"] == "agent_commit_sha_123"
    assert dev_rep["failed_stage"] == "T0_SCOPE_AND_LINT"
    
    # Verify agent.patch was created
    patch_file = run_dir / "agent.patch"
    assert patch_file.exists()
    assert "hello world" in patch_file.read_text()
