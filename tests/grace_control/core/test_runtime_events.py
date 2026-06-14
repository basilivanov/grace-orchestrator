"""Tests for RuntimeEventLogger."""
from __future__ import annotations

import json
from pathlib import Path

from grace_control.core.runtime_artifacts import RuntimeArtifactRef, RuntimeArtifactStore
from grace_control.core.runtime_events import RuntimeEventLogger
from grace_control.core.runtime_trace import RuntimeTraceContext, generate_trace_id


def _make_trace(feature_id: str = "feat_events") -> RuntimeTraceContext:
    return RuntimeTraceContext(trace_id=generate_trace_id(), feature_id=feature_id)


class TestRuntimeEventLogger:

    def test_event_logger_appends_jsonl(self, tmp_path):
        store = RuntimeArtifactStore(root=tmp_path)
        logger = RuntimeEventLogger(store=store)
        trace = _make_trace("feat_ev1")
        logger.emit(
            trace=trace, event="test.event", stage="testing",
            component="TestComponent", status="completed",
            payload={"key": "value"},
        )
        events_path = tmp_path / "feat_ev1" / "events.jsonl"
        assert events_path.exists()
        lines = events_path.read_text().strip().split("\n")
        assert len(lines) >= 1
        data = json.loads(lines[0])
        assert data["event"] == "test.event"
        assert data["trace_id"] == trace.trace_id
        assert data["feature_id"] == "feat_ev1"
        assert data["stage"] == "testing"
        assert data["component"] == "TestComponent"
        assert data["status"] == "completed"

    def test_event_logger_includes_trace_id_feature_id_stage(self, tmp_path):
        store = RuntimeArtifactStore(root=tmp_path)
        logger = RuntimeEventLogger(store=store)
        trace = RuntimeTraceContext(
            trace_id="trace_abc", feature_id="feat_123",
            packet_id="pkt_456", wave_id="wave_0",
        )
        logger.emit(trace=trace, event="detail.event", stage="detail",
                    component="DetailComponent", status="ok",
                    duration_ms=42)
        events_path = tmp_path / "feat_123" / "events.jsonl"
        data = json.loads(events_path.read_text().strip().split("\n")[0])
        assert data["trace_id"] == "trace_abc"
        assert data["feature_id"] == "feat_123"
        assert data["packet_id"] == "pkt_456"
        assert data["wave_id"] == "wave_0"
        assert data["stage"] == "detail"
        assert data["duration_ms"] == 42

    def test_event_logger_includes_artifact_refs(self, tmp_path):
        store = RuntimeArtifactStore(root=tmp_path)
        logger = RuntimeEventLogger(store=store)
        trace = _make_trace("feat_refs")
        ref = RuntimeArtifactRef(
            kind="prompt", path="some/path.txt",
            sha256="abc", size_bytes=100,
        )
        logger.emit(
            trace=trace, event="ref.event", stage="refs",
            component="RefComponent", artifact_refs=[ref],
        )
        events_path = tmp_path / "feat_refs" / "events.jsonl"
        data = json.loads(events_path.read_text().strip().split("\n")[0])
        assert len(data["artifact_refs"]) == 1
        assert data["artifact_refs"][0]["kind"] == "prompt"
        assert data["artifact_refs"][0]["sha256"] == "abc"

    def test_event_logger_respects_disabled(self, tmp_path):
        store = RuntimeArtifactStore(root=tmp_path)
        logger = RuntimeEventLogger(store=store, disabled=True)
        trace = _make_trace("feat_disabled")
        logger.emit(trace=trace, event="disabled.event", stage="test",
                    component="Test")
        events_path = tmp_path / "feat_disabled" / "events.jsonl"
        assert not events_path.exists()

    def test_feature_input_artifact_is_written(self, tmp_path):
        """Test that feature_input.json can be produced via artifact store."""
        store = RuntimeArtifactStore(root=tmp_path)
        trace = _make_trace("feat_input")
        ref = store.write_json(
            trace=trace, stage="feature", name="feature_input.json",
            payload={"task_desc": "Test description", "scope": ["src/"]},
            kind="feature_input",
        )
        assert ref.sha256
        assert (tmp_path / "feat_input" / "feature" / "feature_input.json").exists()
