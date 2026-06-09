import pytest
from pathlib import Path
from fastapi import status
from fastapi.testclient import TestClient
from unittest.mock import MagicMock, patch

from grace_control.api.app_factory import create_app
from grace_control.config.settings import GraceSettings
from grace_control.db.schema import Packet, PacketRun
from grace_control.core.contracts import AcceptanceReport, FinalVerdict, AcceptanceProfile, StageResult, StageName, StageStatus, PacketVerdict
from grace_control.core.reviewer_gate import ReviewerVerdict

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

@pytest.mark.asyncio
async def test_rerun_verifier_success(client_enabled, tmp_path: Path):
    wt_path = tmp_path / "wt"
    wt_path.mkdir()
    run_dir = tmp_path / "run_dir"
    run_dir.mkdir()
    
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
    
    accept_dict = {
        "packet_id": "pkt_t",
        "final_verdict": "rework_required",
        "stages": [
            {
                "name": "T0_SCOPE_AND_LINT",
                "status": "passed",
                "summary": "lint ok",
                "commands": []
            }
        ],
        "summary": "T0 passed"
    }
    
    mock_run = PacketRun(
        id="pkt_t-R01", packet_id="pkt_t", run_number=1, status="running",
        result_json={"dev_replay": dev_rep_metadata, "acceptance_report": accept_dict}
    )
    mock_packet = Packet(
        id="pkt_t", feature_id="feat_f", wave_id="wave_w", slug="pkt_t",
        title="Test packet", description="test", state="running",
        acceptance_profile="NORMAL", spec_json={"scope": ["src/hello.py"]}
    )
    
    fake_db = FakeDB(mock_run, mock_packet)
    
    # Mock verifier result
    mock_evr = MagicMock(
        verdict=PacketVerdict.ACCEPTED,
        summary="verifier passed",
        requirement_results=[],
        test_verdict="passed",
        commands_run=[],
        evidence_paths=[],
        blocking_issues=[]
    )
    mock_evr.model_dump.return_value = {
        "packet_id": "pkt_t",
        "verdict": "accepted",
        "requirement_results": [],
        "test_verdict": "passed",
        "commands_run": [],
        "evidence_paths": [],
        "blocking_issues": []
    }
    
    with patch("grace_control.services.dev_run_replay_service.get_db", lambda: fake_db):
        with patch("grace_control.services.dev_run_replay_service.run_evidence_verifier", return_value=mock_evr):
            r = client_enabled.post("/api/dev/runs/pkt_t-R01/rerun-verifier", json={})
            
            assert r.status_code == status.HTTP_200_OK
            data = r.json()["data"]
            assert data["run_id"] == "pkt_t-R01"
            assert data["verdict"] == "accepted"
            assert data["summary"] == "verifier passed"
            assert mock_run.result_json["dev_replays"][-1]["type"] == "verifier"

@pytest.mark.asyncio
async def test_rerun_reviewer_success(client_enabled, tmp_path: Path):
    wt_path = tmp_path / "wt"
    wt_path.mkdir()
    run_dir = tmp_path / "run_dir"
    run_dir.mkdir()
    
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
    
    accept_dict = {
        "packet_id": "pkt_t",
        "final_verdict": "rework_required",
        "stages": [
            {
                "name": "T0_SCOPE_AND_LINT",
                "status": "passed",
                "summary": "lint ok",
                "commands": []
            }
        ],
        "summary": "T0 passed"
    }
    
    verifier_report = {
        "packet_id": "pkt_t",
        "verdict": "accepted",
        "requirement_results": [],
        "test_verdict": "passed",
        "commands_run": [],
        "evidence_paths": [],
        "blocking_issues": []
    }
    
    mock_run = PacketRun(
        id="pkt_t-R01", packet_id="pkt_t", run_number=1, status="running",
        result_json={
            "dev_replay": dev_rep_metadata,
            "acceptance_report": accept_dict,
            "evidence_verifier_report": verifier_report
        }
    )
    mock_packet = Packet(
        id="pkt_t", feature_id="feat_f", wave_id="wave_w", slug="pkt_t",
        title="Test packet", description="test", state="running",
        acceptance_profile="NORMAL", spec_json={"scope": ["src/hello.py"]}
    )
    
    fake_db = FakeDB(mock_run, mock_packet)
    
    # Mock reviewer result
    mock_rvr = MagicMock(
        verdict=ReviewerVerdict.PASS,
        reasons=[],
        packet_id="pkt_t"
    )
    mock_rvr.model_dump.return_value = {
        "packet_id": "pkt_t",
        "verdict": "PASS",
        "reasons": []
    }
    
    with patch("grace_control.services.dev_run_replay_service.get_db", lambda: fake_db):
        with patch("grace_control.services.dev_run_replay_service.run_reviewer_gate", return_value=mock_rvr):
            r = client_enabled.post("/api/dev/runs/pkt_t-R01/rerun-reviewer", json={})
            
            assert r.status_code == status.HTTP_200_OK
            data = r.json()["data"]
            assert data["run_id"] == "pkt_t-R01"
            assert data["verdict"] == "PASS"
            assert mock_run.result_json["dev_replays"][-1]["type"] == "reviewer"
