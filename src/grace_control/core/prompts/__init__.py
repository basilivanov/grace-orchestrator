"""Prompt templates for GRACE agents.

W03: Canonical architect prompt source and packet schema definition.
All architect prompt consumers must load from here, not from inline strings
or profile YAML, ensuring one source of truth for the plan schema.
"""

from __future__ import annotations

from pathlib import Path

# ── Canonical packet field schema (W03) ──────────────────────────────────
# Every coder packet in a plan MUST include these fields.
# Used by tests, profile validators, and legacy field canonicalization.

CANONICAL_PACKET_FIELDS: list[str] = [
    "title",
    "role",
    "scope",
    "frozen_scope",
    "acceptance_profile",
    "depends_on",
    "conflict_keys",
    "description",
    "coder_instructions",
    "acceptance_criteria",
    "verification",
    "expected_evidence",
    "workspace_requirements",
]

# Fields that are REQUIRED (must be present, no default)
REQUIRED_PACKET_FIELDS: list[str] = [
    "title",
    "role",
    "scope",
    "frozen_scope",
    "acceptance_profile",
    "depends_on",
    "conflict_keys",
    "description",
    "coder_instructions",
    "acceptance_criteria",
    "verification",
    "expected_evidence",
]

# Legacy field → canonical field mapping for canonicalization with warnings
LEGACY_FIELD_MAP: dict[str, str] = {
    "allowed_files": "scope",
    "forbidden_files": "frozen_scope",
    "write_scope": "scope",
    "inputs": "coder_instructions",
}

# ── Canonical architect prompt file ─────────────────────────────────────

_ARCHITECT_PROMPT_PATH = Path(__file__).resolve().parent / "architect_prompt.md"


def _normalize_conflict_keys(value: object) -> list[str]:
    """Normalize and validate semantic parallel-conflict keys."""
    if not isinstance(value, list):
        raise ValueError("conflict_keys must be a list of strings")

    normalized: list[str] = []
    seen: set[str] = set()
    for index, raw_key in enumerate(value):
        if not isinstance(raw_key, str):
            raise ValueError(f"conflict_keys[{index}] must be a string")
        key = raw_key.strip()
        if not key:
            raise ValueError(f"conflict_keys[{index}] must not be empty")
        if key in seen:
            raise ValueError(
                f"conflict_keys contains duplicate key after normalization: {key!r}"
            )
        seen.add(key)
        normalized.append(key)
    return normalized


def load_architect_prompt() -> str:
    """Load the canonical architect prompt from architect_prompt.md.

    This is the single source of truth for the architect prompt body.
    All consumers (_build_architect_prompt, agent_profiles, etc.) must
    use this function rather than embedding inline prompt text.
    """
    if not _ARCHITECT_PROMPT_PATH.exists():
        raise FileNotFoundError(
            f"Canonical architect prompt not found at {_ARCHITECT_PROMPT_PATH}"
        )
    return _ARCHITECT_PROMPT_PATH.read_text(encoding="utf-8")


def canonicalize_packet_fields(packet: dict) -> tuple[dict, list[str]]:
    """Canonicalize legacy packet fields to canonical schema.

    Returns (canonicalized_packet, warnings) where warnings is a list
    of human-readable strings describing each legacy field that was
    canonicalized.

    Legacy fields that are canonicalized (with visible warnings):
    - allowed_files → scope
    - forbidden_files → frozen_scope
    - write_scope → scope
    - inputs → coder_instructions
    """
    warnings: list[str] = []
    result = dict(packet)  # shallow copy

    for legacy_field, canonical_field in LEGACY_FIELD_MAP.items():
        if legacy_field in result:
            # Only canonicalize if canonical field is not already set
            if canonical_field not in result or not result[canonical_field]:
                result[canonical_field] = result.pop(legacy_field)
                warnings.append(
                    f"Legacy field '{legacy_field}' canonicalized to '{canonical_field}' "
                    f"— use '{canonical_field}' in future plans"
                )
            else:
                # Both exist — drop the legacy one and warn
                result.pop(legacy_field)
                warnings.append(
                    f"Legacy field '{legacy_field}' ignored because canonical "
                    f"'{canonical_field}' is already set — remove '{legacy_field}'"
                )

    result["conflict_keys"] = _normalize_conflict_keys(
        result.get("conflict_keys", [])
    )
    return result, warnings
