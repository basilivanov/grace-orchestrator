from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from prefect_grace.tasks.state_store import find_record, update_record

FEATURES_DIR = Path(__file__).resolve().parents[1] / "packets"
STATE_ROOT = Path(__file__).resolve().parents[1] / "state"


def _slugify(value: str) -> str:
    cleaned = "".join(ch.lower() if ch.isalnum() else "-" for ch in str(value).strip())
    parts = [part for part in cleaned.split("-") if part]
    return "-".join(parts) or "feature-slice"


def _xml_escape(value: Any) -> str:
    text = str(value or "")
    return (
        text.replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace('"', "&quot;")
        .replace("'", "&apos;")
    )


def _string_list(value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, list):
        return [str(item).strip() for item in value if str(item).strip()]
    text = str(value).strip()
    return [text] if text else []


def _xml_list(tag: str, items: list[str], *, indent: str = "  ") -> str:
    if not items:
        return f"{indent}<{tag}>-</{tag}>"
    return "\n".join(f"{indent}<{tag}>{_xml_escape(item)}</{tag}>" for item in items)


def _resolve_slice_slug(feature: dict[str, Any], payload: dict[str, Any]) -> str:
    explicit = str(payload.get("slice_slug") or "").strip()
    if explicit:
        return _slugify(explicit)
    explicit_id = str(payload.get("slice_id") or "").strip()
    if explicit_id:
        return _slugify(explicit_id.replace("SLICE-", ""))
    title = str(feature.get("title") or feature.get("feature_id") or "")
    return _slugify(title)


def _normalize_wave_specs(payload: dict[str, Any]) -> list[dict[str, Any]]:
    waves: list[dict[str, Any]] = []
    for index, raw in enumerate(payload.get("waves") or [], start=1):
        if not isinstance(raw, dict):
            continue
        wave_id = str(raw.get("wave_id") or f"W{index:02d}").strip().upper()
        required = raw.get("required")
        if required is None:
            required = not bool(raw.get("optional"))
        waves.append(
            {
                "wave_id": wave_id,
                "title": str(raw.get("title") or wave_id).strip(),
                "goal": str(raw.get("goal") or raw.get("objective") or raw.get("title") or wave_id).strip(),
                "objective": str(raw.get("objective") or raw.get("goal") or raw.get("title") or wave_id).strip(),
                "required": bool(required),
                "module_refs": _string_list(raw.get("module_refs") or raw.get("modules")),
                "allowed_write_scope": _string_list(raw.get("allowed_write_scope") or raw.get("write_scope")),
                "frozen_scope": _string_list(raw.get("frozen_scope")),
                "observability_scope": str(raw.get("observability_scope") or "none").strip().lower().replace("-", "_"),
                "canonical_flow_commands": _string_list(raw.get("canonical_flow_commands")),
                "allow_degraded_but_expected": bool(raw.get("allow_degraded_but_expected")),
                "verification_commands": _string_list(raw.get("verification_commands") or raw.get("verification")),
                "acceptance_criteria": _string_list(raw.get("acceptance_criteria")),
                "deferred_work": _string_list(raw.get("deferred_work")),
            }
        )
    return waves


def _normalize_packet_candidates(payload: dict[str, Any]) -> list[dict[str, Any]]:
    candidates: list[dict[str, Any]] = []
    for raw in payload.get("packet_candidates") or []:
        if not isinstance(raw, dict):
            continue
        role = str(raw.get("role") or "coder").strip().lower()
        if role not in {"coder", "verifier", "reviewer", "architect", "planner"}:
            role = "coder"
        packet_type = str(raw.get("packet_type") or "").strip().lower().replace("-", "_")
        if packet_type not in {"execution", "rework", "gate_decision"}:
            if role == "reviewer" or role == "architect":
                packet_type = "gate_decision"
            else:
                packet_type = "execution"
        candidates.append(
            {
                "key": str(raw.get("key") or raw.get("title") or "").strip(),
                "wave_id": str(raw.get("wave_id") or "W01").strip().upper(),
                "title": str(raw.get("title") or raw.get("key") or role.title()).strip(),
                "role": role,
                "reasoning": str(raw.get("reasoning") or "").strip().lower() or ("xhigh" if role in {"reviewer", "architect", "planner"} else "high"),
                "packet_type": packet_type,
                "summary": str(raw.get("summary") or raw.get("title") or "").strip(),
                "write_scope": _string_list(raw.get("write_scope")),
                "inputs": _string_list(raw.get("inputs")),
                "acceptance_criteria": _string_list(raw.get("acceptance_criteria")),
                "verification_profile": dict(raw.get("verification_profile") or {}),
                "reviewer_gate": _string_list(raw.get("reviewer_gate")),
                "dependencies": _string_list(raw.get("dependencies")),
                "notes": _string_list(raw.get("notes")),
                "review_target_key": str(raw.get("review_target_key") or "").strip(),
            }
        )
    return candidates


def _wave_plan_md(
    feature: dict[str, Any],
    payload: dict[str, Any],
    *,
    feature_dir: Path,
) -> str:
    waves = _normalize_wave_specs(payload) or _default_wave_specs(feature, payload)
    packet_candidates = _normalize_packet_candidates(payload)
    wave_lines = [
        f"{wave['wave_id']} — {wave['title']}: {wave['goal']} ({'required' if wave.get('required', True) else 'optional'})"
        for wave in waves
    ]
    packet_lines = [
        f"`{packet['wave_id']}` / `{packet['role']}` / `{packet['packet_type']}` — {packet['title']}"
        for packet in packet_candidates
    ]
    dependency_lines = [
        (
            f"`{packet['title']}` depends on {', '.join(packet['dependencies'])}"
            if packet["dependencies"]
            else f"`{packet['title']}` depends on nothing"
        )
        for packet in packet_candidates
    ]
    exit_conditions: list[str] = []
    for wave in waves:
        exit_conditions.extend(
            _string_list(wave.get("acceptance_criteria"))
            or [f"{wave['wave_id']} is accepted against its bounded scope."]
        )
    lines = [
        f"# Wave Plan: {feature.get('feature_id')}",
        "",
        "## Objective",
        str(payload.get("system_goal") or feature.get("summary") or feature.get("title") or feature.get("feature_id")),
        "",
        "## Waves",
        "\n".join(f"{index}. {line}" for index, line in enumerate(wave_lines, start=1)) if wave_lines else "1. W01 — implementation wave",
        "",
        "## Packet Registry",
        "\n".join(f"- {line}" for line in packet_lines) if packet_lines else "- Packets will be materialized from architect output.",
        "",
        "## Dependency Rules",
        "\n".join(f"- {line}" for line in dependency_lines) if dependency_lines else "- Architect packet dependencies are packet-local only.",
        "",
        "## Exit Conditions",
        "\n".join(f"- {line}" for line in exit_conditions) if exit_conditions else "- Wave gates are accepted.",
        "",
        "## Source Of Truth",
        f"- `{feature_dir / 'feature-brief.md'}`",
        f"- `{feature_dir / 'wave-plan.md'}`",
        "",
    ]
    return "\n".join(lines)


def _default_wave_specs(feature: dict[str, Any], payload: dict[str, Any]) -> list[dict[str, Any]]:
    frontend_touched = bool(payload.get("touches_frontend"))
    verification_commands = []
    if frontend_touched:
        verification_commands.extend(
            [
                "./scripts/run_e2e.sh --last-failed",
            ]
        )
    verification_commands.append("docker exec astro-project-backend-1 python3 scripts/pipeline.py")
    return [
        {
            "wave_id": "W01",
            "title": "Implementation and acceptance",
            "goal": str(payload.get("wave_goal") or feature.get("title") or feature.get("feature_id")),
            "objective": str(payload.get("wave_goal") or feature.get("title") or feature.get("feature_id")),
            "required": True,
            "module_refs": _string_list(payload.get("impacted_modules")),
            "allowed_write_scope": _string_list(payload.get("allowed_write_scope")),
            "frozen_scope": _string_list(payload.get("frozen_scope")),
            "observability_scope": "none",
            "canonical_flow_commands": [],
            "allow_degraded_but_expected": False,
            "verification_commands": verification_commands,
            "acceptance_criteria": _string_list(payload.get("acceptance_criteria")),
            "deferred_work": _string_list(payload.get("deferred_work")),
        }
    ]


def _requirements_xml(feature: dict[str, Any], payload: dict[str, Any], *, slice_id: str, project_root: Path, project_key: str = "astro-project") -> str:
    in_scope = _string_list(payload.get("in_scope"))
    out_of_scope = _string_list(payload.get("out_of_scope"))
    invariants = _string_list(payload.get("business_invariants"))
    failures = _string_list(payload.get("expected_failure_handling"))
    defects = _string_list(payload.get("known_defects"))
    success = _string_list(payload.get("success_criteria"))
    use_cases = payload.get("use_cases") or []
    lines = [
        f'<requirements_slice project="{_xml_escape(project_key)}" parent_requirements="{project_root / "requirements.xml"}" updated_at="{datetime.now(timezone.utc).date().isoformat()}" slice_id="{_xml_escape(slice_id)}">',
        f"  <system_goal>{_xml_escape(payload.get('system_goal') or feature.get('summary') or feature.get('title') or feature.get('feature_id'))}</system_goal>",
        "  <scope>",
        "    <in_scope>",
    ]
    if in_scope:
        lines.extend(f"      <item>{_xml_escape(item)}</item>" for item in in_scope)
    else:
        lines.append("      <item>-</item>")
    lines.extend(["    </in_scope>", "    <out_of_scope>"])
    if out_of_scope:
        lines.extend(f"      <item>{_xml_escape(item)}</item>" for item in out_of_scope)
    else:
        lines.append("      <item>-</item>")
    lines.extend(["    </out_of_scope>", "  </scope>", "  <use_cases>"])
    if use_cases:
        for raw in use_cases:
            if not isinstance(raw, dict):
                continue
            uc_id = _xml_escape(raw.get("id") or "UC-SLICE")
            actor = _xml_escape(raw.get("actor") or "user")
            lines.append(f'    <use_case id="{uc_id}" actor="{actor}">')
            lines.append(f"      <summary>{_xml_escape(raw.get('summary') or '')}</summary>")
            for scenario in raw.get("scenarios") or []:
                if not isinstance(scenario, dict):
                    continue
                lines.append(
                    f'      <scenario id="{_xml_escape(scenario.get("id") or "SCN-SLICE")}">{_xml_escape(scenario.get("text") or scenario.get("summary") or "")}</scenario>'
                )
            lines.append("    </use_case>")
    else:
        lines.append('    <use_case id="UC-SLICE" actor="user">')
        lines.append(f"      <summary>{_xml_escape(feature.get('title') or feature.get('summary') or feature.get('feature_id'))}</summary>")
        lines.append("    </use_case>")
    lines.extend(["  </use_cases>", "  <business_invariants>"])
    if invariants:
        lines.extend(f"    <invariant>{_xml_escape(item)}</invariant>" for item in invariants)
    else:
        lines.append("    <invariant>-</invariant>")
    lines.extend(["  </business_invariants>", "  <expected_failure_handling>"])
    if failures:
        lines.extend(f"    <item>{_xml_escape(item)}</item>" for item in failures)
    else:
        lines.append("    <item>-</item>")
    lines.extend(["  </expected_failure_handling>", "  <known_defects>"])
    if defects:
        for index, defect in enumerate(defects, start=1):
            lines.append(f'    <defect id="DEFECT-SLICE-{index}">{_xml_escape(defect)}</defect>')
    else:
        lines.append('    <defect id="DEFECT-SLICE-0">-</defect>')
    lines.extend(["  </known_defects>", "  <success_criteria>"])
    if success:
        for index, criterion in enumerate(success, start=1):
            lines.append(f'    <criterion id="SC-SLICE-{index}">{_xml_escape(criterion)}</criterion>')
    else:
        lines.append('    <criterion id="SC-SLICE-0">-</criterion>')
    lines.extend(["  </success_criteria>", "</requirements_slice>", ""])
    return "\n".join(lines)


def _development_plan_xml(payload: dict[str, Any], *, slice_id: str, project_root: Path, project_key: str = "astro-project") -> str:
    waves = _normalize_wave_specs(payload) or _default_wave_specs({}, payload)
    phase_id = _xml_escape(str(payload.get("phase_id") or "PHASE-SLICE"))
    phase_goal = _xml_escape(str(payload.get("phase_goal") or payload.get("system_goal") or "Deliver the bounded slice safely."))
    lines = [
        f'<development_plan_slice project="{_xml_escape(project_key)}" parent_plan="{project_root / "development-plan.xml"}" updated_at="{datetime.now(timezone.utc).date().isoformat()}" slice_id="{_xml_escape(slice_id)}">',
        f'  <phase id="{phase_id}">',
        f"    <goal>{phase_goal}</goal>",
        "",
    ]
    for wave in waves:
        lines.append(f'    <wave id="{_xml_escape(wave["wave_id"])}">')
        lines.append(f"      <goal>{_xml_escape(wave['goal'])}</goal>")
        for module_ref in wave["module_refs"] or ["M-SLICE"]:
            lines.append(f'      <module_ref id="{_xml_escape(module_ref)}" />')
        lines.append("      <allowed_write_scope>")
        if wave["allowed_write_scope"]:
            lines.extend(f"        <file>{_xml_escape(item)}</file>" for item in wave["allowed_write_scope"])
        else:
            lines.append("        <file>-</file>")
        lines.append("      </allowed_write_scope>")
        lines.append("      <frozen_scope>")
        if wave["frozen_scope"]:
            lines.extend(f"        <file>{_xml_escape(item)}</file>" for item in wave["frozen_scope"])
        else:
            lines.append("        <file>-</file>")
        lines.append("      </frozen_scope>")
        lines.append(f"      <observability_scope>{_xml_escape(wave['observability_scope'])}</observability_scope>")
        lines.append(
            f"      <allow_degraded_but_expected>{str(bool(wave['allow_degraded_but_expected'])).lower()}</allow_degraded_but_expected>"
        )
        lines.append("      <canonical_flow_commands>")
        if wave["canonical_flow_commands"]:
            lines.extend(f"        <command>{_xml_escape(item)}</command>" for item in wave["canonical_flow_commands"])
        else:
            lines.append("        <command>-</command>")
        lines.append("      </canonical_flow_commands>")
        lines.append("      <verification>")
        if wave["verification_commands"]:
            lines.extend(f"        <command>{_xml_escape(item)}</command>" for item in wave["verification_commands"])
        else:
            lines.append("        <command>-</command>")
        lines.append("      </verification>")
        lines.append("      <acceptance_criteria>")
        if wave["acceptance_criteria"]:
            lines.extend(f"        <criterion>{_xml_escape(item)}</criterion>" for item in wave["acceptance_criteria"])
        else:
            lines.append("        <criterion>-</criterion>")
        lines.append("      </acceptance_criteria>")
        if wave["deferred_work"]:
            lines.append("      <deferred_work>")
            lines.extend(f"        <item>{_xml_escape(item)}</item>" for item in wave["deferred_work"])
            lines.append("      </deferred_work>")
        lines.append("    </wave>")
        lines.append("")
    lines.extend(["  </phase>", "</development_plan_slice>", ""])
    return "\n".join(lines)


def _verification_matrix_md(feature: dict[str, Any], payload: dict[str, Any], *, slice_id: str, slice_dir: Path, project_root: Path) -> str:
    vm_ids = payload.get("verification_lanes") or []
    if not vm_ids:
        vm_ids = [
            {
                "vm_id": "VM-SLICE-MAIN",
                "covers": ", ".join(_string_list(payload.get("scenario_ids")) or [slice_id]),
                "checks": _string_list(payload.get("verification_commands")),
                "pass_signal": "; ".join(_string_list(payload.get("acceptance_criteria")) or [feature.get("title") or feature.get("feature_id")]),
            }
        ]
    lines = [
        f"# {feature.get('title') or feature.get('feature_id')} Verification Slice",
        "",
        f"Snapshot boundary: $(git -C {project_root} rev-parse HEAD)",
        f"Parent matrix: `{project_root / 'verification-matrix.md'}`",
        f"Slice id: `{slice_id}`",
        "",
        "## VM IDs",
        "",
        "| VM ID | Covers | Deterministic checks | Pass signal |",
        "| --- | --- | --- | --- |",
    ]
    for raw in vm_ids:
        if not isinstance(raw, dict):
            continue
        vm_id = str(raw.get("vm_id") or "VM-SLICE-MAIN").strip()
        covers = str(raw.get("covers") or slice_id).strip()
        checks = "; ".join(_string_list(raw.get("checks") or raw.get("commands")))
        pass_signal = str(raw.get("pass_signal") or raw.get("signal") or "Slice passes bounded acceptance.").strip()
        lines.append(f"| `{vm_id}` | `{covers}` | {checks or '-'} | {pass_signal} |")
    lines.extend(
        [
            "",
            "## Evidence rules",
            "",
            "- Worker MUST attach exact commands executed and PASS/FAIL result.",
            "- Worker MUST include file-level diff summary grouped by frontend/backend/tests.",
            "- Frontend changes MUST include visual evidence when UI is touched.",
            "- Post-test observability review is mandatory when the slice touches Today, Week, Admin, Catalog, or Billing.",
            "",
            f"Architect slice directory: `{slice_dir}`",
            "",
        ]
    )
    return "\n".join(lines)


def _knowledge_graph_xml(payload: dict[str, Any], *, slice_id: str, project_root: Path, project_key: str = "astro-project") -> str:
    modules = _string_list(payload.get("impacted_modules"))
    flows = payload.get("data_flows") or []
    lines = [
        f'<knowledge_graph_slice project="{_xml_escape(project_key)}" parent_graph="{project_root / "knowledge-graph.xml"}" updated_at="{datetime.now(timezone.utc).date().isoformat()}" slice_id="{_xml_escape(slice_id)}">',
        "  <modules>",
    ]
    if modules:
        for module in modules:
            lines.append(f'    <module id="{_xml_escape(module)}" />')
    else:
        lines.append('    <module id="M-SLICE" />')
    lines.extend(["  </modules>", "  <flow_links>"])
    if flows:
        for flow in flows:
            if not isinstance(flow, dict):
                continue
            lines.append(
                f'    <edge from="{_xml_escape(flow.get("from") or "unknown")}" to="{_xml_escape(flow.get("to") or "unknown")}" type="{_xml_escape(flow.get("type") or "related")}" />'
            )
    else:
        lines.append('    <edge from="feature" to="slice" type="implemented_by" />')
    lines.extend(["  </flow_links>", "</knowledge_graph_slice>", ""])
    return "\n".join(lines)


def _architect_handoff_md(feature: dict[str, Any], payload: dict[str, Any], *, slice_id: str, slice_dir: Path) -> str:
    impacted_modules = _string_list(payload.get("impacted_modules"))
    lines = [
        f"# Architect Handoff: {feature.get('feature_id')}",
        "",
        f"- Slice ID: `{slice_id}`",
        f"- Slice dir: `{slice_dir}`",
        f"- Goal: {payload.get('system_goal') or feature.get('summary') or feature.get('title')}",
        f"- Scope: {'; '.join(_string_list(payload.get('in_scope')) or ['See requirements slice.'])}",
        f"- Out of scope: {'; '.join(_string_list(payload.get('out_of_scope')) or ['See requirements slice.'])}",
        f"- Impacted modules: {', '.join(impacted_modules) if impacted_modules else '-'}",
        f"- Verification surfaces: {'; '.join(_string_list(payload.get('verification_surfaces')) or ['See verification matrix slice.'])}",
        f"- Open decisions: {'; '.join(_string_list(payload.get('open_decisions')) or ['-'])}",
        "",
        "Planner must treat the slice docs in this directory as the source of truth for packet decomposition.",
        "",
    ]
    return "\n".join(lines)


def _execution_packet_md(
    feature: dict[str, Any],
    payload: dict[str, Any],
    *,
    slice_id: str,
    slice_dir: Path,
    project_root: Path,
    requirements_path: Path | None = None,
    development_plan_path: Path | None = None,
    verification_matrix_path: Path | None = None,
    knowledge_graph_path: Path | None = None,
) -> str:
    source_of_truth = [
        str(project_root / "GRACE.md"),
        str(project_root / "requirements.xml"),
        str(project_root / "development-plan.xml"),
        str(project_root / "verification-matrix.md"),
    ]
    for optional_path in (requirements_path, development_plan_path, verification_matrix_path, knowledge_graph_path):
        if optional_path:
            source_of_truth.append(str(optional_path))
    lines = [
        f"# Execution Packet: {feature.get('title') or feature.get('feature_id')}",
        "",
        "## Objective",
        str(payload.get("system_goal") or feature.get("summary") or feature.get("title") or feature.get("feature_id")),
        "",
        "## Slice",
        f"- slice_id: `{slice_id}`",
        f"- slice_dir: `{slice_dir}`",
        "",
        "## Source of truth",
        *[f"- `{item}`" for item in source_of_truth],
        "",
        "## Impacted modules",
        *([f"- `{item}`" for item in _string_list(payload.get("impacted_modules"))] or ["- `-`"]),
        "",
        "## Allowed write scope",
        *([f"- `{item}`" for item in _string_list(payload.get("allowed_write_scope"))] or ["- `See packet contract and architect scope.`"]),
        "",
        "## Frozen scope",
        *([f"- `{item}`" for item in _string_list(payload.get("frozen_scope"))] or ["- `-`"]),
        "",
        "## Execution policy",
        "- Respect the slice requirements and write scope exactly.",
        "- Do not widen scope without architect approval.",
        "- If a crash or 500 appears, add or update a reproduction test before claiming green.",
        "- Verification must include post-test observability review when the slice touches a required surface.",
        "",
        "## Worker deliverables",
        "1. Code changes for the active packet only.",
        "2. Updated or added tests for the affected slice.",
        "3. Verification evidence and observability verdict.",
        "4. Short reviewer-facing note: risks, open questions, and whether the next packet is unblocked.",
        "",
    ]
    return "\n".join(lines)


def _architect_manifest(
    *,
    feature: dict[str, Any],
    payload: dict[str, Any],
    slice_id: str,
    slice_slug: str,
    slice_dir: Path,
    requirements_path: Path,
    development_plan_path: Path,
    verification_matrix_path: Path,
    knowledge_graph_path: Path,
    handoff_path: Path,
    execution_packet_path: Path,
) -> dict[str, Any]:
    return {
        "feature_id": feature.get("feature_id"),
        "title": feature.get("title"),
        "slice_id": slice_id,
        "slice_slug": slice_slug,
        "slice_dir": str(slice_dir),
        "complexity": str(payload.get("complexity", "")).strip().lower() or None,
        "requires_planner": payload.get("requires_planner"),
        "materialization_mode": "legacy_grace_docs" if requirements_path else "packet_first",
        "requirements_slice_path": str(requirements_path) if requirements_path else "",
        "development_plan_slice_path": str(development_plan_path) if development_plan_path else "",
        "verification_matrix_slice_path": str(verification_matrix_path) if verification_matrix_path else "",
        "knowledge_graph_slice_path": str(knowledge_graph_path) if knowledge_graph_path else "",
        "architect_handoff_path": str(handoff_path) if handoff_path else "",
        "execution_packet_path": str(execution_packet_path),
        "impacted_modules": _string_list(payload.get("impacted_modules")),
        "waves": _normalize_wave_specs(payload),
        "packet_candidates": _normalize_packet_candidates(payload),
        "next_action": str(payload.get("next_action") or "materialize_packets").strip() or "materialize_packets",
        "planner_inputs": [
            str(execution_packet_path),
            *(
                [
                    str(requirements_path),
                    str(development_plan_path),
                    str(verification_matrix_path),
                    str(knowledge_graph_path),
                    str(handoff_path),
                ]
                if requirements_path and development_plan_path and verification_matrix_path and knowledge_graph_path and handoff_path
                else []
            ),
        ],
        "root_deltas": payload.get("root_deltas") or {},
        "updated_at": datetime.now(timezone.utc).isoformat(),
    }


def default_architect_artifact_plan(
    *,
    feature_id: str,
    title: str,
    summary: str,
    business_context: dict[str, Any] | None = None,
) -> dict[str, Any]:
    business_context = dict(business_context or {})
    return {
        "slice_id": f"SLICE-{_slugify(feature_id).upper()}",
        "slice_slug": _slugify(title or feature_id),
        "complexity": str(business_context.get("complexity") or "medium").strip().lower(),
        "requires_planner": bool(business_context.get("requires_planner")) if business_context.get("requires_planner") is not None else None,
        "system_goal": summary,
        "in_scope": _string_list(business_context.get("scope")) or [summary],
        "out_of_scope": _string_list(business_context.get("non_goals")),
        "business_invariants": _string_list(business_context.get("business_invariants")),
        "expected_failure_handling": _string_list(business_context.get("expected_failure_handling")),
        "known_defects": _string_list(business_context.get("known_defects")),
        "success_criteria": _string_list(business_context.get("acceptance_criteria")),
        "impacted_modules": _string_list(business_context.get("impacted_modules")),
        "verification_surfaces": _string_list(business_context.get("verification_surfaces")),
        "verification_commands": _string_list(business_context.get("verification_commands")),
        "allowed_write_scope": _string_list(business_context.get("allowed_write_scope")),
        "frozen_scope": _string_list(business_context.get("frozen_scope")),
        "data_flows": business_context.get("data_flows") or [],
        "waves": business_context.get("architect_waves") or [],
        "verification_lanes": business_context.get("verification_lanes") or [],
        "packet_candidates": business_context.get("packet_candidates") or [],
        "use_cases": business_context.get("use_cases") or [],
        "open_decisions": _string_list(business_context.get("open_decisions")),
        "next_action": str(business_context.get("next_action") or "materialize_packets").strip() or "materialize_packets",
        "root_deltas": business_context.get("root_deltas") or {},
        "touches_frontend": bool(business_context.get("touches_frontend")),
    }


def write_architect_artifacts(
    *,
    feature_id: str,
    architect_payload: dict[str, Any],
    state_root: Path | str | None = None,
    project_root: Path | str | None = None,
    project_key: str = "astro-project",
) -> dict[str, Any]:
    resolved_state_root = Path(state_root) if state_root else STATE_ROOT
    resolved_project_root = Path(project_root).resolve() if project_root else Path.cwd()
    docs_dir = resolved_project_root / "docs"
    feature = find_record("features", "features", "feature_id", feature_id, state_root=resolved_state_root)
    feature_dir = Path(str(feature.get("feature_dir") or (FEATURES_DIR / feature_id)))
    feature_dir.mkdir(parents=True, exist_ok=True)
    slice_slug = _resolve_slice_slug(feature, architect_payload)
    slice_id = str(architect_payload.get("slice_id") or f"SLICE-{slice_slug.upper()}").strip()
    slice_dir = docs_dir / slice_slug
    slice_dir.mkdir(parents=True, exist_ok=True)

    root_deltas = architect_payload.get("root_deltas") or {}
    materialize_legacy_grace_docs = bool(
        architect_payload.get("materialize_legacy_grace_docs") and root_deltas
    )
    requirements_path = slice_dir / f"requirements.slice.{slice_slug}.xml" if materialize_legacy_grace_docs else None
    development_plan_path = slice_dir / f"development-plan.slice.{slice_slug}.xml" if materialize_legacy_grace_docs else None
    verification_matrix_path = slice_dir / f"verification-matrix.slice.{slice_slug}.md" if materialize_legacy_grace_docs else None
    knowledge_graph_path = slice_dir / f"knowledge-graph.slice.{slice_slug}.xml" if materialize_legacy_grace_docs else None
    handoff_path = slice_dir / "ARCHITECT_HANDOFF.md" if materialize_legacy_grace_docs else None
    execution_packet_path = slice_dir / "EXECUTION_PACKET.md"
    manifest_path = slice_dir / "architect_manifest.json"
    wave_plan_path = feature_dir / "wave-plan.md"

    if materialize_legacy_grace_docs:
        assert requirements_path and development_plan_path and verification_matrix_path and knowledge_graph_path and handoff_path
        requirements_path.write_text(_requirements_xml(feature, architect_payload, slice_id=slice_id, project_root=resolved_project_root, project_key=project_key), encoding="utf-8")
        development_plan_path.write_text(_development_plan_xml(architect_payload, slice_id=slice_id, project_root=resolved_project_root, project_key=project_key), encoding="utf-8")
        verification_matrix_path.write_text(
            _verification_matrix_md(feature, architect_payload, slice_id=slice_id, slice_dir=slice_dir, project_root=resolved_project_root),
            encoding="utf-8",
        )
        knowledge_graph_path.write_text(_knowledge_graph_xml(architect_payload, slice_id=slice_id, project_root=resolved_project_root, project_key=project_key), encoding="utf-8")
        handoff_path.write_text(_architect_handoff_md(feature, architect_payload, slice_id=slice_id, slice_dir=slice_dir), encoding="utf-8")
    execution_packet_path.write_text(
        _execution_packet_md(
            feature,
            architect_payload,
            slice_id=slice_id,
            slice_dir=slice_dir,
            project_root=resolved_project_root,
            requirements_path=requirements_path,
            development_plan_path=development_plan_path,
            verification_matrix_path=verification_matrix_path,
            knowledge_graph_path=knowledge_graph_path,
        ),
        encoding="utf-8",
    )
    wave_plan_path.write_text(
        _wave_plan_md(
            feature,
            architect_payload,
            feature_dir=feature_dir,
        ),
        encoding="utf-8",
    )

    manifest = _architect_manifest(
        feature=feature,
        payload=architect_payload,
        slice_id=slice_id,
        slice_slug=slice_slug,
        slice_dir=slice_dir,
        requirements_path=requirements_path,
        development_plan_path=development_plan_path,
        verification_matrix_path=verification_matrix_path,
        knowledge_graph_path=knowledge_graph_path,
        handoff_path=handoff_path,
        execution_packet_path=execution_packet_path,
    )
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")

    feature_brief_path = feature_dir / "feature-brief.md"
    updates = {
        "architect_slice_id": slice_id,
        "architect_slice_dir": str(slice_dir),
        "architect_manifest_path": str(manifest_path),
        "execution_packet_path": str(execution_packet_path),
        "architect_materialization_mode": "legacy_grace_docs" if materialize_legacy_grace_docs else "packet_first",
        "architect_handoff_path": str(handoff_path) if handoff_path else "",
        "requirements_slice_path": str(requirements_path) if requirements_path else "",
        "development_plan_slice_path": str(development_plan_path) if development_plan_path else "",
        "verification_matrix_slice_path": str(verification_matrix_path) if verification_matrix_path else "",
        "knowledge_graph_slice_path": str(knowledge_graph_path) if knowledge_graph_path else "",
        "feature_brief_path": str(feature_brief_path),
        "wave_plan_path": str(wave_plan_path),
        "planner_contract": {},
    }
    stored_feature = update_record("features", "features", "feature_id", feature_id, updates, state_root=resolved_state_root)
    return {
        "feature": stored_feature,
        "slice_id": slice_id,
        "slice_slug": slice_slug,
        "slice_dir": str(slice_dir),
        "architect_manifest_path": str(manifest_path),
        "execution_packet_path": str(execution_packet_path),
        "materialization_mode": "legacy_grace_docs" if materialize_legacy_grace_docs else "packet_first",
        "architect_handoff_path": str(handoff_path) if handoff_path else "",
        "requirements_slice_path": str(requirements_path) if requirements_path else "",
        "development_plan_slice_path": str(development_plan_path) if development_plan_path else "",
        "verification_matrix_slice_path": str(verification_matrix_path) if verification_matrix_path else "",
        "knowledge_graph_slice_path": str(knowledge_graph_path) if knowledge_graph_path else "",
        "manifest": manifest,
    }
