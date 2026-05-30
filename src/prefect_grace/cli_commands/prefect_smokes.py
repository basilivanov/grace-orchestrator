# ############################################################################
# AI_HEADER: prefect_smokes
# ROLE: Execution of synthetic, dry-run, and batch Prefect smokes.
# ############################################################################

# START_MODULE_CONTRACT
# purpose: Run pipeline smokes, real dry-runs, batch smokes, and nightly verification.
# inputs: CLI argparse Namespace.
# returns: None.
# side_effects: Submits smoke runs, reads/writes project/state data, prints status.
# emitted_logs: None.
# error_behavior: Exits with appropriate status code (0/1/2) depending on smoke result.
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
    _load_adapter_from_args,
)


def _cmd_registry_apply_smoke(args: argparse.Namespace) -> None:
    command = "registry-apply-smoke"
    try:
        from prefect_grace.platform.registry_apply_smoke import run_registry_apply_smoke

        result = run_registry_apply_smoke(
            project_config=Path(args.project),
            state_root=Path(args.state_root),
            packet_root=Path(args.packet_root) if args.packet_root else None,
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
            print(f"Registry apply smoke for {result.project_key}: {'OK' if result.ok else 'FAILED'}")
            print(f"  State root: {result.state_root}")
            print(f"  Bootstrap apply count: {result.bootstrap_apply_count}")
            print(f"  Cases: {sum(1 for case in result.cases if case.ok)}/{len(result.cases)}")
            print(f"  Prefect runs created: {result.prefect_runs_created}")

        if not result.ok:
            sys.exit(1)
    except Exception as e:
        if args.json:
            _print_json(_json_envelope(
                ok=False,
                command=command,
                errors=[{"code": "REGISTRY_APPLY_SMOKE_FAILED", "message": str(e)}],
            ))
        else:
            print(f"Registry apply smoke failed: {e}", file=sys.stderr)
        sys.exit(1)


def _cmd_registry_source_integrity_audit(args: argparse.Namespace) -> None:
    command = "registry-source-integrity-audit"
    try:
        from prefect_grace.platform.registry_source_integrity_audit import (
            audit_registry_source_integrity,
        )

        result = audit_registry_source_integrity(
            project_config=Path(args.project) if args.project else None,
            max_items=int(getattr(args, "max_items", 50)),
        )
        payload = result.to_dict()

        if args.json:
            warning_issues = [issue for issue in result.issues if issue.get("severity") == "warning"]
            blocking_issues = [issue for issue in result.issues if issue.get("severity") == "blocking"]
            _print_json(_json_envelope(
                ok=result.ok,
                command=command,
                project_key=result.project_key,
                result=payload,
                warnings=warning_issues,
                errors=[] if result.ok else blocking_issues,
            ))
        else:
            print(f"Registry source integrity audit for {result.project_key}: {'OK' if result.ok else 'FAILED'}")
            print(f"  Accepted checked: {result.checked_total}")
            print(f"  Blocking issues: {result.blocking_issue_total}")
            print(f"  Warning issues: {result.warning_issue_total}")
            if result.issue_counts:
                print("  Issue counts:")
                for code, count in result.issue_counts.items():
                    print(f"    - {code}: {count}")

        if not result.ok:
            sys.exit(1)
    except Exception as e:
        if args.json:
            _print_json(_json_envelope(
                ok=False,
                command=command,
                errors=[{"code": "REGISTRY_SOURCE_INTEGRITY_AUDIT_FAILED", "message": str(e)}],
            ))
        else:
            print(f"Registry source integrity audit failed: {e}", file=sys.stderr)
        sys.exit(1)


def _cmd_run_e2e_registry_seeded_smoke(args: argparse.Namespace) -> None:
    command = "run-e2e-registry-seeded-smoke"
    try:
        from prefect_grace.platform.e2e_runner_registry_seeded_smoke import (
            run_e2e_runner_registry_seeded_smoke,
        )

        result = run_e2e_runner_registry_seeded_smoke(
            project_config=Path(args.project),
            state_root=Path(args.state_root),
            worktree_root=Path(args.worktree_root),
            packet_root=Path(args.packet_root),
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
            print(f"E2E registry-seeded smoke for {result.project_key}: {'OK' if result.ok else 'FAILED'}")
            print(f"  State root: {result.state_root}")
            print(f"  Worktree root: {result.worktree_root}")
            print(f"  Packet root: {result.packet_root}")
            print(f"  Selected packet: {result.selected_packet_id or '-'}")
            print(f"  Bootstrap apply count: {result.bootstrap_apply_count}")
            print(f"  Prefect runs created: {result.prefect_runs_created}")
            print(f"  Live agents started: {result.live_agents_started}")

        if not result.ok:
            sys.exit(1)
    except Exception as e:
        if args.json:
            _print_json(_json_envelope(
                ok=False,
                command=command,
                errors=[{"code": "E2E_REGISTRY_SEEDED_SMOKE_FAILED", "message": str(e)}],
            ))
        else:
            print(f"E2E registry-seeded smoke failed: {e}", file=sys.stderr)
        sys.exit(1)


def _cmd_run_prefect_e2e_live_smoke(args: argparse.Namespace) -> None:
    command = "run-prefect-e2e-live-smoke"
    try:
        from prefect_grace.platform.prefect_e2e_live_smoke import run_prefect_e2e_live_smoke

        _submitter = None
        if getattr(args, "offline_fake_submitter", False):
            def _submitter(**kwargs):
                packet_id = str(kwargs["parameters"].get("packet_id") or "unknown")
                return {
                    "flow_run_id": f"fake-live-smoke-{packet_id}",
                    "flow_run_name": f"e2e-packet:{packet_id}:attempt-1",
                    "deployment_name": "prefect-grace-e2e-packet-runner/live-e2e-packet-runner",
                    "work_queue_name": "grace-live",
                    "runner_kind": "e2e",
                    "status": "submitted",
                    "url": "http://prefect.local/flow-runs/fake-live-smoke",
                }

        result = run_prefect_e2e_live_smoke(
            project_config=Path(args.project_config),
            state_root=Path(args.state_root),
            worktree_root=Path(args.worktree_root),
            packet_root=Path(args.packet_root),
            dry_run=bool(args.dry_run),
            execute_agent=bool(args.execute_agent),
            allow_live_agent_smoke=bool(args.allow_live_agent_smoke),
            limit=int(getattr(args, "limit", 1)),
            submitter=_submitter,
        )

        if args.json:
            _print_json(_json_envelope(
                ok=result.ok,
                command=command,
                project_key=None,
                result=result.to_dict(),
                errors=result.errors,
            ))
        else:
            print(f"Prefect E2E live smoke: {result.status}")
            print(f"  Packet: {result.packet_id}")
            print(f"  Deployment: {result.deployment_name}")
            print(f"  Runner: {result.runner_kind}")
            print(f"  Submitted: {result.submitted}")
            if result.flow_run_id:
                print(f"  Flow run: {result.flow_run_id}")
        sys.exit(0 if result.ok else 1)
    except Exception as e:
        if args.json:
            _print_json(_json_envelope(
                ok=False,
                command=command,
                errors=[{"code": "SMOKE_FAILED", "message": str(e)}],
            ))
        else:
            print(f"Prefect E2E live smoke failed: {e}", file=sys.stderr)
        sys.exit(2)


def _cmd_run_prefect_e2e_batch_smoke(args: argparse.Namespace) -> None:
    command = "run-prefect-e2e-batch-smoke"
    try:
        from prefect_grace.platform.prefect_e2e_batch_smoke import (
            PrefectE2EBatchSmokeResult,
            run_prefect_e2e_batch_smoke,
        )
        from prefect_grace.tasks.prefect_submitter import E2E_PACKET_DEPLOYMENT_NAME

        batch_size = int(args.batch_size)
        if bool(getattr(args, "execute_agent", False)):
            result = PrefectE2EBatchSmokeResult(
                ok=False,
                mode="prefect_agent_dry_run",
                batch_size=batch_size,
                runner_kind="e2e",
                deployment_name=E2E_PACKET_DEPLOYMENT_NAME,
                work_queue_name=None,
                packets_planned=[],
                packets_submitted=[],
                records=[],
                errors=[{
                    "code": "BATCH_LIVE_AGENT_UNSUPPORTED",
                    "message": "Batch live-agent smoke is out of scope; omit --execute-agent.",
                }],
            )
        else:
            _submitter = None
            if getattr(args, "offline_fake_submitter", False):
                def _submitter(**kwargs):
                    packet_id = str(kwargs["parameters"].get("packet_id") or "unknown")
                    return {
                        "flow_run_id": f"fake-batch-smoke-{packet_id}",
                        "flow_run_name": f"e2e-packet:{packet_id}:attempt-1",
                        "deployment_name": E2E_PACKET_DEPLOYMENT_NAME,
                        "work_queue_name": "grace-live",
                        "runner_kind": "e2e",
                        "status": "submitted",
                        "url": f"http://prefect.local/flow-runs/fake-batch-smoke-{packet_id}",
                    }

            result = run_prefect_e2e_batch_smoke(
                project_config=Path(args.project_config),
                state_root=Path(args.state_root),
                worktree_root=Path(args.worktree_root),
                packet_root=Path(args.packet_root),
                batch_size=batch_size,
                submitter=_submitter,
            )

        if args.json:
            _print_json(_json_envelope(
                ok=result.ok,
                command=command,
                project_key=None,
                result=result.to_dict(),
                errors=result.errors,
            ))
        else:
            print("Prefect E2E batch smoke:")
            print(f"  Batch size: {result.batch_size}")
            print(f"  Submitted: {len(result.packets_submitted)}")
            print(f"  Deployment: {result.deployment_name}")
            print(f"  Queue: {result.work_queue_name or '-'}")
            for record in result.records:
                print(f"  Packet: {record.get('packet_id')} -> {record.get('flow_run_id')}")
            for error in result.errors:
                print(f"ERROR: {error}", file=sys.stderr)
        sys.exit(0 if result.ok else 1)
    except Exception as e:
        if args.json:
            _print_json(_json_envelope(
                ok=False,
                command=command,
                errors=[{"code": "BATCH_SMOKE_FAILED", "message": str(e)}],
            ))
        else:
            print(f"Prefect E2E batch smoke failed: {e}", file=sys.stderr)
        sys.exit(2)


def _cmd_run_prefect_e2e_real_dry_run_smoke(args: argparse.Namespace) -> None:
    command = "run-prefect-e2e-real-dry-run-smoke"
    try:
        from prefect_grace.platform.prefect_e2e_real_dry_run_smoke import (
            PrefectE2ERealDryRunSmokeResult,
            run_prefect_e2e_real_dry_run_smoke,
        )
        from prefect_grace.tasks.prefect_submitter import E2E_PACKET_DEPLOYMENT_NAME

        if bool(getattr(args, "execute_agent", False)):
            result = PrefectE2ERealDryRunSmokeResult(
                ok=False,
                mode="prefect_real_e2e_agent_dry_run",
                packet_id="FEAT-GRACE-PREFECT-REAL-E2E-DRY-RUN-SMOKE-MVP-W01-REAL-E2E-DRY-RUN-SMOKE",
                runner_kind="e2e",
                deployment_name=E2E_PACKET_DEPLOYMENT_NAME,
                work_queue_name=None,
                flow_run_id=None,
                flow_run_name=None,
                flow_run_url=None,
                submitted=False,
                waited=False,
                prefect_state_type=None,
                prefect_state_name=None,
                domain_status=None,
                artifact_ids=[],
                errors=[{
                    "code": "REAL_DRY_RUN_EXECUTE_AGENT_REJECTED",
                    "message": "Real E2E dry-run smoke forbids live agent execution.",
                }],
            )
        else:
            result = run_prefect_e2e_real_dry_run_smoke(
                project_config=Path(args.project_config),
                state_root=Path(args.state_root),
                worktree_root=Path(args.worktree_root),
                packet_root=Path(args.packet_root),
                timeout_seconds=int(args.timeout_seconds),
                poll_interval_seconds=int(args.poll_interval_seconds),
                wait=not bool(args.no_wait),
                execute_agent=False,
            )

        if args.json:
            _print_json(_json_envelope(
                ok=result.ok,
                command=command,
                project_key=None,
                result=result.to_dict(),
                errors=result.errors,
            ))
        else:
            print("Prefect real E2E dry-run smoke:")
            print(f"  Submitted: {result.submitted}")
            print(f"  Packet: {result.packet_id}")
            print(f"  Deployment: {result.deployment_name}")
            print(f"  Queue: {result.work_queue_name or '-'}")
            print(f"  Flow run: {result.flow_run_id or '-'}")
            print(f"  URL: {result.flow_run_url or '-'}")
            print(f"  Waited: {result.waited}")
            print(f"  Prefect state: {result.prefect_state_name or '-'} ({result.prefect_state_type or '-'})")
            print(f"  Domain status: {result.domain_status or '-'}")
            for error in result.errors:
                print(f"ERROR: {error}", file=sys.stderr)
        sys.exit(0 if result.ok else 1)
    except Exception as e:
        if args.json:
            _print_json(_json_envelope(
                ok=False,
                command=command,
                errors=[{"code": "REAL_DRY_RUN_SMOKE_FAILED", "message": str(e)}],
            ))
        else:
            print(f"Prefect real E2E dry-run smoke failed: {e}", file=sys.stderr)
        sys.exit(2)


def _cmd_run_nightly(args: argparse.Namespace) -> None:
    command = "run-nightly"
    try:
        if bool(getattr(args, "execute", False)):
            result = {
                "mode": "nightly_dry_run",
                "until_blocked": bool(args.until_blocked),
                "submitted": [],
                "side_effects": {
                    "registry_updates": 0,
                    "prefect_runs_created": 0,
                    "live_agents_started": 0,
                    "source_files_changed": 0,
                },
            }
            errors = [
                {
                    "code": "NIGHTLY_EXECUTION_NOT_ENABLED",
                    "message": "Real nightly execution is not enabled in this packet.",
                }
            ]
            if args.json:
                _print_json(_json_envelope(
                    ok=False,
                    command=command,
                    result=result,
                    errors=errors,
                ))
            else:
                print(errors[0]["message"], file=sys.stderr)
            sys.exit(1)

        from prefect_grace.platform.nightly_dry_run_controller import run_nightly_dry_run

        result_obj = run_nightly_dry_run(
            project_config=getattr(args, "project", None),
            until_blocked=bool(args.until_blocked),
        )
        result = result_obj.to_dict()
        if args.json:
            _print_json(_json_envelope(
                ok=result_obj.ok,
                command=command,
                project_key=result_obj.project_key or None,
                result=result,
                warnings=result_obj.warnings,
                errors=result_obj.errors,
            ))
        else:
            print(f"Nightly dry-run for {result_obj.project_key}: {result_obj.preflight_status}")
            print(f"  Would submit: {result_obj.plan.get('would_submit_total', 0)}")
            print(f"  Stop reason: {result_obj.plan.get('stop_reason') or '-'}")
        if result_obj.errors:
            sys.exit(1)
    except Exception as e:
        if args.json:
            _print_json(_json_envelope(
                ok=False,
                command=command,
                errors=[{"code": "NIGHTLY_FAILED", "message": str(e)}],
            ))
        else:
            print(f"Nightly failed: {e}", file=sys.stderr)
        sys.exit(1)


def _cmd_nightly_preflight_risk_report(args: argparse.Namespace) -> None:
    command = "nightly-preflight-risk-report"
    try:
        from prefect_grace.platform.nightly_preflight_risk_report import generate_nightly_preflight_risk_report

        result_obj = generate_nightly_preflight_risk_report(
            project_config=getattr(args, "project", None),
        )
        result = result_obj.to_dict()
        if args.json:
            _print_json(_json_envelope(
                ok=result_obj.ok,
                command=command,
                project_key=result_obj.project_key or None,
                result=result,
                warnings=result_obj.warnings,
                errors=result_obj.errors,
            ))
        else:
            print(f"Nightly preflight risk report for {result_obj.project_key}:")
            print(f"  Packets total: {result_obj.packets_total}")
            print(f"  Ready: {result_obj.ready_total}")
            print(f"  Blocked: {result_obj.blocked_total}")
            print(f"  Accepted: {result_obj.accepted_total}")
            print(f"  Safe candidates: {result_obj.safe_candidates_total}")
            print(f"  Risky candidates: {result_obj.risky_candidates_total}")
            print(f"  Blocked candidates: {result_obj.blocked_candidates_total}")
            print(f"  Approval required: {result_obj.approval_required_candidates_total}")
            print(f"  Conflict groups: {result_obj.conflict_groups_total}")
        if result_obj.errors:
            sys.exit(1)
    except Exception as e:
        if args.json:
            _print_json(_json_envelope(
                ok=False,
                command=command,
                errors=[{"code": "PREFLIGHT_RISK_REPORT_FAILED", "message": str(e)}],
            ))
        else:
            print(f"Nightly preflight risk report failed: {e}", file=sys.stderr)
        sys.exit(1)


def _cmd_nightly_select_batch(args: argparse.Namespace) -> None:
    command = "nightly-select-batch"
    try:
        from prefect_grace.platform.nightly_batch_selection import select_safe_batch

        result_obj = select_safe_batch(
            project_config=getattr(args, "project", None),
            preflight_report_path=getattr(args, "preflight_report", None),
            max_packets=int(getattr(args, "max_packets", 10)),
            max_cost=getattr(args, "max_cost", "live_required"),
            allow_conflicts=bool(getattr(args, "allow_conflicts", False)),
            allow_risky=bool(getattr(args, "allow_risky", False)),
        )
        result = result_obj.to_dict()
        if args.json:
            _print_json(_json_envelope(
                ok=result_obj.ok,
                command=command,
                project_key=result_obj.project_key or None,
                result=result,
                warnings=result_obj.warnings,
                errors=result_obj.errors,
            ))
        else:
            print(f"Nightly batch selection for {result_obj.project_key}:")
            print(f"  Selected: {result_obj.selected_total}")
            print(f"  Excluded: {result_obj.excluded_total}")
            print(f"  Batch limit: {result_obj.batch_limits.max_packets}")
            print(f"  Max cost: {result_obj.batch_limits.max_cost}")
            print(f"  Estimated total cost: {result_obj.estimated_total_cost}")
            print(f"  Stop reason: {result_obj.stop_reason}")
            print(f"  Conflict groups detected: {result_obj.conflict_groups_detected}")
            if result_obj.selected_packets:
                print(f"  Selected packets:")
                for pid in result_obj.selected_packets[:10]:
                    print(f"    - {pid}")
            if result_obj.excluded_packets:
                print(f"  Excluded packets (showing first 5):")
                for excluded in result_obj.excluded_packets[:5]:
                    print(f"    - {excluded.packet_id}: {excluded.reason}")
        if result_obj.errors:
            sys.exit(1)
    except Exception as e:
        if args.json:
            _print_json(_json_envelope(
                ok=False,
                command=command,
                errors=[{"code": "BATCH_SELECTION_FAILED", "message": str(e)}],
            ))
        else:
            print(f"Nightly batch selection failed: {e}", file=sys.stderr)
        sys.exit(1)


def _cmd_nightly_recheck_batch(args: argparse.Namespace) -> None:
    command = "nightly-recheck-batch"
    try:
        from prefect_grace.platform.nightly_batch_recheck import recheck_nightly_batch

        result_obj = recheck_nightly_batch(
            project_config=getattr(args, "project", None),
            selection_path=getattr(args, "selection", None),
            max_packets=int(getattr(args, "max_packets", 10)),
            max_cost=getattr(args, "max_cost", "live_required"),
            allow_conflicts=bool(getattr(args, "allow_conflicts", False)),
            allow_risky=bool(getattr(args, "allow_risky", False)),
        )
        result = result_obj.to_dict()
        if args.json:
            _print_json(_json_envelope(
                ok=result_obj.ok,
                command=command,
                project_key=result_obj.project_key or None,
                result=result,
                warnings=result_obj.warnings,
                errors=result_obj.errors,
            ))
        else:
            print(f"Nightly batch recheck for {result_obj.project_key}: {result_obj.preflight_status}")
            print(f"  Selected: {result_obj.selected_total}")
            print(f"  Confirmed: {result_obj.confirmed_total}")
            print(f"  Blocked: {result_obj.blocked_total}")
            print(f"  Blocker classes: {', '.join(result_obj.blocker_classes) or '-'}")
            print(f"  Plan hash: {result_obj.plan_hash or '-'}")
            print(f"  Recheck hash: {result_obj.recheck_hash or '-'}")
            print(f"  Lock acquired: {result_obj.lock_status.get('acquired')}")
            print(f"  Lock released: {result_obj.lock_status.get('released')}")
        if not result_obj.ok:
            sys.exit(1)
    except Exception as e:
        if args.json:
            _print_json(_json_envelope(
                ok=False,
                command=command,
                errors=[{"code": "NIGHTLY_BATCH_RECHECK_FAILED", "message": str(e)}],
            ))
        else:
            print(f"Nightly batch recheck failed: {e}", file=sys.stderr)
        sys.exit(1)


def _cmd_nightly_batch_execute(args: argparse.Namespace) -> None:
    command = "nightly-batch-execute"
    try:
        from prefect_grace.platform.nightly_batch_execution_guard import execute_batch_with_guard

        # Determine dry_run mode
        dry_run = not bool(getattr(args, "execute", False))

        result_obj = execute_batch_with_guard(
            project_config=getattr(args, "project", None),
            max_packets=int(getattr(args, "max_packets", 10)),
            concurrency=int(getattr(args, "concurrency", 1)),
            timeout_seconds_per_packet=int(getattr(args, "timeout_seconds_per_packet", 3600)),
            max_failures=int(getattr(args, "max_failures", 3)),
            stop_on_degradation=not bool(getattr(args, "no_stop_on_degradation", False)),
            allow_git_commit=bool(getattr(args, "allow_git_commit", False)),
            allow_git_push=bool(getattr(args, "allow_git_push", False)),
            allow_git_merge=False,
            dry_run=dry_run,
            execute=bool(getattr(args, "execute", False)),
            acknowledge_live_batch=bool(getattr(args, "i_understand_live_batch", False)),
            opt_in_token=None,  # Read from environment
            base_ref=getattr(args, "base_ref", "origin/master"),
            target_branch=getattr(args, "target_branch", "master"),
            remote=getattr(args, "remote", "origin"),
        )
        result = result_obj.to_dict()
        if args.json:
            _print_json(_json_envelope(
                ok=result_obj.ok,
                command=command,
                project_key=result_obj.project_key or None,
                result=result,
                warnings=result_obj.warnings,
                errors=result_obj.errors,
            ))
        else:
            print(f"Nightly batch execution for {result_obj.project_key}:")
            print(f"  Mode: {'live' if not result_obj.dry_run else 'dry-run'}")
            print(f"  Selected: {result_obj.selected_total}")
            print(f"  Executed: {result_obj.executed_total}")
            print(f"  Passed: {result_obj.passed_total}")
            print(f"  Blocked: {result_obj.blocked_total}")
            print(f"  Failed: {result_obj.failed_total}")
            print(f"  Skipped: {result_obj.skipped_total}")
            print(f"  Stop reason: {result_obj.stop_reason}")
            print(f"  Lock acquired: {result_obj.lock_acquired}")
            print(f"  Lock released: {result_obj.lock_released}")
            print(f"  Live agents started: {result_obj.live_agents_started}")
            print(f"  Git mutations: {result_obj.git_mutations_count}")
            print(f"  Execution time: {result_obj.execution_time_seconds:.2f}s")
            if result_obj.packet_summaries:
                print(f"  Packet summaries (showing first 10):")
                for summary in result_obj.packet_summaries[:10]:
                    print(f"    - {summary.packet_id}: {summary.status}")
        if result_obj.errors or not result_obj.ok:
            sys.exit(1)
    except Exception as e:
        if args.json:
            _print_json(_json_envelope(
                ok=False,
                command=command,
                errors=[{"code": "BATCH_EXECUTION_FAILED", "message": str(e)}],
            ))
        else:
            print(f"Nightly batch execution failed: {e}", file=sys.stderr)
        sys.exit(1)


def _cmd_run_nightly_controlled_batch(args: argparse.Namespace) -> None:
    command = "run-nightly-controlled-batch"
    try:
        from prefect_grace.platform.nightly_controlled_batch_run import run_nightly_controlled_batch

        dry_run = not bool(getattr(args, "execute", False))
        result_obj = run_nightly_controlled_batch(
            project_config=getattr(args, "project", None),
            selection_path=getattr(args, "selection", None),
            max_packets=int(getattr(args, "max_packets", 3)),
            concurrency=int(getattr(args, "concurrency", 1)),
            timeout_seconds_per_packet=int(getattr(args, "timeout_seconds_per_packet", 1800)),
            max_failures=int(getattr(args, "max_failures", 1)),
            stop_on_degradation=not bool(getattr(args, "no_stop_on_degradation", False)),
            allow_git_commit=bool(getattr(args, "allow_git_commit", False)),
            allow_git_push=bool(getattr(args, "allow_git_push", False)),
            dry_run=dry_run,
            execute=bool(getattr(args, "execute", False)),
            acknowledge_live_batch=bool(getattr(args, "i_understand_live_batch", False)),
            opt_in_token=None,
        )
        result = result_obj.to_dict()
        if args.json:
            _print_json(_json_envelope(
                ok=result_obj.ok,
                command=command,
                project_key=result_obj.project_key or None,
                result=result,
                warnings=result_obj.warnings,
                errors=result_obj.errors,
            ))
        else:
            print(f"Nightly controlled batch for {result_obj.project_key}:")
            print(f"  Mode: {'live' if not result_obj.dry_run else 'dry-run'}")
            print(f"  Selected: {result_obj.selected_total}")
            print(f"  Confirmed: {result_obj.confirmed_total}")
            print(f"  Executed: {result_obj.executed_total}")
            print(f"  Stop reason: {result_obj.stop_reason}")
            print(f"  Lock acquired: {result_obj.lock_acquired}")
            print(f"  Lock released: {result_obj.lock_released}")
            print(f"  Live agents started: {result_obj.live_agents_started}")
            print(f"  Prefect runs created: {result_obj.prefect_runs_created}")
            print(f"  Git mutations: {result_obj.git_mutations_count}")
        if result_obj.errors or not result_obj.ok:
            sys.exit(1)
    except Exception as e:
        if args.json:
            _print_json(_json_envelope(
                ok=False,
                command=command,
                errors=[{"code": "CONTROLLED_BATCH_RUN_FAILED", "message": str(e)}],
            ))
        else:
            print(f"Nightly controlled batch failed: {e}", file=sys.stderr)
        sys.exit(1)
