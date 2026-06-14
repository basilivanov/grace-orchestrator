from __future__ import annotations

import json

from grace_control.runtime.opencode_event_collector import OpenCodeEventCollector


class TestOpenCodeEventCollector:

    def test_collects_valid_json_events(self):
        c = OpenCodeEventCollector()
        ev1 = {"event": "agent_started", "ts": "2026-01-01T00:00:00Z"}
        ev2 = {"event": "agent_completed", "ts": "2026-01-01T00:01:00Z"}
        c.feed_line(json.dumps(ev1) + "\n")
        c.feed_line(json.dumps(ev2) + "\n")
        assert len(c.raw_events) == 2
        assert c.raw_events[0] == ev1
        assert c.raw_events[1] == ev2
        assert c.plain_text == ""

    def test_preserves_unparseable_stdout(self):
        c = OpenCodeEventCollector()
        c.feed_line("plain log line\n")
        c.feed_line("another line\n")
        assert c.raw_events == []
        assert "plain log line" in c.plain_text
        assert "another line" in c.plain_text

    def test_mixed_json_and_plain(self):
        c = OpenCodeEventCollector()
        ev = {"event": "step"}
        c.feed_line("progress: 50%\n")
        c.feed_line(json.dumps(ev) + "\n")
        c.feed_line("done\n")
        assert len(c.raw_events) == 1
        assert c.raw_events[0] == ev
        assert "progress: 50%" in c.plain_text
        assert "done" in c.plain_text

    def test_has_meaningful_output_true_with_events(self):
        c = OpenCodeEventCollector(require_json_events=True)
        c.feed_line('{"event":"ok"}\n')
        assert c.has_meaningful_output() is True

    def test_has_meaningful_output_false_when_empty_and_required(self):
        c = OpenCodeEventCollector(require_json_events=True)
        c.feed_line("some plain text\n")
        assert c.has_meaningful_output() is False

    def test_has_meaningful_output_true_with_plain_text_when_not_required(self):
        c = OpenCodeEventCollector(require_json_events=False)
        c.feed_line("some plain text\n")
        assert c.has_meaningful_output() is True

    def test_reset_clears_state(self):
        c = OpenCodeEventCollector()
        c.feed_line('{"event":"ok"}\n')
        c.feed_line("plain\n")
        c.reset()
        assert c.raw_events == []
        assert c.plain_text == ""
        assert c.has_meaningful_output() is False

    def test_ignores_invalid_json_starting_with_brace(self):
        c = OpenCodeEventCollector()
        c.feed_line("{invalid json}\n")
        assert c.raw_events == []
        assert "{invalid json}" in c.plain_text

    def test_handles_empty_lines(self):
        c = OpenCodeEventCollector()
        c.feed_line("\n")
        c.feed_line("")
        c.feed_line("  \n")
        assert c.raw_events == []
        # Empty/whitespace lines are kept in plain_text
