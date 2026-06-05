#!/usr/bin/env python3
"""
Test the cost dashboard with mock data.
"""
import json
import tempfile
from pathlib import Path


def create_mock_metrics():
    """Create mock metrics data for testing."""
    return {
        "total_executions": 150,
        "total_cost_usd": 2.4567,
        "total_tokens": 1250000,
        "avg_duration_seconds": 45.3,
        "by_model": {
            "claude-opus-4": {
                "count": 15,
                "cost": 0.9375,
                "tokens": 125000
            },
            "claude-sonnet-4": {
                "count": 90,
                "cost": 1.125,
                "tokens": 750000
            },
            "claude-haiku-4": {
                "count": 45,
                "cost": 0.3942,
                "tokens": 375000
            }
        },
        "by_complexity": {
            "high": {
                "count": 15,
                "cost": 0.9375,
                "tokens": 125000
            },
            "medium": {
                "count": 90,
                "cost": 1.125,
                "tokens": 750000
            },
            "low": {
                "count": 45,
                "cost": 0.3942,
                "tokens": 375000
            }
        },
        "by_role": {
            "planner": {
                "count": 30,
                "cost": 0.4875,
                "tokens": 250000
            },
            "architect": {
                "count": 25,
                "cost": 0.4063,
                "tokens": 208333
            },
            "coder": {
                "count": 60,
                "cost": 0.9,
                "tokens": 600000
            },
            "reviewer": {
                "count": 20,
                "cost": 0.3250,
                "tokens": 166667
            },
            "verifier": {
                "count": 15,
                "cost": 0.3379,
                "tokens": 125000
            }
        },
        "savings": {
            "actual_cost_usd": 2.4567,
            "premium_only_cost_usd": 9.375,
            "savings_usd": 6.9183,
            "savings_pct": 73.8
        }
    }


def test_dashboard():
    """Test dashboard generation with mock data."""
    import sys
    import os

    # Get script directory
    script_dir = Path(__file__).parent

    # Create temporary output directory
    with tempfile.TemporaryDirectory() as tmpdir:
        output_dir = Path(tmpdir)

        # Write mock metrics
        metrics_file = output_dir / "metrics.json"
        with open(metrics_file, "w") as f:
            json.dump(create_mock_metrics(), f, indent=2)

        # Copy dashboard HTML
        import shutil
        dashboard_src = script_dir / "dashboard.html"
        dashboard_dst = output_dir / "dashboard.html"
        shutil.copy(dashboard_src, dashboard_dst)

        print("✓ Mock dashboard generated successfully!")
        print(f"  Metrics: {metrics_file}")
        print(f"  Dashboard: {dashboard_dst}")
        print(f"\nOpen in browser:")
        print(f"  file://{dashboard_dst}")
        print(f"\nMetrics summary:")

        metrics = create_mock_metrics()
        print(f"  Total executions: {metrics['total_executions']}")
        print(f"  Total cost: ${metrics['total_cost_usd']:.4f}")
        print(f"  Total tokens: {metrics['total_tokens']:,}")
        print(f"  Savings: ${metrics['savings']['savings_usd']:.4f} ({metrics['savings']['savings_pct']:.1f}%)")

        # Keep files for inspection
        print(f"\nFiles will be deleted when test exits.")
        print(f"Press Enter to continue...")
        input()


if __name__ == "__main__":
    test_dashboard()
