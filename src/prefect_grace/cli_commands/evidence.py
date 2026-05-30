# ############################################################################
# AI_HEADER: evidence
# ROLE: Reviews, evidence manifests, scope-guards, and reworks commands.
# ############################################################################

# START_MODULE_CONTRACT
# purpose: Write and validate reviews, evidence, rework files, and scope compliance.
# inputs: CLI argparse Namespace.
# returns: None.
# side_effects: Creates and writes review/evidence/rework files to disk, exits process.
# emitted_logs: None.
# error_behavior: Exits with appropriate status code (0/1/2) depending on check result.
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

from prefect_grace.models import ReviewVerdict
from prefect_grace.tasks.review_router import create_rework_from_review, record_review
from prefect_grace.platform.packet_parser import parse_packet_markdown
from prefect_grace.cli_commands.common import (
    _json_envelope,
    _print_json,
)


def _cmd_review(args: argparse.Namespace) -> None:
    reasons = args.reason or []
    record = record_review(
        packet_id=args.packet_id,
        verdict=ReviewVerdict(args.verdict),
        reasons=reasons,
        follow_up_action=args.follow_up_action,
    )
    print(record["review_path"])
    if args.verdict == ReviewVerdict.REWORK_REQUIRED.value and args.create_rework:
        rework = create_rework_from_review(args.packet_id, reasons)
        print(rework["packet_path"])


def _cmd_write_review(args: argparse.Namespace) -> None:
    command = "write-review"
    try:
        from prefect_grace.platform.packet_artifacts import write_review

        packet_dir = Path(args.packet_dir)
        body = Path(args.body).read_text(encoding="utf-8") if args.body else args.body_text or ""

        metadata = {}
        if args.reviewer:
            metadata["reviewer"] = args.reviewer

        review_path = write_review(packet_dir, args.verdict, body, metadata)

        result = {
            "review_path": str(review_path.relative_to(packet_dir)),
            "verdict": args.verdict,
        }

        if args.json:
            _print_json(_json_envelope(
                ok=True,
                command=command,
                result=result,
            ))
        else:
            print(f"Review written to {review_path}")
    except Exception as e:
        if args.json:
            _print_json(_json_envelope(
                ok=False,
                command=command,
                errors=[{"code": "WRITE_REVIEW_FAILED", "message": str(e)}],
            ))
        else:
            print(f"Write review failed: {e}", file=sys.stderr)
        sys.exit(1)


def _cmd_write_evidence(args: argparse.Namespace) -> None:
    command = "write-evidence"
    try:
        from prefect_grace.platform.packet_artifacts import write_evidence

        packet_dir = Path(args.packet_dir)
        manifest = json.loads(Path(args.manifest).read_text(encoding="utf-8"))

        evidence_path = write_evidence(packet_dir, args.attempt, manifest)

        result = {
            "evidence_path": str(evidence_path.relative_to(packet_dir)),
            "attempt": args.attempt,
        }

        if args.json:
            _print_json(_json_envelope(
                ok=True,
                command=command,
                result=result,
            ))
        else:
            print(f"Evidence written to {evidence_path}")
    except Exception as e:
        if args.json:
            _print_json(_json_envelope(
                ok=False,
                command=command,
                errors=[{"code": "WRITE_EVIDENCE_FAILED", "message": str(e)}],
            ))
        else:
            print(f"Write evidence failed: {e}", file=sys.stderr)
        sys.exit(1)


def _cmd_write_rework(args: argparse.Namespace) -> None:
    command = "write-rework"
    try:
        from prefect_grace.platform.packet_artifacts import write_rework

        packet_dir = Path(args.packet_dir)
        body = Path(args.body).read_text(encoding="utf-8") if args.body else args.body_text or ""

        blockers = args.blocker if args.blocker else None

        rework_path = write_rework(packet_dir, args.attempt, body, blockers)

        result = {
            "rework_path": str(rework_path.relative_to(packet_dir)),
            "attempt": args.attempt,
        }

        if args.json:
            _print_json(_json_envelope(
                ok=True,
                command=command,
                result=result,
            ))
        else:
            print(f"Rework written to {rework_path}")
    except Exception as e:
        if args.json:
            _print_json(_json_envelope(
                ok=False,
                command=command,
                errors=[{"code": "WRITE_REWORK_FAILED", "message": str(e)}],
            ))
        else:
            print(f"Write rework failed: {e}", file=sys.stderr)
        sys.exit(1)


def _cmd_check_scope(args: argparse.Namespace) -> None:
    """Check scope violations for changed files against packet scope."""
    command = "check-scope"
    try:
        from prefect_grace.platform.scope_guard import validate_scope

        # Parse packet
        packet_path = Path(args.packet)
        if not packet_path.exists():
            raise FileNotFoundError(f"Packet file not found: {packet_path}")

        parsed = parse_packet_markdown(packet_path, mode="legacy_warn")

        # Collect changed files
        changed_files = []
        if args.changed_files:
            changed_files.extend(args.changed_files)
        if args.changed_files_file:
            changed_files_file = Path(args.changed_files_file)
            if not changed_files_file.exists():
                raise FileNotFoundError(f"Changed files file not found: {changed_files_file}")
            changed_files.extend(
                line.strip()
                for line in changed_files_file.read_text(encoding="utf-8").splitlines()
                if line.strip()
            )

        if not changed_files:
            raise ValueError("No changed files provided. Use --changed-file or --changed-files-file.")

        # Validate scope
        result = validate_scope(
            changed_files=changed_files,
            allowed_scope=parsed.allowed_write_scope,
            frozen_scope=parsed.frozen_scope,
            repo_root=args.repo_root,
        )

        # Output
        if args.json:
            _print_json(_json_envelope(
                ok=result.ok,
                command=command,
                result=result.to_dict(),
            ))
        else:
            # Text mode
            if result.ok:
                print("Scope check: OK")
                print(f"  Changed: {len(result.changed_files)} files")
                print(f"  Allowed: {len(result.allowed_files)} files")
            else:
                print("Scope check: FAILED")
                print(f"  Changed: {len(result.changed_files)} files")
                print(f"  Allowed: {len(result.allowed_files)} files")

                if result.invalid_paths:
                    print("\nInvalid paths:")
                    for v in result.invalid_paths:
                        print(f"  - {v.file_path}: {v.reason}")

                if result.frozen_violations:
                    print("\nFrozen violations:")
                    for v in result.frozen_violations:
                        pattern_info = f" (matched: {v.matched_pattern})" if v.matched_pattern else ""
                        print(f"  - {v.file_path}{pattern_info}")

                if result.outside_allowed:
                    print("\nOutside allowed:")
                    for v in result.outside_allowed:
                        print(f"  - {v.file_path}")

        # Exit codes
        if not result.ok:
            sys.exit(1)

    except Exception as e:
        if args.json:
            _print_json(_json_envelope(
                ok=False,
                command=command,
                errors=[{"code": "CHECK_SCOPE_FAILED", "message": str(e)}],
            ))
        else:
            print(f"Check scope failed: {e}", file=sys.stderr)
        sys.exit(2)


def _cmd_sync_packet_yaml_sidecar(args: argparse.Namespace) -> None:
    command = "sync-packet-yaml-sidecar"
    try:
        from prefect_grace.platform.packet_yaml_sidecar_sync import sync_packet_yaml_sidecars

        result = sync_packet_yaml_sidecars(
            getattr(args, "packet", None) or [],
            apply=bool(getattr(args, "apply", False)),
        )
        payload = result.to_dict()

        if args.json:
            _print_json(_json_envelope(
                ok=result.ok,
                command=command,
                result=payload,
                errors=result.errors,
            ))
        else:
            mode = "apply" if result.apply else "dry-run"
            print(f"Packet YAML sidecar sync ({mode}): {'OK' if result.ok else 'FAILED'}")
            for item in result.results:
                print(f"  - {item['planned_action']}: {item['packet']}")
                if item.get("error"):
                    print(f"    error: {item['error']['message']}", file=sys.stderr)
            for write_path in result.writes:
                print(f"  wrote: {write_path}")
        sys.exit(0 if result.ok else 1)
    except Exception as e:
        if args.json:
            _print_json(_json_envelope(
                ok=False,
                command=command,
                errors=[{"code": "SYNC_PACKET_YAML_SIDECAR_FAILED", "message": str(e)}],
            ))
        else:
            print(f"Sync packet YAML sidecar failed: {e}", file=sys.stderr)
        sys.exit(2)


def _cmd_audit_packet_yaml_sidecars(args: argparse.Namespace) -> None:
    command = "audit-packet-yaml-sidecars"
    try:
        from prefect_grace.platform.packet_yaml_sidecar_audit import audit_packet_yaml_sidecars

        result = audit_packet_yaml_sidecars(
            getattr(args, "packet_root", "prefect_grace/packets"),
            limit=int(getattr(args, "limit", 20)),
        )
        payload = result.to_dict()

        if args.json:
            _print_json(_json_envelope(
                ok=result.ok,
                command=command,
                result=payload,
                errors=result.errors,
            ))
        else:
            print(f"Packet YAML sidecar audit: {'OK' if result.ok else 'FAILED'}")
            print(f"  packet_root: {result.packet_root}")
            print(f"  packets_total: {result.packets_total}")
            for class_name, count in result.counts.items():
                print(f"  {class_name}: {count}")
            if result.errors:
                print(f"  errors: {len(result.errors)}", file=sys.stderr)
        sys.exit(0 if result.ok else 1)
    except Exception as e:
        if args.json:
            _print_json(_json_envelope(
                ok=False,
                command=command,
                errors=[{"code": "AUDIT_PACKET_YAML_SIDECARS_FAILED", "message": str(e)}],
            ))
        else:
            print(f"Audit packet YAML sidecars failed: {e}", file=sys.stderr)
        sys.exit(2)


def _cmd_plan_packet_yaml_sidecar_migration(args: argparse.Namespace) -> None:
    command = "plan-packet-yaml-sidecar-migration"
    try:
        from prefect_grace.platform.packet_yaml_sidecar_migration_plan import (
            plan_packet_yaml_sidecar_migration,
        )

        result = plan_packet_yaml_sidecar_migration(
            getattr(args, "packet_root", "prefect_grace/packets"),
            project=getattr(args, "project", "prefect_grace/project.yaml"),
            limit=int(getattr(args, "limit", 20)),
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
            print(f"Packet YAML sidecar migration plan: {'OK' if result.ok else 'FAILED'}")
            print(f"  packet_root: {result.packet_root}")
            print(f"  project: {result.project}")
            print(f"  packets_total: {result.packets_total}")
            print(f"  plan_count: {result.plan_count}")
            for class_name, count in result.counts.items():
                print(f"  {class_name}: {count}")
            if result.warnings:
                print(f"  warnings: {len(result.warnings)}", file=sys.stderr)
            if result.errors:
                print(f"  errors: {len(result.errors)}", file=sys.stderr)
        sys.exit(0 if result.ok else 1)
    except Exception as e:
        if args.json:
            _print_json(_json_envelope(
                ok=False,
                command=command,
                errors=[{"code": "PLAN_PACKET_YAML_SIDECAR_MIGRATION_FAILED", "message": str(e)}],
            ))
        else:
            print(f"Plan packet YAML sidecar migration failed: {e}", file=sys.stderr)
        sys.exit(2)


def _cmd_apply_packet_yaml_sidecar_migration(args: argparse.Namespace) -> None:
    command = "apply-packet-yaml-sidecar-migration"
    try:
        from prefect_grace.platform.packet_yaml_sidecar_migration_apply import (
            APPROVAL_ENV_NAME,
            apply_packet_yaml_sidecar_migration,
        )

        result = apply_packet_yaml_sidecar_migration(
            getattr(args, "packet_root", "prefect_grace/packets"),
            project=getattr(args, "project", "prefect_grace/project.yaml"),
            stale_only=bool(getattr(args, "stale_only", False)),
            packet_ids=getattr(args, "packet_id", None) or [],
            apply=bool(getattr(args, "apply", False)),
            limit=getattr(args, "limit", None),
            understand_source_hash_change=bool(getattr(args, "i_understand_source_hash_change", False)),
            approval_token=os.environ.get(APPROVAL_ENV_NAME),
        )
        payload = result.to_dict()

        if args.json:
            _print_json(_json_envelope(
                ok=result.ok,
                command=command,
                result=payload,
                warnings=result.warnings,
                errors=result.errors,
            ))
        else:
            mode = "apply" if result.apply else "dry-run"
            print(f"Packet YAML sidecar migration apply ({mode}): {'OK' if result.ok else 'FAILED'}")
            print(f"  packet_root: {result.packet_root}")
            print(f"  project: {result.project}")
            print(f"  selected_count: {result.selected_count}")
            print(f"  source_hash_change_count: {result.source_hash_change_count}")
            for write_path in result.writes:
                print(f"  wrote: {write_path}")
            if result.warnings:
                print(f"  warnings: {len(result.warnings)}", file=sys.stderr)
            if result.errors:
                print(f"  errors: {len(result.errors)}", file=sys.stderr)
        sys.exit(0 if result.ok else 1)
    except Exception as e:
        if args.json:
            _print_json(_json_envelope(
                ok=False,
                command=command,
                errors=[{"code": "APPLY_PACKET_YAML_SIDECAR_MIGRATION_FAILED", "message": str(e)}],
            ))
        else:
            print(f"Apply packet YAML sidecar migration failed: {e}", file=sys.stderr)
        sys.exit(2)


def _cmd_validate_evidence_contract(args: argparse.Namespace) -> None:
    """Validate evidence contract from packet."""
    command = "validate-evidence-contract"
    try:
        from prefect_grace.platform.evidence_contract import parse_evidence_contract, validate_evidence_contract
        from prefect_grace.platform.verification_profile import load_verification_profiles

        packet = parse_packet_markdown(args.packet_path)
        contract = parse_evidence_contract(packet)
        profiles = load_verification_profiles()
        validation = validate_evidence_contract(contract, profiles)

        result = {
            "packet_id": contract.packet_id,
            "requirements_count": len(contract.requirements),
            "validation": validation.to_dict(),
        }

        if args.json:
            _print_json(_json_envelope(ok=validation.ok, command=command, result=result))
        else:
            print(f"Packet: {contract.packet_id}")
            print(f"Requirements: {len(contract.requirements)}")
            if validation.ok:
                print("✓ Contract valid")
            else:
                print(f"✗ Contract invalid ({len(validation.errors)} errors)")
                for error in validation.errors:
                    print(f"  - {error['code']}: {error['message']}")

        sys.exit(0 if validation.ok else 1)

    except Exception as e:
        if args.json:
            _print_json(_json_envelope(
                ok=False,
                command=command,
                errors=[{"code": "VALIDATE_CONTRACT_FAILED", "message": str(e)}],
            ))
        else:
            print(f"Validate evidence contract failed: {e}", file=sys.stderr)
        sys.exit(2)


def _cmd_validate_evidence_manifest(args: argparse.Namespace) -> None:
    """Validate evidence manifest against contract."""
    command = "validate-evidence-manifest"
    try:
        from prefect_grace.platform.evidence_contract import parse_evidence_contract
        from prefect_grace.platform.evidence_manifest import parse_evidence_manifest, validate_evidence_manifest
        from prefect_grace.platform.artifact_validator import validate_artifact_references

        packet = parse_packet_markdown(args.packet)
        contract = parse_evidence_contract(packet)
        manifest = parse_evidence_manifest(args.manifest_path)

        # Validate artifact references. The manifest directory is a relative
        # root so short sibling paths such as "targeted_pytest.txt" work.
        artifact_roots = [args.manifest_path.parent]
        if args.artifact_root:
            artifact_roots.append(Path(args.artifact_root))

        # Validate manifest against contract and structured trace artifacts
        # using the same roots artifact reference validation uses.
        contract_validation = validate_evidence_manifest(
            manifest,
            contract,
            artifact_roots=artifact_roots,
        )

        artifact_validation = validate_artifact_references(manifest, artifact_roots)

        result = {
            "packet_id": manifest.packet_id,
            "evidence_count": len(manifest.evidence),
            "contract_validation": contract_validation.to_dict(),
            "artifact_validation": artifact_validation.to_dict(),
        }

        ok = contract_validation.ok and artifact_validation.ok

        if args.json:
            _print_json(_json_envelope(ok=ok, command=command, result=result))
        else:
            print(f"Packet: {manifest.packet_id}")
            print(f"Evidence items: {len(manifest.evidence)}")
            if ok:
                print("✓ Manifest valid")
            else:
                print(f"✗ Manifest invalid")
                if not contract_validation.ok:
                    print(f"  Contract errors: {len(contract_validation.errors)}")
                    for error in contract_validation.errors:
                        print(f"    - {error['code']}: {error['message']}")
                if not artifact_validation.ok:
                    print(f"  Missing artifacts: {len(artifact_validation.missing_artifacts)}")
                    for path in artifact_validation.missing_artifacts:
                        print(f"    - {path}")

        sys.exit(0 if ok else 1)

    except Exception as e:
        if args.json:
            _print_json(_json_envelope(
                ok=False,
                command=command,
                errors=[{"code": "VALIDATE_MANIFEST_FAILED", "message": str(e)}],
            ))
        else:
            print(f"Validate evidence manifest failed: {e}", file=sys.stderr)
        sys.exit(2)
