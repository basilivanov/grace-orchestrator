"""Tests for RuntimeArtifactStore and RuntimeArtifactRef."""
from __future__ import annotations

import json
from pathlib import Path

from grace_control.core.runtime_artifacts import RuntimeArtifactRef, RuntimeArtifactStore
from grace_control.core.runtime_trace import RuntimeTraceContext, generate_trace_id


def _make_trace(feature_id: str = "feat_test") -> RuntimeTraceContext:
    return RuntimeTraceContext(trace_id=generate_trace_id(), feature_id=feature_id)


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

    def test_artifact_store_writes_json_with_sha_size_preview(self, tmp_path):
        store = RuntimeArtifactStore(root=tmp_path)
        trace = _make_trace("feat_jtest")
        ref = store.write_json(
            trace=trace, stage="architect", name="parsed_plan.json",
            payload={"waves": []}, kind="parsed_plan",
        )
        assert ref.sha256 and len(ref.sha256) == 64
        assert ref.size_bytes > 0
        assert ref.kind == "parsed_plan"
        # File exists
        artifact_path = tmp_path / "feat_jtest" / "architect" / "parsed_plan.json"
        assert artifact_path.exists()
        data = json.loads(artifact_path.read_text())
        assert data == {"waves": []}

    def test_artifact_store_writes_text_with_sha_size_preview(self, tmp_path):
        store = RuntimeArtifactStore(root=tmp_path)
        trace = _make_trace("feat_jtest")
        ref = store.write_text(
            trace=trace, stage="architect", name="prompt.txt",
            content="Hello, world!", kind="prompt",
        )
        assert ref.sha256 and len(ref.sha256) == 64
        assert ref.size_bytes == 13
        assert ref.kind == "prompt"
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
            trace=trace, stage="", name="events.jsonl",
            payload={"event": "e1"}, kind="events",
        )
        ref2 = store.append_jsonl(
            trace=trace, stage="", name="events.jsonl",
            payload={"event": "e2"}, kind="events",
        )
        assert ref1.sha256 and ref2.sha256
        assert ref1.size_bytes < ref2.size_bytes  # second has more content
        events_path = tmp_path / "feat_jsonl" / "events.jsonl"
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
