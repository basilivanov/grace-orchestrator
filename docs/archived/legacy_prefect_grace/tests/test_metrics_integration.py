"""
Integration tests for metrics collection.

Tests the complete metrics collection flow including:
- Token parsing from different model outputs
- Cost calculation
- Duration tracking
- Metrics aggregation
"""
import json
import re
from pathlib import Path

import pytest
from prefect_grace.tools.aggregate_metrics import (
    aggregate_metrics,
    _empty_metrics,
    _estimate_metrics_from_runs,
)


class TestTokenParsing:
    """Test parsing tokens from different model output formats."""

    def test_parse_gemini_tokens(self, mock_codex_output_gemini):
        """Parse token counts from Gemini output format."""
        output = mock_codex_output_gemini

        # Extract tokens using regex patterns
        total_match = re.search(r"Total tokens:\s*(\d+)", output)
        input_match = re.search(r"Input tokens:\s*(\d+)", output)
        output_match = re.search(r"Output tokens:\s*(\d+)", output)

        assert total_match is not None
        assert int(total_match.group(1)) == 50000
        assert int(input_match.group(1)) == 30000
        assert int(output_match.group(1)) == 20000

    def test_parse_claude_tokens(self, mock_codex_output_claude):
        """Parse token counts from Claude output format."""
        output = mock_codex_output_claude

        # Extract usage JSON
        usage_match = re.search(r'Usage:\s*({[^}]+})', output)
        assert usage_match is not None

        usage = json.loads(usage_match.group(1))
        assert usage["input_tokens"] == 40000
        assert usage["output_tokens"] == 25000

        total_tokens = usage["input_tokens"] + usage["output_tokens"]
        assert total_tokens == 65000

    def test_parse_openai_tokens(self, mock_codex_output_openai):
        """Parse token counts from OpenAI output format."""
        output = mock_codex_output_openai

        completion_match = re.search(r"Completion tokens:\s*(\d+)", output)
        prompt_match = re.search(r"Prompt tokens:\s*(\d+)", output)

        assert completion_match is not None
        assert prompt_match is not None

        completion_tokens = int(completion_match.group(1))
        prompt_tokens = int(prompt_match.group(1))

        assert completion_tokens == 15000
        assert prompt_tokens == 35000
        assert completion_tokens + prompt_tokens == 50000


class TestCostCalculation:
    """Test cost calculation for different models."""

    def test_calculate_gemini_flash_cost(self):
        """Calculate cost for Gemini 3.5 Flash."""
        # Gemini 3.5 Flash pricing: ~$0.075 per 1M input, ~$0.30 per 1M output
        input_tokens = 30000
        output_tokens = 20000

        input_cost = (input_tokens / 1_000_000) * 0.075
        output_cost = (output_tokens / 1_000_000) * 0.30

        total_cost = input_cost + output_cost
        assert abs(total_cost - 0.00825) < 0.0001

    def test_calculate_gemini_pro_cost(self):
        """Calculate cost for Gemini 3.1 Pro."""
        # Gemini 3.1 Pro pricing: ~$1.25 per 1M input, ~$5.00 per 1M output
        input_tokens = 40000
        output_tokens = 30000

        input_cost = (input_tokens / 1_000_000) * 1.25
        output_cost = (output_tokens / 1_000_000) * 5.00

        total_cost = input_cost + output_cost
        assert abs(total_cost - 0.20) < 0.01

    def test_calculate_claude_opus_cost(self):
        """Calculate cost for Claude Opus 4."""
        # Claude Opus 4 pricing: ~$15 per 1M input, ~$75 per 1M output
        input_tokens = 50000
        output_tokens = 25000

        input_cost = (input_tokens / 1_000_000) * 15.0
        output_cost = (output_tokens / 1_000_000) * 75.0

        total_cost = input_cost + output_cost
        assert abs(total_cost - 2.625) < 0.001

    def test_calculate_claude_sonnet_cost(self):
        """Calculate cost for Claude Sonnet 4."""
        # Claude Sonnet 4 pricing: ~$3 per 1M input, ~$15 per 1M output
        input_tokens = 40000
        output_tokens = 25000

        input_cost = (input_tokens / 1_000_000) * 3.0
        output_cost = (output_tokens / 1_000_000) * 15.0

        total_cost = input_cost + output_cost
        assert abs(total_cost - 0.495) < 0.001


class TestMetricsAggregation:
    """Test metrics aggregation from execution logs."""

    def test_aggregate_metrics_with_explicit_events(self, temp_state_dir, execution_trace_file):
        """Aggregate metrics from EXECUTION_METRICS events."""
        metrics = aggregate_metrics(temp_state_dir)

        assert metrics["total_executions"] == 2
        assert metrics["total_cost_usd"] == 1.70  # 0.20 + 1.50
        assert metrics["total_tokens"] == 125000  # 50000 + 75000

        # Check by_model aggregation
        assert "gemini-3.5-flash" in metrics["by_model"]
        assert metrics["by_model"]["gemini-3.5-flash"]["count"] == 1
        assert metrics["by_model"]["gemini-3.5-flash"]["cost"] == 0.20

        assert "gemini-3.1-pro" in metrics["by_model"]
        assert metrics["by_model"]["gemini-3.1-pro"]["count"] == 1
        assert metrics["by_model"]["gemini-3.1-pro"]["cost"] == 1.50

    def test_aggregate_metrics_calculates_savings(self, temp_state_dir, execution_trace_file):
        """Calculate savings vs premium-only execution."""
        metrics = aggregate_metrics(temp_state_dir)

        # Premium cost would be: 125000 tokens * $75/1M = $9.375
        # Actual cost: $1.70
        # Savings: $7.675 (81.9%)

        assert "savings" in metrics
        assert metrics["savings"]["actual_cost_usd"] == 1.70
        assert metrics["savings"]["premium_only_cost_usd"] > 9.0
        assert metrics["savings"]["savings_usd"] > 7.0
        assert metrics["savings"]["savings_pct"] > 80.0

    def test_aggregate_metrics_empty_state(self, temp_state_dir):
        """Handle empty state directory gracefully."""
        metrics = aggregate_metrics(temp_state_dir)

        assert metrics["total_executions"] == 0
        assert metrics["total_cost_usd"] == 0.0
        assert metrics["total_tokens"] == 0
        assert metrics["by_model"] == {}

    def test_aggregate_metrics_by_complexity(self, temp_state_dir):
        """Aggregate metrics by complexity level."""
        # Create logs with complexity metadata
        run_dir = temp_state_dir / "runs" / "run-complexity"
        run_dir.mkdir(parents=True)
        trace_file = run_dir / "execution_trace.jsonl"

        logs = [
            {
                "event": "EXECUTION_METRICS",
                "packet_id": "SIMPLE-001",
                "complexity": "simple",
                "model": "gemini-3.5-flash",
                "total_tokens": 30000,
                "cost_usd": 0.10,
            },
            {
                "event": "EXECUTION_METRICS",
                "packet_id": "COMPLEX-001",
                "complexity": "complex",
                "model": "claude-opus-4",
                "total_tokens": 100000,
                "cost_usd": 5.00,
            },
        ]

        with open(trace_file, "w") as f:
            for log in logs:
                f.write(json.dumps(log) + "\n")

        metrics = aggregate_metrics(temp_state_dir)

        assert "by_complexity" in metrics
        assert "simple" in metrics["by_complexity"]
        assert metrics["by_complexity"]["simple"]["count"] == 1
        assert metrics["by_complexity"]["simple"]["cost"] == 0.10

        assert "complex" in metrics["by_complexity"]
        assert metrics["by_complexity"]["complex"]["count"] == 1
        assert metrics["by_complexity"]["complex"]["cost"] == 5.00

    def test_aggregate_metrics_by_role(self, temp_state_dir):
        """Aggregate metrics by packet role."""
        run_dir = temp_state_dir / "runs" / "run-roles"
        run_dir.mkdir(parents=True)
        trace_file = run_dir / "execution_trace.jsonl"

        logs = [
            {
                "event": "EXECUTION_METRICS",
                "packet_id": "CODER-001",
                "role": "coder",
                "model": "gemini-3.5-flash",
                "total_tokens": 50000,
                "cost_usd": 0.20,
            },
            {
                "event": "EXECUTION_METRICS",
                "packet_id": "VERIFIER-001",
                "role": "verifier",
                "model": "claude-sonnet-4",
                "total_tokens": 30000,
                "cost_usd": 0.50,
            },
        ]

        with open(trace_file, "w") as f:
            for log in logs:
                f.write(json.dumps(log) + "\n")

        metrics = aggregate_metrics(temp_state_dir)

        assert "by_role" in metrics
        assert "coder" in metrics["by_role"]
        assert metrics["by_role"]["coder"]["count"] == 1
        assert metrics["by_role"]["coder"]["cost"] == 0.20

        assert "verifier" in metrics["by_role"]
        assert metrics["by_role"]["verifier"]["count"] == 1
        assert metrics["by_role"]["verifier"]["cost"] == 0.50


class TestMetricsEstimation:
    """Test metrics estimation when explicit metrics are unavailable."""

    def test_estimate_metrics_from_packet_runs(self):
        """Estimate metrics from packet execution logs."""
        packet_runs = [
            {"packet_id": "P1", "event": "packet_execution_completed"},
            {"packet_id": "P2", "event": "packet_execution_completed"},
            {"packet_id": "P3", "event": "packet_execution_completed"},
        ]

        metrics = _estimate_metrics_from_runs(packet_runs)

        assert metrics["total_executions"] == 3
        assert metrics["total_tokens"] > 0
        assert metrics["total_cost_usd"] > 0
        assert "note" in metrics
        assert "estimated" in metrics["note"]

    def test_estimate_metrics_deduplicates_packets(self):
        """Deduplicate packets when estimating."""
        packet_runs = [
            {"packet_id": "P1", "event": "packet_execution_completed"},
            {"packet_id": "P1", "event": "packet_execution_completed"},  # Duplicate
            {"packet_id": "P2", "event": "packet_execution_completed"},
        ]

        metrics = _estimate_metrics_from_runs(packet_runs)

        # Should only count 2 unique packets
        assert metrics["total_executions"] == 2

    def test_empty_metrics_structure(self):
        """Test empty metrics structure."""
        metrics = _empty_metrics()

        assert metrics["total_executions"] == 0
        assert metrics["total_cost_usd"] == 0.0
        assert metrics["total_tokens"] == 0
        assert metrics["avg_duration_seconds"] == 0.0
        assert metrics["by_model"] == {}
        assert metrics["by_complexity"] == {}
        assert metrics["by_role"] == {}
        assert "savings" in metrics


class TestDurationTracking:
    """Test duration tracking in metrics."""

    def test_aggregate_duration_from_metrics(self, temp_state_dir):
        """Calculate average duration from metrics events."""
        run_dir = temp_state_dir / "runs" / "run-duration"
        run_dir.mkdir(parents=True)
        trace_file = run_dir / "execution_trace.jsonl"

        logs = [
            {
                "event": "EXECUTION_METRICS",
                "packet_id": "P1",
                "duration_seconds": 120,
                "total_tokens": 50000,
                "cost_usd": 0.20,
            },
            {
                "event": "EXECUTION_METRICS",
                "packet_id": "P2",
                "duration_seconds": 180,
                "total_tokens": 75000,
                "cost_usd": 1.50,
            },
        ]

        with open(trace_file, "w") as f:
            for log in logs:
                f.write(json.dumps(log) + "\n")

        metrics = aggregate_metrics(temp_state_dir)

        # Average duration: (120 + 180) / 2 = 150
        assert metrics["avg_duration_seconds"] == 150.0


class TestEdgeCases:
    """Test edge cases in metrics collection."""

    def test_missing_token_counts(self, temp_state_dir):
        """Handle missing token counts gracefully."""
        run_dir = temp_state_dir / "runs" / "run-missing"
        run_dir.mkdir(parents=True)
        trace_file = run_dir / "execution_trace.jsonl"

        logs = [
            {
                "event": "EXECUTION_METRICS",
                "packet_id": "P1",
                # Missing total_tokens
                "cost_usd": 0.20,
            },
        ]

        with open(trace_file, "w") as f:
            for log in logs:
                f.write(json.dumps(log) + "\n")

        metrics = aggregate_metrics(temp_state_dir)

        # Should handle gracefully with 0 tokens
        assert metrics["total_executions"] == 1
        assert metrics["total_tokens"] == 0

    def test_unknown_model(self, temp_state_dir):
        """Handle unknown model names."""
        run_dir = temp_state_dir / "runs" / "run-unknown"
        run_dir.mkdir(parents=True)
        trace_file = run_dir / "execution_trace.jsonl"

        logs = [
            {
                "event": "EXECUTION_METRICS",
                "packet_id": "P1",
                "model": "unknown-model-xyz",
                "total_tokens": 50000,
                "cost_usd": 1.00,
            },
        ]

        with open(trace_file, "w") as f:
            for log in logs:
                f.write(json.dumps(log) + "\n")

        metrics = aggregate_metrics(temp_state_dir)

        # Should track under "unknown-model-xyz"
        assert "unknown-model-xyz" in metrics["by_model"]
        assert metrics["by_model"]["unknown-model-xyz"]["count"] == 1

    def test_malformed_json_lines(self, temp_state_dir):
        """Skip malformed JSON lines gracefully."""
        run_dir = temp_state_dir / "runs" / "run-malformed"
        run_dir.mkdir(parents=True)
        trace_file = run_dir / "execution_trace.jsonl"

        with open(trace_file, "w") as f:
            f.write('{"event": "EXECUTION_METRICS", "packet_id": "P1", "cost_usd": 0.20}\n')
            f.write('this is not valid json\n')  # Malformed line
            f.write('{"event": "EXECUTION_METRICS", "packet_id": "P2", "cost_usd": 0.30}\n')

        metrics = aggregate_metrics(temp_state_dir)

        # Should process valid lines and skip malformed
        assert metrics["total_executions"] == 2
        assert metrics["total_cost_usd"] == 0.50

    def test_multiple_run_directories(self, temp_state_dir):
        """Aggregate metrics across multiple run directories."""
        # Create multiple run directories
        for i in range(3):
            run_dir = temp_state_dir / "runs" / f"run-{i}"
            run_dir.mkdir(parents=True)
            trace_file = run_dir / "execution_trace.jsonl"

            log = {
                "event": "EXECUTION_METRICS",
                "packet_id": f"P{i}",
                "total_tokens": 50000,
                "cost_usd": 0.20,
            }

            with open(trace_file, "w") as f:
                f.write(json.dumps(log) + "\n")

        metrics = aggregate_metrics(temp_state_dir)

        # Should aggregate across all runs
        assert metrics["total_executions"] == 3
        assert abs(metrics["total_cost_usd"] - 0.60) < 0.01
        assert metrics["total_tokens"] == 150000
