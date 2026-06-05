# ############################################################################
# AI_HEADER: cli_commands.brief_intake
# ROLE: CLI command handlers for feature brief intake and dynamic planning.
# ############################################################################

# START_MODULE_CONTRACT
# purpose: Parse a feature brief markdown file and generate an execution packet.
# inputs: CLI argparse Namespace.
# returns: None.
# side_effects: Writes execution packet markdown and sidecar YAML files to disk if applied.
# emitted_logs: None.
# error_behavior: Exits with non-zero code on failures or validation errors.
# END_MODULE_CONTRACT

# START_MODULE_MAP
# mapping:
#   - function: _cmd_dynamic_plan
# END_MODULE_MAP

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from prefect_grace.cli_commands.common import _json_envelope, _print_json
from prefect_grace.platform.brief_intake import generate_strict_packet, parse_brief_markdown


def _cmd_dynamic_plan(args: argparse.Namespace) -> None:
    command = "dynamic-plan"
    try:
        brief_path = Path(args.brief)
        if not brief_path.exists():
            raise FileNotFoundError(f"Feature brief not found at {brief_path}")

        # Parse first to get feature_id for default output_dir
        parsed_brief = parse_brief_markdown(brief_path)
        feature_id = parsed_brief["feature_id"]

        if args.output_dir:
            output_dir = Path(args.output_dir)
        else:
            output_dir = Path("prefect_grace/packets") / feature_id

        # generate_strict_packet does the core dynamic planning logic
        result = generate_strict_packet(
            brief_path=brief_path,
            output_dir=output_dir,
            write=bool(args.apply),
        )

        md_path_str = str(result["md_path"]) if result["md_path"] else None
        yaml_path_str = str(result["yaml_path"]) if result["yaml_path"] else None

        output_payload = {
            "packet_id": result["packet_id"],
            "feature_id": feature_id,
            "dry_run": not bool(args.apply),
            "output_dir": str(output_dir),
            "md_path": md_path_str,
            "yaml_path": yaml_path_str,
            "md_content": result["md_content"],
            "yaml_content": result["yaml_content"],
        }

        if args.json:
            _print_json(_json_envelope(
                ok=True,
                command=command,
                result=output_payload,
            ))
        else:
            print(f"Dynamic Plan generated successfully for packet {result['packet_id']}:")
            print(f"  Feature ID: {feature_id}")
            print(f"  Dry-run: {not bool(args.apply)}")
            print(f"  Output Directory: {output_dir}")
            if args.apply:
                print(f"  Written MD packet to: {md_path_str}")
                print(f"  Written YAML sidecar to: {yaml_path_str}")
            else:
                print("  [DRY-RUN] No files were written to disk. Use --apply to write them.")
        sys.exit(0)
    except Exception as e:
        if args.json:
            _print_json(_json_envelope(
                ok=False,
                command=command,
                errors=[{"code": "DYNAMIC_PLAN_FAILED", "message": str(e)}],
            ))
        else:
            print(f"Dynamic plan failed: {e}", file=sys.stderr)
        sys.exit(1)
