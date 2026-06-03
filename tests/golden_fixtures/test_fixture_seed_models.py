"""Tests for fixture DB seeding and preflight validation."""

import os
import tempfile
from pathlib import Path
from unittest.mock import patch

import pytest

from grace_control.core.golden_fixtures import (
    FixtureSpec,
    FixtureChangedFile,
    FixtureRun,
    FixtureGit,
    create_fixture_git_state,
)


def _make_minimal_spec() -> FixtureSpec:
    return FixtureSpec(
        id="test_seed",
        start_stage="merge",
        feature={"title": "Test", "slug": "test"},
        wave={"title": "W1", "order": 1},
        packet={"title": "P1", "slug": "p1", "state": "accepted", "acceptance_profile": "FAST"},
    )


class TestSeedModels:
    def test_fixture_creates_feature_wave_packet_with_uids(self):
        """seed_db_fixture creates real Feature/Wave/Packet rows with feat_/wave_/pkt_ UIDs."""
        from grace_control.db import init_db, get_db
        from grace_control.db.schema import Feature, Wave, Packet

        with tempfile.TemporaryDirectory() as td:
            init_db(f"sqlite:///{td}/test.db")
            spec = _make_minimal_spec()
            from grace_control.core.golden_fixtures import seed_db_fixture

            seed_db_fixture(spec, "feat_test123", "wave_test456", "pkt_test789", {"branch_name": "b", "worktree_path": "/tmp/w"})

            with get_db() as db:
                f = db.query(Feature).filter_by(id="feat_test123").first()
                assert f is not None
                assert f.slug == "test"
                w = db.query(Wave).filter_by(id="wave_test456").first()
                assert w is not None
                assert w.order == 1
                p = db.query(Packet).filter_by(id="pkt_test789").first()
                assert p is not None
                assert p.state == "accepted"

    def test_fixture_creates_packet_run_with_result_json(self):
        """PacketRun has result_json with legacy_result, acceptance_report, etc."""
        from grace_control.db import init_db, get_db
        from grace_control.db.schema import PacketRun

        with tempfile.TemporaryDirectory() as td:
            init_db(f"sqlite:///{td}/test.db")
            spec = _make_minimal_spec()
            from grace_control.core.golden_fixtures import seed_db_fixture

            seed_db_fixture(spec, "feat_r", "wave_r", "pkt_r",
                            {"branch_name": "b", "worktree_path": "/tmp/w", "agent_commit_sha": "abc123"})

            with get_db() as db:
                pr = db.query(PacketRun).filter_by(packet_id="pkt_r").first()
                assert pr is not None
                rj = pr.result_json
                assert "legacy_result" in rj
                assert "acceptance_report" in rj
                assert "evidence_verifier_report" in rj
                assert "reviewer_report" in rj
                assert rj.get("agent_commit_sha") == "abc123"
                assert pr.started_at is not None
                assert pr.finished_at is not None
                assert pr.started_at < pr.finished_at

    def test_fixture_generated_ids_use_uid_prefixes(self):
        """Generated UIDs use feat_/wave_/pkt_ prefixes."""
        from grace_control.core.uid import new_feature_uid, new_wave_uid, new_packet_uid

        assert new_feature_uid().startswith("feat_")
        assert new_wave_uid().startswith("wave_")
        assert new_packet_uid().startswith("pkt_")

    def test_fixture_yaml_does_not_require_ids(self):
        """Fixture YAML should not contain generated UIDs."""
        import yaml
        for yaml_path in Path("fixtures/golden").rglob("*.yaml"):
            data = yaml.safe_load(yaml_path.read_text())
            raw = yaml_path.read_text()
            assert "feat_" not in raw, f"{yaml_path} contains feat_"
            # YAML uses title/slug only
            assert data.get("id")  # fixture id, not UID
