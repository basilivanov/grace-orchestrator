# ############################################################################
# AI_HEADER: project_registry
# ROLE: Project configuration, packet scanning, and backlog synchronizer commands.
# ############################################################################

# START_MODULE_CONTRACT
# purpose: Validate, scan, sync, and bootstrap the project backlog registry.
# inputs: CLI argparse Namespace.
# returns: None.
# side_effects: Reads/writes project config and state files, prints outputs to stdout.
# emitted_logs: None.
# error_behavior: Raises Exceptions, exits process with appropriate status codes on failure.
# END_MODULE_CONTRACT

# START_MODULE_MAP
# mapping:
# END_MODULE_MAP

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from prefect_grace.platform.project_adapter import load_project_adapter
from prefect_grace.platform.verification_profile import load_verification_profiles
from prefect_grace.platform.packet_parser import parse_packet_markdown
from prefect_grace.platform.state_store import PacketRegistryStore, RunStore, ExecutorHistoryStore
from prefect_grace.cli_commands.common import (
    _json_envelope,
    _print_json,
    _profile_config_path,
    _load_adapter_from_args,
    _packet_to_dict,
    _scan_project_packets,
)


def _cmd_validate_project(args: argparse.Namespace) -> None:
    command = "validate-project"
    try:
        adapter = _load_adapter_from_args(args)
        profiles = load_verification_profiles(_profile_config_path(getattr(args, "project", None)))
        if args.json:
            _print_json(_json_envelope(
                ok=True,
                command=command,
                project_key=adapter.project_key,
                result={
                    "project": adapter.to_dict(),
                    "verification_profiles": profiles
                },
            ))
        else:
            print("Project configuration and verification profiles are valid.")
    except Exception as e:
        if args.json:
            _print_json(_json_envelope(
                ok=False,
                command=command,
                errors=[{"code": "VALIDATION_FAILED", "message": str(e)}],
            ))
            sys.exit(1)
        else:
            print(f"Validation failed: {e}", file=sys.stderr)
            sys.exit(1)


def _cmd_scan_packets(args: argparse.Namespace) -> None:
    command = "scan-packets"
    try:
        adapter = _load_adapter_from_args(args)
        mode = args.mode or "legacy_warn"
        packets_data, all_warnings, errors = _scan_project_packets(adapter, mode=mode)

        if errors:
            if args.json:
                _print_json(_json_envelope(
                    ok=False,
                    command=command,
                    project_key=adapter.project_key,
                    warnings=all_warnings,
                    errors=errors,
                ))
                sys.exit(1)
            else:
                for err in errors:
                    print(err["message"], file=sys.stderr)
                sys.exit(1)

        if args.json:
            _print_json(_json_envelope(
                ok=True,
                command=command,
                project_key=adapter.project_key,
                result={
                    "packets": packets_data
                },
                warnings=all_warnings,
            ))
        else:
            print(f"Successfully scanned {len(packets_data)} packets.")
            if all_warnings:
                print(f"Collected {len(all_warnings)} warnings:")
                for w in all_warnings:
                    print(f" - {w}")
    except Exception as e:
        if args.json:
            _print_json(_json_envelope(
                ok=False,
                command=command,
                errors=[{"code": "SCAN_FAILED", "message": str(e)}],
            ))
            sys.exit(1)
        else:
            print(f"Scan failed: {e}", file=sys.stderr)
            sys.exit(1)


def _cmd_validate_packet(args: argparse.Namespace) -> None:
    command = "validate-packet"
    try:
        mode = "strict" if args.strict else "legacy_warn"
        path = Path(args.path)
        if not path.exists():
            raise FileNotFoundError(f"Packet file not found at {path}")

        parsed = parse_packet_markdown(path, mode=mode)
        if args.json:
            _print_json(_json_envelope(
                ok=True,
                command=command,
                result=_packet_to_dict(parsed, path=path),
                warnings=parsed.legacy_warnings,
            ))
        else:
            print(f"Packet {parsed.packet_id} is valid.")
            if parsed.legacy_warnings:
                print("Warnings:")
                for w in parsed.legacy_warnings:
                    print(f" - {w}")
    except Exception as e:
        if args.json:
            _print_json(_json_envelope(
                ok=False,
                command=command,
                errors=[{"code": "PACKET_INVALID", "message": str(e)}],
            ))
            sys.exit(1)
        else:
            print(f"Packet validation failed: {e}", file=sys.stderr)
            sys.exit(1)


def _cmd_sync_packets(args: argparse.Namespace) -> None:
    command = "sync-packets"
    try:
        from prefect_grace.platform.backlog_controller import BacklogController

        adapter = _load_adapter_from_args(args)

        sync_result = BacklogController.sync(
            project=adapter,
            dry_run=args.dry_run,
            retry_blocked=getattr(args, "retry_blocked", False),
            rerun_changed=getattr(args, "rerun_changed", False),
        )

        if sync_result.errors:
            if args.json:
                _print_json(_json_envelope(
                    ok=False,
                    command=command,
                    project_key=adapter.project_key,
                    result={
                        "packets_total": sync_result.packets_total,
                        "registry_updates": sync_result.registry_updates,
                        "ready": sync_result.ready,
                        "accepted": sync_result.accepted,
                        "blocked": sync_result.blocked,
                        "changed_after_acceptance": sync_result.changed_after_acceptance,
                        "ready_for_retry": sync_result.ready_for_retry,
                        "cascading_blocked": sync_result.cascading_blocked,
                        "cycles": sync_result.cycles,
                    },
                    warnings=sync_result.warnings,
                    errors=sync_result.errors,
                ))
            else:
                for err in sync_result.errors:
                    print(err, file=sys.stderr)
            sys.exit(2)

        result = {
            "dry_run": args.dry_run,
            "packets_total": sync_result.packets_total,
            "registry_updates": sync_result.registry_updates,
            "ready": sync_result.ready,
            "accepted": sync_result.accepted,
            "blocked": sync_result.blocked,
            "changed_after_acceptance": sync_result.changed_after_acceptance,
            "ready_for_retry": sync_result.ready_for_retry,
            "cascading_blocked": sync_result.cascading_blocked,
            "cycles": sync_result.cycles,
        }

        if args.json:
            _print_json(_json_envelope(
                ok=True,
                command=command,
                project_key=adapter.project_key,
                result=result,
                warnings=sync_result.warnings,
            ))
        else:
            verb = "Would sync" if args.dry_run else "Synced"
            print(f"{verb} {sync_result.packets_total} packets for {adapter.project_key}.")
            print(f"Ready: {len(sync_result.ready)}, Accepted: {len(sync_result.accepted)}, Blocked: {len(sync_result.blocked)}")
    except Exception as e:
        if args.json:
            _print_json(_json_envelope(
                ok=False,
                command=command,
                errors=[{"code": "SYNC_FAILED", "message": str(e)}],
            ))
        else:
            print(f"Sync failed: {e}", file=sys.stderr)
        sys.exit(1)


def _cmd_bootstrap_backlog(args: argparse.Namespace) -> None:
    command = "bootstrap-backlog"
    try:
        from prefect_grace.platform.controller_backlog_bootstrap import (
            build_backlog_bootstrap_plan,
            dataclass_to_dict,
        )

        if bool(getattr(args, "apply", False)) and not getattr(args, "project", None):
            raise ValueError("bootstrap-backlog --apply requires explicit --project")
        adapter = _load_adapter_from_args(args)
        dry_run = not bool(getattr(args, "apply", False))
        plan = build_backlog_bootstrap_plan(adapter, dry_run=dry_run)
        result = dataclass_to_dict(plan)

        if args.json:
            _print_json(_json_envelope(
                ok=not plan.errors,
                command=command,
                project_key=adapter.project_key,
                result=result,
                warnings=plan.warnings,
                errors=plan.errors,
            ))
        else:
            mode = "dry-run" if dry_run else "apply"
            print(f"Backlog bootstrap {mode} for {adapter.project_key}:")
            print(f"  Candidates: {len(plan.candidates)}")
            print(f"  Applied: {plan.apply_count}")
            print(f"  Warnings: {len(plan.warnings)}")
            print(f"  Errors: {len(plan.errors)}")

        if plan.errors:
            sys.exit(1)
    except Exception as e:
        if args.json:
            _print_json(_json_envelope(
                ok=False,
                command=command,
                errors=[{"code": "BOOTSTRAP_FAILED", "message": str(e)}],
            ))
        else:
            print(f"Backlog bootstrap failed: {e}", file=sys.stderr)
        sys.exit(1)


def _cmd_registry_bootstrap_apply(args: argparse.Namespace) -> None:
    command = "registry-bootstrap-apply"
    try:
        from prefect_grace.platform.registry_bootstrap_apply import run_registry_bootstrap_apply

        result = run_registry_bootstrap_apply(
            project_config=Path(args.project),
            apply=bool(getattr(args, "apply", False)),
            packet_ids=getattr(args, "packet_id", []),
        )
        payload = result.to_dict()

        if args.json:
            _print_json(_json_envelope(
                ok=result.ok,
                command=command,
                project_key=result.project_key or None,
                result=payload,
                warnings=result.warnings,
                errors=result.errors,
            ))
        else:
            mode = "apply" if result.apply else "dry-run"
            print(f"Registry bootstrap {mode} for {result.project_key or '-'}: {'OK' if result.ok else 'FAILED'}")
            print(f"  Runtime state root: {result.runtime_state_root or '-'}")
            print(f"  Write root: {result.write_root or '-'}")
            print(f"  Candidates: {result.preflight.get('source_packet_candidate_count', 0)}")
            print(f"  Planned upserts: {len(result.preflight.get('planned_upserts') or [])}")
            print(f"  Apply count: {result.apply_summary.get('apply_count', 0)}")
            print(f"  Submit dry-run Prefect runs created: {result.submit_dry_run.get('prefect_runs_created', 0)}")
            for error in result.errors:
                print(f"ERROR: {error}", file=sys.stderr)
        if not result.ok:
            sys.exit(1)
    except Exception as e:
        if args.json:
            _print_json(_json_envelope(
                ok=False,
                command=command,
                errors=[{"code": "REGISTRY_BOOTSTRAP_APPLY_FAILED", "message": str(e)}],
            ))
        else:
            print(f"Registry bootstrap apply failed: {e}", file=sys.stderr)
        sys.exit(1)


def _cmd_packet_status(args: argparse.Namespace) -> None:
    command = "packet-status"
    try:
        adapter = _load_adapter_from_args(args)
        registry = PacketRegistryStore(Path(adapter.runtime_state_root) / "state")
        packet = registry.load_packet(args.packet_id)
        if packet is None:
            raise KeyError(f"Packet {args.packet_id} not found in registry")
        if args.json:
            _print_json(_json_envelope(
                ok=True,
                command=command,
                project_key=adapter.project_key,
                result={"packet": packet},
            ))
        else:
            print(json.dumps(packet, indent=2, ensure_ascii=False))
    except Exception as e:
        if args.json:
            _print_json(_json_envelope(
                ok=False,
                command=command,
                errors=[{"code": "PACKET_NOT_FOUND", "message": str(e)}],
            ))
        else:
            print(f"Packet status failed: {e}", file=sys.stderr)
        sys.exit(1)


def _cmd_registry_dump(args: argparse.Namespace) -> None:
    command = "registry-dump"
    try:
        adapter = _load_adapter_from_args(args)
        state_root = Path(adapter.runtime_state_root) / "state"
        result = {
            "packets": PacketRegistryStore(state_root).list_packets(adapter.project_key),
            "runs": RunStore(state_root).list_runs(),
            "executor_history": ExecutorHistoryStore(state_root).list_executions(),
        }
        if args.json:
            _print_json(_json_envelope(
                ok=True,
                command=command,
                project_key=adapter.project_key,
                result=result,
            ))
        else:
            print(json.dumps(result, indent=2, ensure_ascii=False))
    except Exception as e:
        if args.json:
            _print_json(_json_envelope(
                ok=False,
                command=command,
                errors=[{"code": "REGISTRY_DUMP_FAILED", "message": str(e)}],
            ))
        else:
            print(f"Registry dump failed: {e}", file=sys.stderr)
        sys.exit(1)
