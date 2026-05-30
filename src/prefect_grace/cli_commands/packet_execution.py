# ############################################################################
# AI_HEADER: packet_execution
# ROLE: Execution engines for managed, E2E packet runners, and handoff flows.
# ############################################################################

# START_MODULE_CONTRACT
# purpose: Launch isolated managed/E2E packet executions and handoff verification.
# inputs: CLI argparse Namespace.
# returns: None.
# side_effects: Executes agent/verifier/reviewer pipelines, updates git worktrees/state.
# emitted_logs: None.
# error_behavior: Exits with appropriate status code (0/1/2) depending on run result.
# END_MODULE_CONTRACT

# START_MODULE_MAP
# mapping:
# END_MODULE_MAP

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

from prefect_grace.cli_commands.common import (
    _json_envelope,
    _print_json,
)


def _cmd_run_managed_packet(args: argparse.Namespace) -> None:
    """Run managed packet execution with worktree isolation."""
    command = "run-managed-packet"

    # Safety check: fail closed on unsafe flag combinations
    # For live execution, BOTH --execute-agent AND --no-dry-run must be explicitly provided

    # First check if --execute-agent was used without explicit --no-dry-run
    # This catches both: no flags (default dry_run=True) and explicit --dry-run
    if args.execute_agent and not hasattr(args, '_no_dry_run_explicit'):
        error_msg = "Live agent execution requires explicit --no-dry-run flag. Use: --execute-agent --no-dry-run"
        if args.json:
            _print_json(_json_envelope(
                ok=False,
                command=command,
                errors=[{"code": "MISSING_EXPLICIT_NO_DRY_RUN", "message": error_msg}],
            ))
        else:
            print(f"Error: {error_msg}", file=sys.stderr)
        sys.exit(2)

    try:
        from prefect_grace.flows.managed_packet_runner_flow import (
            managed_packet_runner_flow,
        )

        result = managed_packet_runner_flow(
            packet_file=str(args.packet),
            repo_root=str(args.repo_root),
            worktree_root=str(args.worktree_root),
            project_key=args.project_key,
            packet_id=args.packet_id,
            attempt=args.attempt,
            base_ref=args.base_ref,
            dry_run=args.dry_run,
            execute_agent=args.execute_agent,
            timeout_seconds=args.timeout_seconds,
            keep_worktree=args.keep_worktree,
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
                print(f"Managed packet run: PASSED")
                print(f"  Packet: {result['packet_id']}")
                print(f"  Attempt: {result['attempt']}")
                print(f"  Worktree: {result['worktree_path']}")
                print(f"  Branch: {result['branch_name']}")
                print(f"  Changed files: {len(result['changed_files'])}")
                print(f"  Artifacts: {len(result['artifact_ids'])}")
            elif domain_status == "scope_blocked":
                print(f"Managed packet run: SCOPE BLOCKED")
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
            elif domain_status == "agent_failed":
                print(f"Managed packet run: AGENT FAILED")
                print(f"  Packet: {result['packet_id']}")
                print(f"  Attempt: {result['attempt']}")
                print(f"  Worktree: {result['worktree_path']}")
                print(f"  Branch: {result['branch_name']}")
                print(f"  Blocker: {result.get('blocker_reason', 'unknown')}")
            else:
                print(f"Managed packet run: ERROR")
                print(f"  Packet: {result['packet_id']}")
                print(f"  Attempt: {result['attempt']}")
                print(f"  Domain status: {domain_status}")
                if result.get("blocker_reason"):
                    print(f"  Blocker: {result['blocker_reason']}")

        # Exit codes: 0=passed, 1=scope_blocked, 2=agent_failed/runner_error/command_error
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
                errors=[{"code": "RUN_MANAGED_PACKET_FAILED", "message": str(e)}],
            ))
        else:
            print(f"Run managed packet failed: {e}", file=sys.stderr)
        sys.exit(2)


def _cmd_run_e2e_packet(args: argparse.Namespace) -> None:
    """Run end-to-end packet execution."""
    command = "run-e2e-packet"
    try:
        from prefect_grace.platform.e2e_packet_runner import run_e2e_packet

        project_root = Path(args.project_root)
        packet_path = Path(args.packet)
        state_root = Path(args.state_root)
        worktree_root = Path(args.worktree_root)

        # Validate paths
        if not project_root.exists():
            raise FileNotFoundError(f"Project root not found: {project_root}")
        if not packet_path.exists():
            raise FileNotFoundError(f"Packet file not found: {packet_path}")

        # Create state and worktree roots if they don't exist
        state_root.mkdir(parents=True, exist_ok=True)
        worktree_root.mkdir(parents=True, exist_ok=True)

        # Prepare fake output paths
        fake_verifier_output = Path(args.fake_verifier_output) if args.fake_verifier_output else None
        fake_reviewer_output = Path(args.fake_reviewer_output) if args.fake_reviewer_output else None

        # Run e2e packet
        result = run_e2e_packet(
            project_root=project_root,
            packet_path=packet_path,
            state_root=state_root,
            worktree_root=worktree_root,
            project_key=args.project_key,
            attempt=args.attempt,
            base_ref=args.base_ref,
            dry_run=args.dry_run,
            execute_agent=args.execute_agent,
            fake_verifier_output=fake_verifier_output,
            fake_reviewer_output=fake_reviewer_output,
            timeout_seconds=args.timeout_seconds,
            keep_worktree=args.keep_worktree,
        )

        domain_status = result.domain_status

        # Map domain status to exit code
        # 0: accepted
        # 1: rework_required, blocked, scope_blocked, agent_failed
        # 2: runner_error, verifier_failed, reviewer_failed, handoff_error
        if domain_status == "accepted":
            exit_code = 0
        elif domain_status in ["rework_required", "blocked", "scope_blocked", "agent_failed"]:
            exit_code = 1
        else:
            exit_code = 2

        if args.json:
            _print_json(_json_envelope(
                ok=result.ok,
                command=command,
                result=result.to_dict(),
            ))
        else:
            print(f"E2E Packet Runner: {domain_status}")
            print(f"  Packet: {result.packet_id}")
            print(f"  Attempt: {result.attempt}")
            print(f"  Runtime status: {result.runtime_status}")
            print(f"  Registry status: {result.registry_status}")
            print(f"  Registry reason: {result.registry_reason}")
            print(f"  Worktree: {result.worktree_path}")
            print(f"  Branch: {result.branch_name}")
            if result.errors:
                print(f"  Errors: {', '.join(result.errors)}")

        sys.exit(exit_code)

    except Exception as e:
        if args.json:
            _print_json(_json_envelope(
                ok=False,
                command=command,
                errors=[{"code": "E2E_RUNNER_ERROR", "message": str(e)}],
            ))
        else:
            print(f"Error: {e}", file=sys.stderr)
        sys.exit(2)


def _cmd_run_e2e_packet_flow(args: argparse.Namespace) -> None:
    """Run end-to-end packet execution through the Prefect flow wrapper."""
    command = "run-e2e-packet-flow"

    if args.execute_agent and not hasattr(args, '_no_dry_run_explicit'):
        error_msg = "Live agent execution requires explicit --no-dry-run flag. Use: --execute-agent --no-dry-run"
        if args.json:
            _print_json(_json_envelope(
                ok=False,
                command=command,
                errors=[{"code": "MISSING_EXPLICIT_NO_DRY_RUN", "message": error_msg}],
            ))
        else:
            print(f"Error: {error_msg}", file=sys.stderr)
        sys.exit(2)

    try:
        from prefect_grace.flows.e2e_packet_runner_flow import e2e_packet_runner_flow

        result = e2e_packet_runner_flow(
            project_root=str(args.project_root),
            packet_path=str(args.packet),
            state_root=str(args.state_root),
            worktree_root=str(args.worktree_root),
            project_key=args.project_key,
            packet_id=args.packet_id,
            attempt=args.attempt,
            base_ref=args.base_ref,
            dry_run=args.dry_run,
            execute_agent=args.execute_agent,
            fake_verifier_output=str(args.fake_verifier_output) if args.fake_verifier_output else None,
            fake_reviewer_output=str(args.fake_reviewer_output) if args.fake_reviewer_output else None,
            timeout_seconds=args.timeout_seconds,
            keep_worktree=args.keep_worktree,
        )

        if args.json:
            _print_json(_json_envelope(
                ok=result["ok"],
                command=command,
                result=result,
            ))
        else:
            print(f"E2E packet flow: {result['domain_status']}")
            print(f"  Packet: {result['packet_id']}")
            print(f"  Attempt: {result['attempt']}")
            print(f"  Registry status: {result['registry_status']}")
            print(f"  Registry reason: {result['registry_reason']}")
            print(f"  Artifacts: {len(result.get('artifact_ids') or [])}")

        sys.exit(0 if result["domain_status"] == "accepted" else 1)

    except Exception as e:
        if args.json:
            _print_json(_json_envelope(
                ok=False,
                command=command,
                errors=[{"code": "RUN_E2E_PACKET_FLOW_FAILED", "message": str(e)}],
            ))
        else:
            print(f"Run E2E packet flow failed: {e}", file=sys.stderr)
        sys.exit(2)


def _cmd_run_handoff(args: argparse.Namespace) -> None:
    """Run verifier-reviewer handoff."""
    command = "run-handoff"
    try:
        from prefect_grace.flows.verifier_reviewer_handoff_flow import verifier_reviewer_handoff_flow

        packet_dir = Path(args.packet_dir)
        packet_file = Path(args.packet)

        # Load coder result
        coder_result_path = Path(args.coder_result)
        if not coder_result_path.exists():
            raise FileNotFoundError(f"Coder result file not found: {coder_result_path}")

        coder_result = json.loads(coder_result_path.read_text(encoding="utf-8"))

        # In dry-run mode, require fake outputs
        if args.dry_run:
            if not args.fake_verifier_output or not args.fake_reviewer_output:
                error_msg = "Dry-run mode requires --fake-verifier-output and --fake-reviewer-output"
                if args.json:
                    _print_json(_json_envelope(
                        ok=False,
                        command=command,
                        errors=[{"code": "MISSING_FAKE_OUTPUTS", "message": error_msg}],
                    ))
                else:
                    print(f"Error: {error_msg}", file=sys.stderr)
                sys.exit(2)

            # Load fake outputs
            fake_verifier_path = Path(args.fake_verifier_output)
            fake_reviewer_path = Path(args.fake_reviewer_output)

            if not fake_verifier_path.exists():
                raise FileNotFoundError(f"Fake verifier output not found: {fake_verifier_path}")
            if not fake_reviewer_path.exists():
                raise FileNotFoundError(f"Fake reviewer output not found: {fake_reviewer_path}")

            fake_verifier_output = fake_verifier_path.read_text(encoding="utf-8")
            fake_reviewer_output = fake_reviewer_path.read_text(encoding="utf-8")

            # Create fake launchers
            def _fake_verifier_launcher(**kwargs):
                return {"raw_output": fake_verifier_output}

            def _fake_reviewer_launcher(**kwargs):
                return {"raw_output": fake_reviewer_output}

            verifier_launcher = _fake_verifier_launcher
            reviewer_launcher = _fake_reviewer_launcher
        else:
            # Live mode: fail with error (no live launcher implementation in MVP)
            error_msg = "Live handoff execution not implemented in MVP. Use --dry-run with fake outputs."
            if args.json:
                _print_json(_json_envelope(
                    ok=False,
                    command=command,
                    errors=[{"code": "LIVE_EXECUTION_NOT_IMPLEMENTED", "message": error_msg}],
                ))
            else:
                print(f"Error: {error_msg}", file=sys.stderr)
            sys.exit(2)

        # Run handoff flow
        result = verifier_reviewer_handoff_flow(
            packet_dir=packet_dir,
            packet_file=packet_file,
            attempt=args.attempt,
            coder_result=coder_result,
            verifier_launcher=verifier_launcher,
            reviewer_launcher=reviewer_launcher,
            project=None,
            dry_run=args.dry_run,
        )

        domain_status = result["domain_status"]

        # Map domain status to exit code
        exit_code_map = {
            "accepted": 0,
            "rework_required": 1,
            "blocked": 2,
            "escalate_to_architect": 2,
            "verifier_failed": 2,
            "reviewer_failed": 2,
            "handoff_error": 2,
        }
        exit_code = exit_code_map.get(domain_status, 2)

        if args.json:
            _print_json(_json_envelope(
                ok=result["ok"],
                command=command,
                result=result,
            ))
        else:
            print(f"Handoff status: {domain_status}")
            print(f"  Packet: {result['packet_id']}")
            print(f"  Attempt: {result['attempt']}")

            verifier = result["verifier"]
            print(f"\nVerifier:")
            print(f"  OK: {verifier['ok']}")
            print(f"  Marker found: {verifier['marker_found']}")
            if verifier['errors']:
                print(f"  Errors: {len(verifier['errors'])}")
                for error in verifier['errors']:
                    print(f"    - {error}")

            reviewer = result.get("reviewer")
            if reviewer:
                print(f"\nReviewer:")
                print(f"  OK: {reviewer['ok']}")
                print(f"  Marker found: {reviewer['marker_found']}")
                if reviewer['errors']:
                    print(f"  Errors: {len(reviewer['errors'])}")
                    for error in reviewer['errors']:
                        print(f"    - {error}")

            if result.get("evidence_manifest_path"):
                print(f"\nEvidence manifest: {result['evidence_manifest_path']}")
            if result.get("review_path"):
                print(f"Review: {result['review_path']}")
            if result.get("rework_path"):
                print(f"Rework: {result['rework_path']}")

        sys.exit(exit_code)

    except Exception as e:
        if args.json:
            _print_json(_json_envelope(
                ok=False,
                command=command,
                errors=[{"code": "RUN_HANDOFF_FAILED", "message": str(e)}],
            ))
        else:
            print(f"Run handoff failed: {e}", file=sys.stderr)
        sys.exit(2)


def _cmd_run_single_live_packet_pilot(args: argparse.Namespace) -> None:
    """Run single live packet pilot with managed runner and Git mutation gate."""
    command = "run-single-live-packet-pilot"

    # Safety check: fail closed on unsafe flag combinations
    if args.execute_agent and not hasattr(args, '_no_dry_run_explicit'):
        error_msg = "Live agent execution requires explicit --no-dry-run flag. Use: --execute-agent --no-dry-run"
        if args.json:
            _print_json(_json_envelope(
                ok=False,
                command=command,
                errors=[{"code": "MISSING_EXPLICIT_NO_DRY_RUN", "message": error_msg}],
            ))
        else:
            print(f"Error: {error_msg}", file=sys.stderr)
        sys.exit(2)

    try:
        from prefect_grace.platform.single_live_packet_pilot import run_single_live_packet_pilot

        result = run_single_live_packet_pilot(
            packet=Path(args.packet),
            repo_root=Path(args.repo_root),
            worktree_root=Path(args.worktree_root),
            project_key=args.project_key,
            attempt=args.attempt,
            base_ref=args.base_ref,
            target_branch=args.target_branch,
            remote=args.remote,
            dry_run=args.dry_run,
            execute_agent=args.execute_agent,
            acknowledge_live_agent=args.i_understand_live_agent,
            opt_in_token=None,  # Read from environment
            commit=args.commit,
            push=args.push,
            merge=args.merge,
            apply_git_mutations=args.apply_git_mutations,
            timeout_seconds=args.timeout_seconds,
        )

        if args.json:
            _print_json(_json_envelope(
                ok=result.ok,
                command=command,
                project_key=args.project_key,
                result=result.to_dict(),
            ))
        else:
            # Text mode
            print(f"Single live packet pilot: {result.status.upper()}")
            print(f"  Packet: {result.packet_id}")
            print(f"  Attempt: {args.attempt}")
            print(f"  Dry run: {result.dry_run}")
            print(f"  Live opt-in confirmed: {result.live_opt_in_confirmed}")
            print(f"  Git mutation requested: {result.git_mutation_requested}")
            print(f"  Live agents started: {result.live_agents_started}")
            print(f"  Prefect runs created: {result.prefect_runs_created}")

            if result.worktree_path:
                print(f"\n  Worktree: {result.worktree_path}")
                print(f"  Branch: {result.branch_name}")

            if result.managed_runner_status:
                print(f"\n  Managed runner status: {result.managed_runner_status}")
            if result.scope_status:
                print(f"  Scope status: {result.scope_status}")
            if result.evidence_status:
                print(f"  Evidence status: {result.evidence_status}")
            if result.review_status:
                print(f"  Review status: {result.review_status}")
            if result.git_gate_status:
                print(f"  Git gate status: {result.git_gate_status}")

            if result.blockers:
                print(f"\n  Blockers ({len(result.blockers)}):")
                for blocker in result.blockers[:5]:
                    print(f"    - {blocker['code']}: {blocker['message']}")

        # Exit codes: 0=ok, 1=blocked, 2=error
        if result.ok:
            sys.exit(0)
        elif result.status == "blocked":
            sys.exit(1)
        else:
            sys.exit(2)

    except Exception as e:
        if args.json:
            _print_json(_json_envelope(
                ok=False,
                command=command,
                errors=[{"code": "RUN_SINGLE_LIVE_PACKET_PILOT_FAILED", "message": str(e)}],
            ))
        else:
            print(f"Run single live packet pilot failed: {e}", file=sys.stderr)
        sys.exit(2)


def _cmd_run_single_live_prefect_packet_pilot(args: argparse.Namespace) -> None:
    """Run one synthetic scratch packet through managed Prefect submission."""
    command = "run-single-live-prefect-packet-pilot"

    if args.execute_agent and not hasattr(args, '_no_dry_run_explicit'):
        error_msg = "Live Prefect pilot requires explicit --no-dry-run flag. Use: --execute-agent --no-dry-run"
        if args.json:
            _print_json(_json_envelope(
                ok=False,
                command=command,
                errors=[{"code": "MISSING_EXPLICIT_NO_DRY_RUN", "message": error_msg}],
            ))
        else:
            print(f"Error: {error_msg}", file=sys.stderr)
        sys.exit(2)

    try:
        from prefect_grace.platform.single_live_prefect_packet_pilot import (
            run_single_live_prefect_packet_pilot,
            create_bounded_prefect_status_reader,
        )

        # Create bounded status reader for live mode
        status_reader = None
        if not args.dry_run:
            status_reader = create_bounded_prefect_status_reader()

        result = run_single_live_prefect_packet_pilot(
            project_config=Path(args.project),
            state_root=Path(args.state_root),
            worktree_root=Path(args.worktree_root),
            packet_root=Path(args.packet_root),
            dry_run=args.dry_run,
            execute_agent=args.execute_agent,
            acknowledge_live_agent=args.i_understand_live_agent,
            opt_in_token=os.environ.get("GRACE_LIVE_PREFECT_PACKET_OPT_IN"),
            timeout_seconds=args.timeout_seconds,
            status_reader=status_reader,
        )

        if args.json:
            _print_json(_json_envelope(
                ok=result.ok,
                command=command,
                project_key=result.project_key,
                result=result.to_dict(),
                warnings=result.warnings,
                errors=result.errors,
            ))
        else:
            print(f"Single live Prefect packet pilot: {'OK' if result.ok else 'FAILED'}")
            print(f"  Project: {result.project_key}")
            print(f"  Dry run: {result.dry_run}")
            print(f"  Selected packet: {result.selected_packet_id or '-'}")
            print(f"  Deployment: {result.deployment_name or '-'}")
            print(f"  Flow run: {result.flow_run_id or '-'}")
            print(f"  Prefect runs created: {result.prefect_runs_created}")
            print(f"  Live agents started: {result.live_agents_started}")
            print(f"  Domain status: {result.domain_status or '-'}")
            print(f"  Scope verdict: {result.scope_verdict or '-'}")
            for error in result.errors[:8]:
                print(f"ERROR: {error}", file=sys.stderr)

        sys.exit(0 if result.ok else 1)
    except Exception as e:
        if args.json:
            _print_json(_json_envelope(
                ok=False,
                command=command,
                errors=[{"code": "RUN_SINGLE_LIVE_PREFECT_PACKET_PILOT_FAILED", "message": str(e)}],
            ))
        else:
            print(f"Run single live Prefect packet pilot failed: {e}", file=sys.stderr)
        sys.exit(2)


def _cmd_run_single_astro_packet_pilot(args: argparse.Namespace) -> None:
    """Run one low-risk Astro packet through managed Prefect submission."""
    command = "run-single-astro-packet-pilot"

    if args.execute_agent and not hasattr(args, '_no_dry_run_explicit'):
        error_msg = "Astro packet pilot requires explicit --no-dry-run flag. Use: --execute-agent --no-dry-run"
        if args.json:
            _print_json(_json_envelope(
                ok=False,
                command=command,
                errors=[{"code": "MISSING_EXPLICIT_NO_DRY_RUN", "message": error_msg}],
            ))
        else:
            print(f"Error: {error_msg}", file=sys.stderr)
        sys.exit(2)

    try:
        from prefect_grace.platform.single_astro_packet_pilot import (
            run_single_astro_packet_pilot,
            create_bounded_prefect_status_reader,
        )

        status_reader = None
        if not args.dry_run:
            status_reader = create_bounded_prefect_status_reader()

        result = run_single_astro_packet_pilot(
            project_path=Path(args.project),
            state_root=Path(args.state_root),
            worktree_root=Path(args.worktree_root),
            packet_root=Path(args.packet_root),
            dry_run=args.dry_run,
            execute_agent=args.execute_agent,
            acknowledge_live_agent=args.i_understand_live_agent,
            opt_in_token=os.environ.get("GRACE_ASTRO_PACKET_OPT_IN"),
            timeout_seconds=args.timeout_seconds,
            packet_id=args.packet,
            status_reader=status_reader,
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
            print(f"Single Astro packet pilot: {'OK' if result.ok else 'FAILED'}")
            print(f"  Project: {result.project_key}")
            print(f"  Dry run: {result.dry_run}")
            print(f"  Selected packet: {result.selected_packet_id or '-'}")
            print(f"  Deployment: {result.deployment_name or '-'}")
            print(f"  Flow run: {result.flow_run_id or '-'}")
            print(f"  Prefect runs created: {result.prefect_runs_created}")
            print(f"  Live agents started: {result.live_agents_started}")
            print(f"  Domain status: {result.domain_status or '-'}")
            print(f"  Scope verdict: {result.scope_verdict or '-'}")
            for error in result.errors[:8]:
                print(f"ERROR: {error}", file=sys.stderr)

        sys.exit(0 if result.ok else 1)
    except Exception as e:
        if args.json:
            _print_json(_json_envelope(
                ok=False,
                command=command,
                errors=[{"code": "RUN_SINGLE_ASTRO_PACKET_PILOT_FAILED", "message": str(e)}],
            ))
        else:
            print(f"Run single Astro packet pilot failed: {e}", file=sys.stderr)
        sys.exit(2)
