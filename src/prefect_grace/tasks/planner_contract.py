from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from prefect_grace.models import PacketStatus, ReasoningProfile, slugify
from prefect_grace.tasks.state_store import find_record, update_record

WAVE_PLAN_MARKER_START = "FINAL_GRACE_WAVE_PLAN_JSON"
WAVE_PLAN_MARKER_END = "END_FINAL_GRACE_WAVE_PLAN_JSON"

FEATURES_DIR = Path(__file__).resolve().parents[1] / "packets"
STATE_ROOT = Path(__file__).resolve().parents[1] / "state"
OBSERVABILITY_SCOPES = {"none", "packet_local", "wave_final"}


def default_wave_plan_contract(
    *,
    feature_id: str,
    implementation_title: str,
    implementation_summary: str,
    verifier_backend_profile: str | None = "backend_quick",
    verifier_frontend_profile: str | None = None,
    verifier_frontend_commands: list[str] | None = None,
    verifier_observability_profile: str | None = None,
    verifier_observability_commands: list[str] | None = None,
    verifier_artifact_globs: list[str] | None = None,
    verifier_touches_frontend: bool = False,
    verifier_requires_frontend_visual: bool = False,
    verifier_include_day_live_canary: bool = False,
) -> dict[str, Any]:
    coder_key = "coder_main"
    verifier_key = "verifier_main"
    reviewer_key = "reviewer_main"
    architect_key = "architect_wave_gate"
    return {
        "waves": [
            {
                "wave_id": "W01",
                "title": "Implementation and acceptance wave",
                "objective": "Implement, verify, review, and architect-accept the first bounded feature slice.",
                "exit_conditions": [
                    "Coder packet is completed within scope.",
                    "Verifier evidence is recorded.",
                    "Reviewer technical gate is accepted or routed to rework.",
                    "Architect wave gate accepts or blocks the wave.",
                ],
            }
        ],
        "packets": [
            {
                "key": coder_key,
                "wave_id": "W01",
                "title": implementation_title,
                "role": "coder",
                "reasoning": ReasoningProfile.HIGH.value,
                "summary": implementation_summary,
                "write_scope": [
                    "Only files required by the packet.",
                    "Bounded implementation/refactor required by the feature brief.",
                ],
                "inputs": ["planner output", "architect formalization", "feature brief"],
                "acceptance_criteria": [
                    "Requested code change is implemented within scope.",
                    "Targeted tests are added or updated if needed.",
                    "Implementation notes are left for verifier and reviewer.",
                ],
                "verification_profile": {
                    "backend": "backend:quick or targeted tests as required by the packet",
                    "frontend": "targeted Playwright run if the packet touches UI",
                    "observability": "post-test log, digest, and trace review",
                },
                "reviewer_gate": ["Packet scope respected.", "Verification handoff notes included."],
                "dependencies": [],
                "notes": ["Prefer root-cause fixes.", "Strengthen logs if the packet touches runtime flow."],
            },
            {
                "key": verifier_key,
                "wave_id": "W01",
                "title": "Verifier Evidence",
                "role": "verifier",
                "reasoning": ReasoningProfile.MEDIUM.value,
                "summary": "Validate the coder packet with the required test profile and observability gate.",
                "write_scope": ["Verification notes and evidence references only."],
                "inputs": [coder_key, "coder packet file"],
                "acceptance_criteria": [
                    "Commands run are recorded.",
                    "Evidence paths are recorded.",
                    "Observability verdict is explicit.",
                    "Frontend visual verdict is explicit when UI is touched.",
                ],
                "verification_profile": {
                    "backend": "execute minimally sufficient backend profile",
                    "frontend": "execute minimally sufficient frontend profile if UI is touched",
                    "observability": "mandatory log, replay, digest, and trace review",
                },
                "reviewer_gate": [
                    "No green-only pass without evidence review.",
                    "Blocking issues are explicit when evidence is missing.",
                ],
                "dependencies": [coder_key],
                "notes": ["Fail the packet if evidence is missing."],
                "execution_hints": {
                    "runner": "codex",
                    "backend_profile": verifier_backend_profile,
                    "frontend_profile": verifier_frontend_profile,
                    "frontend_commands": verifier_frontend_commands or [],
                    "observability_profile": verifier_observability_profile,
                    "observability_commands": verifier_observability_commands or [],
                    "observability_scope": "packet_local",
                    "canonical_flow_commands": [],
                    "touches_frontend": verifier_touches_frontend,
                    "requires_frontend_visual": verifier_requires_frontend_visual,
                    "artifact_globs": verifier_artifact_globs or [],
                    "include_day_live_canary": verifier_include_day_live_canary,
                },
            },
            {
                "key": reviewer_key,
                "wave_id": "W01",
                "title": "Reviewer Verdict",
                "role": "reviewer",
                "reasoning": ReasoningProfile.XHIGH.value,
                "summary": "Judge the packet outcome and decide accepted, rework_required, blocked, or escalate_to_architect.",
                "write_scope": ["Review verdict and blocker notes only."],
                "inputs": [coder_key, verifier_key],
                "acceptance_criteria": [
                    "Exactly one verdict is returned.",
                    "Blockers are actionable.",
                    "Follow-up action is explicit.",
                ],
                "verification_profile": {
                    "backend": "not required",
                    "frontend": "not required",
                    "observability": "consume verifier evidence and notes",
                },
                "reviewer_gate": ["Do not invent new scope.", "Do not accept missing evidence."],
                "dependencies": [coder_key, verifier_key],
                "notes": ["Escalate to architect when the blocker changes decomposition or business semantics."],
                "review_target_key": coder_key,
            },
            {
                "key": architect_key,
                "wave_id": "W01",
                "title": "Architect Wave Gate",
                "role": "architect",
                "reasoning": ReasoningProfile.XHIGH.value,
                "summary": "Accept or reject the completed wave based on business fit, UX, visual proof, and overall feature intent.",
                "write_scope": ["Wave acceptance note only.", "No direct implementation changes in this gate packet."],
                "inputs": [reviewer_key, verifier_key, coder_key, "wave plan"],
                "acceptance_criteria": [
                    "Wave result matches business intent.",
                    "Frontend visual proof is sufficient when UI is touched.",
                    "Technical acceptance is backed by verifier and reviewer evidence.",
                ],
                "verification_profile": {
                    "backend": "consume verifier evidence",
                    "frontend": "review screenshots, Playwright evidence, and expected UI states if UI is touched",
                    "observability": "review verifier observability verdict for the wave",
                },
                "reviewer_gate": ["Architect confirms wave acceptance or rejects it with explicit reasons."],
                "dependencies": [reviewer_key],
                "notes": [
                    "This is the wave-level acceptance gate.",
                    "Frontend visual review belongs here when the wave touches UI.",
                ],
            },
        ],
    }


def normalize_wave_plan_contract(
    payload: dict[str, Any],
    *,
    external_dependency_refs: set[str] | None = None,
) -> dict[str, Any]:
    if not isinstance(payload, dict):
        raise ValueError("Planner contract must be a JSON object")
    packets = payload.get("packets")
    if not isinstance(packets, list) or not packets:
        raise ValueError("Planner contract must contain non-empty packets list")
    waves = payload.get("waves")
    if waves is not None and not isinstance(waves, list):
        raise ValueError("Planner contract waves must be a list")

    normalized_packets: list[dict[str, Any]] = []
    seen_keys: set[str] = set()
    for index, packet in enumerate(packets):
        if not isinstance(packet, dict):
            raise ValueError(f"Packet #{index + 1} must be an object")
        key = str(packet.get("key") or packet.get("title") or f"packet_{index + 1}").strip()
        if not key:
            raise ValueError(f"Packet #{index + 1} key is empty")
        if key in seen_keys:
            raise ValueError(f"Duplicate packet key: {key}")
        seen_keys.add(key)
        role = str(packet.get("role") or "coder").strip().lower()
        if role not in {"coder", "verifier", "reviewer", "architect", "planner"}:
            raise ValueError(f"Unsupported packet role for {key}: {role}")
        reasoning = str(packet.get("reasoning") or _default_reasoning_for_role(role)).strip().lower()
        ReasoningProfile(reasoning)
        normalized_packets.append(
            {
                "key": key,
                "wave_id": str(packet.get("wave_id") or "W01").strip().upper(),
                "title": str(packet.get("title") or key).strip(),
                "role": role,
                "packet_type": _infer_packet_type(
                    role=role,
                    title=str(packet.get("title") or key).strip(),
                    wave_id=str(packet.get("wave_id") or "W01").strip().upper(),
                    explicit=packet.get("packet_type"),
                ),
                "reasoning": reasoning,
                "complexity": _normalize_complexity(packet.get("complexity")),
                "summary": str(packet.get("summary") or packet.get("title") or key).strip(),
                "write_scope": _string_list(packet.get("write_scope")),
                "inputs": _string_list(packet.get("inputs")),
                "acceptance_criteria": _string_list(packet.get("acceptance_criteria")),
                "verification_profile": _normalize_verification_profile(
                    packet.get("verification_profile"),
                    packet_key=key,
                ),
                "reviewer_gate": _string_list(packet.get("reviewer_gate")),
                "dependencies": _string_list(packet.get("dependencies")),
                "notes": _string_list(packet.get("notes")),
                "execution_hints": _normalize_execution_hint_dict(packet.get("execution_hints")),
                "review_target_key": str(packet.get("review_target_key") or "").strip(),
            }
        )



    known_keys = {packet["key"] for packet in normalized_packets}
    allowed_external_refs = {
        str(ref).strip()
        for ref in (external_dependency_refs or set())
        if str(ref).strip()
    }
    for packet in normalized_packets:
        unknown_dependencies = [
            dependency
            for dependency in packet["dependencies"]
            if dependency not in known_keys and dependency not in allowed_external_refs
        ]
        if unknown_dependencies:
            raise ValueError(f"Packet {packet['key']} has unknown dependencies: {unknown_dependencies}")

    normalized_waves: list[dict[str, Any]] = []
    for index, wave in enumerate(waves or [], start=1):
        wave_id = str(wave.get("wave_id") or f"W{index:02d}").strip().upper()
        required = wave.get("required")
        if required is None:
            required = not bool(wave.get("optional"))
        normalized_waves.append(
            {
                **dict(wave),
                "wave_id": wave_id,
                "title": str(wave.get("title") or wave_id).strip(),
                "objective": str(wave.get("objective") or wave.get("goal") or wave.get("title") or wave_id).strip(),
                "required": bool(required),
            }
        )

    return {
        "waves": normalized_waves,
        "packets": normalized_packets,
    }


def materialize_planner_contract(
    *,
    feature_id: str,
    planner_packet_id: str,
    architect_packet_id: str,
    contract: dict[str, Any],
    base_execution_hints: dict[str, Any] | None = None,
    default_verifier_execution_hints: dict[str, Any] | None = None,
    state_root: Path | str | None = None,
) -> dict[str, Any]:
    resolved_state_root = Path(state_root) if state_root else STATE_ROOT
    normalized = normalize_wave_plan_contract(
        contract,
        external_dependency_refs={
            str(planner_packet_id).strip(),
            str(architect_packet_id).strip(),
            "planner output",
            "architect formalization",
        },
    )
    key_to_packet_id: dict[str, str] = {
        packet_spec["key"]: _planned_packet_id(
            feature_id=feature_id,
            wave_id=packet_spec["wave_id"],
            title=packet_spec["title"],
        )
        for packet_spec in normalized["packets"]
    }
    materialized: list[dict[str, Any]] = []
    base_hints = dict(base_execution_hints or {})

    for packet_spec in normalized["packets"]:
        dependencies = [
            resolved
            for dependency in packet_spec["dependencies"]
            if (
                resolved := _resolve_packet_reference(
                    dependency,
                    key_to_packet_id=key_to_packet_id,
                    planner_packet_id=planner_packet_id,
                    architect_packet_id=architect_packet_id,
                )
            )
        ]
        if packet_spec["role"] == "coder" and not dependencies:
            if str(planner_packet_id or "").strip():
                dependencies = [str(planner_packet_id).strip()]
        execution_hints = _resolve_execution_hints(
            packet_spec,
            base_execution_hints=base_hints,
            default_verifier_execution_hints=default_verifier_execution_hints,
        )
        from prefect_grace.tasks.feature_bootstrap import create_packet

        packet = create_packet(
            feature_id=feature_id,
            wave_id=packet_spec["wave_id"],
            title=packet_spec["title"],
            role=packet_spec["role"],
            reasoning=ReasoningProfile(packet_spec["reasoning"]),
            summary=packet_spec["summary"],
            write_scope=packet_spec["write_scope"],
            inputs=_resolve_inputs(packet_spec["inputs"], key_to_packet_id, planner_packet_id, architect_packet_id),
            acceptance_criteria=packet_spec["acceptance_criteria"],
            verification_profile=packet_spec["verification_profile"],
            reviewer_gate=packet_spec["reviewer_gate"],
            dependencies=dependencies,
            notes=packet_spec["notes"],
            packet_type=packet_spec.get("packet_type"),
            execution_hints=execution_hints,
            status=PacketStatus.READY,
            state_root=resolved_state_root,
        )
        review_target_key = str(packet_spec.get("review_target_key") or "").strip()
        if review_target_key:
            review_target_packet_id = _resolve_packet_reference(
                review_target_key,
                key_to_packet_id=key_to_packet_id,
                planner_packet_id=planner_packet_id,
                architect_packet_id=architect_packet_id,
            )
            packet = update_record(
                "packets",
                "packets",
                "packet_id",
                packet["packet_id"],
                {"review_target_packet_id": review_target_packet_id},
                state_root=resolved_state_root,
            )
            from prefect_grace.tasks.feature_bootstrap import sync_packet_file

            packet = sync_packet_file(packet)
        materialized.append(packet)

    wave_plan_path = _write_dynamic_wave_plan(feature_id, normalized["waves"], materialized, state_root=resolved_state_root)
    update_record(
        "features",
        "features",
        "feature_id",
        feature_id,
        {
            "status": "planned",
            "wave_plan_path": wave_plan_path,
            "planner_contract": normalized,
        },
        state_root=resolved_state_root,
    )
    return {
        "waves": normalized["waves"],
        "packets": materialized,
        "packets_by_key": key_to_packet_id,
        "wave_plan_path": wave_plan_path,
    }


def find_first_packet_id(packets: list[dict[str, Any]], *, role: str) -> str:
    for packet in packets:
        if str(packet.get("role") or "") == role:
            return str(packet["packet_id"])
    raise ValueError(f"Planner contract did not produce a {role} packet")


def find_architect_wave_gate_packet_id(packets: list[dict[str, Any]]) -> str:
    for packet in packets:
        if str(packet.get("role") or "") == "architect" and str(packet.get("wave_id") or "").upper() != "W00":
            return str(packet["packet_id"])
    return find_first_packet_id(packets, role="architect")


def _default_reasoning_for_role(role: str) -> str:
    if role in {"architect", "planner", "reviewer"}:
        return ReasoningProfile.XHIGH.value
    if role == "verifier":
        return ReasoningProfile.MEDIUM.value
    return ReasoningProfile.HIGH.value


def _normalize_complexity(value: Any) -> str:
    """Normalize complexity value to simple|medium|complex or empty string."""
    complexity = str(value or "").strip().lower()
    if complexity in {"simple", "medium", "complex"}:
        return complexity
    return ""


def _normalize_packet_type(value: Any) -> str:
    packet_type = str(value or "").strip().lower().replace("-", "_")
    aliases = {
        "gate": "gate_decision",
        "decision": "gate_decision",
        "gate-decision": "gate_decision",
        "rework": "rework",
        "execution": "execution",
    }
    packet_type = aliases.get(packet_type, packet_type)
    if packet_type not in {"execution", "rework", "gate_decision"}:
        return "execution"
    return packet_type


def _infer_packet_type(
    *,
    role: str,
    title: str,
    wave_id: str,
    explicit: Any = None,
) -> str:
    if explicit not in (None, ""):
        return _normalize_packet_type(explicit)
    lowered_title = str(title or "").strip().lower()
    normalized_role = str(role or "").strip().lower()
    if "rework" in lowered_title:
        return "rework"
    if normalized_role == "reviewer":
        return "gate_decision"
    if normalized_role == "architect" and str(wave_id or "").strip().upper() != "W00":
        return "gate_decision"
    if "gate" in lowered_title or "verdict" in lowered_title or "decision" in lowered_title:
        return "gate_decision"
    return "execution"


def _string_list(value: Any) -> list[str]:
    if value in (None, "", []):
        return []
    if isinstance(value, list):
        return [str(item).strip() for item in value if str(item).strip()]
    text = str(value).strip()
    return [text] if text else []


def _resolve_inputs(
    inputs: list[str],
    key_to_packet_id: dict[str, str],
    planner_packet_id: str,
    architect_packet_id: str,
) -> list[str]:
    resolved: list[str] = []
    for item in inputs:
        if item in key_to_packet_id:
            resolved.append(key_to_packet_id[item])
        elif item == "planner output" and str(planner_packet_id).strip():
            resolved.append(planner_packet_id)
        elif item == "architect formalization" and str(architect_packet_id).strip():
            resolved.append(architect_packet_id)
        else:
            resolved.append(item)
    return resolved


def _resolve_packet_reference(
    reference: str,
    *,
    key_to_packet_id: dict[str, str],
    planner_packet_id: str,
    architect_packet_id: str,
) -> str:
    value = str(reference).strip()
    if not value:
        return ""
    if value in key_to_packet_id:
        return key_to_packet_id[value]
    if (value == "planner output" or value == str(planner_packet_id).strip()) and str(planner_packet_id).strip():
        return str(planner_packet_id).strip()
    if (value == "architect formalization" or value == str(architect_packet_id).strip()) and str(architect_packet_id).strip():
        return str(architect_packet_id).strip()
    return value


def _planned_packet_id(*, feature_id: str, wave_id: str, title: str) -> str:
    return f"{feature_id}-{wave_id}-{slugify(title)}".upper()


def _write_dynamic_wave_plan(feature_id: str, waves: list[dict[str, Any]], packets: list[dict[str, Any]], *, state_root: Path | str | None = None) -> str:
    resolved_state_root = Path(state_root) if state_root else STATE_ROOT
    feature = find_record("features", "features", "feature_id", feature_id, state_root=resolved_state_root)
    feature_dir = Path(feature["feature_dir"])
    wave_lines = []
    for wave in waves:
        wave_id = str(wave.get("wave_id") or "W01")
        title = str(wave.get("title") or "Untitled wave")
        objective = str(wave.get("objective") or "")
        required = bool(wave.get("required", True))
        suffix = "required" if required else "optional"
        wave_lines.append(f"{wave_id} — {title}: {objective} ({suffix})".strip())
    if not wave_lines:
        wave_lines = sorted({f"{packet['wave_id']} — generated execution wave" for packet in packets})

    packet_lines = [
        f"`{packet['packet_id']}` — role `{packet['role']}` — {packet['title']}"
        for packet in packets
    ]
    dependency_lines = [
        f"`{packet['packet_id']}` depends on {', '.join(packet.get('dependencies') or ['nothing'])}"
        for packet in packets
    ]
    exit_conditions: list[str] = []
    for wave in waves:
        exit_conditions.extend(_string_list(wave.get("exit_conditions")))
    if not exit_conditions:
        exit_conditions = [
            "All generated coder packets are implemented.",
            "Verifier evidence is recorded for the wave.",
            "Reviewer and architect gates are resolved.",
        ]

    wave_plan_path = feature_dir / "wave-plan.md"
    wave_plan_path.write_text(
        "\n".join(
            [
                f"# Wave Plan: {feature_id}",
                "",
                "## Objective",
                str(feature.get("title") or feature_id),
                "",
                "## Waves",
                _markdown_numbered(wave_lines),
                "",
                "## Packet Registry",
                _markdown_bullets(packet_lines),
                "",
                "## Dependency Rules",
                _markdown_bullets(dependency_lines),
                "",
                "## Exit Conditions",
                _markdown_bullets(exit_conditions),
                "",
            ]
        ),
        encoding="utf-8",
    )
    return str(wave_plan_path)


def _markdown_bullets(items: list[str]) -> str:
    cleaned = [item.strip() for item in items if item and item.strip()]
    return "\n".join(f"- {item}" for item in cleaned) if cleaned else "-"


def _markdown_numbered(items: list[str]) -> str:
    cleaned = [item.strip() for item in items if item and item.strip()]
    return "\n".join(f"{index}. {item}" for index, item in enumerate(cleaned, start=1)) if cleaned else "1."


COMMAND_PATTERN = re.compile(r"`([^`\n]+)`")


def _resolve_execution_hints(
    packet_spec: dict[str, Any],
    *,
    base_execution_hints: dict[str, Any],
    default_verifier_execution_hints: dict[str, Any] | None,
) -> dict[str, Any]:
    packet_hints = dict(packet_spec.get("execution_hints") or {})
    if packet_spec["role"] != "verifier":
        return {**base_execution_hints, **packet_hints}

    verifier_defaults = dict(default_verifier_execution_hints or {})
    hints: dict[str, Any] = {**base_execution_hints, **packet_hints}
    hints.setdefault("runner", "codex")

    verifier_execution = dict(packet_spec.get("verification_profile") or {}).get("execution")
    if isinstance(verifier_execution, dict):
        backend_commands = _extract_commands(verifier_execution.get("backend_commands"))
        frontend_commands = _extract_commands(verifier_execution.get("frontend_commands"))
        observability_commands = _extract_commands(verifier_execution.get("observability_commands"))
        canonical_flow_commands = _extract_commands(verifier_execution.get("canonical_flow_commands"))
        if backend_commands:
            hints["backend_commands"] = backend_commands
            hints.pop("backend_profile", None)
        if frontend_commands:
            hints["frontend_commands"] = frontend_commands
            hints.pop("frontend_profile", None)
        if observability_commands:
            hints["observability_commands"] = observability_commands
            hints.pop("observability_profile", None)
        if canonical_flow_commands:
            hints["canonical_flow_commands"] = canonical_flow_commands
        if "observability_scope" not in packet_hints and verifier_execution.get("observability_scope") not in (None, ""):
            hints["observability_scope"] = _normalize_observability_scope(verifier_execution.get("observability_scope"))
        if "touches_frontend" not in packet_hints and "touches_frontend" in verifier_execution:
            hints["touches_frontend"] = bool(verifier_execution.get("touches_frontend"))
        if "requires_frontend_visual" not in packet_hints and "requires_frontend_visual" in verifier_execution:
            hints["requires_frontend_visual"] = bool(verifier_execution.get("requires_frontend_visual"))
        if "artifact_globs" not in packet_hints and verifier_execution.get("artifact_globs") is not None:
            hints["artifact_globs"] = _string_list(verifier_execution.get("artifact_globs"))
        if "include_day_live_canary" not in packet_hints and "include_day_live_canary" in verifier_execution:
            hints["include_day_live_canary"] = bool(verifier_execution.get("include_day_live_canary"))

    command_locked_keys = {
        "backend_profile": "backend_commands",
        "frontend_profile": "frontend_commands",
        "observability_profile": "observability_commands",
    }
    for key, value in verifier_defaults.items():
        command_key = command_locked_keys.get(key)
        if command_key and hints.get(command_key):
            continue
        if key not in hints and value not in (None, "", []):
            hints[key] = value

    return hints


def _normalize_verification_profile(value: Any, *, packet_key: str) -> dict[str, Any]:
    profile = dict(value or {})
    execution = profile.get("execution")
    if execution is None:
        return profile
    if not isinstance(execution, dict):
        raise ValueError(f"Packet {packet_key} verification_profile.execution must be an object")
    normalized_execution = dict(execution)
    if "observability_scope" in normalized_execution:
        normalized_execution["observability_scope"] = _normalize_observability_scope(
            normalized_execution.get("observability_scope")
        )
    if "canonical_flow_commands" in normalized_execution:
        normalized_execution["canonical_flow_commands"] = _extract_commands(
            normalized_execution.get("canonical_flow_commands")
        )
    profile["execution"] = normalized_execution
    return profile


def _normalize_execution_hint_dict(value: Any) -> dict[str, Any]:
    hints = dict(value or {})
    if "observability_scope" in hints:
        hints["observability_scope"] = _normalize_observability_scope(hints.get("observability_scope"))
    if "canonical_flow_commands" in hints:
        hints["canonical_flow_commands"] = _extract_commands(hints.get("canonical_flow_commands"))
    return hints


def _normalize_observability_scope(value: Any) -> str:
    scope = str(value or "").strip().lower().replace("-", "_")
    if not scope:
        return ""
    if scope not in OBSERVABILITY_SCOPES:
        raise ValueError(f"Unsupported observability_scope: {value}")
    return scope


def _extract_commands(value: Any) -> list[str]:
    if value in (None, "", []):
        return []
    if isinstance(value, list):
        commands: list[str] = []
        for item in value:
            commands.extend(_extract_commands(item))
        return commands
    text = str(value)
    commands = [match.strip() for match in COMMAND_PATTERN.findall(text) if match.strip()]
    if commands:
        return commands
    stripped = text.strip()
    if not stripped or "not required" in stripped.lower():
        return []
    if any(token in stripped for token in ("./", "python", "pnpm", "npm", "docker ", "docker exec", "bash ", "corepack ")):
        return [stripped]
    return []
