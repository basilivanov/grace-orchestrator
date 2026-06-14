"""Tests for RuntimeArtifactStore and RuntimeArtifactRef."""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from grace_control.core.runtime_artifacts import RuntimeArtifactRef, RuntimeArtifactStore, _safe_part
from grace_control.core.runtime_trace import RuntimeTraceContext, generate_trace_id


def _make_trace(feature_id: str = "feat_test") -> RuntimeTraceContext:
    return RuntimeTraceContext(trace_id=generate_trace_id(), feature_id=feature_id)


class TestSafePart:

    def test_safe_part_accepts_valid(self):
        assert _safe_part("feat_abc", "feature_id") == "feat_abc"

    def test_safe_rejects_slash(self):
        with pytest.raises(ValueError, match="unsafe artifact path component"):
            _safe_part("../evil", "feature_id")

    def test_safe_rejects_backslash(self):
        with pytest.raises(ValueError, match="unsafe artifact path component"):
            _safe_part("foo\\bar", "stage")

    def test_safe_rejects_dot(self):
        with pytest.raises(ValueError, match="unsafe artifact path component"):
            _safe_part(".", "name")

    def test_safe_rejects_dotdot(self):
        with pytest.raises(ValueError, match="unsafe artifact path component"):
            _safe_part("..", "name")

    def test_safe_rejects_empty(self):
        with pytest.raises(ValueError, match="unsafe artifact path component"):
            _safe_part("", "stage")


class TestRuntimeArtifactRef:

    def test_ref_has_all_fields(self):
        ref = RuntimeArtifactRef(
            kind="prompt",
            path=".grace/runs/feat_test/architect/prompt.txt",
            sha256="abc123",
            size_bytes=12000,
            preview="some content",
        )
        assert ref.kind == "prompt"
        assert ref.path == ".grace/runs/feat_test/architect/prompt.txt"
        assert ref.sha256 == "abc123"
        assert ref.size_bytes == 12000
        assert ref.preview == "some content"

    def test_ref_preview_optional(self):
        ref = RuntimeArtifactRef(
            kind="prompt",
            path=".grace/runs/feat_test/architect/prompt.txt",
            sha256="abc123",
            size_bytes=12000,
        )
        assert ref.preview is None


class TestRuntimeArtifactStore:

    def test_artifact_store_writes_json_with_sha_size(self, tmp_path):
        store = RuntimeArtifactStore(root=tmp_path)
        trace = _make_trace("feat_jtest")
        ref = store.write_json(
            trace=trace, stage="architect", name="parsed_plan.json",
            payload={"waves": []}, kind="parsed_plan",
        )
        assert ref.sha256 and len(ref.sha256) == 64
        assert ref.size_bytes > 0
        assert ref.kind == "parsed_plan"
        assert ref.preview is None  # disabled by default
        artifact_path = tmp_path / "feat_jtest" / "architect" / "parsed_plan.json"
        assert artifact_path.exists()
        data = json.loads(artifact_path.read_text())
        assert data == {"waves": []}

    def test_artifact_store_writes_text_with_sha_size(self, tmp_path):
        store = RuntimeArtifactStore(root=tmp_path)
        trace = _make_trace("feat_jtest")
        ref = store.write_text(
            trace=trace, stage="architect", name="prompt.txt",
            content="Hello, world!", kind="prompt",
        )
        assert ref.sha256 and len(ref.sha256) == 64
        assert ref.size_bytes == 13
        assert ref.kind == "prompt"
        assert ref.preview is None  # disabled by default
        artifact_path = tmp_path / "feat_jtest" / "architect" / "prompt.txt"
        assert artifact_path.read_text() == "Hello, world!"

    def test_feature_dir(self, tmp_path):
        store = RuntimeArtifactStore(root=tmp_path)
        assert store.feature_dir("feat_x") == tmp_path / "feat_x"

    def test_packet_dir(self, tmp_path):
        store = RuntimeArtifactStore(root=tmp_path)
        assert store.packet_dir("feat_x", "pkt_y") == tmp_path / "feat_x" / "packets" / "pkt_y"

    def test_append_jsonl_appends_to_file(self, tmp_path):
        store = RuntimeArtifactStore(root=tmp_path)
        trace = _make_trace("feat_jsonl")
        ref1 = store.append_jsonl(
            trace=trace, stage="events", name="events.jsonl",
            payload={"event": "e1"}, kind="events",
        )
        ref2 = store.append_jsonl(
            trace=trace, stage="events", name="events.jsonl",
            payload={"event": "e2"}, kind="events",
        )
        assert ref1.sha256 and ref2.sha256
        assert ref1.size_bytes < ref2.size_bytes
        events_path = tmp_path / "feat_jsonl" / "events" / "events.jsonl"
        lines = events_path.read_text().strip().split("\n")
        assert len(lines) == 2
        assert json.loads(lines[0]) == {"event": "e1"}
        assert json.loads(lines[1]) == {"event": "e2"}

    def test_multiple_stages_create_separate_dirs(self, tmp_path):
        store = RuntimeArtifactStore(root=tmp_path)
        trace = _make_trace("feat_multi")
        store.write_json(trace=trace, stage="context_builder", name="input.json",
                         payload={"scope": []}, kind="input")
        store.write_json(trace=trace, stage="architect", name="prompt.txt",
                         payload={"text": "test"}, kind="prompt")
        assert (tmp_path / "feat_multi" / "context_builder" / "input.json").exists()
        assert (tmp_path / "feat_multi" / "architect" / "prompt.txt").exists()

    def test_feature_id_traversal_rejected(self, tmp_path):
        store = RuntimeArtifactStore(root=tmp_path)
        trace = _make_trace("../evil")
        with pytest.raises(ValueError, match="unsafe.*feature_id"):
            store.write_json(trace=trace, stage="architect", name="file.json",
                             payload={}, kind="test")

    def test_stage_traversal_rejected(self, tmp_path):
        store = RuntimeArtifactStore(root=tmp_path)
        trace = _make_trace("feat_safe")
        with pytest.raises(ValueError, match="unsafe.*stage"):
            store.write_json(trace=trace, stage="../evil", name="file.json",
                             payload={}, kind="test")

    def test_name_traversal_rejected(self, tmp_path):
        store = RuntimeArtifactStore(root=tmp_path)
        trace = _make_trace("feat_safe")
        with pytest.raises(ValueError, match="unsafe.*name"):
            store.write_json(trace=trace, stage="architect", name="../evil.json",
                             payload={}, kind="test")

    def test_append_jsonl_feature_id_traversal_rejected(self, tmp_path):
        store = RuntimeArtifactStore(root=tmp_path)
        trace = _make_trace("../evil")
        with pytest.raises(ValueError, match="unsafe.*feature_id"):
            store.append_jsonl(trace=trace, stage="events", name="events.jsonl",
                               payload={"e": 1}, kind="events")

    def test_preview_disabled_by_default(self, tmp_path):
        """Default is False, so preview should be None."""
        store = RuntimeArtifactStore(root=tmp_path)
        trace = _make_trace("feat_preview")
        ref = store.write_text(
            trace=trace, stage="architect", name="prompt.txt",
            content="x" * 1000, kind="prompt",
        )
        assert ref.preview is None
