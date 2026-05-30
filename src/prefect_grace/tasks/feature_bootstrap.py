from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from prefect_grace.models import FeatureRecord, FeatureStatus, PacketRecord, PacketStatus, ReasoningProfile, slugify
from prefect_grace.tasks.architect_artifacts import default_architect_artifact_plan
from prefect_grace.tasks.grace_ids import grace_refs_for_packet
from prefect_grace.tasks.planner_contract import default_wave_plan_contract, materialize_planner_contract
from prefect_grace.tasks import state_store
from prefect_grace.tasks.state_store import append_record, find_record, update_record

FEATURES_DIR = Path(__file__).resolve().parents[1] / "packets"
TEMPLATE_DIR = Path(__file__).resolve().parents[1] / "templates"
STATE_ROOT = Path(__file__).resolve().parents[1] / "state"
PACKET_CONTRACT_START = "FINAL_PACKET_CONTRACT_JSON"
PACKET_CONTRACT_END = "END_FINAL_PACKET_CONTRACT_JSON"


def _render_template(template_name: str, replacements: dict[str, str]) -> str:
    template = (TEMPLATE_DIR / template_name).read_text(encoding="utf-8")
    for key, value in replacements.items():
        template = template.replace("{{ " + key + " }}", value)
    return template


def _bullet_lines(items: list[str] | None) -> str:
    cleaned = [item.strip() for item in items or [] if item and item.strip()]
    return "\n".join(f"- {item}" for item in cleaned) if cleaned else "-"


def _numbered_lines(items: list[str] | None) -> str:
    cleaned = [item.strip() for item in items or [] if item and item.strip()]
    return "\n".join(f"{index}. {item}" for index, item in enumerate(cleaned, start=1)) if cleaned else "1."


def _verification_lines(profile: dict[str, str] | None) -> str:
    merged = {
        "backend": "not required",
        "frontend": "not required",
        "observability": "artifact review only",
    }
    merged.update(profile or {})
    lines: list[str] = []
    for key, value in merged.items():
        lines.extend(_nested_bullet_lines(key, value))
    return "\n".join(lines) if lines else "-"


def _nested_bullet_lines(key: str, value: Any, *, indent: int = 0) -> list[str]:
    prefix = "  " * indent
    if isinstance(value, dict):
        lines = [f"{prefix}- {key}:"]
        for nested_key, nested_value in value.items():
            lines.extend(_nested_bullet_lines(str(nested_key), nested_value, indent=indent + 1))
        return lines
    if isinstance(value, list):
        lines = [f"{prefix}- {key}:"]
        for item in value:
            if isinstance(item, dict):
                lines.append(f"{prefix}  -")
                for nested_key, nested_value in item.items():
                    lines.extend(_nested_bullet_lines(str(nested_key), nested_value, indent=indent + 2))
            else:
                lines.append(f"{prefix}  - {item}")
        return lines
    return [f"{prefix}- {key}: {value}"]


def _execution_hint_lines(hints: dict[str, Any] | None) -> str:
    if not hints:
        return "-"
    lines: list[str] = []
    for key, value in hints.items():
        if value in (None, "", [], {}):
            continue
        if isinstance(value, list):
            if not value:
                continue
            lines.append(f"- {key}:")
            lines.extend(f"  - {item}" for item in value)
        else:
            lines.append(f"- {key}: {value}")
    return "\n".join(lines) if lines else "-"


def _normalize_packet_type(value: Any) -> str:
    packet_type = str(value or "").strip().lower().replace("-", "_")
    aliases = {
        "gate": "gate_decision",
        "decision": "gate_decision",
        "gate_decision": "gate_decision",
        "gate-decision": "gate_decision",
        "rework": "rework",
        "execution": "execution",
    }
    packet_type = aliases.get(packet_type, packet_type)
    if packet_type not in {"execution", "rework", "gate_decision"}:
        return "execution"
    return packet_type


def infer_packet_type(
    *,
    role: str,
    title: str,
    wave_id: str,
    parent_packet_id: str | None = None,
    explicit: Any = None,
) -> str:
    normalized = _normalize_packet_type(explicit)
    if explicit not in (None, ""):
        return normalized
    lowered_title = str(title or "").strip().lower()
    normalized_role = str(role or "").strip().lower()
    if parent_packet_id or "rework" in lowered_title:
        return "rework"
    if normalized_role == "reviewer":
        return "gate_decision"
    if normalized_role == "architect" and str(wave_id or "").strip().upper() != "W00":
        return "gate_decision"
    if "gate" in lowered_title or "verdict" in lowered_title or "decision" in lowered_title:
        return "gate_decision"
    return normalized


def _packet_contract_payload(packet: dict[str, Any]) -> dict[str, Any]:
    return {
        "packet_id": str(packet.get("packet_id") or ""),
        "feature_id": str(packet.get("feature_id") or ""),
        "wave_id": str(packet.get("wave_id") or ""),
        "packet_type": infer_packet_type(
            role=str(packet.get("role") or ""),
            title=str(packet.get("title") or ""),
            wave_id=str(packet.get("wave_id") or ""),
            parent_packet_id=packet.get("parent_packet_id"),
            explicit=packet.get("packet_type"),
        ),
        "role": str(packet.get("role") or ""),
        "reasoning": str(packet.get("reasoning") or ""),
        "title": str(packet.get("title") or ""),
        "summary": str(packet.get("summary") or ""),
        "write_scope": list(packet.get("write_scope") or []),
        "inputs": list(packet.get("inputs") or []),
        "acceptance_criteria": list(packet.get("acceptance_criteria") or []),
        "verification_profile": dict(packet.get("verification_profile") or {}),
        "execution_hints": dict(packet.get("execution_hints") or {}),
        "reviewer_gate": list(packet.get("reviewer_gate") or []),
        "dependencies": list(packet.get("dependencies") or []),
        "notes": list(packet.get("notes") or []),
        "parent_packet_id": packet.get("parent_packet_id"),
        "review_target_packet_id": packet.get("review_target_packet_id"),
        "route_classification": packet.get("route_classification"),
        "requested_rework_mode": packet.get("requested_rework_mode"),
        "rework_mode": packet.get("rework_mode"),
    }


def render_packet_markdown(packet: dict[str, Any]) -> str:
    grace_refs = {
        "grace_feature_ref": str(packet.get("grace_feature_ref") or ""),
        "grace_wave_ref": str(packet.get("grace_wave_ref") or ""),
        "grace_packet_ref": str(packet.get("grace_packet_ref") or ""),
    }
    contract_payload = _packet_contract_payload(packet)
    return _render_template(
        "packet.md",
        {
            "packet_id": str(packet.get("packet_id") or ""),
            "title": str(packet.get("title") or packet.get("packet_id") or ""),
            "grace_ids": _bullet_lines(
                [
                    f"feature_ref: `{grace_refs['grace_feature_ref']}`",
                    f"wave_ref: `{grace_refs['grace_wave_ref']}`",
                    f"packet_ref: `{grace_refs['grace_packet_ref']}`",
                ]
            ),
            "packet_type": infer_packet_type(
                role=str(packet.get("role") or ""),
                title=str(packet.get("title") or ""),
                wave_id=str(packet.get("wave_id") or ""),
                parent_packet_id=packet.get("parent_packet_id"),
                explicit=packet.get("packet_type"),
            ),
            "summary": str(packet.get("summary") or ""),
            "wave_id": str(packet.get("wave_id") or ""),
            "role": str(packet.get("role") or ""),
            "reasoning": str(packet.get("reasoning") or ""),
            "parent_packet_id": (
                f"`{packet['parent_packet_id']}`"
                if str(packet.get("parent_packet_id") or "").strip()
                else "-"
            ),
            "review_target_packet_id": (
                f"`{packet['review_target_packet_id']}`"
                if str(packet.get("review_target_packet_id") or "").strip()
                else "-"
            ),
            "write_scope": _bullet_lines(list(packet.get("write_scope") or [])),
            "inputs": _bullet_lines(list(packet.get("inputs") or [])),
            "acceptance_criteria": _bullet_lines(list(packet.get("acceptance_criteria") or [])),
            "verification_profile": _verification_lines(dict(packet.get("verification_profile") or {})),
            "execution_hints": _execution_hint_lines(dict(packet.get("execution_hints") or {})),
            "reviewer_gate": _bullet_lines(list(packet.get("reviewer_gate") or [])),
            "dependencies": _bullet_lines(list(packet.get("dependencies") or [])),
            "notes": _bullet_lines(list(packet.get("notes") or [])),
            "contract_json": json.dumps(contract_payload, ensure_ascii=False, indent=2),
        },
    )


def sync_packet_file(packet: dict[str, Any]) -> dict[str, Any]:
    raw_path = str(packet.get("packet_path") or "").strip()
    if not raw_path:
        return packet
    packet_path = Path(raw_path)
    packet_path.parent.mkdir(parents=True, exist_ok=True)
    packet_path.write_text(render_packet_markdown(packet), encoding="utf-8")
    return packet


def _write_wave_plan(feature_dir: Path, feature_id: str, title: str, packets: list[dict[str, Any]]) -> str:
    wave_ids = sorted({str(packet.get("wave_id") or "").strip().upper() for packet in packets if str(packet.get("wave_id") or "").strip()})
    wave_lines = [
        (
            f"{wave_id} — architect formalization"
            if wave_id == "W00"
            else f"{wave_id} — packet execution and gates"
        )
        for wave_id in wave_ids
    ] or ["W00 — architect formalization"]
    packet_registry = [
        f"`{packet['packet_id']}` — role `{packet['role']}` — {packet['title']}"
        for packet in packets
    ]
    dependency_rules = [
        f"`{packet['packet_id']}` depends on {', '.join(packet.get('dependencies') or ['nothing'])}"
        for packet in packets
    ]
    wave_plan_path = feature_dir / "wave-plan.md"
    wave_plan_path.write_text(
        _render_template(
            "wave_plan.md",
            {
                "feature_id": feature_id,
                "objective": title,
                "waves": _numbered_lines(wave_lines),
                "packet_registry": _bullet_lines(packet_registry),
                "dependency_rules": _bullet_lines(dependency_rules),
                "exit_conditions": _bullet_lines(
                    [
                        "Architect packet produced compact packet-first artifacts.",
                        "Planner is used only when explicitly requested or decomposition must change.",
                        "Execution packets, verifier evidence, reviewer gate, and architect wave gate complete in order.",
                    ]
                ),
            },
        ),
        encoding="utf-8",
    )
    return str(wave_plan_path)


def _delete_packet_if_exists(packet_id: str | None, *, state_root: Path | str) -> None:
    resolved_id = str(packet_id or "").strip()
    if not resolved_id:
        return
    state_path = Path(state_root) / "packets.yaml"
    if not state_path.exists():
        return

    def mutator(payload: dict[str, Any]) -> dict[str, Any]:
        payload["packets"] = [
            item
            for item in list(payload.get("packets") or [])
            if str(item.get("packet_id") or "").strip() != resolved_id
        ]
        return payload

    state_store.update_state("packets", mutator, state_root=state_root)


def bootstrap_feature(
    feature_id: str,
    title: str,
    summary: str,
    business_context: dict[str, Any] | None = None,
    *,
    state_root: Path | str | None = None,
) -> dict[str, Any]:
    resolved_state_root = Path(state_root) if state_root else STATE_ROOT
    feature_dir = FEATURES_DIR / feature_id
    feature_dir.mkdir(parents=True, exist_ok=True)
    (feature_dir / "packets").mkdir(exist_ok=True)
    (feature_dir / "reviews").mkdir(exist_ok=True)
    (feature_dir / "decisions").mkdir(exist_ok=True)
    (feature_dir / "evidence").mkdir(exist_ok=True)

    brief_path = feature_dir / "feature-brief.md"
    brief_text = _render_template(
        "feature_brief.md",
        {
            "feature_id": feature_id,
            "business_intent": summary,
            "desired_outcome": title,
            "in_scope": _bullet_lines(
                list((business_context or {}).get("scope") or [
                    "Formalize the feature into GRACE artifacts.",
                    "Slice the feature into bounded execution packets.",
                    "Prepare implementation, verification, and review flow.",
                ])
            ),
            "out_of_scope": _bullet_lines(
                list((business_context or {}).get("non_goals") or [
                    "Full production rollout of the feature.",
                    "Unbounded refactors outside the packet scopes.",
                ])
            ),
            "impacted_surfaces": _bullet_lines(
                list((business_context or {}).get("impacted_surfaces") or [
                    "backend: packet orchestration and state tracking.",
                    "frontend: define visual verification requirements when UI is touched.",
                    "automation: Prefect flows and Codex launcher integration.",
                    "observability: logs, evidence, and reviewer verdict routing.",
                ])
            ),
            "impacted_grace_artifacts": _bullet_lines(
                list((business_context or {}).get("impacted_grace_artifacts") or [
                    "requirements.xml: feature scope and invariants if they change.",
                    "technology.xml: runtime or toolchain updates if they change.",
                    "development-plan.xml: execution topology and packet model.",
                    "knowledge-graph.xml: impacted modules and flow links.",
                    "verification-matrix.md: required tests and evidence gates.",
                ])
            ),
            "wave_proposal": _numbered_lines(
                list((business_context or {}).get("wave_proposal") or [
                    "Architect formalizes the feature and impacted GRACE deltas.",
                    "Planner runs only when decomposition is complex or explicitly requested.",
                    "Coder, verifier, reviewer, and architect execute W01.",
                ])
            ),
            "open_decisions": _bullet_lines(
                list((business_context or {}).get("open_decisions") or [
                    "Confirm whether the feature needs frontend visual proof.",
                    "Confirm whether the first execution should stay dry-run or use real Codex runs.",
                ])
            ),
            "acceptance_criteria": _bullet_lines(list((business_context or {}).get("acceptance_criteria") or [])),
            "visual_expectations": _bullet_lines(list((business_context or {}).get("visual_expectations") or [])),
        },
    )
    if not brief_path.exists() or business_context:
        brief_path.write_text(brief_text, encoding="utf-8")

    try:
        find_record("features", "features", "feature_id", feature_id, state_root=resolved_state_root)
        return update_record(
            "features",
            "features",
            "feature_id",
            feature_id,
            {
                "title": title,
                "summary": summary,
                "feature_dir": str(feature_dir),
                "business_context": business_context or {},
            },
            state_root=resolved_state_root,
        )
    except KeyError:
        record = FeatureRecord(
            feature_id=feature_id,
            title=title,
            summary=summary,
            status=FeatureStatus.DRAFT,
            feature_dir=str(feature_dir),
            business_context=business_context or {},
        ).to_dict()
        append_record("features", "features", record, state_root=resolved_state_root)
        return record


def mark_feature_status(
    feature_id: str,
    status: FeatureStatus,
    *,
    blocker_reasons: list[str] | None = None,
    state_root: Path | str | None = None,
) -> dict[str, Any]:
    resolved_state_root = Path(state_root) if state_root else STATE_ROOT
    updates: dict[str, Any] = {"status": status.value}
    if blocker_reasons is not None:
        updates["blocker_reasons"] = list(blocker_reasons)
    elif status not in {
        FeatureStatus.BLOCKED,
        FeatureStatus.PRODUCT_BLOCKED,
        FeatureStatus.VERIFICATION_BLOCKED,
        FeatureStatus.PIPELINE_INVALID,
        FeatureStatus.ENVIRONMENT_BLOCKED,
    }:
        updates["blocker_reasons"] = []
    return update_record("features", "features", "feature_id", feature_id, updates, state_root=resolved_state_root)


def create_packet(
    *,
    feature_id: str,
    wave_id: str,
    title: str,
    role: str,
    reasoning: ReasoningProfile,
    summary: str,
    write_scope: list[str] | None = None,
    inputs: list[str] | None = None,
    acceptance_criteria: list[str] | None = None,
    verification_profile: dict[str, str] | None = None,
    reviewer_gate: list[str] | None = None,
    dependencies: list[str] | None = None,
    notes: list[str] | None = None,
    parent_packet_id: str | None = None,
    review_target_packet_id: str | None = None,
    packet_type: str | None = None,
    execution_hints: dict[str, Any] | None = None,
    status: PacketStatus = PacketStatus.READY,
    state_root: Path | str | None = None,
) -> dict[str, Any]:
    resolved_state_root = Path(state_root) if state_root else STATE_ROOT
    packet_slug = slugify(title)
    packet_id = f"{feature_id}-{wave_id}-{packet_slug}".upper()
    grace_refs = grace_refs_for_packet({"feature_id": feature_id, "wave_id": wave_id, "packet_id": packet_id})
    feature_dir = FEATURES_DIR / feature_id
    packet_dir = feature_dir / "packets"
    packet_dir.mkdir(parents=True, exist_ok=True)
    packet_path = packet_dir / f"{packet_id}.md"
    record = PacketRecord(
        packet_id=packet_id,
        feature_id=feature_id,
        wave_id=wave_id,
        grace_feature_ref=grace_refs["grace_feature_ref"],
        grace_wave_ref=grace_refs["grace_wave_ref"],
        grace_packet_ref=grace_refs["grace_packet_ref"],
        title=title,
        summary=summary,
        role=role,
        reasoning=reasoning,
        status=status,
        packet_type=infer_packet_type(
            role=role,
            title=title,
            wave_id=wave_id,
            parent_packet_id=parent_packet_id,
            explicit=packet_type,
        ),
        write_scope=list(write_scope or []),
        inputs=list(inputs or []),
        acceptance_criteria=list(acceptance_criteria or []),
        reviewer_gate=list(reviewer_gate or []),
        notes=list(notes or []),
        dependencies=dependencies or [],
        parent_packet_id=parent_packet_id,
        review_target_packet_id=review_target_packet_id,
        verification_profile=verification_profile or {},
        execution_hints=execution_hints or {},
        packet_path=str(packet_path),
    ).to_dict()
    try:
        find_record("packets", "packets", "packet_id", packet_id, state_root=resolved_state_root)
        stored = update_record("packets", "packets", "packet_id", packet_id, record, state_root=resolved_state_root)
    except KeyError:
        append_record("packets", "packets", record, state_root=resolved_state_root)
        stored = record
    return sync_packet_file(stored)


def seed_test_feature(
    *,
    feature_id: str,
    title: str,
    summary: str,
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
    agent_workdir: str | None = None,
    agent_sandbox: str | None = None,
    business_context: dict[str, Any] | None = None,
    planner_contract: dict[str, Any] | None = None,
    include_planner_packet: bool = False,
    materialize_execution_packets: bool = True,
    state_root: Path | str | None = None,
) -> dict[str, Any]:
    resolved_state_root = Path(state_root) if state_root else STATE_ROOT
    business_context = dict(business_context or {})
    impacted_surfaces = list(business_context.get("impacted_surfaces") or [])
    if not impacted_surfaces:
        impacted_surfaces = [
            "frontend: the existing Day dev runtime indicator slice only.",
            "automation: Prefect packet orchestration only if the feature explicitly asks to validate pipeline behavior.",
            "observability: packet-local evidence collection only if explicitly required by the feature.",
        ]
    business_context["impacted_surfaces"] = impacted_surfaces

    impacted_grace_artifacts = list(business_context.get("impacted_grace_artifacts") or [])
    if not impacted_grace_artifacts:
        impacted_grace_artifacts = [
            "requirements.xml: only if the business scope/invariants change.",
            "technology.xml: only if the runtime/tooling contract changes.",
            "development-plan.xml: only if execution topology or packet model changes.",
            "knowledge-graph.xml: only if module/slice links change.",
            "verification-matrix.md: only if verification gates or evidence rules change.",
        ]
    business_context["impacted_grace_artifacts"] = impacted_grace_artifacts

    feature = bootstrap_feature(feature_id=feature_id, title=title, summary=summary, business_context=business_context, state_root=resolved_state_root)
    feature_dir = Path(str(feature.get("feature_dir") or (FEATURES_DIR / feature_id)))
    architect_artifact_plan = default_architect_artifact_plan(
        feature_id=feature_id,
        title=title,
        summary=summary,
        business_context=business_context,
    )
    base_execution_hints = {
        key: value
        for key, value in {
            "workdir": agent_workdir,
            "sandbox": agent_sandbox,
        }.items()
        if value not in (None, "")
    }

    architect_packet = create_packet(
        feature_id=feature_id,
        wave_id="W00",
        title="Architect Formalization",
        role="architect",
        reasoning=ReasoningProfile.XHIGH,
        summary="Formalize the business feature into compact packet-first GRACE artifacts and define execution boundaries.",
        write_scope=[
            "Feature-local packet-first artifacts for this feature.",
            "Impacted sections of core GRACE documents only when root_deltas require them.",
        ],
        inputs=[
            f"Feature brief `{feature_id}/feature-brief.md`.",
            "Compact business context and directly relevant repository baseline.",
        ],
        acceptance_criteria=[
            "Goal, waves, bounded scopes, packet list, and next action are explicit.",
            "Architect produces packet-first artifacts by default.",
            "Open decisions are separated from execution-ready facts.",
            "Wave plan reflects every wave represented by packet candidates.",
        ],
        verification_profile={
            "backend": "not required",
            "frontend": "not required",
            "observability": "artifact review and consistency check",
        },
        reviewer_gate=[
            "No missing artifact delta for impacted surfaces.",
            "No silent scope expansion.",
        ],
        notes=[
            "Do not materialize local GRACE slice docs unless explicitly requested with real root_deltas.",
            "Write feature brief, wave plan, execution packet, and architect manifest before direct execution.",
            "Keep frontend verification explicit if UI is touched.",
            "Return FINAL_ARCHITECT_ARTIFACT_PLAN_JSON markers.",
        ],
        execution_hints=base_execution_hints,
        state_root=resolved_state_root,
    )

    planner_packet = None
    if include_planner_packet:
        planner_packet = create_packet(
            feature_id=feature_id,
            wave_id="W00",
            title="Planner Slicing",
            role="planner",
            reasoning=ReasoningProfile.XHIGH,
            summary="Slice the feature into waves and execution packets with explicit dependencies and acceptance gates.",
            write_scope=[
                "Feature-local wave plan.",
                "Packet definitions for execution waves.",
            ],
            inputs=[
                architect_packet["packet_id"],
                "Architect manifest.",
                f"Feature brief `{feature_id}/feature-brief.md`.",
            ],
            acceptance_criteria=[
                "Every packet has one primary write scope.",
                "Verification and reviewer gates are explicit.",
                "Dependencies allow deterministic execution order.",
                "Planner returns parseable JSON wave contract.",
            ],
            verification_profile={
                "backend": "not required",
                "frontend": "not required",
                "observability": "artifact dependency review",
            },
            reviewer_gate=[
                "No oversized packets.",
                "No packet without verification expectations.",
            ],
            dependencies=[architect_packet["packet_id"]],
            notes=[
                "Planner runs only when explicitly requested or when decomposition must change.",
                "Flag architect escalation when decomposition is ambiguous.",
                "Return FINAL_GRACE_WAVE_PLAN_JSON markers.",
            ],
            execution_hints=base_execution_hints,
            state_root=resolved_state_root,
        )

    materialized: dict[str, Any] = {
        "waves": [],
        "packets": [],
        "packets_by_key": {},
        "wave_plan_path": _write_wave_plan(
            feature_dir,
            feature_id,
            title,
            [architect_packet, *([planner_packet] if planner_packet else [])],
        ),
    }
    if materialize_execution_packets:
        contract = planner_contract or default_wave_plan_contract(
            feature_id=feature_id,
            implementation_title=implementation_title,
            implementation_summary=implementation_summary,
            verifier_backend_profile=verifier_backend_profile,
            verifier_frontend_profile=verifier_frontend_profile,
            verifier_frontend_commands=verifier_frontend_commands,
            verifier_observability_profile=verifier_observability_profile,
            verifier_observability_commands=verifier_observability_commands,
            verifier_artifact_globs=verifier_artifact_globs,
            verifier_touches_frontend=verifier_touches_frontend,
            verifier_requires_frontend_visual=verifier_requires_frontend_visual,
            verifier_include_day_live_canary=verifier_include_day_live_canary,
        )
        materialized = materialize_planner_contract(
            feature_id=feature_id,
            planner_packet_id=planner_packet["packet_id"] if planner_packet else "",
            architect_packet_id=architect_packet["packet_id"],
            contract=contract,
            base_execution_hints=base_execution_hints,
            default_verifier_execution_hints={
                "runner": "codex",
                "backend_profile": verifier_backend_profile,
                "frontend_profile": verifier_frontend_profile,
                "frontend_commands": verifier_frontend_commands or [],
                "observability_profile": verifier_observability_profile,
                "observability_commands": verifier_observability_commands or [],
                "artifact_globs": verifier_artifact_globs or [],
                "touches_frontend": verifier_touches_frontend,
                "requires_frontend_visual": verifier_requires_frontend_visual,
                "include_day_live_canary": verifier_include_day_live_canary,
            },
        )

    if not include_planner_packet and planner_packet is None:
        _delete_packet_if_exists(f"{feature_id}-W00-PLANNER-SLICING".upper(), state_root=resolved_state_root)
    return {
        "feature": {
            **find_record("features", "features", "feature_id", feature_id, state_root=resolved_state_root),
            "wave_plan_path": materialized["wave_plan_path"],
        },
        "packets": {
            "architect": architect_packet,
            "planner": planner_packet,
            "generated": materialized["packets"],
            "packets_by_key": materialized["packets_by_key"],
        },
        "planner_contract": materialized,
    }
