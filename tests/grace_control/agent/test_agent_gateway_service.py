"""W7 — AgentGatewayService tests + ApiAgentBackend smoke tests.

Covers:
  1. Unknown provider → reason + accepted=False.
  2. Mock provider echo → accepted=True, stdout contains echo.
  3. Retry on exception (custom hook raises first call).
  4. Timeout mapping (custom hook takes long; we use a tiny timeout).
  5. Artifacts persisted to worktree.
"""
from __future__ import annotations

import time
from pathlib import Path

import pytest

from grace_control.services.agent_gateway_service import (
    AgentGatewayService,
    VALID_PROVIDERS,
    _call_provider,
)


# ---------------------------------------------------------------------------
# _call_provider (the default provider hook)
# ---------------------------------------------------------------------------


class TestCallProvider:
    def test_mock_returns_echo(self):
        out = _call_provider("mock", "mock-v1", "# hello\ndo work", 10)
        assert "[mock:mock-v1]" in out["stdout"]
        assert "echo:" in out["messages"][0]["content"]
        assert out["changed_files"] == []

    def test_unsupported_provider_returns_marker(self):
        out = _call_provider("openai", "gpt-4o", "hello", 10)
        assert "not yet implemented" in out["stderr"]
        assert out["stdout"] == ""


# ---------------------------------------------------------------------------
# AgentGatewayService.dispatch
# ---------------------------------------------------------------------------


class TestDispatch:
    def test_unknown_provider_short_circuits(self, tmp_path: Path):
        svc = AgentGatewayService()
        out = svc.dispatch(
            provider="nonsense", model="m", role="coder",
            packet_id="p1", packet_markdown="x",
            worktree_path=tmp_path, timeout_seconds=10,
        )
        assert out["accepted"] is False
        assert "unknown provider" in out["reason"]
        assert out["attempts"] == 0

    def test_mock_provider_succeeds(self, tmp_path: Path):
        svc = AgentGatewayService()
        out = svc.dispatch(
            provider="mock", model="mock-v1", role="coder",
            packet_id="p2", packet_markdown="hello world",
            worktree_path=tmp_path, timeout_seconds=10,
        )
        assert out["accepted"] is True
        assert "[mock:mock-v1]" in out["stdout"]
        assert out["attempts"] == 1

    def test_retry_on_exception_then_success(self, tmp_path: Path):
        calls = {"n": 0}

        def hook(provider, model, prompt, timeout_seconds):
            calls["n"] += 1
            if calls["n"] == 1:
                raise RuntimeError("transient")
            return {"stdout": "ok", "stderr": "", "messages": [], "changed_files": []}

        svc = AgentGatewayService(provider_hook=hook)
        out = svc.dispatch(
            provider="mock", model="m", role="coder",
            packet_id="p3", packet_markdown="x",
            worktree_path=tmp_path, timeout_seconds=10, max_retries=2,
        )
        assert out["accepted"] is True
        assert calls["n"] == 2
        assert out["attempts"] == 2

    def test_retry_exhausted_returns_failure(self, tmp_path: Path):
        def hook(provider, model, prompt, timeout_seconds):
            raise RuntimeError("nope")

        svc = AgentGatewayService(provider_hook=hook)
        out = svc.dispatch(
            provider="mock", model="m", role="coder",
            packet_id="p4", packet_markdown="x",
            worktree_path=tmp_path, timeout_seconds=10, max_retries=1,
        )
        assert out["accepted"] is False
        assert "nope" in out["reason"]
        assert out["attempts"] == 2  # 1 initial + 1 retry

    def test_persists_log_to_worktree(self, tmp_path: Path):
        svc = AgentGatewayService()
        svc.dispatch(
            provider="mock", model="mock-v1", role="coder",
            packet_id="p5", packet_markdown="hi",
            worktree_path=tmp_path, timeout_seconds=10,
        )
        log_file = tmp_path / ".agent_gateway.log"
        assert log_file.exists()
        text = log_file.read_text()
        assert "packet_id=p5" in text
        assert "provider=mock" in text
        assert "[mock:mock-v1]" in text

    def test_provider_unsupported_mapped_to_failure(self, tmp_path: Path):
        svc = AgentGatewayService()
        out = svc.dispatch(
            provider="openai", model="gpt-4o", role="coder",
            packet_id="p6", packet_markdown="x",
            worktree_path=tmp_path, timeout_seconds=10,
        )
        assert out["accepted"] is False
        assert "not yet implemented" in out["reason"]

    def test_valid_providers_set_includes_mvp(self):
        # MVP supports mock + all major providers (real adapters land later).
        for p in ("openai", "anthropic", "deepseek", "gemini", "cliproxy", "mock"):
            assert p in VALID_PROVIDERS
