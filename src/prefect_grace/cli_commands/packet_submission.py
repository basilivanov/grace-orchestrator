# ############################################################################
# AI_HEADER: packet_submission
# ROLE: Submits planned ready packets to Prefect runner pipelines.
# ############################################################################

# START_MODULE_CONTRACT
# purpose: Plan and execute native Prefect submission for registry packets.
# inputs: CLI argparse Namespace.
# returns: None.
# side_effects: Submits flow runs to Prefect server, updates runtime registry state.
# emitted_logs: None.
# error_behavior: Exits with status 3 for submission failures, 1 for other exceptions.
# END_MODULE_CONTRACT

# START_MODULE_MAP
# mapping:
# END_MODULE_MAP

from __future__ import annotations

import argparse
import sys

from prefect_grace.platform.backlog_controller import BacklogController
from prefect_grace.platform.prefect_native_submission import submit_ready_packets_to_prefect
from prefect_grace.platform.runtime_adapter import E2EPacketSubmitter, ManagedPacketSubmitter
from prefect_grace.cli_commands.common import (
    _json_envelope,
    _print_json,
    _load_adapter_from_args,
)


def _cmd_submit_packets(args: argparse.Namespace) -> None:
    command = "submit-packets"
    try:
        adapter = _load_adapter_from_args(args)
        runner_kind = getattr(args, "runner", "e2e")

        # Read registry state and plan submission
        submission_plan = BacklogController.plan_submission(adapter)

        if args.execute:
            submitter = E2EPacketSubmitter() if runner_kind == "e2e" else ManagedPacketSubmitter()

            submission_result = submit_ready_packets_to_prefect(
                project=adapter,
                dry_run=False,
                limit=getattr(args, "limit", None),
                execute_agent=False,
                timeout_seconds=getattr(args, "timeout_seconds", 3600),
                base_ref=getattr(args, "base_ref", "HEAD"),
                worktree_root=None,
                scheduled_for=None,
                continue_on_error=getattr(args, "continue_on_error", False),
                submitter=submitter,
                runner_kind=runner_kind,
            )

            if submission_result.errors:
                if args.json:
                    _print_json(_json_envelope(
                        ok=False,
                        command=command,
                        project_key=adapter.project_key,
                        result=submission_result.to_dict(),
                        warnings=submission_result.warnings,
                        errors=submission_result.errors,
                    ))
                else:
                    for err in submission_result.errors:
                        print(f"ERROR: {err}", file=sys.stderr)
                sys.exit(3)  # Exit code 3 for submission errors

            if args.json:
                _print_json(_json_envelope(
                    ok=True,
                    command=command,
                    project_key=adapter.project_key,
                    result=submission_result.to_dict(),
                    warnings=submission_result.warnings,
                ))
            else:
                print(f"Submitted {len(submission_result.packets_submitted)} packets for {adapter.project_key}.")
                print(f"  Runner: {runner_kind}")
                print(f"  Planned: {len(submission_result.packets_planned)}")
                print(f"  Submitted: {len(submission_result.packets_submitted)}")
                print(f"  Blocked: {len(submission_result.blocked_packets)}")
                if submission_result.warnings:
                    print(f"  Warnings: {len(submission_result.warnings)}")
        else:
            submission_result = submit_ready_packets_to_prefect(
                project=adapter,
                dry_run=True,
                limit=getattr(args, "limit", None),
                execute_agent=False,
                timeout_seconds=getattr(args, "timeout_seconds", 3600),
                base_ref=getattr(args, "base_ref", "HEAD"),
                worktree_root=None,
                scheduled_for=None,
                continue_on_error=getattr(args, "continue_on_error", False),
                submitter=None,
                runner_kind=runner_kind,
            )
            result = submission_result.to_dict()
            result["packets_to_submit"] = submission_plan.packets_to_submit
            result["submission_order"] = submission_plan.submission_order
            result["note"] = "Submission plan validated. Use --execute to submit to Prefect."

            if submission_plan.errors:
                if args.json:
                    _print_json(_json_envelope(
                        ok=False,
                        command=command,
                        project_key=adapter.project_key,
                        result=result,
                        warnings=submission_plan.warnings,
                        errors=submission_plan.errors,
                    ))
                else:
                    for err in submission_plan.errors:
                        print(f"ERROR: {err}", file=sys.stderr)
                sys.exit(3)  # Exit code 3 for dependency/DAG invalid

            if args.json:
                _print_json(_json_envelope(
                    ok=True,
                    command=command,
                    project_key=adapter.project_key,
                    result=result,
                    warnings=submission_plan.warnings,
                ))
            else:
                print(f"Submission plan for {adapter.project_key}:")
                print(f"  Runner: {runner_kind}")
                print(f"  Packets to submit: {len(submission_plan.packets_to_submit)}")
                print(f"  Submission order: {submission_plan.submission_order}")
                print(f"  Blocked packets: {len(submission_plan.blocked_packets)}")
                if submission_plan.warnings:
                    print(f"  Warnings: {len(submission_plan.warnings)}")
    except Exception as e:
        if args.json:
            _print_json(_json_envelope(
                ok=False,
                command=command,
                errors=[{"code": "SUBMIT_FAILED", "message": str(e)}],
            ))
        else:
            print(f"Submit failed: {e}", file=sys.stderr)
        sys.exit(1)
