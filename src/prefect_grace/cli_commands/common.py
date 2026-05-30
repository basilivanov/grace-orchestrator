# ############################################################################
# AI_HEADER: common
# ROLE: Shared helpers and common utilities for GRACE CLI.
# ############################################################################

# START_MODULE_CONTRACT
# purpose: Provide shared utilities, printing, and argument resolution helpers.
# inputs: Varied arguments.
# returns: Varied types.
# side_effects: May print JSON to stdout.
# emitted_logs: None.
# error_behavior: Raises Exceptions on failure.
# END_MODULE_CONTRACT

# START_MODULE_MAP
# mapping:
# END_MODULE_MAP

from __future__ import annotations

import argparse
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

from prefect_grace.platform.project_adapter import load_project_adapter
from prefect_grace.platform.verification_profile import load_verification_profiles
from prefect_grace.platform.packet_parser import parse_packet_markdown


def _json_envelope(
    *,
    ok: bool,
    command: str,
    project_key: str | None = None,
    result: dict | list | str | None = None,
    warnings: list | None = None,
    errors: list | None = None,
) -> dict:
    payload = result if result is not None else {}
    return {
        "ok": ok,
        "project_key": project_key,
        "command": command,
        "result": payload,
        "data": payload,
        "warnings": warnings or [],
        "errors": errors or [],
    }


def _print_json(payload: dict) -> None:
    print(json.dumps(payload, indent=2, ensure_ascii=False))


def _profile_config_path(project_path: str | None) -> Path | None:
    if not project_path:
        return None
    path = Path(project_path)
    if path.is_file():
        project_root = path.parent.parent if path.name == "project.yaml" else path.parent
    else:
        project_root = path
    grace_path = project_root / "grace" / "policies" / "verification.yaml"
    if grace_path.exists():
        return grace_path
    legacy_path = project_root / "prefect_grace" / "policies" / "verification.yaml"
    if legacy_path.exists():
        return legacy_path
    return None


def _load_adapter_from_args(args: argparse.Namespace):
    return load_project_adapter(getattr(args, "project", None) or getattr(args, "project_config", None))


def _packet_to_dict(parsed, *, path: Path | None = None, repo_root: Path | None = None) -> dict:
    data = {
        "packet_id": parsed.packet_id,
        "feature_id": parsed.feature_id,
        "wave_id": parsed.wave_id,
        "title": parsed.title,
        "objective": parsed.objective,
        "status": parsed.status,
        "phase": parsed.phase,
        "depends_on": parsed.depends_on,
        "modules": parsed.modules,
        "allowed_write_scope": parsed.allowed_write_scope,
        "frozen_scope": parsed.frozen_scope,
        "must_preserve": parsed.must_preserve,
        "verification": parsed.verification,
        "expected_evidence": parsed.expected_evidence,
        "escalation_triggers": parsed.escalation_triggers,
        "source_hash": parsed.source_hash,
        "section_lines": parsed.section_lines,
        "legacy_warnings": parsed.legacy_warnings,
    }
    if path is not None:
        try:
            data["path"] = str(path.relative_to(repo_root or Path.cwd()))
        except ValueError:
            data["path"] = str(path)
    return data


def _scan_project_packets(adapter, *, mode: str) -> tuple[list[dict], list[str], list[dict]]:
    packets_dir = Path(adapter.repo_root) / adapter.packets_dir
    if not packets_dir.exists():
        raise FileNotFoundError(f"Packets directory not found at {packets_dir}")

    packets_data: list[dict] = []
    all_warnings: list[str] = []
    errors: list[dict] = []

    for path in sorted(packets_dir.glob("**/*.md")):
        try:
            parsed = parse_packet_markdown(path, mode=mode)
            packet_data = _packet_to_dict(parsed, path=path, repo_root=Path(adapter.repo_root))
            packet_data["status"] = packet_data["status"] or "ready"
            packets_data.append(packet_data)
            all_warnings.extend(parsed.legacy_warnings)
        except Exception as e:
            errors.append({"code": "PACKET_INVALID", "message": f"Packet {path}: {e}"})
            if mode == "strict":
                break
    return packets_data, all_warnings, errors


def _scheduled_for_from_args(args: argparse.Namespace) -> str | None:
    scheduled_for = getattr(args, "scheduled_for", None)
    delay_minutes = getattr(args, "delay_minutes", None)
    if scheduled_for and delay_minutes is not None:
        raise SystemExit("Use either --scheduled-for or --delay-minutes, not both.")
    if scheduled_for:
        parsed = datetime.fromisoformat(str(scheduled_for).replace("Z", "+00:00"))
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)
        return parsed.astimezone(timezone.utc).isoformat()
    if delay_minutes is not None:
        return (datetime.now(timezone.utc) + timedelta(minutes=int(delay_minutes))).isoformat()
    return None
