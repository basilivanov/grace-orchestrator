"""Block B: Wave Gate unit tests — 8 tests."""
from grace_control.core.wave_gate import check_wave_gates
from grace_control.db import get_db
from grace_control.db.schema import PacketState
from tests.conftest import make_feature, make_packet, make_wave


def test_wave_gate_empty_db(db):
    assert check_wave_gates() == 0


def test_wave_gate_opens_next_wave(db):
    with get_db() as d:
        make_feature(d, fid="F1")
        make_wave(d, wid="W01", fid="F1", order=1)
        make_wave(d, wid="W02", fid="F1", order=2)
        make_packet(d, pid="P1", fid="F1", wid="W01", state=PacketState.MERGED.value)
        make_packet(d, pid="P2", fid="F1", wid="W01", state=PacketState.MERGED.value)
        make_packet(d, pid="P3", fid="F1", wid="W02", state=PacketState.DRAFT.value)
        make_packet(d, pid="P4", fid="F1", wid="W02", state=PacketState.DRAFT.value)

    gated = check_wave_gates()
    assert gated == 2

    with get_db() as d:
        from grace_control.db.schema import Packet
        for pid in ("P3", "P4"):
            p = d.query(Packet).filter_by(id=pid).first()
            assert p.state == PacketState.READY.value
        from grace_control.db.schema import Wave
        w = d.query(Wave).filter_by(id="W01").first()
        assert w.status == "COMPLETED"


def test_wave_gate_partial_not_opened(db):
    with get_db() as d:
        make_feature(d, fid="F1")
        make_wave(d, wid="W01", fid="F1")
        make_wave(d, wid="W02", fid="F1", order=2)
        make_packet(d, pid="P1", fid="F1", wid="W01", state=PacketState.MERGED.value)
        make_packet(d, pid="P2", fid="F1", wid="W01", state=PacketState.RUNNING.value)
        make_packet(d, pid="P3", fid="F1", wid="W02", state=PacketState.DRAFT.value)

    assert check_wave_gates() == 0
    with get_db() as d:
        from grace_control.db.schema import Packet
        p = d.query(Packet).filter_by(id="P3").first()
        assert p.state == PacketState.DRAFT.value


def test_wave_gate_idempotent(db):
    with get_db() as d:
        make_feature(d, fid="F1")
        make_wave(d, wid="W01", fid="F1")
        make_wave(d, wid="W02", fid="F1", order=2)
        make_packet(d, pid="P1", fid="F1", wid="W01", state=PacketState.MERGED.value)
        make_packet(d, pid="P2", fid="F1", wid="W02", state=PacketState.READY.value)

    assert check_wave_gates() == 0


def test_wave_gate_three_waves_sequential(db):
    with get_db() as d:
        make_feature(d, fid="F1")
        make_wave(d, wid="W01", fid="F1", order=1)
        make_wave(d, wid="W02", fid="F1", order=2)
        make_wave(d, wid="W03", fid="F1", order=3)
        make_packet(d, pid="P1", fid="F1", wid="W01", state=PacketState.MERGED.value)
        make_packet(d, pid="P2", fid="F1", wid="W02", state=PacketState.DRAFT.value)
        make_packet(d, pid="P3", fid="F1", wid="W03", state=PacketState.DRAFT.value)

    gated = check_wave_gates()
    assert gated == 1
    with get_db() as d:
        from grace_control.db.schema import Packet
        assert d.query(Packet).filter_by(id="P2").first().state == PacketState.READY.value
        assert d.query(Packet).filter_by(id="P3").first().state == PacketState.DRAFT.value


def test_wave_gate_single_wave_noop(db):
    with get_db() as d:
        make_feature(d, fid="F1")
        make_wave(d, wid="W01", fid="F1")
        make_packet(d, pid="P1", fid="F1", wid="W01", state=PacketState.MERGED.value)
    assert check_wave_gates() == 0


def test_wave_gate_multiple_features_isolated(db):
    with get_db() as d:
        for f, ready in [("FA", True), ("FB", False)]:
            make_feature(d, fid=f)
            make_wave(d, wid=f"W01-{f}", fid=f, order=1)
            make_wave(d, wid=f"W02-{f}", fid=f, order=2)
            state = PacketState.MERGED.value if ready else PacketState.RUNNING.value
            make_packet(d, pid=f"P-{f}-1", fid=f, wid=f"W01-{f}", state=state)
            make_packet(d, pid=f"P-{f}-2", fid=f, wid=f"W02-{f}", state=PacketState.DRAFT.value)

    gated = check_wave_gates()
    assert gated == 1
    with get_db() as d:
        from grace_control.db.schema import Packet
        assert d.query(Packet).filter_by(id="P-FA-2").first().state == PacketState.READY.value
        assert d.query(Packet).filter_by(id="P-FB-2").first().state == PacketState.DRAFT.value


def test_wave_gate_cancelled_packet_blocks(db):
    with get_db() as d:
        make_feature(d, fid="F1")
        make_wave(d, wid="W01", fid="F1")
        make_wave(d, wid="W02", fid="F1", order=2)
        make_packet(d, pid="P1", fid="F1", wid="W01", state=PacketState.MERGED.value)
        make_packet(d, pid="P2", fid="F1", wid="W01", state=PacketState.CANCELLED.value)
        make_packet(d, pid="P3", fid="F1", wid="W02", state=PacketState.DRAFT.value)

    assert check_wave_gates() == 1  # CANCELLED is terminal → gate opens
