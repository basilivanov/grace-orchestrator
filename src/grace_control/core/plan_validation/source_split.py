# ############################################################################
# AI_HEADER: plan_validation_source_split — source split and import migration checks
# ROLE: Detect refactor intent and validate source origins and old-import scope. The
#       compiler facade re-exports its legacy public symbols for compatibility.
# ############################################################################

# START_MODULE_CONTRACT
# purpose: Detect source-split intent and verify origin/import migration coverage.
# inputs: Feature description, architect plan, execution environment, and target root.
# returns: SourceSplitIntent/RepoReference data or compiler diagnostics.
# side_effects: Reads active Python source and test files in the target repository.
# emitted_logs: None.
# error_behavior: Missing origins and out-of-scope imports become compiler errors.
# END_MODULE_CONTRACT

# START_MODULE_MAP
# mapping:
#   - class: SourceSplitIntent
#   - class: RepoReference
#   - function: detect_source_split_intents
#   - function: collect_repo_references
#   - function: validate_source_split
# END_MODULE_MAP

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

from grace_control.core.execution_environment import ExecutionEnvironment
from grace_control.core.plan_validation.models import CompileResult, _add_error
from grace_control.core.structured_logger import GraceLogger

_log = GraceLogger("plan_validation.source_split")


# START_BLOCK_MODELS
@dataclass
class SourceSplitIntent:
    source_path: str
    old_import_path: str | None = None
    new_package_prefix: str | None = None
    operation: str = "split"
    requires_source_modification: bool = True
    requires_import_migration: bool = False
    allows_shim: bool = True


@dataclass
class RepoReference:
    path: str
    line: int
    text: str
# END_BLOCK_MODELS


# START_BLOCK_PATTERNS
_SOURCE_SPLIT_KEYWORDS = [
    "split", "break up", "extract", "move", "refactor",
    "decompose", "modularize", "shim", "legacy module", "old import",
    "разбить", "разделить", "вынести", "распилить",
    "декомпозировать", "разнести", "рефактор", "перенести",
    "разбиение", "разделение",
]

_SOURCE_SPLIT_PATH_PATTERN = re.compile(
    r"(apps/api/\S+\.py|packages/\S+\.py|src/\S+\.py|grace/\S+\.py)"
)
_OLD_IMPORT_PATTERN = re.compile(r"(app\.\w+(?:\.\w+)+)")
# END_BLOCK_PATTERNS


# START_BLOCK_DETECTION
def _import_path_to_source_path(import_path: str) -> str:
    """Convert a Python import path to its repository source path."""
    parts = import_path.split(".")
    if parts[0] == "app":
        return "apps/api/" + "/".join(parts) + ".py"
    if parts[0] in ("src", "packages", "scripts"):
        return "/".join(parts) + ".py"
    return import_path


# START_FUNCTION_CONTRACT
# name: detect_source_split_intents
# purpose: Detect split/refactor source and import-migration intents in feature text and verification commands.
# inputs: feature_description — feature prose; plan — architect plan; env — execution facts.
# returns: List of SourceSplitIntent entries.
# side_effects: None.
# emitted_logs: None.
# error_behavior: Unrecognized text returns an empty list.
# END_FUNCTION_CONTRACT
def detect_source_split_intents(
    feature_description: str,
    plan: dict,
    env: ExecutionEnvironment,
) -> list[SourceSplitIntent]:
    """Analyze feature description and plan for split/refactor patterns."""
    del env
    intents: list[SourceSplitIntent] = []
    all_text = feature_description.lower()
    if not any(keyword in all_text for keyword in _SOURCE_SPLIT_KEYWORDS):
        return intents

    paths = _SOURCE_SPLIT_PATH_PATTERN.findall(feature_description)
    import_candidates = _OLD_IMPORT_PATTERN.findall(feature_description)

    for wave in plan.get("waves", []):
        for packet in wave.get("packets", []):
            for verification_key in ("t0", "t1", "t2"):
                for command in packet.get("verification", {}).get(verification_key, []):
                    command_text = str(command) if isinstance(command, str) else " ".join(command)
                    import_candidates.extend(_OLD_IMPORT_PATTERN.findall(command_text))

    for path in set(paths):
        parent = str(Path(path).parent)
        intents.append(SourceSplitIntent(
            source_path=path,
            new_package_prefix=parent + "/" if parent else None,
            operation="split",
        ))

    for import_path in set(import_candidates):
        intents.append(SourceSplitIntent(
            source_path=_import_path_to_source_path(import_path),
            old_import_path=import_path,
            operation="refactor",
            requires_import_migration=True,
        ))

    return intents


# START_FUNCTION_CONTRACT
# name: collect_repo_references
# purpose: Find active repository references to an old import path.
# inputs: target_root — repository root; import_path — old import string.
# returns: Up to 100 RepoReference entries in deterministic path/line order.
# side_effects: Reads Python files under active source, test, package, and script roots.
# emitted_logs: None.
# error_behavior: Missing, unreadable, or excluded files are skipped.
# END_FUNCTION_CONTRACT
def collect_repo_references(target_root: Path, import_path: str) -> list[RepoReference]:
    """Scan active code directories for old import path references."""
    if not target_root or not target_root.exists():
        return []
    references: list[RepoReference] = []
    search_dirs = ["apps/", "src/", "tests/", "packages/", "scripts/"]
    exclude_dirs = {
        ".git", ".grace", "node_modules", ".venv", "dist", "build",
        "coverage", "__pycache__", "archive",
    }

    for relative_dir in search_dirs:
        search_root = target_root / relative_dir
        if not search_root.exists():
            continue
        for file_path in sorted(search_root.rglob("*.py")):
            parts = file_path.relative_to(target_root).parts
            if any(excluded in parts for excluded in exclude_dirs):
                continue
            try:
                text = file_path.read_text(encoding="utf-8", errors="replace")
            except Exception:
                continue
            for line_number, line in enumerate(text.splitlines(), 1):
                if import_path in line:
                    references.append(RepoReference(
                        path=str(file_path.relative_to(target_root)),
                        line=line_number,
                        text=line.strip()[:300],
                    ))
                    if len(references) >= 100:
                        return references
    return references
# END_BLOCK_DETECTION


# START_BLOCK_VALIDATOR
# START_FUNCTION_CONTRACT
# name: validate_source_split
# purpose: Reject split/refactor plans missing their existing source origin or active import references.
# inputs: result, plan, environment, feature description, and optional target repository root.
# returns: None; diagnostics are appended to result.
# side_effects: Reads target repository files through source-split detection helpers.
# emitted_logs: None.
# error_behavior: Missing origin or incomplete migration scope appends stable compiler errors.
# END_FUNCTION_CONTRACT
def validate_source_split(
    result: CompileResult,
    plan: dict,
    env: ExecutionEnvironment,
    feature_description: str,
    target_repo_root: Path | None = None,
) -> None:
    """Reject split/refactor plans that omit the original source from scope."""
    if not feature_description:
        return

    intents = detect_source_split_intents(feature_description, plan, env)
    if not intents:
        return

    all_scope_files: set[str] = set()
    for wave in plan.get("waves", []):
        for packet in wave.get("packets", []):
            for scope_path in packet.get("scope", []) or []:
                all_scope_files.add(scope_path)
    for frozen_scope in plan.get("constraints", {}).get("frozen_scope", []) or []:
        all_scope_files.add(frozen_scope)

    for intent in intents:
        source_path = intent.source_path
        old_import_path = intent.old_import_path

        source_exists = False
        if target_repo_root and target_repo_root.exists():
            source_exists = (target_repo_root / source_path).exists()
        if not source_exists and target_repo_root:
            source_exists = Path(source_path).exists()

        if intent.requires_source_modification and source_path not in all_scope_files:
            if not source_exists:
                continue
            _add_error(
                result, "E_SOURCE_SPLIT_ORIGIN_MISSING", "scope",
                f"Task requires split/refactor of {source_path}, but this file is not "
                "in any coder packet's write scope. Creating new modules is not "
                "enough; the original file must become a shim/delegator or be updated.",
                None,
                f"Add {source_path} to an implementation packet's scope, or explicitly declare "
                "this as a create-only preparation phase that does not require old "
                "imports to be removed.",
            )

        if intent.requires_import_migration and old_import_path and target_repo_root and source_exists:
            references = collect_repo_references(target_repo_root, old_import_path)
            if references:
                outside: set[str] = set()
                for reference in references:
                    if (
                        reference.path not in all_scope_files
                        and "docs/" not in reference.path
                        and "archive" not in reference.path
                    ):
                        outside.add(reference.path)
                if outside:
                    reference_paths = sorted(outside)[:10]
                    _add_error(
                        result, "E_IMPORT_MIGRATION_SCOPE_INCOMPLETE", "scope",
                        f"Plan requires old import {old_import_path} from {source_path} to be "
                        f"removed, but {len(outside)} active references remain "
                        f"outside write scope: {reference_paths}",
                        None,
                        "Include all active reference files in scope, split import "
                        "migration into another packet, or keep old module as shim "
                        "and relax T0 to allow shim-only reference.",
                        details={
                            "old_import": old_import_path,
                            "source_path": source_path,
                            "outside_refs": sorted(outside),
                        },
                    )
# END_BLOCK_VALIDATOR
