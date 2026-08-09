# ############################################################################
# AI_HEADER: gate_resolver
# ROLE: Auto-gate matrix — resolve touched areas and default T0/T1/T2 commands
#       from changed files and acceptance profile.
# ############################################################################

# START_MODULE_CONTRACT
# purpose: Analyse changed files and resolve deterministic mechanical gates
#          per profile. Architect no longer needs to provide low-level commands.
# inputs: changed_files list, acceptance profile, worktree path.
# returns: dict of default T0/T1/T2 commands with origin labels.
# side_effects: None (pure logic).
# error_behavior: Returns empty list when no defaults can be resolved.
# END_MODULE_CONTRACT

from __future__ import annotations

import re
from pathlib import Path, PurePosixPath
from typing import Any, Literal

TouchedArea = Literal["frontend", "backend", "contracts", "db", "docs", "domain"]

_FRONTEND_EXTS = {".js", ".jsx", ".ts", ".tsx", ".vue", ".svelte", ".css", ".scss"}
_BACKEND_EXTS = {".py", ".pyi"}
_CONTRACT_EXTS = {".graphql", ".proto", ".yaml", ".yml"}
_DB_EXTS = {".sql"}
_DOCS_EXTS = {".md", ".mdx", ".rst"}

_FRONTEND_PREFIXES = ("app/", "components/", "pages/", "src/", "public/")
_BACKEND_PREFIXES = ("apps/api/", "backend/", "services/")
_CONTRACT_PREFIXES = ("packages/contracts/", "contracts/", "openapi/")
_DB_PREFIXES = ("alembic/", "migrations/")
_DOCS_PREFIXES = ("docs/", "grace/", "wiki/")
_DOMAIN_PREFIXES: tuple[str, ...] = ()


def resolve_touched_areas(changed_files: list[str]) -> list[TouchedArea]:
    areas: set[TouchedArea] = set()
    for f in changed_files:
        fp = f.replace("\\", "/")
        suffix = Path(fp).suffix

        # Check prefix-based areas first (more specific)
        if any(fp.startswith(p) for p in _DB_PREFIXES) or suffix in _DB_EXTS or ("schema" in fp.lower() and fp.endswith(".py")):
            areas.add("db")
        elif any(fp.startswith(p) for p in _BACKEND_PREFIXES) or suffix in _BACKEND_EXTS:
            areas.add("backend")

        if any(fp.startswith(p) for p in _FRONTEND_PREFIXES) or suffix in _FRONTEND_EXTS:
            areas.add("frontend")
        if any(fp.startswith(p) for p in _CONTRACT_PREFIXES) or suffix in _CONTRACT_EXTS or "openapi" in fp.lower():
            areas.add("contracts")
        if any(fp.startswith(p) for p in _DOCS_PREFIXES) or suffix in _DOCS_EXTS:
            areas.add("docs")
        if any(fp.startswith(p) for p in _DOMAIN_PREFIXES):
            areas.add("domain")
    return sorted(areas, key=_area_order)


def _area_order(a: TouchedArea) -> int:
    return {"frontend": 0, "backend": 1, "contracts": 2, "db": 3, "docs": 4, "domain": 5}.get(a, 99)


def _detect_guardrails(worktree_path: Path) -> str | None:
    """Check which guardrails interface the target repo provides."""
    strict = worktree_path / "scripts" / "guardrails.sh"
    if strict.exists():
        return "guardrails.sh"
    return None


_FRONTEND_LINT_MISSING_CMD = [
    "python3", "-c",
    "import sys; print('ERROR: frontend changed but no frontend GRACE lint "
    "(scripts/grace_front_lint.py) available'); sys.exit(1)",
]

# ── Path exclusion patterns (generated/vendor/framework) ──────────────
_EXCLUDED_DIRS: frozenset[str] = frozenset({
    "node_modules", ".next", ".venv", "venv", "__pycache__",
    ".mypy_cache", ".pytest_cache", ".ruff_cache", ".git",
})
_EXCLUDED_PATH_PREFIXES: tuple[str, ...] = (
    "alembic/", "migrations/", "components/ui/",
)
_EXCLUDED_FILE_SUFFIXES: tuple[str, ...] = (
    ".min.js", ".min.css",
)


def _load_canon_config(base: Path) -> dict:
    """Load grace/canon.yaml config if it exists."""
    for config_name in ("grace/canon.yaml", ".grace/canon.yaml"):
        if (base / config_name).is_file():
            try:
                import yaml
                return yaml.safe_load((base / config_name).read_text()) or {}
            except Exception:
                pass
    return {}


def _path_is_excluded(path: str, extra_globs: tuple[str, ...] = ()) -> bool:
    """Check if a relative file path should be excluded from GRACE lint."""
    fp = path.replace("\\", "/")
    pp = PurePosixPath(fp)
    for part in fp.split("/"):
        if part in _EXCLUDED_DIRS:
            return True
    for prefix in _EXCLUDED_PATH_PREFIXES:
        if fp.startswith(prefix):
            return True
    for suffix in _EXCLUDED_FILE_SUFFIXES:
        if fp.endswith(suffix):
            return True
    for glob_pattern in extra_globs:
        if pp.match(glob_pattern):
            return True
    return False


def _is_grace_orchestrator(base: Path) -> bool:
    return (base / ".grace" / "state").exists() or (base / "src" / "grace_control").exists()


def resolve_linter_mode(worktree_path: Path) -> str:
    base = worktree_path.resolve() if worktree_path else Path.cwd()
    if _is_grace_orchestrator(base):
        return "strict"
    canon = _load_canon_config(base)
    gate_mode = canon.get("gate_mode", "")
    if gate_mode in ("changed-files", "strict", "disabled"):
        return gate_mode
    return "disabled"


def enrich_packet(pkt_spec: dict, dep_ids: list[str] | None = None) -> dict:
    """Enrich a packet spec with auto-resolved defaults.

    Sets depends_on from resolved dep_ids, ensures default fields exist.
    Used by architect router _persist_plan after DAG id resolution.

    W02: Does NOT setdefault("scope", []) — empty scope must be caught
    by the plan compiler, not hidden by a default value.
    """
    enriched = dict(pkt_spec)
    if dep_ids:
        enriched["depends_on"] = dep_ids
    # W02: No enriched.setdefault("scope", []) — missing scope is an error
    enriched.setdefault("depends_on", [])
    enriched.setdefault("conflict_keys", [])
    enriched.setdefault("acceptance_profile", "NORMAL")
    return enriched


def resolve_default_t0(
    changed_files: list[str],
    worktree_path: Path,
    profile: str = "NORMAL",
) -> tuple[list[list[str]], list[str]]:
    commands: list[list[str]] = []
    origins: list[str] = []
    base = worktree_path.resolve() if worktree_path else Path.cwd()
    linter_mode = resolve_linter_mode(base)
    canon = _load_canon_config(base)
    extra_globs: tuple[str, ...] = ()
    if "exclude" in canon:
        extra_globs = tuple(p for p in (canon["exclude"] or []) if isinstance(p, str) and p.strip())

    areas = resolve_touched_areas(changed_files)

    py_files = [f for f in changed_files if f.endswith(".py") or f.endswith(".pyi")]
    fe_files = [f for f in changed_files if Path(f).suffix in _FRONTEND_EXTS
                or any(f.startswith(p) for p in _FRONTEND_PREFIXES)]

    # ruff on changed Python files (always, regardless of repo)
    if py_files:
        commands.append(["python3", "-m", "ruff", "check"] + py_files)
        origins.append("auto:t0:ruff")

    if linter_mode == "disabled":
        return commands, origins

    # Filter out excluded paths for GRACE linting
    lint_py = [f for f in py_files if not _path_is_excluded(f, extra_globs)]
    lint_fe = [f for f in fe_files if not _path_is_excluded(f, extra_globs)]

    frontend_lint_ran = False

    # backend GRACE lint — only when there are non-excluded files
    if linter_mode in ("strict", "changed-files") and lint_py and (base / "scripts" / "grace_lint.py").is_file():
        if linter_mode == "strict":
            commands.append(["python3", "scripts/grace_lint.py"] + lint_py)
        else:
            for f in lint_py:
                commands.append(["python3", "scripts/grace_lint.py", f])
        origins.append("auto:t0:backend_grace_lint")

    # frontend GRACE lint — only when there are non-excluded files
    if linter_mode in ("strict", "changed-files") and lint_fe and (base / "scripts" / "grace_front_lint.py").is_file():
        if linter_mode == "strict":
            commands.append(["python3", "scripts/grace_front_lint.py"] + lint_fe)
        else:
            for f in lint_fe:
                commands.append(["python3", "scripts/grace_front_lint.py", f])
        origins.append("auto:t0:frontend_grace_lint")
        frontend_lint_ran = True
    elif linter_mode == "strict" and "frontend" in areas:
        # legacy fallback — orchestrator repo only
        if (base / "scripts" / "grace" / "check-markers.sh").is_file():
            commands.append(["bash", "scripts/grace/check-markers.sh"])
            origins.append("auto:t0:frontend_markers_fallback")
            frontend_lint_ran = True

    # NORMAL/STRICT: fail if frontend changed but no frontend lint available (strict only)
    if linter_mode == "strict" and "frontend" in areas and not frontend_lint_ran and profile in ("NORMAL", "STRICT"):
        commands.append(_FRONTEND_LINT_MISSING_CMD)
        origins.append("auto:t0:frontend_lint_missing")

    return commands, origins


def resolve_default_t1(
    changed_files: list[str],
    worktree_path: Path,
    profile: str = "NORMAL",
) -> tuple[list[list[str]], list[str]]:
    commands: list[list[str]] = []
    origins: list[str] = []
    base = worktree_path.resolve() if worktree_path else Path.cwd()

    # T1 is only for NORMAL and STRICT profiles
    if profile == "FAST":
        return commands, origins

    areas = resolve_touched_areas(changed_files)
    guardrails = _detect_guardrails(base)

    # Use guardrails.sh normal level if available
    if guardrails:
        commands.append(["bash", f"scripts/{guardrails}", "normal"])
        origins.append("auto:t1:guardrails_normal")
        return commands, origins

    # Fallback per area
    if "frontend" in areas:
        pnpm_test = ["pnpm", "test:run"] if (base / "package.json").exists() else []
        if pnpm_test:
            commands.append(pnpm_test)
            origins.append("auto:t1:pnpm_test")

    if "backend" in areas:
        commands.append(["python3", "-m", "pytest", "-q", "--tb=short"])
        origins.append("auto:t1:pytest")

    return commands, origins


def resolve_default_t2(
    changed_files: list[str],
    worktree_path: Path,
    profile: str = "STRICT",
) -> tuple[list[list[str]], list[str]]:
    commands: list[list[str]] = []
    origins: list[str] = []
    base = worktree_path.resolve() if worktree_path else Path.cwd()

    # T2 is only for STRICT profile
    if profile != "STRICT":
        return commands, origins

    guardrails = _detect_guardrails(base)
    if guardrails:
        strict_script = ["bash", f"scripts/{guardrails}", "strict"]
        if (base / "scripts" / guardrails).is_file():
            commands.append(strict_script)
            origins.append("auto:t2:guardrails_strict")
            return commands, origins
        commands.append(["bash", f"scripts/{guardrails}", "full"])
        origins.append("auto:t2:guardrails_full")
        return commands, origins

    return commands, origins


def resolve_default_gates(
    changed_files: list[str],
    profile: str,
    worktree_path: Path,
) -> dict[str, Any]:
    t0_cmds, t0_origins = resolve_default_t0(changed_files, worktree_path, profile)
    t1_cmds, t1_origins = resolve_default_t1(changed_files, worktree_path, profile)
    t2_cmds, t2_origins = resolve_default_t2(changed_files, worktree_path, profile)

    return {
        "t0": {"commands": t0_cmds, "origins": t0_origins},
        "t1": {"commands": t1_cmds, "origins": t1_origins},
        "t2": {"commands": t2_cmds, "origins": t2_origins},
        "touched_areas": resolve_touched_areas(changed_files),
    }
