# ############################################################################
# AI_HEADER: worktrees
# ROLE: Git worktree management and scope checks CLI commands.
# ############################################################################

# START_MODULE_CONTRACT
# purpose: Create, clean up, check status, and check scope of git worktrees.
# inputs: CLI argparse Namespace.
# returns: None.
# side_effects: Runs git commands, creates/removes worktree folders, prints results.
# emitted_logs: None.
# error_behavior: Exits with appropriate status code (0/1/2) depending on outcome.
# END_MODULE_CONTRACT

# START_MODULE_MAP
# mapping:
# END_MODULE_MAP

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from prefect_grace.cli_commands.common import (
    _json_envelope,
    _print_json,
)


def _cmd_worktree_create(args: argparse.Namespace) -> None:
    """Create a worktree for packet execution."""
    command = "worktree-create"
    try:
        from prefect_grace.platform.worktree_manager import WorktreeManager

        manager = WorktreeManager(
            repo_root=args.repo_root,
            worktree_root=args.worktree_root,
            project_key=args.project_key,
        )

        context = manager.create_packet_worktree(
            packet_id=args.packet_id,
            attempt=args.attempt,
            base_ref=args.base_ref,
        )

        result = {
            "packet_id": context.packet_id,
            "attempt": context.attempt,
            "worktree_path": str(context.worktree_path),
            "branch_name": context.branch_name,
            "base_ref": context.base_ref,
            "created": context.created,
        }

        if args.json:
            _print_json(_json_envelope(
                ok=True,
                command=command,
                result=result,
            ))
        else:
            print(f"Worktree created: {context.worktree_path}")
            print(f"  Branch: {context.branch_name}")
            print(f"  Base ref: {context.base_ref}")

    except Exception as e:
        if args.json:
            _print_json(_json_envelope(
                ok=False,
                command=command,
                errors=[{"code": "WORKTREE_CREATE_FAILED", "message": str(e)}],
            ))
        else:
            print(f"Worktree create failed: {e}", file=sys.stderr)
        sys.exit(1)


def _cmd_worktree_status(args: argparse.Namespace) -> None:
    """Get status of a worktree."""
    command = "worktree-status"
    try:
        from prefect_grace.platform.worktree_manager import WorktreeManager

        manager = WorktreeManager(
            repo_root=args.repo_root,
            worktree_root=args.worktree_root,
            project_key=args.project_key,
        )

        status = manager.status(
            packet_id=args.packet_id,
            attempt=args.attempt,
        )

        if args.json:
            _print_json(_json_envelope(
                ok=True,
                command=command,
                result=status.to_dict(),
            ))
        else:
            if status.exists:
                print(f"Worktree: {status.path}")
                print(f"  Branch: {status.branch_name}")
                print(f"  Dirty: {status.dirty}")
                print(f"  Changed files: {len(status.changed_files)}")
            else:
                print(f"Worktree does not exist: {status.path}")

    except Exception as e:
        if args.json:
            _print_json(_json_envelope(
                ok=False,
                command=command,
                errors=[{"code": "WORKTREE_STATUS_FAILED", "message": str(e)}],
            ))
        else:
            print(f"Worktree status failed: {e}", file=sys.stderr)
        sys.exit(1)


def _cmd_worktree_cleanup(args: argparse.Namespace) -> None:
    """Clean up a worktree."""
    command = "worktree-cleanup"
    try:
        from prefect_grace.platform.worktree_manager import WorktreeManager

        manager = WorktreeManager(
            repo_root=args.repo_root,
            worktree_root=args.worktree_root,
            project_key=args.project_key,
        )

        status = manager.cleanup_worktree(
            packet_id=args.packet_id,
            attempt=args.attempt,
            keep_on_failure=args.keep_on_failure,
        )

        if args.json:
            _print_json(_json_envelope(
                ok=True,
                command=command,
                result=status.to_dict(),
            ))
        else:
            if status.exists:
                print(f"Worktree preserved: {status.path}")
            else:
                print(f"Worktree cleaned up: {status.path}")

    except Exception as e:
        if args.json:
            _print_json(_json_envelope(
                ok=False,
                command=command,
                errors=[{"code": "WORKTREE_CLEANUP_FAILED", "message": str(e)}],
            ))
        else:
            print(f"Worktree cleanup failed: {e}", file=sys.stderr)
        sys.exit(1)


def _cmd_worktree_scope_check(args: argparse.Namespace) -> None:
    """Evaluate worktree scope lifecycle gate."""
    command = "worktree-scope-check"
    try:
        from prefect_grace.platform.worktree_scope_lifecycle import evaluate_worktree_scope

        result = evaluate_worktree_scope(
            packet_file=args.packet,
            repo_root=args.repo_root,
            worktree_root=args.worktree_root,
            project_key=args.project_key,
            packet_id=args.packet_id,
            attempt=args.attempt,
            base_ref=args.base_ref,
            keep_on_failure=args.keep_on_failure,
        )

        if args.json:
            _print_json(_json_envelope(
                ok=result.ok,
                command=command,
                result=result.to_dict(),
            ))
        else:
            # Text mode
            if result.status == "passed":
                print(f"Lifecycle: PASSED")
                print(f"  Packet: {result.packet_id}")
                print(f"  Attempt: {result.attempt}")
                print(f"  Worktree: {result.worktree_path}")
                print(f"  Branch: {result.branch_name}")
                print(f"  Changed files: {len(result.changed_files)}")
            elif result.status == "scope_blocked":
                print(f"Lifecycle: SCOPE BLOCKED")
                print(f"  Packet: {result.packet_id}")
                print(f"  Attempt: {result.attempt}")
                print(f"  Worktree: {result.worktree_path}")
                print(f"  Branch: {result.branch_name}")
                print(f"  Blocker: {result.blocker_reason}")
                print(f"  Changed files: {len(result.changed_files)}")

                scope_guard = result.scope_guard
                if scope_guard.get("frozen_violations"):
                    print(f"\n  Frozen violations:")
                    for v in scope_guard["frozen_violations"][:5]:
                        print(f"    - {v['file_path']}")
                if scope_guard.get("outside_allowed"):
                    print(f"\n  Outside allowed:")
                    for v in scope_guard["outside_allowed"][:5]:
                        print(f"    - {v['file_path']}")
            else:
                print(f"Lifecycle: ERROR")
                print(f"  Packet: {result.packet_id}")
                print(f"  Attempt: {result.attempt}")
                print(f"  Blocker: {result.blocker_reason}")

        # Exit codes
        if result.status == "passed":
            sys.exit(0)
        elif result.status == "scope_blocked":
            sys.exit(1)
        else:
            sys.exit(2)

    except Exception as e:
        if args.json:
            _print_json(_json_envelope(
                ok=False,
                command=command,
                errors=[{"code": "WORKTREE_SCOPE_CHECK_FAILED", "message": str(e)}],
            ))
        else:
            print(f"Worktree scope check failed: {e}", file=sys.stderr)
        sys.exit(2)


def _cmd_run_worktree_scope_flow(args: argparse.Namespace) -> None:
    """Run worktree scope lifecycle Prefect flow."""
    command = "run-worktree-scope-flow"
    try:
        from prefect_grace.flows.worktree_scope_lifecycle_flow import (
            worktree_scope_lifecycle_flow,
        )

        result = worktree_scope_lifecycle_flow(
            packet_file=str(args.packet),
            repo_root=str(args.repo_root),
            worktree_root=str(args.worktree_root),
            project_key=args.project_key,
            packet_id=args.packet_id,
            attempt=args.attempt,
            base_ref=args.base_ref,
            keep_on_failure=args.keep_on_failure,
        )

        if args.json:
            _print_json(_json_envelope(
                ok=result["ok"],
                command=command,
                result=result,
            ))
        else:
            # Text mode
            domain_status = result["domain_status"]
            if domain_status == "passed":
                print(f"Flow: PASSED")
                print(f"  Packet: {result['packet_id']}")
                print(f"  Attempt: {result['attempt']}")
                print(f"  Worktree: {result['worktree_path']}")
                print(f"  Branch: {result['branch_name']}")
                print(f"  Changed files: {len(result['changed_files'])}")
                print(f"  Artifacts: {len(result['artifact_ids'])}")
            elif domain_status == "scope_blocked":
                print(f"Flow: SCOPE BLOCKED")
                print(f"  Packet: {result['packet_id']}")
                print(f"  Attempt: {result['attempt']}")
                print(f"  Worktree: {result['worktree_path']}")
                print(f"  Branch: {result['branch_name']}")
                print(f"  Changed files: {len(result['changed_files'])}")
                print(f"  Artifacts: {len(result['artifact_ids'])}")

                scope_guard = result["scope_guard"]
                if scope_guard.get("frozen_violations"):
                    print(f"\n  Frozen violations:")
                    for v in scope_guard["frozen_violations"][:5]:
                        print(f"    - {v['file_path']}")
                if scope_guard.get("outside_allowed"):
                    print(f"\n  Outside allowed:")
                    for v in scope_guard["outside_allowed"][:5]:
                        print(f"    - {v['file_path']}")
            else:
                print(f"Flow: ERROR")
                print(f"  Packet: {result['packet_id']}")
                print(f"  Attempt: {result['attempt']}")
                if result.get("worktree_path"):
                    print(f"  Worktree: {result['worktree_path']}")

        # Exit codes
        domain_status = result["domain_status"]
        if domain_status == "passed":
            sys.exit(0)
        elif domain_status == "scope_blocked":
            sys.exit(1)
        else:
            sys.exit(2)

    except Exception as e:
        if args.json:
            _print_json(_json_envelope(
                ok=False,
                command=command,
                errors=[{"code": "RUN_WORKTREE_SCOPE_FLOW_FAILED", "message": str(e)}],
            ))
        else:
            print(f"Run worktree scope flow failed: {e}", file=sys.stderr)
        sys.exit(2)
