# ############################################################################
# AI_HEADER: plan_compiler
# ROLE: Deterministic preflight validator — compiles architect plan before
#        coder execution, rejecting invalid packets before runtime.
# ############################################################################

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Literal

from pydantic import BaseModel

from grace_control.core.execution_environment import ExecutionEnvironment
from grace_control.core.structured_logger import GraceLogger

_log = GraceLogger("plan_compiler")


# ── Source split intent models ──────────────────────────────────────────
@dataclass
class SourceSplitIntent:
    source_path: str
    old_import_path: str | None = None
    new_package_prefix: str | None = None
    operation: str = "split"  # split, extract, move, refactor
    requires_source_modification: bool = True
    requires_import_migration: bool = False
    allows_shim: bool = True


@dataclass
class RepoReference:
    path: str
    line: int
    text: str


class CompileError(BaseModel):
    code: str
    severity: Literal["error", "warning"]
    packet_title: str | None = None
    field_path: str
    message: str
    suggestion: str | None = None
    details: dict | None = None

    model_config = {"frozen": False}


class CompileResult(BaseModel):
    ok: bool
    errors: list[CompileError] = []
    warnings: list[CompileError] = []
    normalized_plan: dict | None = None

    model_config = {"frozen": False}


# ── Grep pattern with unquoted spaces ──────────────────────────────────
_GREP_SPACE_PATTERN = re.compile(
    r'\bgrep\s+(?:-[A-Za-z]+\s+)*([^-\'\"][\w\s]+?)\s+\S+'
)


# ── Invalid Python one-liner patterns ─────────────────────────────────
_INVALID_PY_PATTERNS = [
    # for/while at end of line with colon (no body possible)
    re.compile(r'\bfor\s+\w+\s+in\s+[^:]+:\s*$'),
    re.compile(r'\bwhile\s+[^:]+:\s*$'),
    re.compile(r'\bif\s+[^:]+:\s*$'),
    # class/def at end of file (no body possible)
    re.compile(r'\b(class|def)\s+\w+[^(]*:\s*$'),
]


# ── Bash-only syntax patterns ──────────────────────────────────────────
_BASH_ONLY_PATTERNS = [
    (re.compile(r'\bsource\s'), "source", "use . (dot) instead of source"),
    (re.compile(r'\[\[\s+'), "[[", "use [ instead of [[ for POSIX sh"),
    (re.compile(r'\$\{(\w+)[/#]'), "${VAR//x/y}", "bash-only parameter expansion, use sed/tr instead"),
]


# ── Shell operators in argv list (require shell=True) ──────────────────
_SHELL_OPS_IN_CMDS = re.compile(r'&&|\|\||[;|><]|\$\(|2>&1')


def _add_error(
    result: CompileResult,
    code: str,
    field_path: str,
    message: str,
    packet_title: str | None = None,
    suggestion: str | None = None,
    details: dict | None = None,
) -> None:
    result.errors.append(
        CompileError(
            code=code,
            severity="error",
            packet_title=packet_title,
            field_path=field_path,
            message=message,
            suggestion=suggestion,
            details=details,
        )
    )
    result.ok = False


def _add_warning(
    result: CompileResult,
    code: str,
    field_path: str,
    message: str,
    packet_title: str | None = None,
    suggestion: str | None = None,
) -> None:
    result.warnings.append(
        CompileError(
            code=code,
            severity="warning",
            packet_title=packet_title,
            field_path=field_path,
            message=message,
            suggestion=suggestion,
        )
    )


# ── Source split / import migration helpers ────────────────────────────

_SOURCE_SPLIT_KEYWORDS = [
    "split", "break up", "extract", "move", "refactor",
    "decompose", "modularize", "shim", "legacy module", "old import",
    # Russian
    "разбить", "разделить", "вынести", "распилить",
    "декомпозировать", "разнести", "рефактор", "перенести",
    "разбиение", "разделение",
]

_SOURCE_SPLIT_PATH_PATTERN = re.compile(
    r'(apps/api/\S+\.py|packages/\S+\.py|src/\S+\.py|grace/\S+\.py)'
)

_OLD_IMPORT_PATTERN = re.compile(
    r'(app\.\w+(?:\.\w+)+)'  # e.g. app.services.llm_service
)


def _import_path_to_source_path(import_path: str) -> str:
    """Convert app.services.llm_service → apps/api/app/services/llm_service.py."""
    parts = import_path.split(".")
    if parts[0] == "app":
        # app.services.llm_service → apps/api/app/services/llm_service.py
        return "apps/api/" + "/".join(parts) + ".py"
    if parts[0] in ("src", "packages", "scripts"):
        return "/".join(parts) + ".py"
    return import_path


def detect_source_split_intents(feature_description: str, plan: dict, env: ExecutionEnvironment) -> list[SourceSplitIntent]:
    """Analyze feature description + plan for split/refactor patterns."""
    intents: list[SourceSplitIntent] = []
    all_text = feature_description.lower()

    # Check if it's a split/refactor task
    is_split = any(kw in all_text for kw in _SOURCE_SPLIT_KEYWORDS)
    if not is_split:
        return intents

    # Find source file paths in description
    paths = _SOURCE_SPLIT_PATH_PATTERN.findall(feature_description)
    import_candidates = _OLD_IMPORT_PATTERN.findall(feature_description)

    # Also scan T0/T1/T2 for old import references
    for wave in plan.get("waves", []):
        for pkt in wave.get("packets", []):
            for v_key in ("t0", "t1", "t2"):
                for cmd in pkt.get("verification", {}).get(v_key, []):
                    cmd_str = str(cmd) if isinstance(cmd, str) else " ".join(cmd)
                    imps = _OLD_IMPORT_PATTERN.findall(cmd_str)
                    import_candidates.extend(imps)

    unique_paths = set(paths)
    unique_imports = set(import_candidates)

    for path in unique_paths:
        parent = str(Path(path).parent)
        intents.append(SourceSplitIntent(
            source_path=path,
            new_package_prefix=parent + "/" if parent else None,
            operation="split",
        ))

    for imp in unique_imports:
        source = _import_path_to_source_path(imp)
        # Always create a refactor intent for import migration checks,
        # even if the source path was also detected from feature description.
        intents.append(SourceSplitIntent(
            source_path=source,
            old_import_path=imp,
            operation="refactor",
            requires_import_migration=True,
        ))

    return intents


def collect_repo_references(target_root: Path, import_path: str) -> list[RepoReference]:
    """Scan active code dirs for old import path references."""
    if not target_root or not target_root.exists():
        return []
    refs: list[RepoReference] = []
    search_dirs = ["apps/", "src/", "tests/", "packages/", "scripts/"]
    exclude_dirs = {".git", ".grace", "node_modules", ".venv", "dist", "build", "coverage", "__pycache__", "archive"}

    for rel_dir in search_dirs:
        search_root = target_root / rel_dir
        if not search_root.exists():
            continue
        for fpath in sorted(search_root.rglob("*.py")):
            # Check if in excluded dir
            parts = fpath.relative_to(target_root).parts
            if any(ex in parts for ex in exclude_dirs):
                continue
            try:
                text = fpath.read_text(encoding="utf-8", errors="replace")
            except Exception:
                continue
            for lineno, line in enumerate(text.splitlines(), 1):
                if import_path in line:
                    refs.append(RepoReference(
                        path=str(fpath.relative_to(target_root)),
                        line=lineno,
                        text=line.strip()[:300],
                    ))
                    if len(refs) >= 100:
                        return refs
    return refs


class PlanCompiler:

    _VALID_EXPECTATIONS = frozenset({
        "exists", "created", "modified", "deleted", "absent",
        "diff_contains", "test_output", "import_absent", "import_updated",
    })

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
            env = probe_execution_environment()

        result = CompileResult(ok=True)

        waves = plan.get("waves", [])
        if not waves:
            return result  # Empty plan is valid (nothing to do)

        # ── 0. Source-split preflight (before per-packet checks) ─────
        self._validate_source_split(result, plan, env, feature_description, target_repo_root)

        for wi, wave in enumerate(waves):
            for pi, packet in enumerate(wave.get("packets", [])):
                title = packet.get("title", f"wave-{wi}-pkt-{pi}")
                scope = packet.get("scope", [])
                role = packet.get("role", "coder")

                # ── W02: Fail-closed scope type validation ──────────────
                # Scope MUST be a list. A string scope is truthy but iterates
                # as characters (e.g. "src/foo/" → ["s","r","c","/","f","o","o","/"]),
                # producing misleading per-character errors. Reject early.
                if scope is not None and not isinstance(scope, list):
                    _add_error(
                        result, "E_SCOPE_NOT_LIST",
                        f"waves[{wi}].packets[{pi}].scope",
                        f"scope must be a list of strings, got {type(scope).__name__} — "
                        f"string scope iterates as characters instead of file paths",
                        title,
                        "use a list of strings: ['path/to/file.py', 'path/to/dir/']",
                    )
                    # Reset to empty list to avoid iterating non-list
                    scope = []

                # ── W02: Fail-closed scope validation ────────────────
                # Coder packets MUST have explicit, non-empty scope.
                # Missing/empty scope = compiler error, not a default fallback.
                if role == "coder" and not scope:
                    _add_error(
                        result, "E_CODER_EMPTY_SCOPE",
                        f"waves[{wi}].packets[{pi}].scope",
                        f"coder packet '{title}' has no write scope — "
                        f"every coder packet must specify explicit repo-relative scope",
                        title,
                        "add target files/directories to scope (e.g. ['src/grace_control/services/'])",
                    )

                # W02: Validate each scope path
                for si, sp in enumerate(scope):
                    if not isinstance(sp, str):
                        _add_error(
                            result, "E_SCOPE_PATH_NOT_STRING",
                            f"waves[{wi}].packets[{pi}].scope[{si}]",
                            f"scope entry must be a string, got {type(sp).__name__}",
                            title,
                        )
                        continue

                    # W02: Reject absolute paths (not silently stripped)
                    if sp.startswith("/"):
                        _add_error(
                            result, "E_SCOPE_ABSOLUTE_PATH",
                            f"waves[{wi}].packets[{pi}].scope[{si}]",
                            f"scope path '{sp}' is absolute — scope must be repo-relative",
                            title,
                            f"remove leading '/': '{sp.lstrip("/")}'",
                        )

                    # W02: Reject parent paths (..)
                    if ".." in Path(sp).parts:
                        _add_error(
                            result, "E_SCOPE_PARENT_PATH",
                            f"waves[{wi}].packets[{pi}].scope[{si}]",
                            f"scope path '{sp}' contains '..' — scope must be within repo",
                            title,
                            "use repo-relative path without parent references",
                        )

                    # W02: Reject Python import paths (dot-separated, no /)
                    # Exclude filenames with common extensions (e.g. "file.py", "config.yaml")
                    # which are valid filesystem paths, not Python imports.
                    _FILE_EXTENSIONS = (
                        ".py", ".yaml", ".yml", ".json", ".toml", ".txt", ".md",
                        ".cfg", ".ini", ".sh", ".bash", ".sql", ".html", ".css",
                        ".js", ".ts", ".tsx", ".jsx", ".rs", ".go",
                    )
                    if "." in sp and "/" not in sp and not sp.startswith(".") and not sp.endswith(_FILE_EXTENSIONS):
                        _add_error(
                            result, "E_SCOPE_PYTHON_IMPORT_PATH",
                            f"waves[{wi}].packets[{pi}].scope[{si}]",
                            f"scope path '{sp}' looks like a Python import path — "
                            f"scope must be filesystem paths (e.g. 'src/grace_control/services/')",
                            title,
                            f"convert to filesystem path: replace dots with '/' and add '.py' or '/'",
                        )

                    # Existing: non-canonical scope paths (app/, app.)
                    if isinstance(sp, str) and (
                        sp.startswith("app/")
                        or sp.startswith("app.")
                        or (".services" in sp and "/" not in sp)
                    ):
                        _add_error(
                            result, "E_SCOPE_PATH_NOT_CANONICAL",
                            f"waves[{wi}].packets[{pi}].scope[{si}]",
                            f"scope path '{sp}' is not canonical (e.g. use "
                            f"apps/api/app/services/... not app/... or app.services...)",
                            title,
                            f"replace '{sp}' with the full filesystem path",
                        )

                # W02: Reject scope/frozen_scope overlap (not silently strip)
                frozen = packet.get("frozen_scope", []) or []
                if scope and frozen:
                    overlap = set(scope) & set(frozen)
                    if overlap:
                        _add_error(
                            result, "E_SCOPE_FROZEN_OVERLAP",
                            f"waves[{wi}].packets[{pi}].scope",
                            f"scope and frozen_scope overlap: {sorted(overlap)} — "
                            f"a file cannot be both writable and frozen",
                            title,
                            f"remove overlapping paths from either scope or frozen_scope",
                        )

                # W02: Reject root constraints.frozen_scope overlap with packet scope.
                # Root frozen_scope is applied during materialization AFTER compiler
                # validation — so a packet with scope overlapping root frozen_scope
                # would silently become a READY packet that violates scope contract.
                root_constraints = plan.get("constraints", {})
                root_frozen = root_constraints.get("frozen_scope", []) or []
                if scope and root_frozen:
                    root_overlap = set(scope) & set(root_frozen)
                    if root_overlap:
                        _add_error(
                            result, "E_ROOT_FROZEN_SCOPE_OVERLAP",
                            f"waves[{wi}].packets[{pi}].scope",
                            f"scope overlaps with root constraints.frozen_scope: "
                            f"{sorted(root_overlap)} — root frozen paths are applied "
                            f"during materialization and cannot be writable",
                            title,
                            "remove overlapping paths from packet scope or root constraints.frozen_scope",
                        )

                verification = packet.get("verification", {})
                evidence = packet.get("expected_evidence", [])
                role = packet.get("role", "coder")
                description = packet.get("description", "")
                acceptance = packet.get("acceptance_criteria", [])
                coder_instructions = packet.get("coder_instructions", [])

                t0 = verification.get("t0", [])
                t1 = verification.get("t1", [])
                t2 = verification.get("t2", [])

                # ── 1. Command syntax validation ──────────────────
                all_cmds = [(t0, "t0"), (t1, "t1"), (t2, "t2")]
                for cmds, stage_name in all_cmds:
                    for ci, cmd in enumerate(cmds):
                        if isinstance(cmd, str):
                            self._validate_cmd(
                                result, cmd, env, title, f"verification.{stage_name}[{ci}]"
                            )

                # ── 2. Scope vs acceptance ────────────────────────
                self._validate_scope_acceptance(
                    result, title, scope, t1, acceptance, coder_instructions, role
                )

                # ── 3. Evidence contract ──────────────────────────
                self._validate_evidence(
                    result, title, evidence, role, description, scope
                )

                # ── 3b. Evidence–instruction contradiction ──────
                self._validate_evidence_contradiction(
                    result, title, evidence, coder_instructions,
                    description, packet.get("validation_hint", ""),
                )

                # ── 4. Role/scope consistency ─────────────────────
                self._validate_role_scope(result, title, role, scope, description)

        _log.info("compile_done", ok=result.ok, errors=len(result.errors),
                  warnings=len(result.warnings))
        return result

    def _validate_source_split(
        self,
        result: CompileResult,
        plan: dict,
        env: ExecutionEnvironment,
        feature_description: str,
        target_repo_root: Path | None = None,
    ) -> None:
        """Reject split/refactor plans that omit the original source file from scope."""
        if not feature_description:
            return

        intents = detect_source_split_intents(feature_description, plan, env)
        if not intents:
            return

        # Collect all files in scope across all packets + global frozen scope
        all_scope_files: set[str] = set()
        for wave in plan.get("waves", []):
            for pkt in wave.get("packets", []):
                for s in pkt.get("scope", []) or []:
                    all_scope_files.add(s)
        # Plan-level frozen_scope also counts — files that are explicitly
        # protected from modification don't need to be in packet scope.
        for fs in plan.get("constraints", {}).get("frozen_scope", []) or []:
            all_scope_files.add(fs)

        for intent in intents:
            src = intent.source_path
            old_imp = intent.old_import_path

            # Skip intents for files that don't exist in the repo — these
            # are new files being created, not source files being refactored.
            source_exists = False
            if target_repo_root and target_repo_root.exists():
                test_path = target_repo_root / src
                if test_path.exists():
                    source_exists = True
            if not source_exists and target_repo_root:
                # Fallback: check relative paths without target repo root
                if Path(src).exists():
                    source_exists = True

            # E_SOURCE_SPLIT_ORIGIN_MISSING: source file must be in scope
            if intent.requires_source_modification and src not in all_scope_files:
                # Only flag if source file ACTUALLY EXISTS — new files being
                # created don't need an origin source to be in scope.
                if not source_exists:
                    continue
                _add_error(
                    result, "E_SOURCE_SPLIT_ORIGIN_MISSING",
                    "scope",
                    f"Task requires split/refactor of {src}, but this file is not "
                    f"in any coder packet's write scope. Creating new modules is not "
                    f"enough; the original file must become a shim/delegator or be updated.",
                    None,
                    f"Add {src} to an implementation packet's scope, or explicitly declare "
                    f"this as a create-only preparation phase that does not require old "
                    f"imports to be removed.",
                )

            # E_IMPORT_MIGRATION_SCOPE_INCOMPLETE: old imports outside scope
            if intent.requires_import_migration and old_imp and target_repo_root and source_exists:
                refs = collect_repo_references(target_repo_root, old_imp)
                if refs:
                    outside: set[str] = set()
                    for r in refs:
                        if r.path not in all_scope_files and "docs/" not in r.path and "archive" not in r.path:
                            outside.add(r.path)
                    if outside:
                        ref_paths = sorted(outside)[:10]
                        import_details = {
                            "old_import": old_imp,
                            "source_path": src,
                            "outside_refs": sorted(outside),
                        }
                        _add_error(
                            result, "E_IMPORT_MIGRATION_SCOPE_INCOMPLETE",
                            "scope",
                            f"Plan requires old import {old_imp} from {src} to be "
                            f"removed, but {len(outside)} active references remain "
                            f"outside write scope: {ref_paths}",
                            None,
                            "Include all active reference files in scope, split import "
                            "migration into another packet, or keep old module as shim "
                            "and relax T0 to allow shim-only reference.",
                            details=import_details,
                        )

    def _validate_cmd(
        self,
        result: CompileResult,
        cmd: str,
        env: ExecutionEnvironment,
        title: str,
        field_path: str,
    ) -> None:
        # Shell incompatibility: source under dash
        if not env.shell_is_bash and " source " in cmd:
            _add_error(
                result, "E_SHELL_SOURCE_UNDER_DASH",
                field_path, f"command uses 'source' but shell is {env.shell} (not bash)",
                title, "use '.' (dot) instead or run under bash",
            )

        # Source in general → warn (should use .)
        if "source .venv" in cmd or "source venv" in cmd:
            _add_warning(
                result, "W_SHELL_SOURCE",
                field_path, "command uses 'source' for venv activation (bash-only)",
                title, "use '. .venv/bin/activate' or run python directly",
            )

        # Missing venv reference
        if ".venv/bin/activate" in cmd or ".venv/bin/python" in cmd:
            if not env.has_api_venv:
                _add_error(
                    result, "E_VENV_MISSING",
                    field_path,
                    "command references venv but target repo has no .venv",
                    title,
                    f"system python3 at {env.api_python_path} is available; "
                    "use it directly or install venv in target repo",
                )
            else:
                _add_warning(
                    result, "W_VENV_ACTIVATE_IN_WORKTREE",
                    field_path,
                    "venv exists in target repo but may not exist in worktree; "
                    "activation will fail at runtime in worktree",
                    title,
                    "use the absolute python path instead of activation: "
                    f"{env.api_python_path} -m pytest ...",
                )

        # Unsafe grep splitting
        if cmd.startswith("grep ") or cmd.startswith("egrep "):
            # Check the raw string for unquoted multi-word patterns
            # Pattern: grep -c word1 word2 file → word1+word2 is an unquoted pattern
            # The command runner will see word2 as a filename argument
            words = cmd.split()
            if len(words) >= 4:
                # After grep + flags, check if there are 2+ consecutive non-flag
                # non-file words before the last argument (the file path)
                idx = 1
                while idx < len(words) and words[idx].startswith("-"):
                    idx += 1
                # words[idx] is the first non-flag word (pattern start)
                # If words[idx+1] looks like a pattern continuation (not a path, not quoted)
                if idx + 2 < len(words):
                    next_word = words[idx + 1]
                    last_word = words[-1]
                    # If next_word doesn't look like a file path and isn't quoted
                    if (not ("/" in next_word or next_word.endswith((".py",".yml",".yaml",".json",".md",".sh")))
                        and not (next_word.startswith("'") or next_word.startswith('"'))):
                        pattern_combined = " ".join(words[idx:idx+2])
                        _add_warning(
                            result, "W_GREP_UNQUOTED_SPACE",
                            field_path,
                            f"grep pattern '{pattern_combined}' has spaces without quotes "
                            f"— '{words[idx+1]}' will be treated as a filename argument",
                            title, f"use single quotes: '...{pattern_combined}...'",
                        )

        # Invalid Python one-liners
        if cmd.startswith("python3 -c ") or cmd.startswith("python -c "):
            code = cmd.split("-c ", 1)[1] if "-c " in cmd else ""
            # Try to extract code (may be quoted)
            if code.startswith("'") and "'" in code[1:]:
                code = code.split("'")[1]
            elif code.startswith('"') and '"' in code[1:]:
                code = code.split('"')[1]
            for pat in _INVALID_PY_PATTERNS:
                if pat.search(code):
                    _add_error(
                        result, "E_PYTHON_INVALID_ONELINER",
                        field_path, f"inline Python has invalid one-liner syntax: {pat.pattern[:40]}...",
                        title, "for/while/if/class/def cannot be one-liners; use comprehensions or wrap in exec()",
                    )
                    break

            # Check for missing quotes around -c argument
            non_quoted = cmd.split("-c ", 1)[1] if "-c " in cmd else ""
            if not (non_quoted.startswith("'") or non_quoted.startswith('"')):
                _add_warning(
                    result, "W_PYTHON_C_UNQUOTED",
                    field_path, "python3 -c argument is not quoted; only first word will be executed",
                    title, f"use single quotes: python3 -c '{non_quoted[:50]}...'",
                )

        # Bash-only syntax under sh
        if not env.shell_is_bash:
            for pattern, feature, fix in _BASH_ONLY_PATTERNS:
                if pattern.search(cmd):
                    # Skip 'source' when it's for venv activation (caught by E_VENV_MISSING)
                    if feature == "source" and ("venv" in cmd.lower() or "activate" in cmd.lower()):
                        continue
                    _add_error(
                        result, "E_BASH_SYNTAX_UNDER_SH",
                        field_path, f"command uses bash-only feature '{feature}' but shell is {env.shell}",
                        title, fix,
                    )

        # Shell operators that need shell=True
        if _SHELL_OPS_IN_CMDS.search(cmd):
            pass  # shell=True is now default for non-python3, so this is fine

    def _validate_scope_acceptance(
        self,
        result: CompileResult,
        title: str,
        scope: list[str],
        t1: list[str],
        acceptance: list[str],
        coder_instructions: list[str],
        role: str,
    ) -> None:
        # Check if T1 runs tests on files outside scope
        test_files_in_t1: set[str] = set()
        for cmd in (t1 if isinstance(t1, list) else []):
            cmd_s = str(cmd) if isinstance(cmd, str) else " ".join(cmd)
            import re as _re
            test_refs = _re.findall(r'tests?/[\w/_.-]+\.py', cmd_s)
            test_files_in_t1.update(test_refs)

        test_files_in_scope: set[str] = set()
        for s in scope:
            if "test" in s.lower():
                test_files_in_scope.add(s)

        tests_outside = test_files_in_t1 - test_files_in_scope

        # Check if the packet deletes/renames symbols
        deletes_symbol = False
        all_text = " ".join(coder_instructions + [str(acceptance)])
        if any(
            kw in all_text.lower()
            for kw in ("remove", "delete", "rename", "move ", "extract from")
        ):
            # Negative patterns: phrases like "do not delete", "no renames"
            # should NOT trigger the detection.
            neg = re.compile(
                r'\b(do not|don.t|no|without|never|avoid|prevent)\s+'
                r'(remove|delet|renam|mov|extract)\w*\b',
                re.IGNORECASE,
            )
            has_negative = neg.search(all_text)
            if not has_negative:
                deletes_symbol = True

        # Error only when: tests outside scope + delete/rename + no shim
        if tests_outside and deletes_symbol and role == "coder":
            has_shim = any(
                kw in all_text.lower()
                for kw in ("shim", "compatibility wrapper", "keep old", "deprecated stub",
                          "re-export", "backward compat")
            )
            if not has_shim:
                _add_error(
                    result, "E_SCOPE_ACCEPTANCE_IMPOSSIBLE",
                    f"verification.t1",
                    f"T1 runs tests {tests_outside} outside write scope {scope}, "
                    f"packet deletes/renames/moves symbols, and no compatibility "
                    f"shim is described",
                    title,
                    "keep compatibility shim/wrapper/re-export for old symbol, "
                    "or include test files in write scope",
                )

    def _validate_evidence(
        self,
        result: CompileResult,
        title: str,
        evidence: list[dict],
        role: str,
        description: str,
        scope: list[str],
    ) -> None:
        for ei, ev in enumerate(evidence):
            if not isinstance(ev, dict):
                continue
            kind = ev.get("kind", "")
            patterns = ev.get("artifact_patterns", [])
            required = ev.get("required", True)

            # Validate expectation enum
            expectation = ev.get("expectation", "") or "exists"
            if expectation not in self._VALID_EXPECTATIONS:
                _add_error(
                    result, "E_EVIDENCE_EXPECTATION_UNKNOWN",
                    f"expected_evidence[{ei}].expectation",
                    f"unknown expectation '{expectation}' — "
                    f"valid values: {sorted(self._VALID_EXPECTATIONS)}",
                    title,
                    f"use one of: {', '.join(sorted(self._VALID_EXPECTATIONS))}",
                )

            # kind=diff with pattern=agent.patch → wrong
            if kind == "diff" and required:
                if "agent.patch" in str(patterns):
                    _add_warning(
                        result, "W_EVIDENCE_DIFF_AGENT_PATCH",
                        f"expected_evidence[{ei}]",
                        "expected_evidence uses kind=diff with pattern=agent.patch — "
                        "agent.patch never matches changed_files from git diff",
                        title, "use kind=diff without pattern, or kind=file with specific filenames",
                    )

            # Verification-only packet requiring diff
            if kind == "diff" and required and role == "coder":
                no_code = "no code changes" in description.lower() or "no files need modification" in description.lower()
                if no_code:
                    _add_error(
                        result, "E_EVIDENCE_DIFF_VERIFICATION_ONLY",
                        f"expected_evidence[{ei}]",
                        "packet is verification-only but requires diff evidence",
                        title, "remove diff evidence requirement or change role to verifier",
                    )

            # No scope files but requires diff
            if kind == "diff" and required and not scope:
                _add_error(
                    result, "E_EVIDENCE_DIFF_EMPTY_SCOPE",
                    f"expected_evidence[{ei}]",
                    "packet requires diff evidence but has empty write scope",
                    title, "add target files to scope or remove diff evidence",
                )

    # ── Remove/delete keywords for contradiction detection ─────────────
    _REMOVE_INTENT_KEYWORDS = [
        "remove", "delete", "consolidate", "drop", "eliminate",
        "get rid of", "clean up", "delete the file",
        # Russian
        "удалить", "убрать", "избавиться", "удали",
        "удаление", "удаляем",
    ]

    def _has_remove_intent(self, texts: list[str]) -> list[str]:
        """Check if any text expresses intent to remove files.
        Returns list of matched keywords for context."""
        matched: list[str] = []
        for text in texts:
            t = text.lower()
            for kw in self._REMOVE_INTENT_KEYWORDS:
                if kw in t:
                    matched.append(kw)
                    break  # one match per text is enough
        return matched

    def _extract_target_paths_for_removal(
        self, texts: list[str], evidence_paths: list[str],
    ) -> list[str]:
        """Extract file paths from instructions that match evidence paths
        and are likely being removed. Looks for patterns like:
        'delete models.py', 'remove src/foo.py', 'consolidate bar.py into'
        """
        targets: list[str] = []
        for text in texts:
            t = text.lower()
            for ep in evidence_paths:
                ep_lower = ep.lower()
                ep_name = Path(ep).name.lower()
                # Check if evidence path or filename appears near remove keyword
                for kw in self._REMOVE_INTENT_KEYWORDS:
                    if kw in t and (ep_lower in t or ep_name in t):
                        targets.append(ep)
                        break
        return list(set(targets))

    def _validate_evidence_contradiction(
        self,
        result: CompileResult,
        title: str,
        evidence: list[dict],
        coder_instructions: list[str],
        description: str,
        validation_hint: str,
    ) -> None:
        """Detect when expected_evidence expects a file to exist ('exists')
        but instructions tell the coder to delete/remove that same file."""
        if not evidence:
            return

        # Collect evidence paths + their expectations
        ev_paths: list[str] = []
        for ev in evidence:
            if not isinstance(ev, dict):
                continue
            patterns = ev.get("artifact_patterns", ev.get("pattern", []))
            if isinstance(patterns, str):
                patterns = [patterns]
            ev_paths.extend(p for p in patterns if p.endswith(".py") or "." in p)

        if not ev_paths:
            return

        # Check all text sources for remove intent
        all_texts = coder_instructions + [description, validation_hint]
        remove_kws = self._has_remove_intent(all_texts)
        if not remove_kws:
            return

        # Find which evidence paths are targeted for removal
        removal_targets = self._extract_target_paths_for_removal(
            all_texts, ev_paths
        )
        if not removal_targets:
            return

        # For each removal target, check if evidence says 'exists' (default)
        for ev in evidence:
            if not isinstance(ev, dict):
                continue
            patterns = ev.get("artifact_patterns", ev.get("pattern", []))
            if isinstance(patterns, str):
                patterns = [patterns]
            expectation = ev.get("expectation", "") or "exists"
            ev_id = ev.get("id", "?")
            for p in patterns:
                if p in removal_targets and expectation == "exists":
                    _add_error(
                        result, "E_EVIDENCE_CONTRADICTS_INSTRUCTIONS",
                        f"expected_evidence",
                        f"Evidence '{ev_id}' expects '{p}' to exist (expectation='exists'), "
                        f"but instructions say to remove/delete it (keywords: {remove_kws}). "
                        f"Change expectation to 'deleted' or 'absent', or remove this evidence entry.",
                        title,
                        f"Set expectation: 'deleted' for file being removed, or "
                        f"'absent' if the file does not need to be removed by this packet.",
                        details={
                            "evidence_id": ev_id,
                            "file": p,
                            "current_expectation": expectation,
                            "remove_keywords": remove_kws,
                            "suggested_fix": "deleted",
                        },
                    )
                elif p in removal_targets and expectation in ("deleted", "absent"):
                    pass  # explicit deletion expectation — no contradiction

    def _validate_role_scope(
        self,
        result: CompileResult,
        title: str,
        role: str,
        scope: list[str],
        description: str,
    ) -> None:
        # W02: Empty coder scope is now checked in compile_plan() main loop
        # with more detail (wave/packet index). Keep the old check as a
        # safety net for direct _validate_role_scope() callers.
        if role == "coder" and not scope:
            _add_error(
                result, "E_CODER_EMPTY_SCOPE",
                "scope", "coder packet has empty write scope — nothing to write",
                title, "add target files to scope or change role to verifier",
            )

        # Coder packets described as verification-only
        if role == "coder" and (
            "no code changes" in description.lower()
            or "no files need modification" in description.lower()
            or "verification-only" in description.lower()
        ):
            _add_error(
                result, "E_VERIFICATION_ONLY_CODER",
                "role", "coder packet described as verification-only",
                title, "change role to 'verifier' or add files to modify",
            )

        # W02: Frozen scope vs scope overlap is now checked in compile_plan()
        # main loop as E_SCOPE_FROZEN_OVERLAP (not silently stripped).


# ── Public convenience function ────────────────────────────────────────

def compile_plan(
    plan: dict,
    env: ExecutionEnvironment | None = None,
    *,
    feature_description: str = "",
    target_repo_root: Path | None = None,
) -> CompileResult:
    return PlanCompiler().compile_plan(
        plan, env,
        feature_description=feature_description,
        target_repo_root=target_repo_root,
    )
