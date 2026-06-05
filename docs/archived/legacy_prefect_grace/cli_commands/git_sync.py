# ############################################################################
# AI_HEADER: git_sync
# ROLE: CLI command handler for guarded git-sync and auto-branching operations.
# ############################################################################

# START_MODULE_CONTRACT
# purpose: Expose the Git sync and auto-branching operation through the split GRACE CLI.
# inputs: argparse Namespace.
# returns: None.
# side_effects: Prints JSON or text; may perform git sync and auto-branching only when apply is set.
# emitted_logs: None.
# error_behavior: Exits 0 for success, 1 for blocked gate, 2 for command errors.
# END_MODULE_CONTRACT

# START_MODULE_MAP
# mapping:
#   - function: _cmd_git_sync
# END_MODULE_MAP

from __future__ import annotations

import argparse
from pathlib import Path
import sys

from prefect_grace.cli_commands.common import _json_envelope, _print_json


def _cmd_git_sync(args: argparse.Namespace) -> None:
    command = "git-sync"
    try:
        from prefect_grace.platform.git_sync import run_git_sync

        result = run_git_sync(
            packet=Path(args.packet),
            repo_root=Path(args.repo_root),
            worktree_root=Path(args.worktree_root),
            project_key=args.project_key,
            packet_id=args.packet_id,
            attempt=int(args.attempt),
            base_ref=args.base_ref,
            remote=args.remote,
            dry_run=bool(args.dry_run) or not bool(args.apply),
            apply=bool(args.apply),
        )
        payload = result.to_dict()
        if args.json:
            _print_json(_json_envelope(
                ok=result.ok,
                command=command,
                result=payload,
                errors=result.blockers,
            ))
        else:
            print(f"Git sync: {result.status.upper()}")
            print(f"  Packet: {result.packet_id}")
            print(f"  Attempt: {args.attempt}")
            print(f"  Branch name: {result.branch_name}")
            print(f"  Worktree path: {result.worktree_path}")
            print(f"  Review status: {result.review_status}")
            if result.commit_sha:
                print(f"  Commit SHA: {result.commit_sha}")
            if result.pushed_ref:
                print(f"  Pushed ref: {result.pushed_ref}")
            if result.blocker_reason:
                print(f"  Blocker: {result.blocker_reason}")
        sys.exit(0 if result.ok else 1)
    except Exception as exc:
        if args.json:
            _print_json(_json_envelope(
                ok=False,
                command=command,
                errors=[{"code": "GIT_SYNC_COMMAND_FAILED", "message": str(exc)}],
            ))
        else:
            print(f"Git sync failed: {exc}", file=sys.stderr)
        sys.exit(2)
