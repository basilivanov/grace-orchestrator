# ############################################################################
# AI_HEADER: packet_parser
# ROLE: Parses and normalizes markdown controller packet files for GRACE.
# ############################################################################

# START_MODULE_CONTRACT
# purpose: Parse markdown files into typed packet objects, computing normalized source hashes.
# inputs: Markdown file path or string content.
# returns: ParsedPacket dataclass object.
# side_effects: Reads files from disk if Path is provided.
# emitted_logs: none.
# error_behavior: Raises ValueError if strict validation fails.
# END_MODULE_CONTRACT

# START_MODULE_MAP
# mapping:
#   - class: ParsedPacket
#   - function: compute_normalized_source_hash
#   - function: compute_packet_source_hash
#   - function: packet_to_canonical_sidecar_payload
#   - function: dump_packet_sidecar_payload
#   - function: load_packet_sidecar_payload
#   - function: parse_packet_markdown
# END_MODULE_MAP

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

#START_BLOCK_MODELS
@dataclass
class ParsedPacket:
    packet_id: str
    feature_id: str
    wave_id: str
    title: str
    objective: str
    status: str = ""
    phase: str = ""
    depends_on: list[str] = field(default_factory=list)
    modules: list[str] = field(default_factory=list)
    allowed_write_scope: list[str] = field(default_factory=list)
    frozen_scope: list[str] = field(default_factory=list)
    must_preserve: list[str] = field(default_factory=list)
    verification: str = ""
    expected_evidence: list[str] = field(default_factory=list)
    escalation_triggers: list[str] = field(default_factory=list)
    source_hash: str = ""
    section_lines: dict[str, int] = field(default_factory=dict)
    legacy_warnings: list[str] = field(default_factory=list)

#END_BLOCK_MODELS
#START_BLOCK_PARSER_CORE
# Sections to exclude from source hash computation
EXCLUDED_SECTIONS_RE = re.compile(
    r"^#+\s+(evidence|reviewer\s+notes|review|runtime|artifacts)\b",
    re.IGNORECASE,
)

PACKET_SIDECAR_NAME = "EXECUTION_PACKET.yaml"
PACKET_SIDECAR_ARTIFACT_TYPE = "execution_packet"
PACKET_SIDECAR_CANONICAL_FIELDS = [
    "schema_version",
    "artifact_type",
    "packet_id",
    "feature_id",
    "wave_id",
    "title",
    "objective",
    "status",
    "phase",
    "depends_on",
    "modules",
    "allowed_write_scope",
    "frozen_scope",
    "must_preserve",
    "verification",
    "expected_evidence",
    "escalation_triggers",
]
PACKET_SIDECAR_CANONICAL_FIELD_SET = set(PACKET_SIDECAR_CANONICAL_FIELDS)
PACKET_SIDECAR_LIST_FIELDS = {
    "depends_on",
    "modules",
    "allowed_write_scope",
    "frozen_scope",
    "must_preserve",
    "expected_evidence",
    "escalation_triggers",
}

# START_FUNCTION_CONTRACT
# name: compute_normalized_source_hash
# purpose: Computes a stable SHA-256 hash of the packet, ignoring runtime sections.
# inputs:
#   content: raw markdown content.
# returns: hexadecimal SHA-256 hash string.
# side_effects: none.
# emitted_logs: none.
# error_behavior: none.
# END_FUNCTION_CONTRACT
def compute_normalized_source_hash(content: str) -> str:
    normalized_content = _normalized_markdown_source(content)
    digest = hashlib.sha256(normalized_content.encode("utf-8")).hexdigest()
    return f"sha256:{digest}"


# START_FUNCTION_CONTRACT
# name: compute_packet_source_hash
# purpose: Computes the parser-equivalent packet source hash for markdown plus optional sidecar payload.
# inputs:
#   content: raw markdown content.
#   sidecar_payload: normalized sidecar payload, or None for markdown-only hashing.
# returns: sha256-prefixed source hash string.
# side_effects: none.
# emitted_logs: none.
# error_behavior: Propagates YAML serialization errors for non-serializable sidecar payloads.
# END_FUNCTION_CONTRACT
def compute_packet_source_hash(
    content: str,
    sidecar_payload: dict[str, Any] | None = None,
) -> str:
    return _compute_packet_source_hash(content, sidecar_payload)


def _normalized_markdown_source(content: str) -> str:
    lines = content.splitlines()
    filtered_lines: list[str] = []
    excluding = False

    for line in lines:
        stripped = line.strip()
        if stripped.startswith("#"):
            if EXCLUDED_SECTIONS_RE.match(stripped):
                excluding = True
            else:
                excluding = False

        if not excluding:
            if stripped:
                filtered_lines.append(stripped)

    return "\n".join(filtered_lines)


def _compute_packet_source_hash(content: str, sidecar_payload: dict[str, Any] | None) -> str:
    normalized_content = _normalized_markdown_source(content)
    if sidecar_payload is not None:
        normalized_sidecar = yaml.safe_dump(
            sidecar_payload,
            sort_keys=True,
            allow_unicode=True,
        ).strip()
        normalized_content = "\n".join(
            [
                normalized_content,
                f"--- {PACKET_SIDECAR_NAME} ---",
                normalized_sidecar,
            ]
        )

    digest = hashlib.sha256(normalized_content.encode("utf-8")).hexdigest()
    return f"sha256:{digest}"


def _read_packet_content(path_or_content: Path | str) -> str:
    if isinstance(path_or_content, Path):
        return path_or_content.read_text(encoding="utf-8")
    return path_or_content


def _packet_sidecar_path(path_or_content: Path | str) -> Path | None:
    if not isinstance(path_or_content, Path):
        return None
    if path_or_content.name != "EXECUTION_PACKET.md":
        return None
    return path_or_content.with_name(PACKET_SIDECAR_NAME)


def _sidecar_text(value: Any, field_name: str) -> str:
    if value is None:
        return ""
    if isinstance(value, (dict, list)):
        raise ValueError(f"YAML sidecar field {field_name} must be scalar text")
    return str(value).strip()


def _normalize_sidecar_list(value: Any, field_name: str) -> list[str]:
    if value is None:
        return []
    if isinstance(value, list):
        normalized_items: list[str] = []
        for item in value:
            if isinstance(item, (dict, list)):
                raise ValueError(f"YAML sidecar list field {field_name} contains a non-scalar item")
            item_text = str(item).strip()
            if item_text:
                normalized_items.append(item_text)
        return normalized_items
    if not isinstance(value, str):
        raise ValueError(f"YAML sidecar list field {field_name} must be a list or scalar string")

    stripped = value.strip()
    if not stripped:
        return []

    lines = [line.strip() for line in stripped.splitlines() if line.strip()]
    if len(lines) > 1:
        items: list[str] = []
        for line in lines:
            item = re.sub(r"^[-*]\s+", "", line).strip()
            if item:
                items.append(item)
        return items

    if "," in stripped or "·" in stripped:
        return _split_words(stripped)
    return [stripped]


def _normalize_packet_sidecar_payload(payload: dict[str, Any], sidecar_path: Path) -> dict[str, Any]:
    unknown_fields = sorted(set(payload) - PACKET_SIDECAR_CANONICAL_FIELD_SET)
    if unknown_fields:
        raise ValueError(
            f"YAML sidecar {sidecar_path} contains unknown fields: {', '.join(unknown_fields)}"
        )

    artifact_type = _sidecar_text(payload.get("artifact_type"), "artifact_type")
    if artifact_type != PACKET_SIDECAR_ARTIFACT_TYPE:
        raise ValueError(
            f"YAML sidecar {sidecar_path} must declare artifact_type: {PACKET_SIDECAR_ARTIFACT_TYPE}"
        )

    normalized: dict[str, Any] = {}
    for field_name in PACKET_SIDECAR_CANONICAL_FIELDS:
        if field_name not in payload:
            continue
        if field_name in PACKET_SIDECAR_LIST_FIELDS:
            normalized[field_name] = _normalize_sidecar_list(payload[field_name], field_name)
        else:
            normalized[field_name] = _sidecar_text(payload[field_name], field_name)
    return normalized


def _load_packet_sidecar(sidecar_path: Path | None) -> dict[str, Any] | None:
    if sidecar_path is None or not sidecar_path.exists():
        return None
    try:
        payload = yaml.safe_load(sidecar_path.read_text(encoding="utf-8"))
    except Exception as exc:
        raise ValueError(f"Invalid YAML sidecar {sidecar_path}: {exc}") from exc
    if not isinstance(payload, dict):
        raise ValueError(f"Invalid YAML sidecar {sidecar_path}: top-level payload must be a mapping")
    return _normalize_packet_sidecar_payload(payload, sidecar_path)


# START_FUNCTION_CONTRACT
# name: packet_to_canonical_sidecar_payload
# purpose: Convert a parsed packet to the canonical EXECUTION_PACKET.yaml payload.
# inputs:
#   parsed: ParsedPacket instance produced from markdown packet metadata.
# returns: Ordered dict containing only canonical sidecar fields.
# side_effects: none.
# emitted_logs: none.
# error_behavior: Propagates attribute access errors if parsed is malformed.
# END_FUNCTION_CONTRACT
def packet_to_canonical_sidecar_payload(parsed: ParsedPacket) -> dict[str, Any]:
    return {
        "schema_version": "1",
        "artifact_type": PACKET_SIDECAR_ARTIFACT_TYPE,
        "packet_id": parsed.packet_id,
        "feature_id": parsed.feature_id,
        "wave_id": parsed.wave_id,
        "title": parsed.title,
        "objective": parsed.objective,
        "status": parsed.status,
        "phase": parsed.phase,
        "depends_on": list(parsed.depends_on),
        "modules": list(parsed.modules),
        "allowed_write_scope": list(parsed.allowed_write_scope),
        "frozen_scope": list(parsed.frozen_scope),
        "must_preserve": list(parsed.must_preserve),
        "verification": parsed.verification,
        "expected_evidence": list(parsed.expected_evidence),
        "escalation_triggers": list(parsed.escalation_triggers),
    }


# START_FUNCTION_CONTRACT
# name: dump_packet_sidecar_payload
# purpose: Serialize a canonical packet sidecar payload with stable field order.
# inputs:
#   payload: canonical sidecar mapping.
# returns: YAML string ending with a newline.
# side_effects: none.
# emitted_logs: none.
# error_behavior: Propagates yaml serialization errors.
# END_FUNCTION_CONTRACT
def dump_packet_sidecar_payload(payload: dict[str, Any]) -> str:
    ordered_payload = {
        field_name: payload[field_name]
        for field_name in PACKET_SIDECAR_CANONICAL_FIELDS
        if field_name in payload
    }
    return yaml.safe_dump(
        ordered_payload,
        sort_keys=False,
        allow_unicode=True,
        default_flow_style=False,
    )


# START_FUNCTION_CONTRACT
# name: load_packet_sidecar_payload
# purpose: Load and normalize an EXECUTION_PACKET.yaml sidecar using parser validation rules.
# inputs:
#   sidecar_path: Path to EXECUTION_PACKET.yaml.
# returns: Normalized canonical-field mapping.
# side_effects: Reads sidecar file.
# emitted_logs: none.
# error_behavior: Raises ValueError for malformed, non-mapping, or unknown-field sidecars.
# END_FUNCTION_CONTRACT
def load_packet_sidecar_payload(sidecar_path: Path) -> dict[str, Any]:
    loaded = _load_packet_sidecar(sidecar_path)
    return loaded or {}


def _parse_sections(content: str) -> tuple[dict[str, list[str]], dict[str, int], str]:
    sections: dict[str, list[str]] = {}
    section_lines: dict[str, int] = {}
    current_section = "_header"
    first_heading = ""

    for line_no, line in enumerate(content.splitlines(), start=1):
        stripped = line.strip()
        if stripped.startswith("#"):
            h_match = re.match(r"^#+\s*(.*)$", stripped)
            current_section = h_match.group(1).strip().lower() if h_match else stripped.lower()
            section_lines.setdefault(current_section, line_no)
            sections.setdefault(current_section, [])
            if stripped.startswith("# ") and not first_heading:
                first_heading = stripped[2:].strip()
        else:
            sections.setdefault(current_section, []).append(line)

    return sections, section_lines, first_heading


def _parse_header_metadata(content: str, sections: dict[str, list[str]]) -> dict[str, Any]:
    header_lines = sections.get("_header", [])
    if not any(line.strip() for line in header_lines):
        for section_name, section_lines in sections.items():
            if section_name != "_header":
                header_lines = section_lines
                break
    first_body_lines: list[str] = []
    seen_separator = False

    for line in header_lines:
        stripped = line.strip()
        if stripped == "---":
            seen_separator = True
            break
        if stripped:
            first_body_lines.append(line)

    if not first_body_lines and not seen_separator:
        return {}

    header_text = "\n".join(first_body_lines)
    try:
        parsed = yaml.safe_load(header_text) if header_text.strip() else {}
    except Exception:
        parsed = {}
    return parsed if isinstance(parsed, dict) else {}


def _parse_bullet_metadata(sections: dict[str, list[str]]) -> dict[str, str]:
    all_metadata: dict[str, str] = {}
    for sect_lines in sections.values():
        for line in sect_lines:
            stripped = line.strip()
            if stripped.startswith("-") or stripped.startswith("*"):
                item_content = stripped[1:].strip()
                kv_match = re.match(
                    r"^([a-zA-Z0-9_\-]+)\s*:\s*[`'\\\"]?([^`'\\\"]+?)[`'\\\"]?\s*$",
                    item_content,
                )
                if kv_match:
                    all_metadata[kv_match.group(1).lower()] = kv_match.group(2).strip()
    return all_metadata


def _split_words(value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, list):
        return [str(item).strip() for item in value if str(item).strip()]
    return [
        item.strip()
        for item in re.split(r"\s*[·,]\s*", str(value))
        if item.strip()
    ]


def _infer_feature_from_packet(packet_id: str) -> str:
    feat_match = re.match(r"^(FEAT-[A-Z0-9\-]+?)-W\d+[A-Z]?(?:\.\d+[A-Z]?)?", packet_id)
    if feat_match:
        return feat_match.group(1)
    parts = packet_id.split("-")
    for i, part in enumerate(parts):
        if re.match(r"^W\d", part):
            return "-".join(parts[:i])
    return ""


def _infer_wave_from_packet(packet_id: str) -> str:
    w_match = re.search(r"-(W\d+[A-Z]?(?:\.\d+[A-Z]?)?)-", packet_id)
    return w_match.group(1) if w_match else ""


def _looks_like_packet_id(candidate: str) -> bool:
    candidate = candidate.strip().strip("`'\"")
    if not candidate or " " in candidate:
        return False
    if not re.match(r"^[A-Z0-9]+(?:-[A-Z0-9]+)*$", candidate):
        return False
    return bool(re.search(r"(?:^|-)W\d+[A-Z]?(?:\.\d+[A-Z]?)?(?:-|$)", candidate))


# START_FUNCTION_CONTRACT
# name: parse_packet_markdown
# purpose: Parses packet markdown file/content and performs structural validation.
# inputs:
#   path_or_content: Path of markdown file or raw string content.
#   mode: validation mode string ('strict' or 'legacy_warn').
# returns: ParsedPacket dataclass instance.
# side_effects: Reads file from disk if path_or_content is Path.
# emitted_logs: none.
# error_behavior: Raises ValueError if strict validation requirements are missed.
# END_FUNCTION_CONTRACT
def parse_packet_markdown(
    path_or_content: Path | str,
    *,
    mode: str = "strict",
) -> ParsedPacket:
    content = _read_packet_content(path_or_content)
    sidecar_payload = _load_packet_sidecar(_packet_sidecar_path(path_or_content))

    source_hash = _compute_packet_source_hash(content, sidecar_payload)
    sections, section_lines, first_heading = _parse_sections(content)
    header_metadata = _parse_header_metadata(content, sections)

    title = ""
    packet_id = ""
    markdown_packet_ids: list[str] = []
    feature_id = ""
    wave_id = ""
    status = str(header_metadata.get("status") or "").strip()
    phase = str(header_metadata.get("phase") or "").strip()
    depends_on = _split_words(header_metadata.get("depends_on"))
    legacy_warnings: list[str] = []

    if first_heading:
        id_match = re.match(
            r"^(?:execution\s+)?packet:\s*([a-zA-Z0-9_\-]+)",
            first_heading,
            re.IGNORECASE,
        )
        if id_match:
            title = first_heading.split(":", 1)[1].strip()
            h1_packet_id = id_match.group(1).strip()
            if _looks_like_packet_id(h1_packet_id):
                packet_id = h1_packet_id
                markdown_packet_ids.append(packet_id)
        else:
            controller_match = re.match(
                r"^Controller\s+Packet\s+[—-]\s*([^:]+)\s*:\s*(.+)$",
                first_heading,
                re.IGNORECASE,
            )
            if controller_match:
                h1_packet_id = controller_match.group(1).strip()
                if _looks_like_packet_id(h1_packet_id):
                    packet_id = h1_packet_id
                    markdown_packet_ids.append(packet_id)
                    wave_id = packet_id
                title = controller_match.group(2).strip()
            else:
                title = first_heading

    all_metadata = _parse_bullet_metadata(sections)
    for key, value in header_metadata.items():
        if isinstance(value, str):
            all_metadata.setdefault(key.lower(), value.strip())

    if "packet_id" in all_metadata:
        packet_id = all_metadata["packet_id"]
        markdown_packet_ids.append(packet_id)
    elif "packet" in all_metadata:
        packet_id = all_metadata["packet"]
        markdown_packet_ids.append(packet_id)
    if "feature_id" in all_metadata:
        feature_id = all_metadata["feature_id"]
    if "wave_id" in all_metadata:
        wave_id = all_metadata["wave_id"]
    elif "wave" in all_metadata:
        wave_id = all_metadata["wave"]
    if not phase and "phase" in all_metadata:
        phase = all_metadata["phase"]
    if not status and "status" in all_metadata:
        status = all_metadata["status"]
    if not depends_on and "depends_on" in all_metadata:
        depends_on = _split_words(all_metadata["depends_on"])

    if not wave_id and "wave" in sections:
        wave_content = "\n".join(sections["wave"]).strip()
        w_match = re.search(r"\b(W[\dA-Z][\dA-Z.\-]*)\b", wave_content)
        if w_match:
            wave_id = w_match.group(1)

    if packet_id and not feature_id:
        feature_id = _infer_feature_from_packet(packet_id)

    if packet_id and not wave_id:
        wave_id = _infer_wave_from_packet(packet_id)

    def _get_bullet_list(section_names: list[str]) -> list[str]:
        items = []
        for name in section_names:
            if name in sections:
                for line in sections[name]:
                    stripped = line.strip()
                    if stripped.startswith("-") or stripped.startswith("*"):
                        val = stripped[1:].strip()
                        val = re.sub(r"^[`'\"].*[`'\"]$", lambda m: m.group(0)[1:-1], val)
                        items.append(val)
        return items

    def _get_section_text(section_names: list[str]) -> str:
        for name in section_names:
            if name in sections:
                return "\n".join(sections[name]).strip()
        return ""

    objective = _get_section_text(["objective", "goal", "summary"])
    modules = _get_bullet_list(["impacted modules", "modules"])
    if not modules:
        modules = _split_words(header_metadata.get("modules") or all_metadata.get("modules"))
    allowed_write_scope = _get_bullet_list(["allowed write scope", "write scope"])
    frozen_scope = _get_bullet_list(["frozen scope", "frozen / out of scope", "frozen/out of scope"])
    must_preserve = _get_bullet_list(["must preserve"])
    verification = _get_section_text(["verification", "verification profile"])
    expected_evidence = _get_bullet_list(["expected evidence"])
    escalation_triggers = _get_bullet_list(["escalation triggers"])

    if sidecar_payload is not None:
        sidecar_packet_id = str(sidecar_payload.get("packet_id") or "").strip()
        markdown_ids = {item.strip() for item in markdown_packet_ids if item.strip()}
        mismatches = sorted(item for item in markdown_ids if sidecar_packet_id and item != sidecar_packet_id)
        if mismatches:
            raise ValueError(
                "YAML sidecar packet_id does not match markdown packet_id: "
                f"{sidecar_packet_id} != {', '.join(mismatches)}"
            )

        if "packet_id" in sidecar_payload:
            packet_id = sidecar_packet_id
        if "feature_id" in sidecar_payload:
            feature_id = str(sidecar_payload["feature_id"])
        if "wave_id" in sidecar_payload:
            wave_id = str(sidecar_payload["wave_id"])
        if "title" in sidecar_payload:
            title = str(sidecar_payload["title"])
        if "objective" in sidecar_payload:
            objective = str(sidecar_payload["objective"])
        if "status" in sidecar_payload:
            status = str(sidecar_payload["status"])
        if "phase" in sidecar_payload:
            phase = str(sidecar_payload["phase"])
        if "depends_on" in sidecar_payload:
            depends_on = list(sidecar_payload["depends_on"])
        if "modules" in sidecar_payload:
            modules = list(sidecar_payload["modules"])
        if "allowed_write_scope" in sidecar_payload:
            allowed_write_scope = list(sidecar_payload["allowed_write_scope"])
        if "frozen_scope" in sidecar_payload:
            frozen_scope = list(sidecar_payload["frozen_scope"])
        if "must_preserve" in sidecar_payload:
            must_preserve = list(sidecar_payload["must_preserve"])
        if "verification" in sidecar_payload:
            verification = str(sidecar_payload["verification"])
        if "expected_evidence" in sidecar_payload:
            expected_evidence = list(sidecar_payload["expected_evidence"])
        if "escalation_triggers" in sidecar_payload:
            escalation_triggers = list(sidecar_payload["escalation_triggers"])

    core_checks = {
        "packet_id": packet_id,
        "feature_id": feature_id,
        "wave_id": wave_id,
        "allowed_write_scope": allowed_write_scope,
        "frozen_scope": frozen_scope,
        "must_preserve": must_preserve,
        "verification": verification,
        "expected_evidence": expected_evidence,
        "escalation_triggers": escalation_triggers,
    }

    missing_fields = []
    for field_name, value in core_checks.items():
        if not value:
            missing_fields.append(field_name)

    if missing_fields:
        msg = f"Missing core fields/sections: {', '.join(missing_fields)}"
        if mode == "strict":
            raise ValueError(f"Strict packet validation failed: {msg}")
        else:
            legacy_warnings.append(msg)

    def _clean_scope_list(lst: list[str]) -> list[str]:
        cleaned = []
        for item in lst:
            if " " in item and not ("*" in item or "/" in item):
                continue
            cleaned.append(item)
        return cleaned

    allowed_write_scope = _clean_scope_list(allowed_write_scope)
    frozen_scope = _clean_scope_list(frozen_scope)

    return ParsedPacket(
        packet_id=packet_id,
        feature_id=feature_id,
        wave_id=wave_id,
        title=title,
        objective=objective,
        status=status,
        phase=phase,
        depends_on=depends_on,
        modules=modules,
        allowed_write_scope=allowed_write_scope,
        frozen_scope=frozen_scope,
        must_preserve=must_preserve,
        verification=verification,
        expected_evidence=expected_evidence,
        escalation_triggers=escalation_triggers,
        source_hash=source_hash,
        section_lines=section_lines,
        legacy_warnings=legacy_warnings,
    )

#END_BLOCK_PARSER_CORE
