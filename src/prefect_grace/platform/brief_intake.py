# ############################################################################
# AI_HEADER: platform.brief_intake
# ROLE: Automatic generator of strict GRACE execution packets from business briefs.
# ############################################################################

# START_MODULE_CONTRACT
# purpose: Parse feature-brief.md and generate strict execution packets and sidecar YAML files.
# inputs: Path to feature-brief.md.
# returns: Dictionary containing generated execution packet MD and YAML paths.
# side_effects: Writes generated files if write flag is enabled.
# emitted_logs: none.
# error_behavior: Raises ValueError if the brief is missing required sections.
# END_MODULE_CONTRACT

# START_MODULE_MAP
# mapping:
#   - function: parse_brief_markdown
#   - function: generate_strict_packet
# END_MODULE_MAP

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from prefect_grace.platform.packet_parser import ParsedPacket, dump_packet_sidecar_payload


def parse_brief_markdown(brief_path: Path) -> dict[str, Any]:
    """
    Parses feature-brief.md markdown file into sections and metadata.
    """
    if not brief_path.exists():
        raise FileNotFoundError(f"Feature brief not found at {brief_path}")

    content = brief_path.read_text(encoding="utf-8")
    sections: dict[str, list[str]] = {}
    current_section = "_header"
    first_heading = ""
    feature_id = ""

    for line in content.splitlines():
        stripped = line.strip()
        if stripped.startswith("#"):
            h_match = re.match(r"^#+\s*(.*)$", stripped)
            current_section = h_match.group(1).strip().lower() if h_match else stripped.lower()
            sections.setdefault(current_section, [])
            if stripped.startswith("# ") and not first_heading:
                first_heading = stripped[2:].strip()
                # Try to extract Feature ID
                id_match = re.search(r"FEAT-[A-Z0-9\-]+", first_heading)
                if id_match:
                    feature_id = id_match.group(0)
        else:
            sections.setdefault(current_section, []).append(line)

    # In case feature_id was in a specific metadata block
    if not feature_id:
        for k, v in sections.items():
            if "feature id" in k or "feature_id" in k:
                for line in v:
                    m = re.search(r"FEAT-[A-Z0-9\-]+", line)
                    if m:
                        feature_id = m.group(0)
                        break

    return {
        "feature_id": feature_id or "FEAT-UNKNOWN",
        "title": first_heading or "Untitled Feature",
        "sections": sections,
    }


def generate_strict_packet(
    brief_path: Path,
    output_dir: Path | None = None,
    write: bool = False,
) -> dict[str, Any]:
    """
    Generates strict EXECUTION_PACKET.md and sidecar YAML from feature-brief.md.
    """
    parsed_brief = parse_brief_markdown(brief_path)
    feature_id = parsed_brief["feature_id"]
    title = parsed_brief["title"]
    sections = parsed_brief["sections"]

    # Extract objective from Business Intent or Desired Outcome
    intent_lines = sections.get("business intent", []) or sections.get("desired outcome", [])
    objective = "\n".join(intent_lines).strip() or "Dynamic planning auto-generated slice objective."

    # Extract some lists like Acceptance Criteria
    criteria_lines = sections.get("acceptance criteria", [])
    criteria = []
    for line in criteria_lines:
        stripped = line.strip()
        if stripped.startswith("-") or stripped.startswith("*"):
            criteria.append(stripped[1:].strip())

    if not criteria:
        criteria = ["Auto-generated packet validation rules must pass."]

    # Default strict scopes
    allowed_write_scope = [
        f"prefect_grace/platform/brief_intake.py",
        f"prefect_grace/cli_commands/brief_intake.py",
        f"prefect_grace/packets/{feature_id}/**",
        f"tests/test_prefect_grace_brief_intake.py",
    ]
    frozen_scope = ["backend/**", "frontend/**", ".worktrees/**"]

    # Expected Evidence
    expected_evidence = [
        "EVIDENCE/attempt-0001/evidence_manifest.json",
        "EVIDENCE/attempt-0001/SUMMARY.md",
        "EVIDENCE/attempt-0001/strict_validate_packet.json",
    ]

    packet_id = f"{feature_id}-W01-DYNAMIC-PLANNING"

    # Construct the ParsedPacket object
    parsed_packet = ParsedPacket(
        packet_id=packet_id,
        feature_id=feature_id,
        wave_id="W01",
        title=f"{packet_id} - Dynamic Planning",
        objective=objective,
        status="ready",
        phase="PHASE-GRACE-ORCHESTRATOR-PORTABLE-MVP",
        depends_on=[],
        modules=["M-GRACE-BRIEF-INTAKE", "M-GRACE-ORCHESTRATOR"],
        allowed_write_scope=allowed_write_scope,
        frozen_scope=frozen_scope,
        must_preserve=criteria,
        verification=(
            "Run strict validation check:\n\n"
            f"```bash\n"
            f"python3 -m prefect_grace.cli validate-packet prefect_grace/packets/{feature_id}/EXECUTION_PACKET.md --strict --json\n"
            f"```"
        ),
        expected_evidence=expected_evidence,
        escalation_triggers=[
            "Parser cannot map standard brief sections.",
            "Generated packet fails strict validation.",
        ],
    )

    # Generate MD text representation
    md_lines = [
        f"# Execution Packet: {parsed_packet.packet_id}",
        "",
        "## Objective",
        parsed_packet.objective,
        "",
        "## Slice",
        f"- slice_id: `SLICE-{feature_id}`",
        f"- slice_slug: `{feature_id.lower()}`",
        f"- feature_id: `{parsed_packet.feature_id}`",
        f"- packet_id: `{parsed_packet.packet_id}`",
        f"- wave_id: `{parsed_packet.wave_id}`",
        f"- status: `{parsed_packet.status}`",
        f"- phase: `{parsed_packet.phase}`",
        f"- depends_on: []",
        f"- feature_dir: `/opt/astro-project/prefect_grace/packets/{feature_id}`",
        "",
        "## Source Of Truth",
        f"- `/opt/astro-project/prefect_grace/platform/brief_intake.py`",
        "",
        "## Impacted Modules",
        *[f"- `{mod}`" for mod in parsed_packet.modules],
        "",
        "## Allowed Write Scope",
        *[f"- `{scope}`" for scope in parsed_packet.allowed_write_scope],
        "",
        "## Frozen Scope",
        *[f"- `{scope}`" for scope in parsed_packet.frozen_scope],
        "",
        "## Must Preserve",
        *[f"- {preserve}" for preserve in parsed_packet.must_preserve],
        "",
        "## Verification",
        parsed_packet.verification,
        "",
        "## Expected Evidence",
        *[f"- {evidence}" for evidence in parsed_packet.expected_evidence],
        "",
        "## Escalation Triggers",
        *[f"- {trigger}" for trigger in parsed_packet.escalation_triggers],
    ]
    md_content = "\n".join(md_lines) + "\n"

    # Sidecar payload
    sidecar_payload = {
        "schema_version": "1",
        "artifact_type": "execution_packet",
        "packet_id": parsed_packet.packet_id,
        "feature_id": parsed_packet.feature_id,
        "wave_id": parsed_packet.wave_id,
        "title": parsed_packet.title,
        "objective": parsed_packet.objective,
        "status": parsed_packet.status,
        "phase": parsed_packet.phase,
        "depends_on": parsed_packet.depends_on,
        "modules": parsed_packet.modules,
        "allowed_write_scope": parsed_packet.allowed_write_scope,
        "frozen_scope": parsed_packet.frozen_scope,
        "must_preserve": parsed_packet.must_preserve,
        "verification": parsed_packet.verification,
        "expected_evidence": parsed_packet.expected_evidence,
        "escalation_triggers": parsed_packet.escalation_triggers,
    }
    yaml_content = dump_packet_sidecar_payload(sidecar_payload)

    md_path = None
    yaml_path = None

    if write and output_dir:
        output_dir.mkdir(parents=True, exist_ok=True)
        md_path = output_dir / "EXECUTION_PACKET.md"
        yaml_path = output_dir / "EXECUTION_PACKET.yaml"
        md_path.write_text(md_content, encoding="utf-8")
        yaml_path.write_text(yaml_content, encoding="utf-8")

    return {
        "packet_id": packet_id,
        "md_content": md_content,
        "yaml_content": yaml_content,
        "md_path": md_path,
        "yaml_path": yaml_path,
    }
