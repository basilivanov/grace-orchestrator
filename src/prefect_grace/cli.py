# ############################################################################
# AI_HEADER: cli
# ROLE: Main facade and entrypoint for the GRACE CLI platform commands.
# ############################################################################

# START_MODULE_CONTRACT
# purpose: Expose a unified facade command line interface to run GRACE platform actions.
# inputs: CLI arguments.
# returns: None.
# side_effects: Executes selected subcommands, writes state, prints results, exits process.
# emitted_logs: None.
# error_behavior: Exits with non-zero code on parser errors or command execution failures.
# END_MODULE_CONTRACT

# START_MODULE_MAP
# mapping:
# END_MODULE_MAP

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

# Re-exporting models and all command functions for backward compatibility
from prefect_grace.models import (
    FeatureStatus,
    FrontendVisualVerdict,
    ObservabilityVerdict,
    ReasoningProfile,
    ReviewVerdict,
    TestVerdict,
    WaveVerdict,
)

# Common helpers
from prefect_grace.cli_commands.common import (
    _json_envelope,
    _print_json,
    _profile_config_path,
    _load_adapter_from_args,
    _packet_to_dict,
    _scan_project_packets,
    _scheduled_for_from_args,
)

# Command groups
from prefect_grace.cli_commands.legacy_feature import (
    _cmd_feature,
    _cmd_mark_feature,
    _cmd_packet,
    _cmd_run_codex,
    _cmd_run_verifier,
    _cmd_test_feature,
    _cmd_submit_feature,
    _cmd_submit_brief,
    _cmd_print_brief_template,
    _cmd_queue,
    _cmd_dashboard,
)
from prefect_grace.cli_commands.project_registry import (
    _cmd_validate_project,
    _cmd_scan_packets,
    _cmd_validate_packet,
    _cmd_sync_packets,
    _cmd_bootstrap_backlog,
    _cmd_registry_bootstrap_apply,
    _cmd_packet_status,
    _cmd_registry_dump,
)
from prefect_grace.cli_commands.packet_submission import (
    _cmd_submit_packets,
)
from prefect_grace.cli_commands.prefect_smokes import (
    _cmd_registry_apply_smoke,
    _cmd_run_e2e_registry_seeded_smoke,
    _cmd_run_prefect_e2e_live_smoke,
    _cmd_run_prefect_e2e_batch_smoke,
    _cmd_run_prefect_e2e_real_dry_run_smoke,
    _cmd_run_nightly,
    _cmd_nightly_recheck_batch,
    _cmd_run_nightly_controlled_batch,
)
from prefect_grace.cli_commands.queue_watcher import _cmd_queue_watcher
from prefect_grace.cli_commands.worktrees import (
    _cmd_worktree_create,
    _cmd_worktree_status,
    _cmd_worktree_cleanup,
    _cmd_worktree_scope_check,
    _cmd_run_worktree_scope_flow,
)
from prefect_grace.cli_commands.packet_execution import (
    _cmd_run_managed_packet,
    _cmd_run_e2e_packet,
    _cmd_run_e2e_packet_flow,
    _cmd_run_handoff,
    _cmd_run_single_live_packet_pilot,
    _cmd_run_single_live_prefect_packet_pilot,
    _cmd_run_single_astro_packet_pilot,
)
from prefect_grace.cli_commands.evidence import (
    _cmd_review,
    _cmd_write_review,
    _cmd_write_evidence,
    _cmd_write_rework,
    _cmd_check_scope,
    _cmd_validate_evidence_contract,
    _cmd_validate_evidence_manifest,
)
from prefect_grace.cli_commands.executors import (
    _cmd_list_executors,
    _cmd_select_executor,
    _cmd_synthetic_edge_matrix,
)
from prefect_grace.cli_commands.git_mutation import (
    _cmd_git_mutation_gate,
    _cmd_packet_branch_push_gate,
)
from prefect_grace.cli_commands.git_sync import _cmd_git_sync

# Parser constructor
from prefect_grace.cli_commands.parser import build_parser as _base_build_parser


def _cmd_run_prefect_real_dry_run_seeded_smoke(args: argparse.Namespace) -> None:
    command = "run-prefect-real-dry-run-seeded-smoke"
    try:
        from prefect_grace.platform.prefect_real_dry_run_seeded_smoke import (
            run_prefect_real_dry_run_seeded_smoke,
        )

        result = run_prefect_real_dry_run_seeded_smoke(
            project_config=Path(args.project),
            state_root=Path(args.state_root),
            worktree_root=Path(args.worktree_root),
            packet_root=Path(args.packet_root),
            timeout_seconds=int(args.timeout_seconds),
            poll_interval_seconds=int(args.poll_interval_seconds),
            wait=not bool(args.no_wait),
            execute_agent=bool(getattr(args, "execute_agent", False)),
        )
        payload = result.to_dict()

        if args.json:
            _print_json(_json_envelope(
                ok=result.ok,
                command=command,
                project_key=result.project_key,
                result=payload,
                warnings=result.warnings,
                errors=result.errors,
            ))
        else:
            print(f"Prefect real dry-run seeded smoke for {result.project_key}: {'OK' if result.ok else 'FAILED'}")
            print(f"  State root: {result.state_root}")
            print(f"  Worktree root: {result.worktree_root}")
            print(f"  Packet root: {result.packet_root}")
            print(f"  Selected packet: {result.selected_packet_id or '-'}")
            print(f"  Bootstrap apply count: {result.bootstrap_apply_count}")
            print(f"  Prefect runs created: {result.prefect_runs_created}")
            print(f"  Live agents started: {result.live_agents_started}")
            print(f"  Flow run: {result.flow_run_id or '-'}")
            for error in result.errors:
                print(f"ERROR: {error}", file=sys.stderr)
        sys.exit(0 if result.ok else 1)
    except Exception as e:
        if args.json:
            _print_json(_json_envelope(
                ok=False,
                command=command,
                errors=[{"code": "PREFECT_REAL_DRY_RUN_SEEDED_SMOKE_FAILED", "message": str(e)}],
            ))
        else:
            print(f"Prefect real dry-run seeded smoke failed: {e}", file=sys.stderr)
        sys.exit(2)


def _cmd_run_live_opt_in_single_scratch_packet(args: argparse.Namespace) -> None:
    command = "run-live-opt-in-single-scratch-packet"
    try:
        from prefect_grace.platform.live_opt_in_single_scratch_packet import (
            run_live_opt_in_single_scratch_packet,
        )

        result = run_live_opt_in_single_scratch_packet(
            project_config=Path(args.project),
            state_root=Path(args.state_root),
            worktree_root=Path(args.worktree_root),
            packet_root=Path(args.packet_root),
            execute_agent=bool(getattr(args, "execute_agent", False)),
            acknowledge_live_agent=bool(getattr(args, "i_understand_live_agent", False)),
            opt_in_token=os.environ.get("GRACE_LIVE_AGENT_OPT_IN"),
            timeout_seconds=int(args.timeout_seconds),
        )
        payload = result.to_dict()

        if args.json:
            _print_json(_json_envelope(
                ok=result.ok,
                command=command,
                project_key=result.project_key,
                result=payload,
                warnings=result.warnings,
                errors=result.errors,
            ))
        else:
            print(f"Live opt-in single scratch packet for {result.project_key}: {'OK' if result.ok else 'FAILED'}")
            print(f"  State root: {result.state_root}")
            print(f"  Worktree root: {result.worktree_root}")
            print(f"  Packet root: {result.packet_root}")
            print(f"  Selected packet: {result.selected_packet_id or '-'}")
            print(f"  Opt-in confirmed: {result.opt_in_confirmed}")
            print(f"  Agent launch count: {result.agent_launch_count}")
            print(f"  Scope verdict: {result.scope_verdict or '-'}")
            print(f"  Flow run: {result.flow_run_id or '-'}")
            for error in result.errors:
                print(f"ERROR: {error}", file=sys.stderr)
        sys.exit(0 if result.ok else 1)
    except Exception as e:
        if args.json:
            _print_json(_json_envelope(
                ok=False,
                command=command,
                errors=[{"code": "LIVE_OPT_IN_SINGLE_SCRATCH_PACKET_FAILED", "message": str(e)}],
            ))
        else:
            print(f"Live opt-in single scratch packet failed: {e}", file=sys.stderr)
        sys.exit(2)


# START_FUNCTION_CONTRACT
# name: build_parser
# purpose: Build the CLI parser and register facade-level commands.
# inputs: None.
# returns: argparse.ArgumentParser with all supported subcommands.
# side_effects: None.
# emitted_logs: None.
# error_behavior: Propagates parser construction errors.
# END_FUNCTION_CONTRACT
def build_parser() -> argparse.ArgumentParser:
    parser = _base_build_parser()
    subparsers = next(action for action in parser._actions if isinstance(action, argparse._SubParsersAction))
    if "run-prefect-real-dry-run-seeded-smoke" not in subparsers.choices:
        seeded = subparsers.add_parser(
            "run-prefect-real-dry-run-seeded-smoke",
            help="Run one registry-seeded real Prefect E2E dry-run smoke",
        )
        seeded.add_argument("--project", required=True, help="Project config path")
        seeded.add_argument("--state-root", required=True, help="Smoke state root")
        seeded.add_argument("--worktree-root", required=True, help="Smoke worktree root")
        seeded.add_argument("--packet-root", required=True, help="Synthetic smoke packet root")
        seeded.add_argument("--timeout-seconds", type=int, default=900, help="Wait timeout seconds")
        seeded.add_argument("--poll-interval-seconds", type=int, default=5, help="Wait poll interval seconds")
        seeded.add_argument("--no-wait", action="store_true", help="Only verify Prefect flow run creation")
        seeded.add_argument("--execute-agent", action="store_true", help="Rejected in seeded dry-run smoke mode")
        seeded.add_argument("--json", action="store_true", help="JSON output")
        seeded.set_defaults(func=_cmd_run_prefect_real_dry_run_seeded_smoke)
    if "run-live-opt-in-single-scratch-packet" not in subparsers.choices:
        live = subparsers.add_parser(
            "run-live-opt-in-single-scratch-packet",
            help="Run one explicitly opt-in live-agent scratch packet smoke",
        )
        live.add_argument("--project", required=True, help="Project config path")
        live.add_argument("--state-root", required=True, help="Smoke state root")
        live.add_argument("--worktree-root", required=True, help="Smoke worktree root")
        live.add_argument("--packet-root", required=True, help="Synthetic smoke packet root")
        live.add_argument("--execute-agent", action="store_true", help="Required live-agent execution gate")
        live.add_argument("--i-understand-live-agent", action="store_true", help="Required live-agent acknowledgement gate")
        live.add_argument("--timeout-seconds", type=int, default=1800, help="Runner or submission timeout seconds")
        live.add_argument("--json", action="store_true", help="JSON output")
        live.set_defaults(func=_cmd_run_live_opt_in_single_scratch_packet)
    return parser


def main() -> None:
    args = build_parser().parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
