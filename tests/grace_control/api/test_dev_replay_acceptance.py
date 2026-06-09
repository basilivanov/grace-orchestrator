import pytest
from pathlib import Path
from fastapi import status
from fastapi.testclient import TestClient
from unittest.mock import MagicMock, patch

from grace_control.api.app_factory import create_app
from grace_control.config.settings import GraceSettings
from grace_control.db.schema import Packet, PacketRun
from grace_control.core.contracts import AcceptanceReport, FinalVerdict, AcceptanceProfile, StageResult, StageName, StageStatus

class FakeQuery:
    def __init__(self, result):
        self.result = result
    def filter_by(self, id=None, packet_id=None):
        return self
    def first(self):
        return self.result

class FakeDB:
    def __init__(self, run, packet):
        self.run = run
        self.packet = packet
    def __enter__(self):
        return self
    def __exit__(self, exc_type, exc_val, exc_tb):
        pass
    def query(self, model):
        if model == PacketRun:
            return FakeQuery(self.run)
        else:
            return FakeQuery(self.packet)
    def commit(self):
        pass

@pytest.fixture
def client_enabled(tmp_path: Path):
    settings = GraceSettings()
    settings.dev_tools_enabled = True
    
    with patch("grace_control.config.settings.settings", settings):
        app = create_app(settings)
        yield TestClient(app)

def test_replay_acceptance_success(client_enabled, tmp_path: Path):
    wt_path = tmp_path / "wt"
    wt_path.mkdir()
    run_dir = tmp_path / "run_dir"
    run_dir.mkdir()
    
    # Mock data
    dev_rep_metadata = {
        "version": 1,
        "replayable": True,
        "packet_id": "pkt_t",
        "run_id": "pkt_t-R01",
        "run_number": 1,
        "worktree_path": str(wt_path),
        "branch_name": "agent/pkt_t-attempt-0001",
        "base_ref": "main",
        "base_sha": "base_sha_123",
        "agent_commit_sha": "commit_sha_123",
        "changed_files": ["src/hello.py"],
        "run_dir": str(run_dir),
        "acceptance_report_path": "",
        "evidence_path": "",
        "failed_stage": "T0_SCOPE_AND_LINT",
    }
    
    mock_run = PacketRun(
        id="pkt_t-R01", packet_id="pkt_t", run_number=1, status="running",
        result_json={"dev_replay": dev_rep_metadata}
    )
    mock_packet = Packet(
        id="pkt_t", feature_id="feat_f", wave_id="wave_w", slug="pkt_t",
        title="Test packet", description="test", state="running",
        acceptance_profile="NORMAL", spec_json={"scope": ["src/hello.py"]}
    )
    
    fake_db = FakeDB(mock_run, mock_packet)
    
    # Mock reports
    stage = StageResult(name=StageName.T0_SCOPE_AND_LINT, status=StageStatus.PASSED, summary="lint passed")
    mock_report = AcceptanceReport(
        packet_id="pkt_t", final_verdict=FinalVerdict.ACCEPTED, profile=AcceptanceProfile.NORMAL,
        stages=[stage], summary="lint passed"
    )
    
    with patch("grace_control.services.dev_run_replay_service.get_db", lambda: fake_db):
        with patch("grace_control.core.acceptance_pipeline.run_acceptance_stage_replay", return_value=mock_report):
            r = client_enabled.post("/api/dev/runs/pkt_t-R01/replay-acceptance", json={"stage": "t0"})
            
            assert r.status_code == status.HTTP_200_OK
            data = r.json()["data"]
            assert data["run_id"] == "pkt_t-R01"
            assert data["stage"] == "t0"
            assert data["status"] == "passed"
            assert data["summary"] == "lint passed"
            assert len(data["stages"]) == 1
            assert data["stages"][0]["name"] == "T0_SCOPE_AND_LINT"
