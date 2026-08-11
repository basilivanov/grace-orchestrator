# ############################################################################
# AI_HEADER: plan_compiler — bounded facade coordinating plan validation domains
# ROLE: Deterministic preflight compiler for architect plans. It preserves the
#       public compiler contract while delegating command, scope, evidence, DAG,
#       and source-split rules to coherent validation owners.
# ############################################################################

# START_MODULE_CONTRACT
# purpose: Compile an architect plan into a validated CompileResult before coder execution.
# inputs: Architect plan, optional ExecutionEnvironment, feature description, and target repository root.
# returns: CompileResult with stable errors, warnings, and compatibility fields.
# side_effects: Reads the target repository and may mutate packet conflict_keys during normalization.
# emitted_logs: compile_done.
# error_behavior: Invalid plans return ok=False with ordered compiler diagnostics.
# END_MODULE_CONTRACT

# START_MODULE_MAP
# mapping:
#   - class: PlanCompiler
#   - function: compile_plan
#   - class: CompileError
#   - class: CompileResult
#   - class: SourceSplitIntent
#   - class: RepoReference
# END_MODULE_MAP

from __future__ import annotations

import re
from pathlib import Path

from grace_control.core.execution_environment import ExecutionEnvironment
from grace_control.core.plan_validation.command import validate_command
from grace_control.core.plan_validation.dependencies import validate_dependencies
from grace_control.core.plan_validation.evidence import (
    VALID_EXPECTATIONS,
    _REMOVE_INTENT_KEYWORDS,
    _is_descriptive_artifact_pattern,
    validate_evidence,
    validate_evidence_contradiction,
)
from grace_control.core.plan_validation.models import (
    CompileError,
    CompileResult,
    _add_error,
    _add_warning,
)
from grace_control.core.plan_validation.scope import (
    validate_packet_scope,
    validate_role_scope,
    validate_scope_acceptance,
)
from grace_control.core.plan_validation.source_split import (
    RepoReference,
    SourceSplitIntent,
    _SOURCE_SPLIT_KEYWORDS,
    _import_path_to_source_path,
    collect_repo_references,
    detect_source_split_intents,
    validate_source_split,
)
from grace_control.core.prompts import _normalize_conflict_keys
from grace_control.core.structured_logger import GraceLogger

_log = GraceLogger("plan_compiler")

__all__ = [
    "CompileError",
    "CompileResult",
    "PlanCompiler",
    "RepoReference",
    "SourceSplitIntent",
    "collect_repo_references",
    "compile_plan",
    "detect_source_split_intents",
    "_SOURCE_SPLIT_KEYWORDS",
    "_import_path_to_source_path",
]


# START_BLOCK_COORDINATOR_HELPERS
def _feature_python_file_limit(feature_description: str, plan: dict) -> int | None:
    limit_text = feature_description + "\n" + str(plan.get("constraints", {}))
    limit_match = re.search(
        r"(?:at\s+most|no\s+more\s+than|maximum(?:\s+of)?|<=|≤)\s*"
        r"(\d+)\s+(?:tracked\s+)?(?:python[- ]?)?files?",
        limit_text,
        re.IGNORECASE,
    )
    return int(limit_match.group(1)) if limit_match else None


def _plan_bootstraps_venv(waves: list[dict]) -> bool:
    """Return whether a plan explicitly creates a project-level venv."""
    for wave in waves:
        if not isinstance(wave, dict):
            continue
        for packet in wave.get("packets", []) or []:
            if not isinstance(packet, dict):
                continue
            scope_entries = packet.get("scope", [])
            if not isinstance(scope_entries, list):
                continue
            has_venv_scope = any(
                isinstance(scope_entry, str) and ".venv" in scope_entry
                for scope_entry in scope_entries
            )
            packet_text = " ".join(
                str(packet.get(key, ""))
                for key in ("title", "description", "coder_instructions")
            )
            declares_venv_bootstrap = (
                ".venv" in packet_text
                and re.search(r"\b(bootstrap|create)\b", packet_text, re.IGNORECASE)
            )
            if (has_venv_scope or declares_venv_bootstrap) and re.search(
                r"\b(bootstrap|create)\b", packet_text, re.IGNORECASE
            ):
                return True
    return False
# END_BLOCK_COORDINATOR_HELPERS


# START_BLOCK_COMPILER
class PlanCompiler:
    """Compatibility facade coordinating the domain validators in stable order."""

    _VALID_EXPECTATIONS = VALID_EXPECTATIONS
    _REMOVE_INTENT_KEYWORDS = _REMOVE_INTENT_KEYWORDS
    _is_descriptive_artifact_pattern = staticmethod(_is_descriptive_artifact_pattern)

    # START_FUNCTION_CONTRACT
    # name: compile_plan
    # purpose: Run ordered source-split, dependency, scope, command, evidence, and role validation.
    # inputs: plan — architect plan; env — optional discovered environment; feature_description and target_repo_root — target context.
    # returns: CompileResult containing stable diagnostics and normalized packet fields.
    # side_effects: Probes the environment when env is omitted and normalizes packet conflict_keys in place.
    # emitted_logs: compile_done.
    # error_behavior: Invalid plans return diagnostics rather than raising for normal validation failures.
    # END_FUNCTION_CONTRACT
    def compile_plan(
        self,
        plan: dict,
        env: ExecutionEnvironment | None = None,
        *,
        feature_description: str = "",
        target_repo_root: Path | None = None,
    ) -> CompileResult:
        if env is None:
            from grace_control.core.execution_environment import probe_execution_environment

            env = probe_execution_environment(target_repo_root=target_repo_root)

        result = CompileResult(ok=True)
        waves = plan.get("waves", [])
        if not waves:
            return result

        validate_dependencies(result, plan)
        python_file_limit = _feature_python_file_limit(feature_description, plan)
        plan_bootstraps_venv = _plan_bootstraps_venv(waves)

        validate_source_split(
            result, plan, env, feature_description, target_repo_root,
        )

        for wave_index, wave in enumerate(waves):
            for packet_index, packet in enumerate(wave.get("packets", [])):
                title = packet.get("title", f"wave-{wave_index}-pkt-{packet_index}")
                scope = packet.get("scope", [])
                role = packet.get("role", "coder")

                try:
                    packet["conflict_keys"] = _normalize_conflict_keys(
                        packet.get("conflict_keys", [])
                    )
                except ValueError as exc:
                    _add_error(
                        result,
                        "E_CONFLICT_KEYS_INVALID",
                        f"waves[{wave_index}].packets[{packet_index}].conflict_keys",
                        str(exc),
                        title,
                        "use a list of non-empty, unique strings",
                    )

                scope = validate_packet_scope(
                    result,
                    plan,
                    packet,
                    scope,
                    role,
                    title,
                    wave_index,
                    packet_index,
                    python_file_limit,
                    target_repo_root,
                )

                verification = packet.get("verification", {})
                evidence = packet.get("expected_evidence", [])
                description = packet.get("description", "")
                acceptance = packet.get("acceptance_criteria", [])
                coder_instructions = packet.get("coder_instructions", [])

                if isinstance(verification, dict):
                    t0 = verification.get("t0", [])
                    t1 = verification.get("t1", [])
                    t2 = verification.get("t2", [])
                elif isinstance(verification, list):
                    t0 = []
                    t1 = verification
                    t2 = []
                    _add_warning(
                        result,
                        "W_VERIFICATION_LEGACY_LIST",
                        f"waves[{wave_index}].packets[{packet_index}].verification",
                        "verification is a legacy command list; canonical packets use an object with t0/t1/t2 arrays",
                        title,
                        "use verification: {t0: [], t1: [...], t2: []}",
                    )
                else:
                    t0 = []
                    t1 = []
                    t2 = []
                    _add_error(
                        result,
                        "E_VERIFICATION_INVALID_TYPE",
                        f"waves[{wave_index}].packets[{packet_index}].verification",
                        f"verification must be an object or legacy list, got {type(verification).__name__}",
                        title,
                        "use verification: {t0: [], t1: [], t2: []}",
                    )

                for commands, stage_name in ((t0, "t0"), (t1, "t1"), (t2, "t2")):
                    for command_index, command in enumerate(commands):
                        if isinstance(command, str):
                            validate_command(
                                result,
                                command,
                                env,
                                title,
                                f"verification.{stage_name}[{command_index}]",
                                allow_planned_venv=plan_bootstraps_venv,
                                target_repo_root=target_repo_root,
                            )

                validate_scope_acceptance(
                    result,
                    title,
                    scope,
                    t1,
                    acceptance,
                    coder_instructions,
                    role,
                    target_repo_root,
                )
                validate_evidence(
                    result, title, evidence, role, description, scope, verification,
                )
                validate_evidence_contradiction(
                    result,
                    title,
                    evidence,
                    coder_instructions,
                    description,
                    packet.get("validation_hint", ""),
                )
                validate_role_scope(result, title, role, scope, description)

        _log.info(
            "compile_done", ok=result.ok,
            errors=len(result.errors), warnings=len(result.warnings),
        )
        return result
# END_BLOCK_COMPILER


# START_BLOCK_PUBLIC_API
# START_FUNCTION_CONTRACT
# name: compile_plan
# purpose: Compile a plan through the compatibility PlanCompiler facade.
# inputs: plan — architect plan; env — optional environment; feature_description and target_repo_root — target context.
# returns: CompileResult with ordered validation diagnostics.
# side_effects: Same as PlanCompiler.compile_plan.
# emitted_logs: compile_done.
# error_behavior: Returns compiler diagnostics for invalid plans.
# END_FUNCTION_CONTRACT
def compile_plan(
    plan: dict,
    env: ExecutionEnvironment | None = None,
    *,
    feature_description: str = "",
    target_repo_root: Path | None = None,
) -> CompileResult:
    return PlanCompiler().compile_plan(
        plan,
        env,
        feature_description=feature_description,
        target_repo_root=target_repo_root,
    )
# END_BLOCK_PUBLIC_API
