"""Block C: Feature Gate unit tests — 6 tests."""
from grace_control.core.feature_gate import check_feature_completion
from grace_control.db import get_db
from grace_control.db.schema import PacketState
from tests.conftest import make_feature, make_packet


def test_feature_gate_all_merged(db):
    with get_db() as d:
        make_feature(d, fid="F1")
        make_packet(d, pid="P1", fid="F1", state=PacketState.MERGED.value)
        make_packet(d, pid="P2", fid="F1", state=PacketState.MERGED.value)
    assert check_feature_completion() == 1
    with get_db() as d:
        from grace_control.db.schema import Feature
        assert d.query(Feature).filter_by(id="F1").first().status == "COMPLETED"


def test_feature_gate_partial_not_completed(db):
    with get_db() as d:
        make_feature(d, fid="F1")
        make_packet(d, pid="P1", fid="F1", state=PacketState.MERGED.value)
        make_packet(d, pid="P2", fid="F1", state=PacketState.RUNNING.value)
    assert check_feature_completion() == 0


def test_feature_gate_merged_and_cancelled(db):
    with get_db() as d:
        make_feature(d, fid="F1")
        make_packet(d, pid="P1", fid="F1", state=PacketState.MERGED.value)
        make_packet(d, pid="P2", fid="F1", state=PacketState.CANCELLED.value)
    assert check_feature_completion() == 1
    with get_db() as d:
        from grace_control.db.schema import Feature
        assert d.query(Feature).filter_by(id="F1").first().status == "COMPLETED"


def test_feature_gate_already_completed_skipped(db):
    with get_db() as d:
        make_feature(d, fid="F1", status="COMPLETED")
        make_packet(d, pid="P1", fid="F1", state=PacketState.MERGED.value)
    assert check_feature_completion() == 0


def test_feature_gate_no_packets_skipped(db):
    with get_db() as d:
        make_feature(d, fid="F1")
    assert check_feature_completion() == 0


def test_feature_gate_multiple_features(db):
    with get_db() as d:
        make_feature(d, fid="FA")
        make_feature(d, fid="FB")
        make_packet(d, pid="PA", fid="FA", state=PacketState.MERGED.value)
        make_packet(d, pid="PB", fid="FB", state=PacketState.RUNNING.value)
    assert check_feature_completion() == 1
    with get_db() as d:
        from grace_control.db.schema import Feature
        assert d.query(Feature).filter_by(id="FA").first().status == "COMPLETED"
        assert d.query(Feature).filter_by(id="FB").first().status == "NOT_STARTED"
