# ############################################################################
# AI_HEADER: test_execution_environment_vertical_slice — verify runtime fact flow
# ROLE: Regression coverage for discovery, architect prompt enrichment, and compiler
#       rejection using one shared ExecutionEnvironment contract.
# ############################################################################

# START_MODULE_CONTRACT
# purpose: Prove the minimal runtime discovery to architect to compiler vertical slice.
# inputs: Temporary Python and Node repository layouts.
# returns: Pytest assertions for the four required scenarios.
# side_effects: Creates files and symlinks only below pytest temporary directories.
# emitted_logs: None.
# error_behavior: Fails assertions when deterministic facts or validation drift.
# END_MODULE_CONTRACT

# START_MODULE_MAP
# mapping:
#   - function: test_python_project_discovers_standard_facts
#   - function: test_node_project_does_not_invent_python
#   - function: test_architect_prompt_contains_environment_facts
#   - function: test_compiler_rejects_missing_python_module
# END_MODULE_MAP

from __future__ import annotations

import sys

from grace_control.core.execution_environment import (
    ExecutionEnvironment,
    probe_execution_environment,
)
from grace_control.core.plan_compiler import PlanCompiler
from grace_control.core.structured_logger import GraceLogger
from grace_control.services.feature_planning_service import FeaturePlanningService

_log = GraceLogger("test_execution_environment_vertical_slice")


def _minimal_plan(command: str) -> dict:
    return {
        "waves": [{
            "title": "W00",
            "packets": [{
                "title": "Validate environment",
                "role": "coder",
                "scope": ["pyproject.toml"],
                "description": "Validate the discovered Python environment.",
                "coder_instructions": ["Keep the project configuration valid."],
                "acceptance_criteria": ["The verification command passes."],
                "verification": {"t0": [], "t1": [command], "t2": []},
                "expected_evidence": [],
            }],
        }],
    }


# START_BLOCK_VERTICAL_SLICE
# START_FUNCTION_CONTRACT
# name: test_python_project_discovers_standard_facts
# purpose: Verify venv, scripts, PostgreSQL compose service, and ignore discovery.
# inputs: tmp_path — isolated Python repository root.
# returns: None; assertions describe the required facts.
# side_effects: Creates a temporary repository layout.
# emitted_logs: None.
# error_behavior: Assertion failure on missing or non-relative facts.
# END_FUNCTION_CONTRACT
def test_python_project_discovers_standard_facts(tmp_path) -> None:
    python_path = tmp_path / ".venv" / "bin" / "python"
    python_path.parent.mkdir(parents=True)
    python_path.symlink_to(sys.executable)
    scripts = tmp_path / "scripts"
    scripts.mkdir()
    gate = scripts / "run_pr_gate.sh"
    gate.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
    gate.chmod(0o755)
    (scripts / "grace_lint.py").write_text("raise SystemExit(0)\n", encoding="utf-8")
    (tmp_path / "pyproject.toml").write_text("[project]\nname='demo'\n", encoding="utf-8")
    (tmp_path / "docker-compose.yml").write_text(
        "services:\n  postgres:\n    image: postgres:16\n",
        encoding="utf-8",
    )
    (tmp_path / ".gitignore").write_text(
        "verification-output/\n.coverage\n",
        encoding="utf-8",
    )

    environment = probe_execution_environment(target_repo_root=tmp_path)

    assert environment.python_candidates == [".venv/bin/python"]
    assert environment.executable_scripts == ["scripts/run_pr_gate.sh"]
    assert environment.verification_entrypoints == [
        "scripts/grace_lint.py",
        "scripts/run_pr_gate.sh",
    ]
    assert environment.compose_services == ["postgres"]
    assert environment.ignored_patterns == ["verification-output/", ".coverage"]
    assert all(not value.startswith(str(tmp_path)) for value in environment.config_sources)

    grace_dir = tmp_path / "grace"
    grace_dir.mkdir()
    (grace_dir / "project.yaml").write_text(
        "environment:\n"
        "  python: tools/python\n"
        "verification:\n"
        "  lint: tools/python scripts/grace_lint.py app tests\n"
        "  full: scripts/run_pr_gate.sh\n",
        encoding="utf-8",
    )
    overridden = probe_execution_environment(target_repo_root=tmp_path)
    assert overridden.python_candidates == ["tools/python"]
    assert overridden.verification_entrypoints == [
        "tools/python scripts/grace_lint.py app tests",
        "scripts/run_pr_gate.sh",
    ]


# START_FUNCTION_CONTRACT
# name: test_node_project_does_not_invent_python
# purpose: Verify a Node-only repository has no inferred Python executable.
# inputs: tmp_path — isolated Node repository root.
# returns: None; asserts the Python candidate list is empty.
# side_effects: Creates a temporary package.json.
# emitted_logs: None.
# error_behavior: Assertion failure if host Python leaks into target facts.
# END_FUNCTION_CONTRACT
def test_node_project_does_not_invent_python(tmp_path) -> None:
    (tmp_path / "package.json").write_text(
        '{"name":"node-only","scripts":{"test":"node --test"}}\n',
        encoding="utf-8",
    )

    environment = probe_execution_environment(target_repo_root=tmp_path)

    assert environment.python_candidates == []
    assert environment.config_sources == ["package.json"]


# START_FUNCTION_CONTRACT
# name: test_architect_prompt_contains_environment_facts
# purpose: Verify deterministic facts are rendered before the canonical architect prompt.
# inputs: None; uses an in-memory ExecutionEnvironment.
# returns: None; asserts exact prompt labels and values.
# side_effects: Loads the canonical architect prompt file.
# emitted_logs: None.
# error_behavior: Assertion failure when prompt enrichment is absent.
# END_FUNCTION_CONTRACT
def test_architect_prompt_contains_environment_facts() -> None:
    environment = ExecutionEnvironment(
        shell="/bin/sh",
        python_candidates=[".venv/bin/python"],
        executable_scripts=["scripts/run_pr_gate.sh"],
        verification_entrypoints=[
            "scripts/grace_lint.py",
            "scripts/run_pr_gate.sh",
        ],
        compose_services=["postgres"],
        ignored_patterns=["verification-output/", ".coverage"],
        config_sources=["pyproject.toml", "docker-compose.yml", ".gitignore"],
    )
    service = FeaturePlanningService(None)

    prompt = service._build_architect_prompt(
        "Implement a small feature.",
        {"summary": "Python service", "files": []},
        environment,
    )

    assert "DETERMINISTIC ENVIRONMENT FACTS" in prompt
    assert "Python: .venv/bin/python" in prompt
    assert "Verification entrypoints:\n- scripts/grace_lint.py\n- scripts/run_pr_gate.sh" in prompt
    assert "Compose services:\n- postgres" in prompt
    assert "Ignored patterns:\n- verification-output/\n- .coverage" in prompt


# START_FUNCTION_CONTRACT
# name: test_compiler_rejects_missing_python_module
# purpose: Verify compiler rejects python -m when the module is absent.
# inputs: tmp_path — isolated Python repository with a real venv executable link.
# returns: None; asserts E_PYTHON_MODULE_MISSING is emitted.
# side_effects: Creates a temporary executable symlink and pyproject.toml.
# emitted_logs: None.
# error_behavior: Assertion failure if an invalid packet materializes.
# END_FUNCTION_CONTRACT
def test_compiler_rejects_missing_python_module(tmp_path) -> None:
    python_path = tmp_path / ".venv" / "bin" / "python"
    python_path.parent.mkdir(parents=True)
    python_path.symlink_to(sys.executable)
    (tmp_path / "pyproject.toml").write_text("[project]\nname='demo'\n", encoding="utf-8")
    environment = probe_execution_environment(target_repo_root=tmp_path)

    result = PlanCompiler().compile_plan(
        _minimal_plan(".venv/bin/python -m grace_lint"),
        environment,
        target_repo_root=tmp_path,
    )

    assert not result.ok
    assert any(error.code == "E_PYTHON_MODULE_MISSING" for error in result.errors)
# END_BLOCK_VERTICAL_SLICE
