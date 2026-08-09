"""Block E: DAG Validator extended unit tests — 5 tests."""
from grace_control.core.dag_validator import detect_scope_conflicts, validate_dag


def test_dag_empty_packets_valid():
    r = validate_dag([])
    assert r.valid
    assert r.ordered_packets == []


def test_dag_self_dependency_is_cycle():
    r = validate_dag([{"id": "P1", "depends_on": ["P1"], "scope": []}])
    assert not r.valid
    assert len(r.cycles) == 1


def test_dag_diamond_dependency():
    packets = [
        {"id": "P-BASE", "depends_on": [], "scope": []},
        {"id": "P-A", "depends_on": ["P-BASE"], "scope": []},
        {"id": "P-B", "depends_on": ["P-BASE"], "scope": []},
        {"id": "P-FINAL", "depends_on": ["P-A", "P-B"], "scope": []},
    ]
    r = validate_dag(packets)
    assert r.valid
    order = r.ordered_packets
    assert order.index("P-BASE") == 0
    assert order.index("P-FINAL") > order.index("P-A")
    assert order.index("P-FINAL") > order.index("P-B")


def test_scope_conflict_multiple_files():
    conflicts = detect_scope_conflicts({
        "P1": ["a.py", "b.py", "c.py"],
        "P2": ["b.py", "c.py", "d.py"],
    })
    assert len(conflicts) == 1
    assert sorted(conflicts[0].overlapping_files) == ["b.py", "c.py"]


def test_scope_conflict_three_way():
    conflicts = detect_scope_conflicts({
        "P1": ["shared.py"], "P2": ["shared.py"], "P3": ["shared.py"],
    })
    assert len(conflicts) == 3


def test_validate_dag_allows_directly_ordered_scope_overlap():
    packets = [
        {"id": "P1", "depends_on": [], "scope": ["shared.py"]},
        {"id": "P2", "depends_on": ["P1"], "scope": ["shared.py"]},
    ]

    result = validate_dag(packets)

    assert result.valid
    assert result.conflicts == []


def test_validate_dag_allows_transitively_ordered_scope_overlap():
    packets = [
        {"id": "P1", "depends_on": [], "scope": ["shared.py"]},
        {"id": "P2", "depends_on": ["P1"], "scope": ["middle.py"]},
        {"id": "P3", "depends_on": ["P2"], "scope": ["shared.py"]},
    ]

    result = validate_dag(packets)

    assert result.valid
    assert result.conflicts == []


def test_validate_dag_rejects_missing_dependency_reference():
    result = validate_dag([{"id": "P1", "depends_on": ["missing"], "scope": []}])

    assert not result.valid
    assert any("Missing dependency" in error for error in result.errors)


def test_validate_dag_resolves_dependency_by_packet_title():
    result = validate_dag([
        {"id": "packet-a", "title": "Producer", "depends_on": [], "scope": []},
        {"id": "packet-b", "title": "Consumer", "depends_on": ["Producer"], "scope": []},
    ])

    assert result.valid
    assert result.ordered_packets == ["packet-a", "packet-b"]


def test_validate_dag_rejects_same_wave_dependency_for_new_plan():
    result = validate_dag(
        [
            {"id": "P1", "depends_on": [], "scope": [], "wave_index": 0},
            {"id": "P2", "depends_on": ["P1"], "scope": [], "wave_index": 0},
        ],
        strict_wave_order=True,
    )

    assert not result.valid
    assert any("Dependency wave order invalid" in error for error in result.errors)


def test_validate_dag_keeps_legacy_same_wave_dependency_compatible():
    result = validate_dag(
        [
            {"id": "P1", "depends_on": [], "scope": [], "wave_index": 0},
            {"id": "P2", "depends_on": ["P1"], "scope": [], "wave_index": 0},
        ]
    )

    assert result.valid
