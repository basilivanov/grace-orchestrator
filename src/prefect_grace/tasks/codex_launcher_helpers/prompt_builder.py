# AI_HEADER: codex_launcher_helpers
# START_MODULE_CONTRACT
# END_MODULE_CONTRACT
# START_MODULE_MAP
# END_MODULE_MAP

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from prefect_grace.tasks.agent_output_parser import PACKET_DECISION_START, read_agent_message
from prefect_grace.tasks.state_store import find_record

FEATURES_DIR = Path(__file__).resolve().parents[2] / "packets"
DEFAULT_PROMPT_DIGEST_MAX_CHARS = 4000
PACKET_CONTRACT_START = "FINAL_PACKET_CONTRACT_JSON"
PACKET_CONTRACT_END = "END_FINAL_PACKET_CONTRACT_JSON"
ARCHITECT_CONTEXT_FULL = "full"
ARCHITECT_CONTEXT_REWORK = "rework"
ARCHITECT_CONTEXT_GATE_DECISION = "gate_decision"

def _read_text(path: str | Path | None) -> str:
    if not path:
        return ""
    file_path = Path(path)
    if not file_path.exists():
        return ""
    return file_path.read_text(encoding="utf-8").strip()

def _artifact_block(tag: str, path: str | Path | None, **attrs: str) -> str:
    text = _read_text(path)
    if not text:
        return ""
    attr_text = " ".join(f'{key}="{value}"' for key, value in attrs.items() if value)
    prefix = f" {attr_text}" if attr_text else ""
    return f"<{tag}{prefix}>\n{text}\n</{tag}>"

def _compact_text(text: str, *, limit: int = DEFAULT_PROMPT_DIGEST_MAX_CHARS) -> str:
    stripped = text.strip()
    if len(stripped) <= limit:
        return stripped
    head = int(limit * 0.7)
    tail = max(0, limit - head - 64)
    return (
        stripped[:head].rstrip()
        + "\n\n...[prompt digest truncated for size]...\n\n"
        + stripped[-tail:].lstrip()
    )

def _normalize_paths_in_packet(packet_text: str, repo_root: str | Path) -> str:
    """
    Normalize absolute paths in packet text to repo-relative paths.

    This ensures agents work with relative paths regardless of where they execute,
    enabling proper worktree isolation.

    Args:
        packet_text: Raw packet markdown text
        repo_root: Repository root path (e.g., /opt/astro-project)

    Returns:
        Packet text with absolute paths converted to relative paths
    """
    repo_root_str = str(Path(repo_root).resolve())

    # Replace absolute paths with relative paths
    # Match patterns like: /opt/astro-project/backend/... or `/opt/astro-project/backend/...`
    # Replace with: backend/... or `backend/...`

    # Pattern 1: Backtick-quoted paths: `/opt/astro-project/path`
    packet_text = re.sub(
        rf'`{re.escape(repo_root_str)}/([^`]+)`',
        r'`\1`',
        packet_text
    )

    # Pattern 2: Unquoted paths at start of line or after whitespace: /opt/astro-project/path
    packet_text = re.sub(
        rf'(^|\s){re.escape(repo_root_str)}/(\S+)',
        r'\1\2',
        packet_text,
        flags=re.MULTILINE
    )

    # Pattern 3: Paths in markdown lists: - /opt/astro-project/path
    packet_text = re.sub(
        rf'^(\s*[-*]\s+){re.escape(repo_root_str)}/(.+)$',
        r'\1\2',
        packet_text,
        flags=re.MULTILINE
    )

    return packet_text

def _bullet_digest(text: str, *, max_lines: int = 24, max_chars: int = DEFAULT_PROMPT_DIGEST_MAX_CHARS) -> str:
    lines = [line.rstrip() for line in text.splitlines() if line.strip()]
    selected: list[str] = []
    for line in lines:
        keep = False
        stripped = line.lstrip()
        if stripped.startswith(("#", "- ", "* ", "##", "###")):
            keep = True
        if ":" in stripped and len(stripped) < 220:
            keep = True
        if keep:
            selected.append(line)
        if len(selected) >= max_lines:
            break
    if not selected:
        return _compact_text(text, limit=max_chars)
    return _compact_text("\n".join(selected), limit=max_chars)

def _extract_packet_contract_block(text: str) -> str:
    if not text:
        return ""
    pattern = re.compile(
        rf"{re.escape(PACKET_CONTRACT_START)}\s*(\{{.*?\}})\s*{re.escape(PACKET_CONTRACT_END)}",
        re.DOTALL,
    )
    match = pattern.search(text)
    if not match:
        return ""
    return match.group(0).strip()

def _architect_context_mode(packet: dict[str, Any], *, role: str | None = None) -> str:
    normalized_role = str(role or packet.get("role") or "").strip().lower()
    if normalized_role != "architect":
        return ARCHITECT_CONTEXT_FULL
    packet_type = str(packet.get("packet_type") or "").strip().lower().replace("-", "_")
    if packet_type == "rework" or str(packet.get("parent_packet_id") or "").strip():
        return ARCHITECT_CONTEXT_REWORK
    if packet_type == "gate_decision" or str(packet.get("wave_id") or "").strip().upper() != "W00":
        return ARCHITECT_CONTEXT_GATE_DECISION
    return ARCHITECT_CONTEXT_FULL

def _architect_packet_tags(packet: dict[str, Any], *, role: str) -> set[str]:
    if str(role or "").strip().lower() != "architect":
        return set()
    tags = {_architect_context_mode(packet, role=role)}
    tags.add("architect")
    return tags

def _context_text_for_role(*, role: str, tag: str, text: str) -> str:
    strict_digest_roles = {"architect", "planner"}
    if role not in strict_digest_roles:
        return text
    digest_tags = {
        "feature_brief",
        "wave_plan",
        "architect_handoff",
        "execution_packet",
        "requirements_slice",
        "development_plan_slice",
        "verification_matrix_slice",
        "knowledge_graph_slice",
        "dependency_packet",
        "dependency_output",
        "dependency_verification",
        "dependency_review",
        "dependency_wave_review",
    }
    if tag == "dependency_packet":
        contract_only = _extract_packet_contract_block(text)
        if contract_only:
            return contract_only
    if tag == "architect_manifest":
        return _compact_text(text, limit=2500)
    if role == "architect" and tag == "feature_brief":
        return _bullet_digest(text, max_lines=18, max_chars=2200)
    if role == "architect" and tag == "wave_plan":
        return _bullet_digest(text, max_lines=20, max_chars=2400)
    if role == "architect" and tag == "execution_packet":
        return _bullet_digest(text, max_lines=28, max_chars=2600)
    if tag in digest_tags:
        return _bullet_digest(text)
    return _compact_text(text)

def _feature_context_blocks(packet: dict[str, Any], *, role: str, context_mode: str = ARCHITECT_CONTEXT_FULL) -> list[str]:
    feature_dir = FEATURES_DIR / str(packet.get("feature_id"))
    blocks: list[str] = []
    feature_files = [
        ("feature_brief", feature_dir / "feature-brief.md"),
        ("wave_plan", feature_dir / "wave-plan.md"),
    ]
    if role == "architect" and context_mode in {ARCHITECT_CONTEXT_REWORK, ARCHITECT_CONTEXT_GATE_DECISION}:
        feature_files = feature_files
    for tag, path in feature_files:
        text = _read_text(path)
        if text:
            blocks.append(f"<{tag} path=\"{path}\">\n{_context_text_for_role(role=role, tag=tag, text=text)}\n</{tag}>")
    try:
        feature = find_record("features", "features", "feature_id", str(packet.get("feature_id")))
    except KeyError:
        feature = {}
    artifact_specs = [
        ("architect_manifest", "architect_manifest_path"),
        ("architect_handoff", "architect_handoff_path"),
        ("execution_packet", "execution_packet_path"),
        ("requirements_slice", "requirements_slice_path"),
        ("development_plan_slice", "development_plan_slice_path"),
        ("verification_matrix_slice", "verification_matrix_slice_path"),
        ("knowledge_graph_slice", "knowledge_graph_slice_path"),
    ]
    if role == "architect" and context_mode == ARCHITECT_CONTEXT_REWORK:
        artifact_specs = [
            ("architect_manifest", "architect_manifest_path"),
            ("execution_packet", "execution_packet_path"),
        ]
    elif role == "architect" and context_mode == ARCHITECT_CONTEXT_GATE_DECISION:
        artifact_specs = [
            ("architect_manifest", "architect_manifest_path"),
            ("execution_packet", "execution_packet_path"),
        ]
    for tag, key in artifact_specs:
        path = feature.get(key)
        text = _read_text(path)
        if text:
            blocks.append(f"<{tag} path=\"{path}\">\n{_context_text_for_role(role=role, tag=tag, text=text)}\n</{tag}>")
    return blocks

def _dependency_context_blocks(packet: dict[str, Any], *, role: str) -> list[str]:
    blocks: list[str] = []
    related_packet_ids = list(packet.get("dependencies") or [])
    parent_packet_id = packet.get("parent_packet_id")
    if parent_packet_id:
        related_packet_ids.append(parent_packet_id)
    architect_context_mode = _architect_context_mode(packet, role=role)
    if role == "architect" and architect_context_mode == ARCHITECT_CONTEXT_GATE_DECISION:
        related_packet_ids = [
            packet_id
            for packet_id in related_packet_ids
            if _related_packet_role(packet_id) in {"reviewer", "verifier", "coder"}
        ][-3:]
    elif role == "architect" and architect_context_mode == ARCHITECT_CONTEXT_REWORK:
        target_packet_id = str(packet.get("review_target_packet_id") or parent_packet_id or "").strip()
        preferred_ids = [target_packet_id]
        for dependency in list(packet.get("dependencies") or []):
            dependency_role = _related_packet_role(str(dependency))
            if dependency_role in {"reviewer", "verifier"}:
                preferred_ids.append(dependency)
        if parent_packet_id:
            preferred_ids.append(parent_packet_id)
        related_packet_ids = [packet_id for packet_id in preferred_ids if str(packet_id or "").strip()]
    seen: set[str] = set()
    for related_packet_id in related_packet_ids:
        if related_packet_id in seen:
            continue
        seen.add(related_packet_id)
        try:
            related_packet = find_record("packets", "packets", "packet_id", related_packet_id)
        except KeyError:
            continue
        related_packet_text = _read_text(related_packet.get("packet_path"))
        if related_packet_text:
            blocks.append(
                f"<dependency_packet packet_id=\"{related_packet_id}\" role=\"{related_packet.get('role', '')}\">\n"
                f"{_context_text_for_role(role=role, tag='dependency_packet', text=related_packet_text)}\n"
                f"</dependency_packet>"
            )
        related_run = related_packet.get("last_execution_run") or related_packet.get("last_verifier_run") or related_packet.get("last_codex_run") or {}
        related_message = read_agent_message(related_run.get("last_message_path"), related_run.get("stdout_path"))
        include_dependency_output = not (
            role == "architect"
            and architect_context_mode in {ARCHITECT_CONTEXT_REWORK, ARCHITECT_CONTEXT_GATE_DECISION}
            and str(related_packet.get("role") or "").strip().lower() not in {"reviewer", "verifier"}
        )
        if related_message and include_dependency_output:
            blocks.append(
                f"<dependency_output packet_id=\"{related_packet_id}\" role=\"{related_packet.get('role', '')}\">\n"
                f"{_context_text_for_role(role=role, tag='dependency_output', text=related_message)}\n"
                f"</dependency_output>"
            )
        last_verification = related_packet.get("last_verification") or {}
        verification_path = last_verification.get("verification_path")
        verification_block = ""
        if not (role == "architect" and architect_context_mode == ARCHITECT_CONTEXT_REWORK and str(related_packet.get("role") or "") not in {"verifier"}):
            verification_block = _artifact_block(
                "dependency_verification",
                verification_path,
                packet_id=related_packet_id,
                role=str(related_packet.get("role", "")),
            )
        if verification_block:
            blocks.append(verification_block)
        last_review = related_packet.get("last_review") or {}
        review_path = last_review.get("review_path")
        review_block = ""
        if not (role == "architect" and architect_context_mode == ARCHITECT_CONTEXT_REWORK and str(related_packet.get("role") or "") not in {"reviewer", "coder"}):
            review_block = _artifact_block(
                "dependency_review",
                review_path,
                packet_id=related_packet_id,
                role=str(related_packet.get("role", "")),
            )
        if review_block:
            blocks.append(review_block)
        last_wave_review = related_packet.get("last_wave_review") or {}
        wave_review_path = last_wave_review.get("review_path")
        wave_review_block = ""
        if not (role == "architect" and architect_context_mode in {ARCHITECT_CONTEXT_REWORK, ARCHITECT_CONTEXT_GATE_DECISION}):
            wave_review_block = _artifact_block(
                "dependency_wave_review",
                wave_review_path,
                packet_id=related_packet_id,
                role=str(related_packet.get("role", "")),
            )
        if wave_review_block:
            blocks.append(wave_review_block)
    return blocks

def _related_packet_role(packet_id: str) -> str:
    try:
        return str(find_record("packets", "packets", "packet_id", str(packet_id)).get("role") or "").strip().lower()
    except KeyError:
        return ""

def _architect_mode_preamble(context_mode: str) -> str:
    if context_mode == ARCHITECT_CONTEXT_REWORK:
        return "\n".join(
            [
                "ARCHITECT MODE: rework",
                "Resume the existing architectural context. Do not repeat feature formalization or reslice unless the blocker explicitly requires it.",
                "Use only the target packet contract, reviewer blockers, latest relevant verifier evidence, and minimal local wave context.",
                "Return FINAL_DIRECT_REWORK_PACKET_JSON with packet_type semantics: execution, rework, or gate_decision. Do not introduce light/basic packet semantics.",
            ]
        )
    if context_mode == ARCHITECT_CONTEXT_GATE_DECISION:
        return "\n".join(
            [
                "ARCHITECT MODE: gate-decision",
                "Issue a lightweight wave verdict only: accepted, rework_required, blocked, or next-step reasons.",
                "Do not perform start/formalize work and do not pull unrelated feature history into the verdict.",
                "Return FINAL_WAVE_DECISION_JSON.",
            ]
        )
    return "\n".join(
        [
            "ARCHITECT MODE: start/formalize",
            "Formalize the business feature as a compact packet-first plan, define waves, and produce small execution packets.",
            "Keep context bounded: use compact business context, local impacted modules, and only real root deltas.",
            "Keep packet.md as the primary execution contract. Machine JSON must stay as a compact embedded final block.",
        ]
    )

# START_FUNCTION_CONTRACT
# name: build_packet_prompt
# purpose: Build complete prompt for a packet and role prompt.
# inputs: packet dict and role prompt text.
# returns: Prompt string for Codex stdin.
# side_effects: Reads packet/context artifacts from disk.
# emitted_logs: None
# error_behavior: Missing optional artifacts are omitted from context.
# END_FUNCTION_CONTRACT
def build_packet_prompt(packet: dict[str, Any], role_prompt: str) -> str:
    role = str(packet.get("role") or "")
    packet_path = packet.get("packet_path") or ""
    packet_text = _read_text(packet_path)

    # Normalize absolute paths to relative paths for worktree isolation
    repo_root = packet.get("project_root") or Path(__file__).resolve().parents[2]
    packet_text = _normalize_paths_in_packet(packet_text, repo_root)

    execution_hints = dict(packet.get("execution_hints") or {})
    packet_type = str(packet.get("packet_type") or "").strip().lower().replace("-", "_")
    parent_packet_id = str(packet.get("parent_packet_id") or "").strip()
    architect_context_mode = _architect_context_mode(packet, role=role)
    if role == "coder" and execution_hints.get("light_resume_stage"):
        original_title = str(packet.get("title") or "").strip() or str(packet.get("packet_id") or "").strip()
        summary = str(execution_hints.get("light_resume_summary") or packet.get("summary") or "").strip()
        write_scope = [str(item).strip() for item in list(execution_hints.get("light_resume_write_scope") or []) if str(item).strip()]
        inputs = [str(item).strip() for item in list(execution_hints.get("light_resume_inputs") or []) if str(item).strip()]
        acceptance = [
            str(item).strip()
            for item in list(execution_hints.get("light_resume_acceptance_criteria") or [])
            if str(item).strip()
        ]
        reviewer_gate = [
            str(item).strip()
            for item in list(execution_hints.get("light_resume_reviewer_gate") or [])
            if str(item).strip()
        ]
        notes = [str(item).strip() for item in list(execution_hints.get("light_resume_notes") or []) if str(item).strip()]
        reasons = [str(item).strip() for item in list(execution_hints.get("light_resume_reasons") or []) if str(item).strip()]
        light_resume_lines = [
            f"# Packet\n{original_title} (light resume stage)",
            "",
            f"## Summary\n{summary or f'Resume the existing coder context for `{original_title}`.'}",
            "",
            "## Light Resume Routing",
            f"- source_packet_id: {execution_hints.get('light_resume_source_packet_id') or packet.get('packet_id')}",
            f"- attempt: {execution_hints.get('light_resume_attempt') or 1}",
            f"- max_attempts: {execution_hints.get('light_resume_max_attempts') or 1}",
            "- scope: packet_local small fix only",
            "- resume_strategy: packet_parent",
        ]
        if reasons:
            light_resume_lines.extend(["", "## Reviewer Blockers", *[f"- {reason}" for reason in reasons]])
        if write_scope:
            light_resume_lines.extend(["", "## Write Scope", *[f"- {item}" for item in write_scope]])
        if inputs:
            light_resume_lines.extend(["", "## Inputs", *[f"- {item}" for item in inputs]])
        if acceptance:
            light_resume_lines.extend(["", "## Acceptance Criteria", *[f"- {item}" for item in acceptance]])
        if reviewer_gate:
            light_resume_lines.extend(["", "## Reviewer Gate", *[f"- {item}" for item in reviewer_gate]])
        if notes:
            light_resume_lines.extend(["", "## Notes", *[f"- {item}" for item in notes]])
        packet_text = "\n".join(light_resume_lines).strip() + "\n"
    if role == "architect":
        if packet_type == "rework" or parent_packet_id:
            role_prompt = role_prompt.replace(
                "Your job is to either:\n- transform a business feature request into incremental GRACE canon updates, explicit slice boundaries, and an execution-ready wave / packet graph; or\n- accept or reject a completed wave as the architect gate.",
                "Your job is to issue a bounded architect rework packet or escalation decision for the current blocker.",
            )
        elif packet_type == "gate_decision":
            role_prompt = role_prompt.replace(
                "Your job is to either:\n- transform a business feature request into incremental GRACE canon updates, explicit slice boundaries, and an execution-ready wave / packet graph; or\n- accept or reject a completed wave as the architect gate.",
                "Your job is to accept or reject the completed wave as a lightweight architect gate.",
            )
    context_blocks = _feature_context_blocks(
        packet,
        role=role,
        context_mode=architect_context_mode,
    ) + _dependency_context_blocks(packet, role=role)
    context_text = "\n\n".join(context_blocks)
    prompt_parts = [
        role_prompt.strip(),
        "\n".join(
            [
                f"You are running as role: {packet.get('role')}",
                f"Packet ID: {packet.get('packet_id')}",
                f"Feature ID: {packet.get('feature_id')}",
                f"Wave ID: {packet.get('wave_id')}",
                f"Packet type: {packet.get('packet_type') or 'execution'}",
                f"Packet file: {packet_path}",
            ]
        ),
    ]
    if role == "architect":
        prompt_parts.append(_architect_mode_preamble(architect_context_mode))
    if context_text:
        prompt_parts.append(context_text)
    prompt_parts.append(f"<packet>\n{packet_text}\n</packet>")
    return "\n\n".join(prompt_parts) + "\n"

# START_FUNCTION_CONTRACT
# name: role_prompt_for
# purpose: Load role-specific prompt template from prompts directory.
# inputs: role name.
# returns: Prompt template text.
# side_effects: Reads prompt file from disk.
# emitted_logs: None
# error_behavior: Raises file read errors for missing prompt files.
# END_FUNCTION_CONTRACT
def role_prompt_for(role: str) -> str:
    prompt_path = Path(__file__).resolve().parents[2] / "prompts" / f"{role}_prompt.md"
    if prompt_path.exists():
        return prompt_path.read_text(encoding="utf-8")
    return "You are a strict-GRACE agent. Follow the assigned packet exactly."
