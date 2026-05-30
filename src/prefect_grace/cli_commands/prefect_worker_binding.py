# ############################################################################
# AI_HEADER: prefect_worker_binding
# ROLE: CLI command handler for Prefect worker binding preflight checks.
# ############################################################################

# START_MODULE_CONTRACT
# purpose: Expose Prefect worker binding validation through the GRACE CLI.
# inputs: argparse Namespace.
# returns: None.
# side_effects: Prints JSON/text; validates Prefect infrastructure readiness.
# emitted_logs: None.
# error_behavior: Exits 0 for ready, 1 for blocked, 2 for command errors.
# END_MODULE_CONTRACT

# START_MODULE_MAP
# mapping:
#   - function: _cmd_prefect_worker_binding
# END_MODULE_MAP

from __future__ import annotations

import json
import os
import sys
from pathlib import Path


def _cmd_prefect_worker_binding(args):
    """Run Prefect worker binding preflight check."""
    from prefect_grace.platform.prefect_worker_binding import run_prefect_worker_binding_preflight
    from prefect_grace.platform.runtime_adapter import create_prefect_sync_client

    # Determine dry-run mode: default to True unless --apply is specified
    dry_run = not args.apply if hasattr(args, 'apply') else True

    # Check approval gates for apply mode
    approval_token = os.environ.get("GRACE_PREFECT_BINDING_APPROVED")

    # When --apply-deployment is used in live mode (not dry-run), enforce approval gates
    if args.apply_deployment and not dry_run:
        if not args.i_understand_prefect_mutation:
            print("ERROR: --apply-deployment requires --i-understand-prefect-mutation", file=sys.stderr)
            sys.exit(2)
        if approval_token != "deployment":
            print("ERROR: --apply-deployment requires GRACE_PREFECT_BINDING_APPROVED=deployment", file=sys.stderr)
            sys.exit(2)

    # Create Prefect client for live validation
    # Returns None if Prefect unavailable (fail-closed)
    prefect_client = create_prefect_sync_client()

    # Run preflight with client (or None if Prefect unavailable)
    result = run_prefect_worker_binding_preflight(
        project_config=args.project,
        dry_run=dry_run,
        apply_deployment=args.apply_deployment,
        acknowledge_prefect_mutation=args.i_understand_prefect_mutation,
        approval_token=approval_token,
        run_worker_smoke=args.run_worker_smoke,
        prefect_client=prefect_client,
    )

    # Output
    if args.json:
        envelope = {
            "ok": result.ok,
            "project_key": result.project_key,
            "command": "prefect-worker-binding",
            "result": result.to_dict(),
            "data": result.to_dict(),
            "warnings": result.warnings,
            "errors": [e["message"] for e in result.errors],
        }
        print(json.dumps(envelope, indent=2))
    else:
        # Human-readable output
        print(f"Prefect Worker Binding Preflight - Project: {result.project_key}")
        print(f"Mode: {'DRY-RUN' if result.dry_run else 'LIVE'}")
        print()

        print(f"Prefect API: {result.prefect_api_url}")
        print(f"  Version: {result.prefect_version or 'N/A'}")
        print(f"  Healthy: {result.server_healthy}")
        print()

        print(f"Work Pool: {result.work_pool_name}")
        print(f"  Status: {result.work_pool_status or 'NOT FOUND'}")
        print(f"  Type: {result.work_pool_type or 'N/A'}")
        print()

        print("Queues:")
        for queue_name in result.required_queues:
            status = result.queue_statuses.get(queue_name, {})
            exists = status.get("exists", False)
            queue_status = status.get("status", "NOT FOUND")
            print(f"  {queue_name}: {queue_status if exists else 'NOT FOUND'}")
        print()

        print(f"Deployment: {result.deployment_name}")
        print(f"  Exists: {result.deployment_exists}")
        if result.deployment_exists:
            print(f"  Work Pool: {result.deployment_work_pool_name}")
            print(f"  Work Queue: {result.deployment_work_queue_name}")
            print(f"  Parameters Valid: {result.deployment_parameters_valid}")
        print(f"  Mutation: {result.deployment_mutation}")
        print()

        print("Side Effects:")
        print(f"  Prefect Runs Created: {result.prefect_runs_created}")
        print(f"  Live Agents Started: {result.live_agents_started}")
        print()

        if result.warnings:
            print("Warnings:")
            for warning in result.warnings:
                print(f"  - {warning}")
            print()

        if result.errors:
            print("Errors:")
            for error in result.errors:
                print(f"  - {error['message']}")
            print()

        print(f"Ready for Live Packet: {result.ok}")

    # Exit code
    if result.ok:
        sys.exit(0)
    elif result.errors:
        sys.exit(1)
    else:
        sys.exit(2)
