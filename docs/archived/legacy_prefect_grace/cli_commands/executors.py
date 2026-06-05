# ############################################################################
# AI_HEADER: executors
# ROLE: Executor specs, rotation selections, and synthetic edge matrix flows.
# ############################################################################

# START_MODULE_CONTRACT
# purpose: List and select packet executors, and run synthetic path matrix validations.
# inputs: CLI argparse Namespace.
# returns: None.
# side_effects: Selects/rotates executors, runs synthetic test runs, writes temp files.
# emitted_logs: None.
# error_behavior: Exits with appropriate status code (0/1/2) depending on check result.
# END_MODULE_CONTRACT

# START_MODULE_MAP
# mapping:
# END_MODULE_MAP

from __future__ import annotations

import argparse
import sys
import time
import tempfile
from pathlib import Path

from prefect_grace.cli_commands.common import (
    _json_envelope,
    _print_json,
)


def _cmd_list_executors(args: argparse.Namespace) -> None:
    """List all executor specs from project config."""
    command = "list-executors"
    try:
        from prefect_grace.platform.project_adapter import load_project_adapter
        from prefect_grace.platform.executor_registry import load_executor_specs

        project = load_project_adapter(args.project)
        specs = load_executor_specs(project)

        result = {
            "executors": [spec.to_dict() for spec in specs],
            "count": len(specs),
        }

        if args.json:
            _print_json(_json_envelope(ok=True, command=command, result=result))
        else:
            print(f"Executors: {len(specs)}")
            for spec in specs:
                status = "enabled" if spec.enabled else "disabled"
                roles = ", ".join(spec.roles) if spec.roles else "all"
                print(f"  - {spec.executor_id} ({spec.kind}) [{status}] roles={roles} priority={spec.priority}")

        sys.exit(0)

    except Exception as e:
        if args.json:
            _print_json(_json_envelope(
                ok=False,
                command=command,
                errors=[{"code": "LIST_EXECUTORS_FAILED", "message": str(e)}],
            ))
        else:
            print(f"List executors failed: {e}", file=sys.stderr)
        sys.exit(2)


def _cmd_select_executor(args: argparse.Namespace) -> None:
    """Select executor for packet."""
    command = "select-executor"
    try:
        from prefect_grace.platform.project_adapter import load_project_adapter
        from prefect_grace.platform.executor_registry import select_executor_for_packet
        from prefect_grace.platform.state_store import ExecutorHistoryStore

        project = load_project_adapter(args.project)
        history_store = ExecutorHistoryStore(Path(project.runtime_state_root))
        history = history_store.list_executions()

        packet = {
            "packet_id": args.packet_id,
            "role": args.role or "coder",
        }

        selection = select_executor_for_packet(
            project=project,
            packet=packet,
            history=history,
            requested_executor=args.requested_executor,
        )

        if args.json:
            _print_json(_json_envelope(ok=selection.ok, command=command, result=selection.to_dict()))
        else:
            if selection.ok:
                print(f"Selected: {selection.selected.executor_id} ({selection.selected.kind})")
                if selection.rotated_from:
                    print(f"  Rotated from: {selection.rotated_from}")
                if selection.reason:
                    print(f"  Reason: {selection.reason}")
            else:
                print(f"Selection failed: {selection.reason}")
                if selection.warnings:
                    for warning in selection.warnings:
                        print(f"  Warning: {warning}")

        sys.exit(0 if selection.ok else 1)

    except Exception as e:
        if args.json:
            _print_json(_json_envelope(
                ok=False,
                command=command,
                errors=[{"code": "SELECT_EXECUTOR_FAILED", "message": str(e)}],
            ))
        else:
            print(f"Select executor failed: {e}", file=sys.stderr)
        sys.exit(2)


def _cmd_synthetic_edge_matrix(args: argparse.Namespace) -> None:
    """Run synthetic edge matrix tests."""
    from prefect_grace.platform.synthetic_edge_matrix import build_synthetic_edge_matrix
    from prefect_grace.platform.synthetic_runner import run_synthetic_scenario
    from prefect_grace.platform.synthetic_invariants import assert_all_invariants

    profile = args.profile
    seed = args.seed

    # Generate scenarios
    scenarios = build_synthetic_edge_matrix(profile=profile, seed=seed)

    # Count scenarios
    total_generated = len(scenarios)
    pruned_scenarios = [s for s in scenarios if s.pruned]
    executed_scenarios = [s for s in scenarios if not s.pruned]

    pruned_list = []
    for scenario in pruned_scenarios:
        pruned_list.append({
            "scenario_id": scenario.scenario_id,
            "dimensions": scenario.dimensions,
            "reason": scenario.prune_reason,
        })

    # Run scenarios
    failures = []
    passed_count = 0
    failed_count = 0

    with tempfile.TemporaryDirectory() as tmp_dir:
        tmp_path = Path(tmp_dir)
        start_time = time.time()

        for scenario in executed_scenarios:
            result = run_synthetic_scenario(scenario, tmp_path)

            # Check invariants
            passed_invariants, failed_invariants = assert_all_invariants(
                result, scenario.expected_invariants
            )

            if failed_invariants:
                failed_count += 1
                # Build detailed per-failure records
                for failed_inv_msg in failed_invariants:
                    # Parse invariant name and assertion message
                    if ":" in failed_inv_msg:
                        failed_invariant, assertion = failed_inv_msg.split(":", 1)
                        assertion = assertion.strip()
                    else:
                        failed_invariant = failed_inv_msg
                        assertion = "Invariant failed"

                    # Determine expected command pattern based on invariant
                    expected_pattern = []
                    if "NO-RESUME" in failed_invariant:
                        expected_pattern = ["mock-codex", "exec", "-C", "...", "-m", "mock-model", "--json", "-"]
                    elif "MERGE" in failed_invariant:
                        expected_pattern = ["no merge command expected"]
                    elif "ACCEPT" in failed_invariant:
                        expected_pattern = ["returncode != 0 or packet_accepted = false"]

                    failures.append({
                        "scenario_id": scenario.scenario_id,
                        "dimensions": scenario.dimensions,
                        "failed_invariant": failed_invariant,
                        "assertion": assertion,
                        "actual_command": result.command,
                        "expected_command_pattern": expected_pattern,
                        "session_mode": result.session_mode,
                        "resumed_from_thread_id": result.resumed_from_thread_id,
                        "returncode": result.returncode,
                        "merge_allowed": result.merge_allowed,
                        "packet_accepted": result.packet_accepted,
                        "blocked_reason": result.blocked_reason,
                    })
            else:
                passed_count += 1

        elapsed_time = time.time() - start_time

    # Build result
    result = {
        "ok": failed_count == 0,
        "profile": profile,
        "seed": seed,
        "generated": total_generated,
        "pruned": len(pruned_scenarios),
        "passed": passed_count,
        "failed": failed_count,
        "elapsed_seconds": round(elapsed_time, 2),
        "pruned_scenarios": pruned_list,
        "failures": failures,
    }

    if args.json:
        _print_json(result)
    else:
        print(f"Synthetic Edge Matrix: {profile} profile")
        print(f"  Generated: {total_generated}")
        print(f"  Pruned: {len(pruned_scenarios)}")
        print(f"  Executed: {len(executed_scenarios)}")
        print(f"  Passed: {passed_count}")
        print(f"  Failed: {failed_count}")
        print(f"  Elapsed: {elapsed_time:.2f}s")
        if failures:
            print(f"\nFailures:")
            for failure in failures[:5]:  # Show first 5
                # Handle both old and new payload formats
                failed_inv = failure.get('failed_invariant') or ', '.join(failure.get('failed_invariants', []))
                print(f"  - {failure['scenario_id']}: {failed_inv}")

    if failed_count > 0:
        sys.exit(1)
