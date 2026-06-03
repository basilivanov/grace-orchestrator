"""Tests for NanoID UID generation."""

import pytest
from unittest.mock import MagicMock

from grace_control.core.uid import (
    nanoid,
    new_feature_uid,
    new_wave_uid,
    new_packet_uid,
    new_run_uid,
    generate_unique_id,
)


class TestNanoID:
    def test_nanoid_length_and_alphabet(self):
        for size in (8, 10, 16):
            v = nanoid(size)
            assert len(v) == size
            assert all(c in "0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz" for c in v)

    def test_new_feature_uid_prefix(self):
        v = new_feature_uid()
        assert v.startswith("feat_")
        assert len(v) == 15  # feat_ + 10

    def test_new_wave_uid_prefix(self):
        v = new_wave_uid()
        assert v.startswith("wave_")
        assert len(v) == 15

    def test_new_packet_uid_prefix(self):
        v = new_packet_uid()
        assert v.startswith("pkt_")
        assert len(v) == 14

    def test_new_run_uid_prefix(self):
        v = new_run_uid()
        assert v.startswith("run_")
        assert len(v) == 14

    def test_generate_unique_id_no_collision(self):
        db = MagicMock()
        db.query.return_value.filter_by.return_value.first.return_value = None
        uid = generate_unique_id(db, object, new_feature_uid)
        assert uid.startswith("feat_")

    def test_generate_unique_id_retries_on_collision(self):
        db = MagicMock()
        db.query.return_value.filter_by.return_value.first.side_effect = [MagicMock(), MagicMock(), None]
        uid = generate_unique_id(db, object, new_feature_uid, max_attempts=5)
        assert uid.startswith("feat_")

    def test_generate_unique_id_raises_on_exhaustion(self):
        db = MagicMock()
        db.query.return_value.filter_by.return_value.first.return_value = MagicMock()
        with pytest.raises(RuntimeError, match="failed to generate unique id"):
            generate_unique_id(db, object, new_feature_uid, max_attempts=2)

    def test_generate_unique_id_reserved_collision(self):
        db = MagicMock()
        db.query.return_value.filter_by.return_value.first.return_value = None
        counter = [0]
        def factory():
            counter[0] += 1
            return "feat_EXISTS" if counter[0] == 1 else "feat_FREE"
        reserved = {"feat_EXISTS"}
        uid = generate_unique_id(db, object, factory, reserved=reserved)
        assert uid == "feat_FREE"
        assert uid not in reserved
