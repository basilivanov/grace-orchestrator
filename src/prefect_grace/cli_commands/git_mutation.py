# ############################################################################
# AI_HEADER: git_mutation
# ROLE: CLI command handlers for guarded Git mutation planning and apply.
# ############################################################################

# START_MODULE_CONTRACT
# purpose: Expose the Git mutation gate through the split GRACE CLI.
# inputs: argparse Namespace.
# returns: None.
# side_effects: Prints JSON/text; may apply Git mutations only through platform gate flags.
# emitted_logs: None.
# error_behavior: Exits 0 for success, 1 for blocked gate, 2 for command errors.
# END_MODULE_CONTRACT

# START_MODULE_MAP
# mapping:
#   - function: _cmd_git_mutation_gate
#   - function: _cmd_packet_branch_push_gate
#   - function: _cmd_merge_steward
# END_MODULE_MAP

from __future__ import annotations

import argparse
from pathlib import Path
import sys

from prefect_grace.cli_commands.common import _json_envelope, _print_json


def _cmd_git_mutation_gate(args: argparse.Namespace) -> None:
    command = "git-mutation-gate"
    try:
        from prefect_grace.platform.git_mutation_gate import run_git_mutation_gate

        result = run_git_mutation_gate(
            packet=args.packet,
            repo_root=args.repo_root,
            worktree_root=args.worktree_root,
            worktree_path=args.worktree_path,
            project_key=args.project_key,
            packet_id=args.packet_id,
            attempt=int(args.attempt),
            base_ref=args.base_ref,
            target_branch=args.target_branch,
            remote=args.remote,
            dry_run=bool(args.dry_run) or not bool(args.apply),
            apply=bool(args.apply),
            commit=bool(args.commit),
            push=bool(args.push),
            merge=bool(args.merge),
            understand_merge=bool(args.i_understand_merge),
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
            print(f"Git mutation gate: {result.status}")
            print(f"  Packet: {result.packet_id}")
            print(f"  Commit: {result.mutations.get('commit')}")
            print(f"  Push: {result.mutations.get('push')}")
            print(f"  Merge: {result.mutations.get('merge')}")
            if result.blocker_reason:
                print(f"  Blocker: {result.blocker_reason}")
        sys.exit(0 if result.ok else 1)
    except Exception as exc:
        if args.json:
            _print_json(_json_envelope(
                ok=False,
                command=command,
                errors=[{"code": "GIT_MUTATION_GATE_COMMAND_FAILED", "message": str(exc)}],
            ))
        else:
            print(f"Git mutation gate failed: {exc}", file=sys.stderr)
        sys.exit(2)


def _cmd_packet_branch_push_gate(args: argparse.Namespace) -> None:
    command = "packet-branch-push-gate"
    try:
        from prefect_grace.platform.packet_branch_push_gate import run_packet_branch_push_gate

        result = run_packet_branch_push_gate(
            packet=args.packet,
            repo_root=args.repo_root,
            worktree_root=args.worktree_root,
            worktree_path=args.worktree_path,
            project_key=args.project_key,
            packet_id=args.packet_id,
            attempt=int(args.attempt),
            base_ref=args.base_ref,
            remote=args.remote,
            dry_run=bool(args.dry_run) or not bool(args.apply),
            apply=bool(args.apply),
            commit=bool(args.commit),
            push=bool(args.push),
            approve_commit=bool(args.allow_git_commit),
            approve_push=bool(args.allow_git_push),
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
            print(f"Packet branch push gate: {result.status}")
            print(f"  Packet: {result.packet_id}")
            print(f"  Commit: {result.mutations.get('commit')}")
            print(f"  Push: {result.mutations.get('push')}")
            if result.blocker_reason:
                print(f"  Blocker: {result.blocker_reason}")
        sys.exit(0 if result.ok else 1)
    except Exception as exc:
        if args.json:
            _print_json(_json_envelope(
                ok=False,
                command=command,
                errors=[{"code": "PACKET_BRANCH_PUSH_GATE_COMMAND_FAILED", "message": str(exc)}],
            ))
        else:
            print(f"Packet branch push gate failed: {exc}", file=sys.stderr)
        sys.exit(2)


def _cmd_merge_steward(args: argparse.Namespace) -> None:
    command = "merge-steward"
    try:
        from prefect_grace.platform.merge_steward import run_merge_steward

        # Parse packet branches and paths
        packet_branches = args.packet_branches or []
        packet_paths = {}
        if args.packet_path:
            for entry in args.packet_path:
                parts = entry.split(":", 1)
                if len(parts) == 2:
                    branch, path = parts
                    packet_paths[branch] = Path(path)

        result = run_merge_steward(
            repo_root=args.repo_root,
            target_branch=args.target_branch,
            packet_branches=packet_branches,
            packet_paths=packet_paths,
            remote=args.remote,
            dry_run=bool(args.dry_run) or not bool(args.apply),
            apply=bool(args.apply),
            merge=bool(args.merge),
            understand_merge=bool(args.i_understand_merge),
        )
        payload = result.to_dict()
        if args.json:
            _print_json(_json_envelope(
                ok=result.ok,
                command=command,
                result=payload,
                errors=result.blockers,
                warnings=result.warnings,
            ))
        else:
            print(f"Merge steward: {result.status}")
            if result.plan:
                print(f"  Target branch: {result.plan.target_branch}")
                print(f"  Candidates: {result.plan.candidates_total}")
                print(f"  Excluded: {result.plan.excluded_total}")
                print(f"  Fast-forward eligible: {result.plan.fast_forward_eligible}")
            if result.merged_count > 0:
                print(f"  Merged: {result.merged_count}")
            if result.blocker_reason:
                print(f"  Blocker: {result.blocker_reason}")
        sys.exit(0 if result.ok else 1)
    except Exception as exc:
        if args.json:
            _print_json(_json_envelope(
                ok=False,
                command=command,
                errors=[{"code": "MERGE_STEWARD_COMMAND_FAILED", "message": str(exc)}],
            ))
        else:
            print(f"Merge steward failed: {exc}", file=sys.stderr)
        sys.exit(2)
