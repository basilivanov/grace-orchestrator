"""
GRACE Development Tools CLI

This module provides the grace-dev command-line interface for development,
testing, and smoke test operations. These commands are separated from the
main grace CLI to keep production commands clean and focused.

Commands include:
- Smoke tests (registry, e2e, batch)
- Pilot runs (single packet testing)
- Nightly operations (batch execution)
"""

import argparse
import sys
from pathlib import Path


# Import command implementations from main CLI
from prefect_grace.cli_commands.parser import (
    _cmd_registry_apply_smoke,
    _cmd_registry_source_integrity_audit,
    _cmd_run_e2e_registry_seeded_smoke,
    _cmd_run_prefect_e2e_live_smoke,
    _cmd_run_prefect_e2e_batch_smoke,
    _cmd_run_prefect_e2e_real_dry_run_smoke,
    _cmd_run_nightly,
    _cmd_nightly_preflight_risk_report,
    _cmd_nightly_select_batch,
    _cmd_nightly_recheck_batch,
    _cmd_nightly_batch_execute,
    _cmd_run_nightly_controlled_batch,
    _cmd_run_single_live_packet_pilot,
    _cmd_run_single_live_prefect_packet_pilot,
    _cmd_run_single_astro_packet_pilot,
    NoDryRunAction,
)


def _register_smoke_commands(subparsers) -> None:
    """Register smoke test commands."""

    registry_apply_smoke = subparsers.add_parser(
        "registry-apply-smoke",
        help="Smoke test for registry apply operation"
    )
    registry_apply_smoke.add_argument("--project", required=True)
    registry_apply_smoke.add_argument("--state-root", required=True)
    registry_apply_smoke.add_argument("--packet-root")
    registry_apply_smoke.add_argument("--json", action="store_true")
    registry_apply_smoke.set_defaults(func=_cmd_registry_apply_smoke)

    registry_source_integrity_audit = subparsers.add_parser(
        "registry-source-integrity-audit",
        help="Audit registry source integrity"
    )
    registry_source_integrity_audit.add_argument("--project", "--project-config", dest="project", required=True)
    registry_source_integrity_audit.add_argument("--max-items", type=int, default=50)
    registry_source_integrity_audit.add_argument("--json", action="store_true")
    registry_source_integrity_audit.set_defaults(func=_cmd_registry_source_integrity_audit)

    e2e_registry_seeded_smoke = subparsers.add_parser(
        "e2e-registry-seeded",
        help="End-to-end registry seeded smoke test"
    )
    e2e_registry_seeded_smoke.add_argument("--project", required=True)
    e2e_registry_seeded_smoke.add_argument("--state-root", required=True)
    e2e_registry_seeded_smoke.add_argument("--worktree-root", required=True)
    e2e_registry_seeded_smoke.add_argument("--packet-root", required=True)
    e2e_registry_seeded_smoke.add_argument("--json", action="store_true")
    e2e_registry_seeded_smoke.set_defaults(func=_cmd_run_e2e_registry_seeded_smoke)

    e2e_live_smoke = subparsers.add_parser(
        "e2e-live",
        help="End-to-end live smoke test with Prefect"
    )
    e2e_live_smoke.add_argument("--project-config", required=True, help="Project config path")
    e2e_live_smoke.add_argument("--state-root", required=True, help="Smoke state root")
    e2e_live_smoke.add_argument("--worktree-root", required=True, help="Smoke worktree root")
    e2e_live_smoke.add_argument("--packet-root", required=True, help="Smoke packet root")
    e2e_live_smoke.add_argument("--dry-run", dest="dry_run", action="store_true", default=True, help="Agent dry-run mode (default)")
    e2e_live_smoke.add_argument("--no-dry-run", dest="dry_run", action=NoDryRunAction, nargs=0, help="Disable agent dry-run")
    e2e_live_smoke.add_argument("--execute-agent", action="store_true", help="Enable live agent execution")
    e2e_live_smoke.add_argument("--allow-live-agent-smoke", action="store_true", help="Allow one-packet live agent smoke")
    e2e_live_smoke.add_argument("--offline-fake-submitter", action="store_true", help="Use fake submitter for offline validation")
    e2e_live_smoke.add_argument("--limit", type=int, default=1, help="Submission limit (must be 1)")
    e2e_live_smoke.add_argument("--json", action="store_true", help="JSON output")
    e2e_live_smoke.set_defaults(func=_cmd_run_prefect_e2e_live_smoke)

    e2e_batch_smoke = subparsers.add_parser(
        "e2e-batch",
        help="End-to-end batch queue smoke test"
    )
    e2e_batch_smoke.add_argument("--project-config", required=True, help="Project config path")
    e2e_batch_smoke.add_argument("--state-root", required=True, help="Smoke state root")
    e2e_batch_smoke.add_argument("--worktree-root", required=True, help="Smoke worktree root")
    e2e_batch_smoke.add_argument("--packet-root", required=True, help="Smoke packet root")
    e2e_batch_smoke.add_argument("--batch-size", type=int, default=2, help="Batch size, must be 2 or 3")
    e2e_batch_smoke.add_argument("--execute-agent", action="store_true", help="Rejected in batch smoke mode")
    e2e_batch_smoke.add_argument("--offline-fake-submitter", action="store_true", help="Use fake submitter for offline validation")
    e2e_batch_smoke.add_argument("--json", action="store_true", help="JSON output")
    e2e_batch_smoke.set_defaults(func=_cmd_run_prefect_e2e_batch_smoke)

    e2e_dry_run_smoke = subparsers.add_parser(
        "e2e-dry-run",
        help="End-to-end real dry-run smoke test"
    )
    e2e_dry_run_smoke.add_argument("--project-config", required=True, help="Project config path")
    e2e_dry_run_smoke.add_argument("--state-root", required=True, help="Smoke state root")
    e2e_dry_run_smoke.add_argument("--worktree-root", required=True, help="Smoke worktree root")
    e2e_dry_run_smoke.add_argument("--packet-root", required=True, help="Smoke packet root")
    e2e_dry_run_smoke.add_argument("--timeout-seconds", type=int, default=900, help="Wait timeout seconds")
    e2e_dry_run_smoke.add_argument("--poll-interval-seconds", type=int, default=5, help="Wait poll interval seconds")
    e2e_dry_run_smoke.add_argument("--no-wait", action="store_true", help="Only verify Prefect flow run creation")
    e2e_dry_run_smoke.add_argument("--execute-agent", action="store_true", help="Rejected in real dry-run smoke mode")
    e2e_dry_run_smoke.add_argument("--json", action="store_true", help="JSON output")
    e2e_dry_run_smoke.set_defaults(func=_cmd_run_prefect_e2e_real_dry_run_smoke)


def _register_pilot_commands(subparsers) -> None:
    """Register pilot test commands."""

    single_packet_pilot = subparsers.add_parser(
        "single-packet",
        help="Run single live packet pilot with managed runner"
    )
    single_packet_pilot.add_argument("--packet", type=Path, required=True, help="Path to EXECUTION_PACKET.md")
    single_packet_pilot.add_argument("--repo-root", type=Path, required=True, help="Repository root")
    single_packet_pilot.add_argument("--worktree-root", type=Path, required=True, help="Worktree root directory")
    single_packet_pilot.add_argument("--project-key", required=True, help="Project key")
    single_packet_pilot.add_argument("--attempt", type=int, default=1, help="Attempt number (default: 1)")
    single_packet_pilot.add_argument("--base-ref", required=True, help="Base git ref")
    single_packet_pilot.add_argument("--target-branch", required=True, help="Target branch for merge (not used in pilot)")
    single_packet_pilot.add_argument("--remote", default="origin", help="Remote name for push (default: origin)")
    single_packet_pilot.add_argument("--dry-run", action="store_true", default=True, help="Dry run mode (no agent execution, no Git mutations, default)")
    single_packet_pilot.add_argument("--no-dry-run", dest="dry_run", action=NoDryRunAction, nargs=0, help="Disable dry run (required with --execute-agent)")
    single_packet_pilot.add_argument("--execute-agent", action="store_true", help="Explicitly allow live agent execution")
    single_packet_pilot.add_argument("--i-understand-live-agent", action="store_true", help="Required acknowledgement for live agent execution")
    single_packet_pilot.add_argument("--commit", action="store_true", help="Request guarded commit")
    single_packet_pilot.add_argument("--push", action="store_true", help="Request guarded push")
    single_packet_pilot.add_argument("--merge", action="store_true", help="Request guarded merge to target branch")
    single_packet_pilot.add_argument("--apply-git-mutations", action="store_true", help="Allow Git mutations to be applied (requires evidence and review)")
    single_packet_pilot.add_argument("--timeout-seconds", type=int, default=3600, help="Agent timeout in seconds (default: 3600)")
    single_packet_pilot.add_argument("--json", action="store_true", help="JSON output")
    single_packet_pilot.set_defaults(func=_cmd_run_single_live_packet_pilot)

    prefect_packet_pilot = subparsers.add_parser(
        "prefect-packet",
        help="Run synthetic scratch packet through Prefect"
    )
    prefect_packet_pilot.add_argument("--project", required=True, help="Project config path")
    prefect_packet_pilot.add_argument("--state-root", type=Path, required=True, help="Pilot state root")
    prefect_packet_pilot.add_argument("--worktree-root", type=Path, required=True, help="Pilot worktree root")
    prefect_packet_pilot.add_argument("--packet-root", type=Path, required=True, help="Synthetic packet root")
    prefect_packet_pilot.add_argument("--dry-run", action="store_true", default=True, help="Plan only, default")
    prefect_packet_pilot.add_argument("--no-dry-run", dest="dry_run", action=NoDryRunAction, nargs=0, help="Disable dry run")
    prefect_packet_pilot.add_argument("--execute-agent", action="store_true", help="Allow live managed runner agent execution")
    prefect_packet_pilot.add_argument("--i-understand-live-agent", action="store_true", help="Required live-agent acknowledgement gate")
    prefect_packet_pilot.add_argument("--timeout-seconds", type=int, default=1800, help="Submission/status timeout seconds")
    prefect_packet_pilot.add_argument("--json", action="store_true", help="JSON output")
    prefect_packet_pilot.set_defaults(func=_cmd_run_single_live_prefect_packet_pilot)

    astro_packet_pilot = subparsers.add_parser(
        "astro-packet",
        help="Run low-risk Astro packet through Prefect"
    )
    astro_packet_pilot.add_argument("--project", required=True, help="Project config path")
    astro_packet_pilot.add_argument("--state-root", type=Path, required=True, help="Pilot state root")
    astro_packet_pilot.add_argument("--worktree-root", type=Path, required=True, help="Pilot worktree root")
    astro_packet_pilot.add_argument("--packet-root", type=Path, required=True, help="Pilot packet temp root")
    astro_packet_pilot.add_argument("--packet", help="Explicit packet ID to select")
    astro_packet_pilot.add_argument("--dry-run", action="store_true", default=True, help="Plan only, default")
    astro_packet_pilot.add_argument("--no-dry-run", dest="dry_run", action=NoDryRunAction, nargs=0, help="Disable dry run")
    astro_packet_pilot.add_argument("--execute-agent", action="store_true", help="Allow live managed runner agent execution")
    astro_packet_pilot.add_argument("--i-understand-live-agent", action="store_true", help="Required live-agent acknowledgement gate")
    astro_packet_pilot.add_argument("--timeout-seconds", type=int, default=1800, help="Submission/status timeout seconds")
    astro_packet_pilot.add_argument("--json", action="store_true", help="JSON output")
    astro_packet_pilot.set_defaults(func=_cmd_run_single_astro_packet_pilot)


def _register_nightly_commands(subparsers) -> None:
    """Register nightly batch operation commands."""

    run_nightly = subparsers.add_parser(
        "run",
        help="Run nightly batch execution"
    )
    run_nightly.add_argument("--project")
    run_nightly.add_argument("--dry-run", action="store_true", default=True)
    run_nightly.add_argument("--execute", action="store_true")
    run_nightly.add_argument("--until-blocked", action="store_true")
    run_nightly.add_argument("--json", action="store_true")
    run_nightly.set_defaults(func=_cmd_run_nightly)

    nightly_preflight = subparsers.add_parser(
        "preflight",
        help="Generate nightly preflight risk report"
    )
    nightly_preflight.add_argument("--project")
    nightly_preflight.add_argument("--json", action="store_true")
    nightly_preflight.set_defaults(func=_cmd_nightly_preflight_risk_report)

    nightly_select = subparsers.add_parser(
        "select",
        help="Select nightly batch"
    )
    nightly_select.add_argument("--project")
    nightly_select.add_argument("--preflight-report", help="Path to saved preflight report JSON")
    nightly_select.add_argument("--max-packets", type=int, default=10, help="Maximum packets to select")
    nightly_select.add_argument("--max-cost", default="live_required", help="Maximum cost level")
    nightly_select.add_argument("--allow-conflicts", action="store_true", help="Allow file conflicts")
    nightly_select.add_argument("--allow-risky", action="store_true", help="Allow risky packets")
    nightly_select.add_argument("--json", action="store_true")
    nightly_select.set_defaults(func=_cmd_nightly_select_batch)

    nightly_recheck = subparsers.add_parser(
        "recheck",
        help="Recheck nightly batch selection"
    )
    nightly_recheck.add_argument("--project")
    nightly_recheck.add_argument("--selection", help="Path to saved nightly selection JSON")
    nightly_recheck.add_argument("--max-packets", type=int, default=10, help="Current maximum packets")
    nightly_recheck.add_argument("--max-cost", default="live_required", help="Current maximum cost level")
    nightly_recheck.add_argument("--allow-conflicts", action="store_true", help="Allow conflicts when generating selection")
    nightly_recheck.add_argument("--allow-risky", action="store_true", help="Allow risky packets when generating selection")
    nightly_recheck.add_argument("--json", action="store_true")
    nightly_recheck.set_defaults(func=_cmd_nightly_recheck_batch)

    nightly_execute = subparsers.add_parser(
        "execute",
        help="Execute nightly batch"
    )
    nightly_execute.add_argument("--project")
    nightly_execute.add_argument("--max-packets", type=int, default=10, help="Maximum packets to execute")
    nightly_execute.add_argument("--concurrency", type=int, default=1, help="Maximum concurrent executions")
    nightly_execute.add_argument("--timeout-seconds-per-packet", type=int, default=3600, help="Timeout per packet")
    nightly_execute.add_argument("--max-failures", type=int, default=3, help="Stop after this many failures")
    nightly_execute.add_argument("--no-stop-on-degradation", action="store_true", help="Do not stop on degradation")
    nightly_execute.add_argument("--allow-git-commit", action="store_true", help="Request guarded commit")
    nightly_execute.add_argument("--allow-git-push", action="store_true", help="Request guarded push")
    nightly_execute.add_argument("--base-ref", default="origin/master", help="Git base reference")
    nightly_execute.add_argument("--target-branch", default="master", help="Target branch")
    nightly_execute.add_argument("--remote", default="origin", help="Remote name")
    nightly_execute.add_argument("--dry-run", action="store_true", default=True, help="Dry run mode (default)")
    nightly_execute.add_argument("--execute", action="store_true", help="Execute packets (requires opt-in)")
    nightly_execute.add_argument("--i-understand-live-batch", action="store_true", help="Required for live execution")
    nightly_execute.add_argument("--json", action="store_true")
    nightly_execute.set_defaults(func=_cmd_nightly_batch_execute)

    nightly_controlled = subparsers.add_parser(
        "controlled",
        help="Run controlled nightly batch"
    )
    nightly_controlled.add_argument("--project")
    nightly_controlled.add_argument("--selection", help="Path to saved nightly selection JSON")
    nightly_controlled.add_argument("--max-packets", type=int, default=3, help="Maximum packets to execute")
    nightly_controlled.add_argument("--concurrency", type=int, default=1, help="Must be 1 for controlled batch")
    nightly_controlled.add_argument("--timeout-seconds-per-packet", type=int, default=1800, help="Bounded timeout per packet")
    nightly_controlled.add_argument("--max-failures", type=int, default=1, help="Stop after this many failures")
    nightly_controlled.add_argument("--no-stop-on-degradation", action="store_true", help="Do not stop on unexpected degradation")
    nightly_controlled.add_argument("--allow-git-commit", action="store_true", help="Delegate guarded packet branch commit")
    nightly_controlled.add_argument("--allow-git-push", action="store_true", help="Delegate guarded packet branch push")
    controlled_mode = nightly_controlled.add_mutually_exclusive_group()
    controlled_mode.add_argument("--dry-run", action="store_true", default=True, help="Dry run mode (default)")
    controlled_mode.add_argument("--execute", action="store_true", help="Execute packets (requires all live gates)")
    nightly_controlled.add_argument("--i-understand-live-batch", action="store_true", help="Required for live execution")
    nightly_controlled.add_argument("--json", action="store_true", help="JSON output")
    nightly_controlled.set_defaults(func=_cmd_run_nightly_controlled_batch)


def build_devtools_parser() -> argparse.ArgumentParser:
    """Build the grace-dev argument parser."""
    parser = argparse.ArgumentParser(
        prog="grace-dev",
        description="GRACE development tools and smoke tests"
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    # Create command groups
    smoke = subparsers.add_parser("smoke", help="Smoke test commands")
    smoke_subparsers = smoke.add_subparsers(dest="smoke_command", required=True)
    _register_smoke_commands(smoke_subparsers)

    pilot = subparsers.add_parser("pilot", help="Pilot test commands")
    pilot_subparsers = pilot.add_subparsers(dest="pilot_command", required=True)
    _register_pilot_commands(pilot_subparsers)

    nightly = subparsers.add_parser("nightly", help="Nightly batch operations")
    nightly_subparsers = nightly.add_subparsers(dest="nightly_command", required=True)
    _register_nightly_commands(nightly_subparsers)

    return parser


def main():
    """Main entry point for grace-dev CLI."""
    parser = build_devtools_parser()
    args = parser.parse_args()

    # Execute the command function
    if hasattr(args, "func"):
        try:
            return args.func(args)
        except Exception as e:
            print(f"Error: {e}", file=sys.stderr)
            return 1

    # No function set, print help
    parser.print_help()
    return 1


if __name__ == "__main__":
    sys.exit(main())
