"""Tests for plan_compiler and execution_environment."""
from __future__ import annotations

import pytest
from pathlib import Path

from grace_control.core.execution_environment import (
    ExecutionEnvironment,
    probe_execution_environment,
)
from grace_control.core.plan_compiler import (
    CompileError,
    CompileResult,
    PlanCompiler,
    compile_plan,
)


def _env(**kwargs) -> ExecutionEnvironment:
    """Shortcut to build test environment."""
    defaults = {
        "shell": "/bin/sh",
        "shell_is_bash": False,
        "shell_supports_source": False,
        "subprocess_shell_default": True,
        "project_root": "/opt/solarsage-astro",
        "target_repo_root": "/opt/solarsage-astro",
        "worktree_root": "/opt/solarsage-astro/.grace/worktrees",
        "state_root": "/opt/solarsage-astro/.grace/state",
        "api_python_path": "/usr/bin/python3",
        "has_api_venv": False,
        "package_manager": "pnpm",
    }
    defaults.update(kwargs)
    return ExecutionEnvironment(**defaults)


def _plan(*packets) -> dict:
    """Build a minimal plan with given packets."""
    return {"waves": [{"title": "Wave 1", "packets": list(packets)}]}


def _pkt(title="Test packet", scope=None, t0=None, t1=None, t2=None,
         evidence=None, role="coder", description="", acceptance=None,
         instructions=None) -> dict:
    if scope is None:
        scope = ["path/to/file.py"]
    return {
        "title": title,
        "scope": scope,
        "verification": {"t0": t0 or [], "t1": t1 or [], "t2": t2 or []},
        "expected_evidence": evidence or [],
        "role": role,
        "description": description,
        "acceptance_criteria": acceptance or [],
        "coder_instructions": instructions or [],
    }


# ══════════════════════════════════════════════════════════════════════
# Shell / environment
# ══════════════════════════════════════════════════════════════════════


class TestShellEnvironment:

    def test_rejects_source_when_shell_is_dash(self):
        """source is bash-only; dash/sh should fail."""
        compiler = PlanCompiler()
        env = _env(shell_is_bash=False, shell_supports_source=False)
        result = compiler.compile_plan(
            _plan(_pkt(t0=["source .venv/bin/activate && pytest"])),
            env,
        )
        assert not result.ok
        assert any("bash" in e.code.lower() or "venv" in e.code.lower() for e in result.errors)

    def test_rejects_missing_venv_reference(self):
        """venv activation should fail when venv doesn't exist."""
        compiler = PlanCompiler()
        env = _env(has_api_venv=False)
        result = compiler.compile_plan(
            _plan(_pkt(t1=["cd apps/api && . .venv/bin/activate && pytest"])),
            env,
        )
        assert not result.ok
        assert any("venv" in e.code.lower() for e in result.errors)

    def test_rejects_bash_syntax_under_sh(self):
        """[[ ... ]] should fail under dash."""
        compiler = PlanCompiler()
        env = _env(shell_is_bash=False)
        result = compiler.compile_plan(
            _plan(_pkt(t0=["[[ -f file.yml ]] && echo ok"])),
            env,
        )
        assert not result.ok

    def test_accepts_posix_syntax(self):
        """POSIX syntax should pass even under dash."""
        compiler = PlanCompiler()
        env = _env(shell_is_bash=False)
        result = compiler.compile_plan(
            _plan(_pkt(t0=["test -f file.yml && echo ok"])),
            env,
        )
        assert result.ok

    def test_accepts_bash_command_when_runner_is_bash(self):
        """source should be allowed when shell is bash."""
        compiler = PlanCompiler()
        env = _env(shell_is_bash=True, shell_supports_source=True, has_api_venv=True)
        result = compiler.compile_plan(
            _plan(_pkt(t0=["source .venv/bin/activate && pytest"])),
            env,
        )
        assert result.ok


# ══════════════════════════════════════════════════════════════════════
# Command syntax
# ══════════════════════════════════════════════════════════════════════


class TestCommandSyntax:

    def test_warns_unquoted_grep_pattern_with_spaces(self):
        compiler = PlanCompiler()
        env = _env()
        result = compiler.compile_plan(
            _plan(_pkt(
                t0=["grep -c class LLMService apps/api/app/services/llm_service.py"]
            )),
            env,
        )
        assert any("grep" in str(w.code).lower() for w in result.warnings)

    def test_accepts_quoted_grep_pattern(self):
        compiler = PlanCompiler()
        env = _env()
        result = compiler.compile_plan(
            _plan(_pkt(
                t0=["grep -c 'class LLMService' apps/api/app/services/llm_service.py"]
            )),
            env,
        )
        assert result.ok

    def test_rejects_missing_quotes_on_python_c(self):
        compiler = PlanCompiler()
        env = _env()
        result = compiler.compile_plan(
            _plan(_pkt(
                t0=["python3 -c import sys; import yaml; print(yaml.__version__)"]
            )),
            env,
        )
        assert any("quoted" in str(w.message).lower() for w in result.warnings)

    def test_accepts_properly_quoted_python_c(self):
        compiler = PlanCompiler()
        env = _env()
        result = compiler.compile_plan(
            _plan(_pkt(
                t0=["python3 -c 'import sys; import yaml; print(yaml.__version__)'"]
            )),
            env,
        )
        assert result.ok

    def test_rejects_for_loop_oneliner(self):
        compiler = PlanCompiler()
        env = _env()
        result = compiler.compile_plan(
            _plan(_pkt(
                t0=["python3 -c 'for k in [\"packet_dir\",\"roles_dir\",\"packet_schema\"] :'"]
            )),
            env,
        )
        assert not result.ok


# ══════════════════════════════════════════════════════════════════════
# Scope / acceptance
# ══════════════════════════════════════════════════════════════════════


class TestScopeAcceptance:

    def test_rejects_symbol_delete_when_tests_outside_scope(self):
        compiler = PlanCompiler()
        env = _env()
        pkt = _pkt(
            title="Move method from ServiceA to ServiceB",
            scope=["apps/api/app/services/service_a.py",
                   "apps/api/app/services/service_b.py"],
            t1=["cd apps/api && python -m pytest tests/test_service_a.py -q"],
            instructions=["remove _build_llm_input from NatalReportService",
                         "delete the old method entirely"],
            acceptance=["All existing tests pass"],
            role="coder",
        )
        result = compiler.compile_plan(_plan(pkt), env)
        assert not result.ok
        assert any("scope" in str(e.code).lower() for e in result.errors)

    def test_accepts_no_moves_without_test_conflict(self):
        compiler = PlanCompiler()
        env = _env()
        pkt = _pkt(
            title="Add new method to ServiceB",
            scope=["apps/api/app/services/service_b.py"],
            t1=["cd apps/api && python -m pytest tests/test_service_b.py -q"],
            instructions=["add new helper method to ServiceB"],
        )
        result = compiler.compile_plan(_plan(pkt), env)
        assert result.ok  # Adding a method shouldn't break existing tests

    def test_rejects_all_tests_pass_without_test_scope(self):
        compiler = PlanCompiler()
        env = _env()
        pkt = _pkt(
            title="Change internal logic",
            scope=["apps/api/app/services/logic.py"],
            acceptance=["All existing tests pass"],
            instructions=["refactor internal logic"],
            role="coder",
        )
        result = compiler.compile_plan(_plan(pkt), env)
        assert not result.ok


# ══════════════════════════════════════════════════════════════════════
# Evidence
# ══════════════════════════════════════════════════════════════════════


class TestEvidence:

    def test_rejects_diff_evidence_for_verification_only(self):
        compiler = PlanCompiler()
        env = _env()
        pkt = _pkt(
            title="Verify files exist",
            scope=[],
            description="No code changes needed, just verify paths",
            evidence=[{"id": "EV1", "kind": "diff", "required": True,
                       "artifact_patterns": ["agent.patch"]}],
            role="coder",
        )
        result = compiler.compile_plan(_plan(pkt), env)
        assert not result.ok

    def test_warns_diff_with_agent_patch_pattern(self):
        compiler = PlanCompiler()
        env = _env()
        pkt = _pkt(
            title="Create file",
            scope=["path/to/new_file.py"],
            evidence=[{"id": "EV1", "kind": "diff", "required": True,
                       "artifact_patterns": ["agent.patch"]}],
        )
        result = compiler.compile_plan(_plan(pkt), env)
        assert any("agent.patch" in str(w.message) for w in result.warnings)

    def test_accepts_file_evidence_for_creation(self):
        compiler = PlanCompiler()
        env = _env()
        pkt = _pkt(
            title="Create file",
            scope=["path/to/new_file.py"],
            evidence=[{"id": "EV1", "kind": "file", "required": True,
                       "artifact_patterns": ["path/to/new_file.py"]}],
        )
        result = compiler.compile_plan(_plan(pkt), env)
        assert result.ok


# ══════════════════════════════════════════════════════════════════════
# Role / scope consistency
# ══════════════════════════════════════════════════════════════════════


class TestRoleScope:

    def test_rejects_coder_with_empty_scope(self):
        compiler = PlanCompiler()
        env = _env()
        pkt = _pkt(title="Verify something", scope=[], role="coder")
        result = compiler.compile_plan(_plan(pkt), env)
        assert not result.ok

    def test_rejects_verification_only_coder(self):
        compiler = PlanCompiler()
        env = _env()
        pkt = _pkt(
            title="Verify files",
            scope=["file.py"],
            description="No code changes needed — verification-only",
            role="coder",
        )
        result = compiler.compile_plan(_plan(pkt), env)
        assert not result.ok

    def test_accepts_verifier_role_with_no_changes(self):
        compiler = PlanCompiler()
        env = _env()
        pkt = _pkt(
            title="Verify files",
            scope=["file.py"],
            description="No code changes needed — verification-only",
            role="verifier",
        )
        result = compiler.compile_plan(_plan(pkt), env)
        assert result.ok  # verifier role is fine for verification-only


# ══════════════════════════════════════════════════════════════════════
# Environment probe
# ══════════════════════════════════════════════════════════════════════


class TestEnvironmentProbe:

    def test_probe_returns_environment(self):
        env = probe_execution_environment()
        assert env.shell
        assert env.project_root
        assert env.api_python_path is not None

    def test_probe_detects_shell(self):
        env = probe_execution_environment()
        assert "/sh" in env.shell.lower() or "bash" in env.shell.lower()

    def test_empty_plan_is_valid(self):
        compiler = PlanCompiler()
        result = compiler.compile_plan({"waves": []})
        assert result.ok
        assert not result.errors

    def test_plan_without_waves_is_valid(self):
        compiler = PlanCompiler()
        result = compiler.compile_plan({})
        assert result.ok
