# ############################################################################
# AI_HEADER: plan_validation_evidence — evidence contract validation
# ROLE: Own typed evidence, artifact-path, deletion, and instruction-contradiction
#       checks while preserving the compiler's diagnostic codes and order.
# ############################################################################

# START_MODULE_CONTRACT
# purpose: Validate packet expected_evidence entries and contradictions with instructions.
# inputs: Evidence entries, packet role/description/scope, verification, and text instructions.
# returns: None; appends stable errors and warnings to CompileResult.
# side_effects: None.
# emitted_logs: None.
# error_behavior: Invalid evidence contracts become compiler diagnostics.
# END_MODULE_CONTRACT

# START_MODULE_MAP
# mapping:
#   - function: validate_evidence
#   - function: validate_evidence_contradiction
#   - function: _is_descriptive_artifact_pattern
# END_MODULE_MAP

from __future__ import annotations

import re
from pathlib import Path

from grace_control.core.contracts import SUPPORTED_EVIDENCE_KINDS
from grace_control.core.plan_validation.models import CompileResult, _add_error, _add_warning
from grace_control.core.structured_logger import GraceLogger

_log = GraceLogger("plan_validation.evidence")


# START_BLOCK_CONSTANTS
VALID_EXPECTATIONS = frozenset({
    "exists", "created", "modified", "deleted", "absent",
    "diff_contains", "test_output", "import_absent", "import_updated",
})

_REMOVE_INTENT_KEYWORDS = [
    "remove", "delete", "consolidate", "drop", "eliminate",
    "get rid of", "clean up", "delete the file",
    "удалить", "убрать", "избавиться", "удали",
    "удаление", "удаляем",
]
# END_BLOCK_CONSTANTS


# START_BLOCK_EVIDENCE
# START_FUNCTION_CONTRACT
# name: validate_evidence
# purpose: Validate evidence kinds, artifact patterns, expectations, and diff constraints.
# inputs: result, packet title, evidence, role, description, scope, and verification.
# returns: None; diagnostics are appended to result.
# side_effects: None.
# emitted_logs: None.
# error_behavior: Invalid evidence entries append compiler errors or warnings.
# END_FUNCTION_CONTRACT
def validate_evidence(
    result: CompileResult,
    title: str,
    evidence: list[dict],
    role: str,
    description: str,
    scope: list[str],
    verification: dict | list,
) -> None:
    for evidence_index, entry in enumerate(evidence):
        if not isinstance(entry, dict):
            continue
        kind = entry.get("kind", "")
        patterns = entry.get("artifact_patterns", [])
        required = entry.get("required", True)

        if kind not in SUPPORTED_EVIDENCE_KINDS:
            _add_error(
                result, "E_EVIDENCE_KIND_UNKNOWN",
                f"expected_evidence[{evidence_index}].kind",
                f"unknown evidence kind '{kind}' — "
                f"valid values: {sorted(SUPPORTED_EVIDENCE_KINDS)}",
                title,
                f"use one of: {', '.join(sorted(SUPPORTED_EVIDENCE_KINDS))}",
            )

        for pattern in patterns if isinstance(patterns, list) else [patterns]:
            if isinstance(pattern, str) and pattern.startswith("/"):
                _add_error(
                    result, "E_EVIDENCE_ABSOLUTE_PATTERN",
                    f"expected_evidence[{evidence_index}].artifact_patterns",
                    f"artifact pattern '{pattern}' is absolute; evidence artifacts "
                    "must be repository-relative",
                    title,
                    "use a repository-relative artifact path or leave artifact_patterns empty",
                    details={"pattern": pattern},
                )
            if isinstance(pattern, str) and _is_descriptive_artifact_pattern(pattern):
                _add_error(
                    result, "E_EVIDENCE_DESCRIPTIVE_PATTERN",
                    f"expected_evidence[{evidence_index}].artifact_patterns",
                    f"artifact pattern '{pattern}' is a description, not a relative artifact glob",
                    title,
                    "use a run-relative artifact path such as t1/cmd_002_stdout.log",
                    details={
                        "pattern": pattern,
                        "evidence_id": entry.get("id", ""),
                        "producer": entry.get("producer", ""),
                        "verification": verification,
                    },
                )
            if (
                isinstance(pattern, str)
                and re.fullmatch(
                    r"\.grace-t\d[^/]*\.(?:stdout|stderr|log)",
                    pattern.strip(),
                    flags=re.IGNORECASE,
                )
            ):
                _add_error(
                    result, "E_EVIDENCE_EPHEMERAL_ROOT_ARTIFACT",
                    f"expected_evidence[{evidence_index}].artifact_patterns",
                    f"artifact pattern '{pattern}' would persist controller command "
                    "output in the target repository",
                    title,
                    "use the controller's run-relative artifact path, for example "
                    "t1/cmd_001_stdout.log",
                    details={"pattern": pattern},
                )

        expectation = entry.get("expectation", "") or "exists"
        if expectation not in VALID_EXPECTATIONS:
            _add_error(
                result, "E_EVIDENCE_EXPECTATION_UNKNOWN",
                f"expected_evidence[{evidence_index}].expectation",
                f"unknown expectation '{expectation}' — "
                f"valid values: {sorted(VALID_EXPECTATIONS)}",
                title,
                f"use one of: {', '.join(sorted(VALID_EXPECTATIONS))}",
            )

        if kind == "diff" and required:
            if patterns:
                _add_error(
                    result, "E_EVIDENCE_DIFF_HAS_PATTERN",
                    f"expected_evidence[{evidence_index}].artifact_patterns",
                    "kind=diff is produced by the controller's captured patch and must not "
                    "depend on a worktree file or command-stdout pattern",
                    title, "leave artifact_patterns empty for kind=diff",
                )
            if "agent.patch" in str(patterns):
                _add_warning(
                    result, "W_EVIDENCE_DIFF_AGENT_PATCH",
                    f"expected_evidence[{evidence_index}]",
                    "expected_evidence uses kind=diff with pattern=agent.patch — "
                    "agent.patch never matches changed_files from git diff",
                    title, "use kind=diff without pattern, or kind=file with specific filenames",
                )

        if kind == "diff" and required and role == "coder":
            no_code = (
                "no code changes" in description.lower()
                or "no files need modification" in description.lower()
            )
            if no_code:
                _add_error(
                    result, "E_EVIDENCE_DIFF_VERIFICATION_ONLY",
                    f"expected_evidence[{evidence_index}]",
                    "packet is verification-only but requires diff evidence",
                    title, "remove diff evidence requirement or change role to verifier",
                )

        if kind == "diff" and required and not scope:
            _add_error(
                result, "E_EVIDENCE_DIFF_EMPTY_SCOPE",
                f"expected_evidence[{evidence_index}]",
                "packet requires diff evidence but has empty write scope",
                title, "add target files to scope or remove diff evidence",
            )


def _is_descriptive_artifact_pattern(pattern: str) -> bool:
    """Return whether an artifact pattern is prose instead of a path glob."""
    value = pattern.strip().lower()
    command_prefixes = (
        "git ", "npm ", "node ", "python ", "python3 ", "pytest ",
        "grep ", "egrep ", "rg ", "test ", "make ", "just ", "sh ",
        "bash ", "curl ", "get ", "post ", "patch ", "delete ",
    )
    looks_like_single_path = (
        "/" in value
        and bool(re.search(r"\.[a-z0-9*?]+$", value))
        and not any(token in value for token in (" --", " &&", " ||", "|", ">", ";"))
    )
    return (
        " stdout" in value
        or value.endswith(" output")
        or value.startswith("run: ")
        or value.startswith(command_prefixes)
        or value.startswith("coder note ")
        or " requirement-by-requirement " in value
        or " version and " in value
        or " description or " in value
        or " screenshot reference " in value
        or (len(value.split()) >= 4 and not looks_like_single_path)
    )


def _has_remove_intent(texts: list[str]) -> list[str]:
    """Check whether any text expresses intent to remove files."""
    matched: list[str] = []
    for text in texts:
        lowered = text.lower()
        for keyword in _REMOVE_INTENT_KEYWORDS:
            if keyword in lowered:
                matched.append(keyword)
                break
    return matched


def _extract_target_paths_for_removal(
    texts: list[str], evidence_paths: list[str],
) -> list[str]:
    """Extract evidence paths explicitly named as removal targets."""
    targets: list[str] = []
    for text in texts:
        lowered = text.lower()
        for evidence_path in evidence_paths:
            evidence_lower = evidence_path.lower()
            evidence_name = Path(evidence_path).name.lower()
            for keyword in _REMOVE_INTENT_KEYWORDS:
                escaped_keyword = re.escape(keyword)
                qualifiers = r"(?:(?:the|this|old|obsolete|target)\s+){0,3}"
                file_word = r"(?:file\s+)?"
                target = rf"(?:{re.escape(evidence_lower)}|{re.escape(evidence_name)})"
                explicit_removal = re.search(
                    rf"(?:^|[\s:;,(]){escaped_keyword}\s+{qualifiers}{file_word}"
                    rf"[`'\"]?{target}(?=$|[\s`'\".,;:)])",
                    lowered,
                )
                if explicit_removal:
                    targets.append(evidence_path)
                    break
    return list(set(targets))


# START_FUNCTION_CONTRACT
# name: validate_evidence_contradiction
# purpose: Detect existence evidence contradicted by explicit removal instructions.
# inputs: result, packet title, evidence, coder instructions, description, and validation hint.
# returns: None; diagnostics are appended to result.
# side_effects: None.
# emitted_logs: None.
# error_behavior: Contradictory or non-explicit deletion evidence becomes a compiler error.
# END_FUNCTION_CONTRACT
def validate_evidence_contradiction(
    result: CompileResult,
    title: str,
    evidence: list[dict],
    coder_instructions: list[str],
    description: str,
    validation_hint: str,
) -> None:
    if not evidence:
        return

    evidence_paths: list[str] = []
    for entry in evidence:
        if not isinstance(entry, dict):
            continue
        patterns = entry.get("artifact_patterns", entry.get("pattern", []))
        if isinstance(patterns, str):
            patterns = [patterns]
        evidence_paths.extend(
            pattern for pattern in patterns
            if pattern.endswith(".py") or "." in pattern
        )

    if not evidence_paths:
        return

    all_texts = coder_instructions + [description, validation_hint]
    remove_keywords = _has_remove_intent(all_texts)
    removal_targets = (
        _extract_target_paths_for_removal(all_texts, evidence_paths)
        if remove_keywords else []
    )

    for entry in evidence:
        if not isinstance(entry, dict) or entry.get("expectation") != "deleted":
            continue
        patterns = entry.get("artifact_patterns", entry.get("pattern", []))
        if isinstance(patterns, str):
            patterns = [patterns]
        for pattern in patterns:
            if pattern in removal_targets:
                continue
            _add_error(
                result,
                "E_EVIDENCE_DELETION_NOT_EXPLICIT",
                "expected_evidence",
                f"Evidence '{entry.get('id', '?')}' expects '{pattern}' to be deleted, "
                "but the packet does not explicitly define that file deletion operation.",
                title,
                f"explicitly instruct the coder to delete {pattern}, or use expectation='absent'",
                details={
                    "evidence_id": entry.get("id", "?"),
                    "file": pattern,
                    "remove_target_explicit": False,
                },
            )

    if not remove_keywords or not removal_targets:
        return

    for entry in evidence:
        if not isinstance(entry, dict):
            continue
        patterns = entry.get("artifact_patterns", entry.get("pattern", []))
        if isinstance(patterns, str):
            patterns = [patterns]
        expectation = entry.get("expectation", "") or "exists"
        evidence_id = entry.get("id", "?")
        for pattern in patterns:
            if pattern in removal_targets and expectation == "exists":
                _add_error(
                    result, "E_EVIDENCE_CONTRADICTS_INSTRUCTIONS", "expected_evidence",
                    f"Evidence '{evidence_id}' expects '{pattern}' to exist (expectation='exists'), "
                    f"but instructions say to remove/delete it (keywords: {remove_keywords}). "
                    "Change expectation to 'deleted' or 'absent', or remove this evidence entry.",
                    title,
                    "Set expectation: 'deleted' for file being removed, or "
                    "'absent' if the file does not need to be removed by this packet.",
                    details={
                        "evidence_id": evidence_id,
                        "file": pattern,
                        "current_expectation": expectation,
                        "remove_keywords": remove_keywords,
                        "remove_target_explicit": True,
                        "suggested_fix": "deleted",
                    },
                )
            elif pattern in removal_targets and expectation in ("deleted", "absent"):
                pass
# END_BLOCK_EVIDENCE
