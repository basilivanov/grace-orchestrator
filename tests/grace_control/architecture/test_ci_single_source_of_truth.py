# ############################################################################
# AI_HEADER: test_ci_single_source_of_truth — guard canonical CI command ownership
# ROLE: Structural regression tests for the Makefile/workflow boundary. These tests
#       keep CI policy in Make targets and prevent duplicate shell implementations.
# ############################################################################

# START_MODULE_CONTRACT
# purpose: Verify that Makefile targets own deterministic CI policy and workflow jobs delegate to them.
# inputs: Repository Makefile, GitHub Actions workflow, and hygiene script paths.
# returns: Pytest assertions for canonical target composition and orphan-reference absence.
# side_effects: Reads repository text files only.
# emitted_logs: None.
# error_behavior: Assertion failure when a CI policy is duplicated or an orphan reference returns.
# END_MODULE_CONTRACT

# START_MODULE_MAP
# mapping:
#   - function: test_makefile_defines_canonical_ci_targets
#   - function: test_ci_target_composes_canonical_targets
#   - function: test_workflow_delegates_to_make_targets
#   - function: test_hygiene_policy_has_one_owner
#   - function: test_removed_changed_files_lint_helper_has_no_active_reference
# END_MODULE_MAP

from __future__ import annotations

from pathlib import Path

from grace_control.core.structured_logger import GraceLogger

_log = GraceLogger("test_ci_single_source_of_truth")
_ROOT = Path(__file__).resolve().parents[3]


# START_FUNCTION_CONTRACT
# name: test_makefile_defines_canonical_ci_targets
# purpose: Ensure test, lint, docs-check, and hygiene are explicit Make targets with shared scopes.
# inputs: None; reads the repository Makefile.
# returns: None; assertions pass when canonical target definitions are present.
# side_effects: Reads Makefile text.
# emitted_logs: None.
# error_behavior: Assertion failure when a required target or scope is absent.
# END_FUNCTION_CONTRACT
def test_makefile_defines_canonical_ci_targets() -> None:
    makefile = (_ROOT / "Makefile").read_text(encoding="utf-8")

    assert "test:" in makefile
    assert 'pytest tests -m "not external and not live"' in makefile
    assert "lint:" in makefile
    assert "CI_LINT_SCOPE :=" in makefile
    assert "ruff check $(CI_LINT_SCOPE)" in makefile
    assert "scripts/grace_lint.py $(CI_LINT_SCOPE)" in makefile
    assert "docs-check:" in makefile
    assert "generate_docs.py --check" in makefile
    assert "hygiene:" in makefile
    assert "scripts/ci_repo_hygiene.py" in makefile
    assert 'pytest tests -m "external"' in makefile
    assert "tests/live/test_*.py" in makefile


# START_FUNCTION_CONTRACT
# name: test_ci_target_composes_canonical_targets
# purpose: Ensure make ci composes gates instead of reimplementing their commands.
# inputs: None; reads the repository Makefile.
# returns: None; assertion passes when composition has no duplicate hygiene recipe.
# side_effects: Reads Makefile text.
# emitted_logs: None.
# error_behavior: Assertion failure when ci bypasses a canonical target.
# END_FUNCTION_CONTRACT
def test_ci_target_composes_canonical_targets() -> None:
    makefile = (_ROOT / "Makefile").read_text(encoding="utf-8")
    assert "ci: test lint docs-check hygiene" in makefile

    ci_start = makefile.index("ci: test lint docs-check hygiene")
    ci_end = makefile.find("\n\n", ci_start)
    ci_body = makefile[ci_start:] if ci_end == -1 else makefile[ci_start:ci_end]
    assert "ci_repo_hygiene.py" not in ci_body


# START_FUNCTION_CONTRACT
# name: test_workflow_delegates_to_make_targets
# purpose: Ensure GitHub Actions invokes canonical Make targets without inline test or hygiene policy.
# inputs: None; reads the CI workflow.
# returns: None; assertions pass when workflow jobs delegate to Make.
# side_effects: Reads workflow text.
# emitted_logs: None.
# error_behavior: Assertion failure when workflow scope diverges from Makefile scope.
# END_FUNCTION_CONTRACT
def test_workflow_delegates_to_make_targets() -> None:
    workflow = (_ROOT / ".github" / "workflows" / "ci.yml").read_text(encoding="utf-8")

    for target in ("make test", "make lint", "make docs-check", "make hygiene"):
        assert target in workflow
    assert "pytest tests/grace_control/" not in workflow
    assert "scripts/ci_repo_hygiene.py" not in workflow
    assert "python scripts/grace_lint.py" not in workflow


# START_FUNCTION_CONTRACT
# name: test_hygiene_policy_has_one_owner
# purpose: Ensure repository hygiene is implemented only by the canonical hygiene script and target.
# inputs: None; reads Makefile and workflow text.
# returns: None; assertions pass when no second hygiene implementation exists.
# side_effects: Reads repository text files.
# emitted_logs: None.
# error_behavior: Assertion failure when hygiene policy is duplicated.
# END_FUNCTION_CONTRACT
def test_hygiene_policy_has_one_owner() -> None:
    makefile = (_ROOT / "Makefile").read_text(encoding="utf-8")
    workflow = (_ROOT / ".github" / "workflows" / "ci.yml").read_text(encoding="utf-8")
    script = (_ROOT / "scripts" / "ci_repo_hygiene.py").read_text(encoding="utf-8")

    hygiene_target = makefile[makefile.index("hygiene:"):]
    assert hygiene_target.splitlines()[1].strip() == "$(PYTHON) scripts/ci_repo_hygiene.py"
    assert "scripts/ci_repo_hygiene.py" not in workflow
    assert "repo_hygiene_passed" in script


# START_FUNCTION_CONTRACT
# name: test_removed_changed_files_lint_helper_has_no_active_reference
# purpose: Keep the obsolete one-off changed-files lint helper and its test out of active CI.
# inputs: None; reads active source, test, script, and workflow paths.
# returns: None; assertions pass when no active caller names the removed helper.
# side_effects: Reads selected repository text files.
# emitted_logs: None.
# error_behavior: Assertion failure when an orphan helper reference is reintroduced.
# END_FUNCTION_CONTRACT
def test_removed_changed_files_lint_helper_has_no_active_reference() -> None:
    removed_helper_name = "grace_changed_files_" + "lint.py"
    active_roots = (
        _ROOT / "Makefile",
        _ROOT / ".github" / "workflows",
        _ROOT / "src",
        _ROOT / "tests",
        _ROOT / "scripts",
    )
    for path in active_roots:
        paths = (path,) if path.is_file() else path.rglob("*")
        for candidate in paths:
            if candidate.is_file() and candidate.suffix in {".py", ".yml", ".yaml", ""}:
                if candidate == Path(__file__):
                    continue
                assert removed_helper_name not in candidate.read_text(
                    encoding="utf-8", errors="replace"
                )
