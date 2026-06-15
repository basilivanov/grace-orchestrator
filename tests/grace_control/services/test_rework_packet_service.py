"""Tests for ReworkPacketService — pure logic + DB integration."""

from __future__ import annotations

from grace_control.core.uid import generate_unique_id, new_packet_uid
from grace_control.db import get_db
from grace_control.db.schema import Packet, PacketState
from grace_control.services.rework_packet_service import RUNTIME_FAILURE_CODES, create_rework_packet


class TestCreateReworkPacket:
    """Unit tests for create_rework_packet()."""

    def test_creates_packet_with_origin_review_rework(self, db):
        with get_db() as d:
            original = Packet(
                id="pkt-original-001",
                feature_id="feat-001",
                wave_id="W01",
                slug="test-packet",
                title="Original Packet",
                spec_json={
                    "scope": ["src/grace_control/"],
                    "frozen_scope": ["docs/archived/"],
                    "verification": {"t1": [["echo", "ok"]]},
                    "target_repo_root": "/tmp/repo",
                    "workspace_mode": "target_repo_worktree",
                },
                acceptance_profile="NORMAL",
                attempt_count=1,
                max_attempts=3,
                state=PacketState.REJECTED.value,
            )
            d.add(original)
            d.commit()

            rework = create_rework_packet(
                d,
                original_packet_id="pkt-original-001",
                feature_id="feat-001",
                wave_id="W01",
                original_spec=original.spec_json,
                acceptance_profile="NORMAL",
                title="Original Packet",
                slug="test-packet",
                max_attempts=3,
                verdict_source="reviewer",
                summary="Tests need fixing",
                blocking_issues=["test_foo fails", "test_bar missing"],
                coder_instructions=["Fix the tests"],
            )
            d.commit()

            assert rework.id.startswith("pkt_")
            assert rework.feature_id == "feat-001"
            assert rework.wave_id == "W01"
            assert rework.state == PacketState.READY.value
            assert rework.acceptance_profile == "NORMAL"
            assert rework.attempt_count == 0
            assert rework.max_attempts == 3
            assert "rework" in rework.slug

            spec = rework.spec_json
            assert spec["origin"] == "review_rework"
            assert spec["parent_packet_id"] == "pkt-original-001"
            assert spec["original_packet_id"] == "pkt-original-001"
            assert spec["scope"] == ["src/grace_control/"]
            assert spec["frozen_scope"] == ["docs/archived/"]
            assert spec["target_repo_root"] == "/tmp/repo"
            assert spec["workspace_mode"] == "target_repo_worktree"
            assert spec["priority"] == "immediate"
            assert spec["rework_source"] == "reviewer"
            assert spec["rework_summary"] == "Tests need fixing"
            assert spec["blocking_issues"] == ["test_foo fails", "test_bar missing"]
            assert spec["coder_instructions"] == ["Fix the tests"]
            assert "review rework packet" in spec["rework_prompt"].lower()
            assert "do not redesign" in spec["rework_prompt"].lower()

            rework_from_db = d.query(Packet).filter_by(id=rework.id).first()
            assert rework_from_db is not None
            assert rework_from_db.spec_json["origin"] == "review_rework"

    def test_preserves_feature_and_wave_ids(self, db):
        with get_db() as d:
            original = Packet(
                id="pkt-orig-002",
                feature_id="feat-custom",
                wave_id="W99",
                slug="my-packet",
                title="My Packet",
                spec_json={"scope": ["src/"]},
                acceptance_profile="STRICT",
                attempt_count=2,
                max_attempts=5,
                state=PacketState.REJECTED.value,
            )
            d.add(original)
            d.commit()

            rework = create_rework_packet(
                d,
                original_packet_id="pkt-orig-002",
                feature_id="feat-custom",
                wave_id="W99",
                original_spec=original.spec_json,
                acceptance_profile="STRICT",
                title="My Packet",
                slug="my-packet",
                max_attempts=5,
                verdict_source="evidence_verifier",
                summary="Evidence missing",
                blocking_issues=["no evidence for requirement X"],
            )
            d.commit()

            assert rework.feature_id == "feat-custom"
            assert rework.wave_id == "W99"
            assert rework.acceptance_profile == "STRICT"
            assert rework.max_attempts == 5
            assert rework.spec_json["rework_source"] == "evidence_verifier"

    def test_defaults_with_empty_spec(self, db):
        with get_db() as d:
            original = Packet(
                id="pkt-orig-003",
                feature_id="feat-003",
                wave_id="W01",
                slug="empty-pkt",
                title="Empty",
                spec_json={},
                acceptance_profile="NORMAL",
                attempt_count=1,
                max_attempts=3,
                state=PacketState.REJECTED.value,
            )
            d.add(original)
            d.commit()

            rework = create_rework_packet(
                d,
                original_packet_id="pkt-orig-003",
                feature_id="feat-003",
                wave_id="W01",
                original_spec={},
                acceptance_profile="NORMAL",
                title="Empty",
                slug="empty-pkt",
                max_attempts=3,
                verdict_source="reviewer",
                summary="fix",
                blocking_issues=[],
            )
            d.commit()

            spec = rework.spec_json
            assert spec["origin"] == "review_rework"
            assert spec["parent_packet_id"] == "pkt-orig-003"
            assert spec["scope"] == ["src/grace_control/"]
            assert "target_repo_root" not in spec or spec["target_repo_root"] == ""
            assert "workspace_mode" not in spec

    def test_no_workspace_mode_when_not_in_original(self, db):
        with get_db() as d:
            original = Packet(
                id="pkt-orig-004",
                feature_id="feat-004",
                wave_id="W01",
                slug="no-ws",
                title="No Workspace",
                spec_json={"scope": ["src/"], "target_repo_root": "/tmp/r"},
                acceptance_profile="NORMAL",
                attempt_count=1,
                max_attempts=3,
                state=PacketState.REJECTED.value,
            )
            d.add(original)
            d.commit()

            rework = create_rework_packet(
                d,
                original_packet_id="pkt-orig-004",
                feature_id="feat-004",
                wave_id="W01",
                original_spec=original.spec_json,
                acceptance_profile="NORMAL",
                title="No Workspace",
                slug="no-ws",
                max_attempts=3,
                verdict_source="evidence_verifier",
                summary="fix",
                blocking_issues=[],
            )
            d.commit()

            assert "workspace_mode" not in rework.spec_json
            assert rework.spec_json["target_repo_root"] == "/tmp/r"


class TestRuntimeFailureCodes:
    """Verify RUNTIME_FAILURE_CODES contains expected values."""

    def test_runtime_failure_codes_defined(self):
        assert "auth_error" in RUNTIME_FAILURE_CODES
        assert "timeout" in RUNTIME_FAILURE_CODES
        assert "worktree_missing" in RUNTIME_FAILURE_CODES
        assert "not_git" in RUNTIME_FAILURE_CODES
        assert "AGENT_WORKTREE_NOT_GIT" in RUNTIME_FAILURE_CODES
        assert "AGENT_NO_CHANGES_PRODUCED" in RUNTIME_FAILURE_CODES
        assert "AGENT_DIFF_INSPECTION_FAILED" in RUNTIME_FAILURE_CODES
        assert "AGENT_CHANGED_OUT_OF_SCOPE" in RUNTIME_FAILURE_CODES

    def test_acceptance_failure_not_runtime(self):
        assert "t1_failed" not in RUNTIME_FAILURE_CODES
        assert "scope_violation" not in RUNTIME_FAILURE_CODES
        assert "unknown" not in RUNTIME_FAILURE_CODES
        assert "REWORK_TO_CODER" not in RUNTIME_FAILURE_CODES
        assert "RETURN_TO_ARCHITECT" not in RUNTIME_FAILURE_CODES


class TestIdempotency:
    """Idempotency: same original + source must not create duplicate rework packets."""

    def test_maybe_create_skips_when_rework_exists(self, db, tmp_path):
        """_maybe_create_rework_packet skips when existing rework packet is found."""
        from unittest.mock import MagicMock, patch
        from grace_control.adapters.packet_executor import PacketExecutionAdapter
        from grace_control.core.uid import generate_unique_id, new_packet_uid

        with get_db() as d:
            original = Packet(
                id="pkt-idem-adapter-001",
                feature_id="feat-idem",
                wave_id="W01",
                slug="idem-pkt",
                title="Idempotency Test",
                spec_json={"scope": ["src/"]},
                acceptance_profile="NORMAL",
                attempt_count=1, max_attempts=3,
                state=PacketState.REJECTED.value,
            )
            d.add(original)

            existing_rework = Packet(
                id="pkt-existing-rework",
                feature_id="feat-idem",
                wave_id="W01",
                slug="idem-pkt-rework",
                title="Rework: Idempotency Test",
                spec_json={
                    "origin": "review_rework",
                    "parent_packet_id": "pkt-idem-adapter-001",
                    "rework_source": "reviewer",
                },
                acceptance_profile="NORMAL",
                attempt_count=0, max_attempts=3,
                state=PacketState.READY.value,
            )
            d.add(existing_rework)
            d.commit()

        adapter = PacketExecutionAdapter(
            project_root=tmp_path,
            state_root=tmp_path,
            worktree_root=tmp_path,
            backend=MagicMock(),
        )

        with patch("grace_control.config.settings.settings.agent_runtime_rework_packets_enabled", True):
            adapter._maybe_create_rework_packet(
                "pkt-idem-adapter-001",
                verdict_source="reviewer",
                summary="fix it",
                blocking_issues=["issue"],
            )

        with get_db() as d:
            rework_packets = [
                p for p in d.query(Packet).all()
                if (p.spec_json or {}).get("origin") == "review_rework"
            ]
            assert len(rework_packets) == 1
            assert rework_packets[0].id == "pkt-existing-rework"

    def test_maybe_create_creates_when_no_existing_rework(self, db, tmp_path):
        """_maybe_create_rework_packet creates when no existing rework packet found."""
        from unittest.mock import MagicMock, patch
        from grace_control.adapters.packet_executor import PacketExecutionAdapter

        with get_db() as d:
            original = Packet(
                id="pkt-idem-adapter-002",
                feature_id="feat-idem",
                wave_id="W01",
                slug="idem-pkt-2",
                title="Idempotency Test 2",
                spec_json={"scope": ["src/"]},
                acceptance_profile="NORMAL",
                attempt_count=1, max_attempts=3,
                state=PacketState.REJECTED.value,
            )
            d.add(original)
            d.commit()

        adapter = PacketExecutionAdapter(
            project_root=tmp_path,
            state_root=tmp_path,
            worktree_root=tmp_path,
            backend=MagicMock(),
        )

        with patch("grace_control.config.settings.settings.agent_runtime_rework_packets_enabled", True):
            adapter._maybe_create_rework_packet(
                "pkt-idem-adapter-002",
                verdict_source="reviewer",
                summary="fix it",
                blocking_issues=["issue"],
            )

        with get_db() as d:
            rework_packets = [
                p for p in d.query(Packet).all()
                if (p.spec_json or {}).get("origin") == "review_rework"
            ]
            assert len(rework_packets) == 1
            spec = rework_packets[0].spec_json
            assert spec["parent_packet_id"] == "pkt-idem-adapter-002"
            assert spec["rework_source"] == "reviewer"

    def test_create_rework_packet_twice_produces_two_packets(self, db):
        """Service layer has no guard — _maybe_create_rework_packet owns idempotency."""
        with get_db() as d:
            original = Packet(
                id="pkt-idem-001",
                feature_id="feat-idem",
                wave_id="W01",
                slug="idem-pkt",
                title="Idempotency Test",
                spec_json={
                    "scope": ["src/grace_control/"],
                    "frozen_scope": ["docs/archived/"],
                },
                acceptance_profile="NORMAL",
                attempt_count=1,
                max_attempts=3,
                state=PacketState.REJECTED.value,
            )
            d.add(original)
            d.commit()

            first = create_rework_packet(
                d, original_packet_id="pkt-idem-001",
                feature_id="feat-idem", wave_id="W01",
                original_spec=original.spec_json,
                acceptance_profile="NORMAL", title="Idempotency Test",
                slug="idem-pkt", max_attempts=3,
                verdict_source="reviewer", summary="fix issues",
                blocking_issues=["issue 1"],
            )
            d.commit()

            second = create_rework_packet(
                d, original_packet_id="pkt-idem-001",
                feature_id="feat-idem", wave_id="W01",
                original_spec=original.spec_json,
                acceptance_profile="NORMAL", title="Idempotency Test",
                slug="idem-pkt", max_attempts=3,
                verdict_source="reviewer", summary="fix issues again",
                blocking_issues=["issue 2"],
            )
            d.commit()

            assert first.id != second.id

            all_rework = [p for p in d.query(Packet).all()
                          if (p.spec_json or {}).get("origin") == "review_rework"]
            assert len(all_rework) == 2
