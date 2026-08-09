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
    SourceSplitIntent,
    RepoReference,
    detect_source_split_intents,
    _import_path_to_source_path,
    _SOURCE_SPLIT_KEYWORDS,
    compile_plan,
)


def _env(**kwargs) -> ExecutionEnvironment:
    """Shortcut to build test environment."""
    defaults = {
        "shell": "/bin/sh",
        "python_candidates": ["python", "python3"],
        "executable_scripts": [],
        "verification_entrypoints": ["scripts/grace_lint.py"],
        "compose_services": [],
        "ignored_patterns": [],
        "config_sources": [],
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
        """source is bash-only; sh should fail (even for non-venv usage)."""
        compiler = PlanCompiler()
        env = _env()
        result = compiler.compile_plan(
            _plan(_pkt(t0=["source /etc/profile && echo ok"])),
            env,
        )
        assert not result.ok
        assert any("bash" in e.code.lower() for e in result.errors)

    def test_accepts_source_word_inside_quoted_grep_pattern(self):
        """Quoted forbidden-text assertions are data, not shell syntax."""
        compiler = PlanCompiler()
        env = _env()
        result = compiler.compile_plan(
            _plan(_pkt(t0=[
                '! grep -R "source \\|bash\\|BIDDER_APPLY_ENABLED=true" scripts/run_pr_gate.sh',
                "node -e 'console.log(\"browser source safety check passed\")'",
            ])),
            env,
        )
        assert result.ok

    def test_rejects_missing_venv_reference(self):
        """venv activation should fail when venv doesn't exist."""
        compiler = PlanCompiler()
        env = _env(python_candidates=[])
        result = compiler.compile_plan(
            _plan(_pkt(t1=["cd apps/api && . .venv/bin/activate && pytest"])),
            env,
        )
        assert not result.ok
        assert any("venv" in e.code.lower() for e in result.errors)

    def test_allows_venv_reference_after_explicit_bootstrap_packet(self):
        compiler = PlanCompiler()
        env = _env(python_candidates=[])
        packet = _pkt(
            scope=[".venv/", "scripts/bootstrap.py"],
            description="Bootstrap the reusable project venv before tests.",
            instructions=["Create and install the project venv."],
            t1=[".venv/bin/python -m pytest -q"],
        )

        result = compiler.compile_plan(_plan(packet), env)

        assert result.ok
        assert any(e.code == "W_VENV_PLANNED_BOOTSTRAP" for e in result.warnings)

    def test_allows_generated_venv_bootstrap_outside_tracked_scope(self):
        compiler = PlanCompiler()
        env = _env(python_candidates=[])
        packet = _pkt(
            scope=["pyproject.toml", "scripts/bootstrap.py"],
            description="Bootstrap /opt/project/.venv before later verification.",
            instructions=["Create the reusable .venv as a generated, ignored side effect."],
            t1=[".venv/bin/python -m pytest -q"],
        )

        result = compiler.compile_plan(_plan(packet), env)

        assert result.ok
        assert any(e.code == "W_VENV_PLANNED_BOOTSTRAP" for e in result.warnings)

    def test_rejects_venv_use_without_create_or_bootstrap_intent(self):
        compiler = PlanCompiler()
        env = _env(python_candidates=[])
        packet = _pkt(
            scope=["pyproject.toml"],
            description="Use the existing .venv to install dependencies.",
            t1=[".venv/bin/python -m pytest -q"],
        )

        result = compiler.compile_plan(_plan(packet), env)

        assert not result.ok
        assert any(e.code == "E_VENV_MISSING" for e in result.errors)

    def test_enforces_feature_declared_python_file_limit(self, tmp_path):
        app_dir = tmp_path / "app"
        app_dir.mkdir()
        for index in range(16):
            (app_dir / f"module_{index}.py").write_text("", encoding="utf-8")
        compiler = PlanCompiler()
        env = _env(target_repo_root=str(tmp_path))

        result = compiler.compile_plan(
            _plan(_pkt(scope=["app"])),
            env,
            feature_description="Coder packets contain at most 15 Python files.",
            target_repo_root=tmp_path,
        )

        assert not result.ok
        error = next(e for e in result.errors if e.code == "E_SCOPE_PYTHON_FILE_LIMIT")
        assert error.details["python_file_count"] == 16
        assert error.details["python_file_limit"] == 15

    def test_does_not_invent_python_file_limit(self, tmp_path):
        app_dir = tmp_path / "app"
        app_dir.mkdir()
        for index in range(16):
            (app_dir / f"module_{index}.py").write_text("", encoding="utf-8")
        compiler = PlanCompiler()
        env = _env(target_repo_root=str(tmp_path))

        result = compiler.compile_plan(
            _plan(_pkt(scope=["app"])),
            env,
            target_repo_root=tmp_path,
        )

        assert result.ok

    def test_rejects_bash_syntax_under_sh(self):
        """[[ ... ]] should fail under sh — bash-only syntax."""
        compiler = PlanCompiler()
        env = _env()
        result = compiler.compile_plan(
            _plan(_pkt(t0=["[[ -f /etc/hostname ]] && echo ok"])),
            env,
        )
        assert not result.ok
        assert any("bash" in e.code.lower() for e in result.errors)

    def test_accepts_posix_syntax(self):
        """POSIX syntax should pass even under dash."""
        compiler = PlanCompiler()
        env = _env(shell="/bin/sh")
        result = compiler.compile_plan(
            _plan(_pkt(t0=["test -f file.yml && echo ok"])),
            env,
        )
        assert result.ok

    def test_runner_shell_is_always_sh(self):
        """Commands always run through /bin/sh, not login $SHELL."""
        # Even if $SHELL=/bin/bash, the compiler hardcodes /bin/sh
        env = _env()
        assert env.shell == "/bin/sh" or "sh" in env.shell
        assert env.shell == "/bin/sh"


# ══════════════════════════════════════════════════════════════════════
# Command syntax
# ══════════════════════════════════════════════════════════════════════


class TestCommandSyntax:

    def test_rejects_negative_search_that_scans_regression_tests(self):
        compiler = PlanCompiler()
        env = _env()
        result = compiler.compile_plan(
            _plan(_pkt(
                scope=["src/http/router.js", "test/api.test.js"],
                t0=['! grep -R "legacy.example" -n src docs test'],
            )),
            env,
        )

        assert not result.ok
        assert any(e.code == "E_NEGATIVE_SEARCH_SCANS_TESTS" for e in result.errors)

    def test_accepts_negative_search_limited_to_product_paths(self):
        compiler = PlanCompiler()
        env = _env()
        result = compiler.compile_plan(
            _plan(_pkt(
                scope=["src/http/router.js", "test/api.test.js"],
                t0=['! grep -R "legacy.example" -n src docs'],
            )),
            env,
        )

        assert result.ok

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

    def test_accepts_repo_root_app_layout_and_alembic_template(self):
        compiler = PlanCompiler()
        env = _env()
        pkt = _pkt(scope=[
            "app/core/config.py",
            "app/storage/migrations/script.py.mako",
        ])
        result = compiler.compile_plan(_plan(pkt), env)
        assert result.ok

    def test_rejects_recursive_grace_lint_broader_than_file_scope(self, tmp_path):
        bidder = tmp_path / "app" / "bidder"
        bidder.mkdir(parents=True)
        (bidder / "smart_window.py").write_text("", encoding="utf-8")
        (bidder / "time_window.py").write_text("", encoding="utf-8")
        (bidder / "service.py").write_text("", encoding="utf-8")
        compiler = PlanCompiler()
        env = _env(target_repo_root=str(tmp_path))
        pkt = _pkt(
            scope=["app/bidder/smart_window.py", "app/bidder/time_window.py"],
            t1=["python3 scripts/grace_lint.py app/bidder"],
        )

        result = compiler.compile_plan(_plan(pkt), env, target_repo_root=tmp_path)

        assert not result.ok
        assert any(error.code == "E_SCOPE_ACCEPTANCE_IMPOSSIBLE" for error in result.errors)

    def test_accepts_recursive_grace_lint_when_all_files_are_in_scope(self, tmp_path):
        bidder = tmp_path / "app" / "bidder"
        bidder.mkdir(parents=True)
        (bidder / "smart_window.py").write_text("", encoding="utf-8")
        (bidder / "time_window.py").write_text("", encoding="utf-8")
        lint_script = tmp_path / "scripts" / "grace_lint.py"
        lint_script.parent.mkdir()
        lint_script.write_text("raise SystemExit(0)\n", encoding="utf-8")
        compiler = PlanCompiler()
        env = _env(target_repo_root=str(tmp_path))
        pkt = _pkt(
            scope=["app/bidder/smart_window.py", "app/bidder/time_window.py"],
            t1=["python3 scripts/grace_lint.py app/bidder"],
        )

        result = compiler.compile_plan(_plan(pkt), env, target_repo_root=tmp_path)

        assert result.ok

    def test_rejects_symbol_delete_when_tests_outside_scope(self):
        compiler = PlanCompiler()
        env = _env()
        pkt = _pkt(
            title="Move method from ServiceA to ServiceB",
            scope=["apps/api/app/services/service_a.py",
                   "apps/api/app/services/service_b.py"],
            t1=["cd apps/api && python3 -m pytest tests/test_service_a.py -q"],
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
            t1=["cd apps/api && python3 -m pytest tests/test_service_b.py -q"],
            instructions=["add new helper method to ServiceB"],
        )
        result = compiler.compile_plan(_plan(pkt), env)
        assert result.ok  # Adding a method shouldn't break existing tests

    def test_all_tests_pass_ok_when_no_move_delete(self):
        """all existing tests pass with narrow code scope is OK when no delete/rename/move."""
        compiler = PlanCompiler()
        env = _env()
        pkt = _pkt(
            title="Refactor internal logic",
            scope=["apps/api/app/services/logic.py"],
            acceptance=["All existing tests pass"],
            instructions=["refactor internal logic — no symbol renames"],
            role="coder",
        )
        result = compiler.compile_plan(_plan(pkt), env)
        assert result.ok  # No error: no delete/rename/move, tests may pass naturally

    def test_all_tests_pass_error_when_move_delete_no_shim(self):
        """all existing tests pass + move/delete + no shim = error."""
        compiler = PlanCompiler()
        env = _env()
        pkt = _pkt(
            title="Move method from ServiceA to ServiceB",
            scope=["apps/api/app/services/service_a.py",
                   "apps/api/app/services/service_b.py"],
            t1=["cd apps/api && python3 -m pytest tests/test_service_a.py -q"],
            instructions=["remove _build_llm_input from NatalReportService",
                         "delete the old method entirely"],
            acceptance=["All existing tests pass"],
            role="coder",
        )
        result = compiler.compile_plan(_plan(pkt), env)
        assert not result.ok  # Error: delete + tests outside scope + no shim

    def test_all_tests_pass_ok_when_move_with_shim(self):
        """all existing tests pass + move/delete + shim instruction = OK."""
        compiler = PlanCompiler()
        env = _env()
        pkt = _pkt(
            title="Move method with compatibility shim",
            scope=["apps/api/app/services/service_a.py",
                   "apps/api/app/services/service_b.py"],
            t1=["cd apps/api && python3 -m pytest tests/test_service_a.py -q"],
            instructions=["move method to ServiceB",
                         "keep old method as compatibility shim in ServiceA",
                         "add deprecated stub wrapper"],
            acceptance=["All existing tests pass"],
            role="coder",
        )
        result = compiler.compile_plan(_plan(pkt), env)
        assert result.ok  # OK: has shim instruction

    def test_all_tests_pass_ok_when_tests_in_scope(self):
        """all existing tests pass with tests in scope is OK."""
        compiler = PlanCompiler()
        env = _env()
        pkt = _pkt(
            title="Move method with test scope",
            scope=["apps/api/app/services/service_a.py",
                   "tests/test_service_a.py"],
            t1=["cd apps/api && python3 -m pytest tests/test_service_a.py -q"],
            instructions=["remove _build_llm_input from ServiceA"],
            acceptance=["All existing tests pass"],
            role="coder",
        )
        result = compiler.compile_plan(_plan(pkt), env)
        assert result.ok  # OK: tests are in scope


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
        assert not result.ok
        assert any(e.code == "E_EVIDENCE_DIFF_HAS_PATTERN" for e in result.errors)
        assert any("agent.patch" in str(w.message) for w in result.warnings)

    def test_accepts_controller_diff_evidence_without_pattern(self):
        compiler = PlanCompiler()
        env = _env()
        pkt = _pkt(
            title="Modify file",
            scope=["path/to/file.py"],
            evidence=[{"id": "EV1", "kind": "diff", "required": True,
                       "artifact_patterns": []}],
        )

        result = compiler.compile_plan(_plan(pkt), env)

        assert result.ok

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

    def test_rejects_descriptive_artifact_pattern(self):
        compiler = PlanCompiler()
        env = _env()
        pkt = _pkt(
            title="Run tests",
            t1=["python3 -m pytest tests/unit/test_example.py -q"],
            evidence=[{
                "id": "EV-TEST",
                "kind": "test",
                "producer": "pytest",
                "artifact_patterns": ["pytest stdout for tests/unit/test_example.py"],
            }],
        )

        result = compiler.compile_plan(_plan(pkt), env)

        assert any(e.code == "E_EVIDENCE_DESCRIPTIVE_PATTERN" for e in result.errors)

    def test_rejects_command_output_artifact_label(self):
        compiler = PlanCompiler()
        env = _env()
        pkt = _pkt(
            title="Run npm tests",
            t1=["npm test"],
            evidence=[{
                "id": "EV-TEST",
                "kind": "test",
                "producer": "cli",
                "artifact_patterns": ["npm test output"],
            }],
        )

        result = compiler.compile_plan(_plan(pkt), env)

        assert any(e.code == "E_EVIDENCE_DESCRIPTIVE_PATTERN" for e in result.errors)

    def test_rejects_run_command_artifact_label(self):
        compiler = PlanCompiler()
        env = _env()
        pkt = _pkt(
            title="Run npm tests",
            t1=["npm test"],
            evidence=[{
                "id": "EV-TEST",
                "kind": "test",
                "producer": "cli",
                "artifact_patterns": ["run: npm test"],
            }],
        )

        result = compiler.compile_plan(_plan(pkt), env)

        assert any(e.code == "E_EVIDENCE_DESCRIPTIVE_PATTERN" for e in result.errors)

    def test_rejects_bare_verification_command_as_artifact_pattern(self):
        compiler = PlanCompiler()
        env = _env()
        pkt = _pkt(
            title="Run npm tests",
            t1=["npm run check"],
            evidence=[{
                "id": "EV-TEST",
                "kind": "test",
                "producer": "cli",
                "artifact_patterns": ["npm run check"],
            }],
        )

        result = compiler.compile_plan(_plan(pkt), env)

        assert any(e.code == "E_EVIDENCE_DESCRIPTIVE_PATTERN" for e in result.errors)

    def test_rejects_ephemeral_root_command_output_artifact(self):
        compiler = PlanCompiler()
        env = _env()
        pkt = _pkt(
            title="Run npm tests",
            t1=["npm test"],
            evidence=[{
                "id": "EV-TEST",
                "kind": "test",
                "producer": "cli",
                "artifact_patterns": [".grace-t1-npm-test.stdout"],
            }],
        )

        result = compiler.compile_plan(_plan(pkt), env)

        assert any(
            e.code == "E_EVIDENCE_EPHEMERAL_ROOT_ARTIFACT"
            for e in result.errors
        )

    def test_rejects_contract_sentence_as_artifact_pattern(self):
        compiler = PlanCompiler()
        env = _env()
        pkt = _pkt(
            title="Document source links",
            evidence=[{
                "id": "EV-CONTRACT",
                "kind": "contract",
                "producer": "agent",
                "artifact_patterns": [
                    "GET /api/sources discoveryLinks include all required public links",
                ],
            }],
        )

        result = compiler.compile_plan(_plan(pkt), env)

        assert any(e.code == "E_EVIDENCE_DESCRIPTIVE_PATTERN" for e in result.errors)

    def test_rejects_unknown_visual_evidence_kind_and_descriptive_pattern(self):
        compiler = PlanCompiler()
        env = _env()
        pkt = _pkt(
            title="Verify dashboard",
            evidence=[{
                "id": "EV-VISUAL",
                "kind": "visual",
                "producer": "manual",
                "coder_blocking": False,
                "artifact_patterns": [
                    "dashboard state description or screenshot reference for mobile UI",
                ],
            }],
        )

        result = compiler.compile_plan(_plan(pkt), env)

        assert any(e.code == "E_EVIDENCE_KIND_UNKNOWN" for e in result.errors)
        assert any(e.code == "E_EVIDENCE_DESCRIPTIVE_PATTERN" for e in result.errors)


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
        assert isinstance(env.python_candidates, list)

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


# ══════════════════════════════════════════════════════════════════════
# Source split / import migration
# ══════════════════════════════════════════════════════════════════════


def _split_plan(scope_files: list[str], t0_cmds: list[str] | None = None) -> dict:
    """Build a minimal split/refactor plan."""
    pkt = _pkt(
        title="Split LLM service into modules",
        scope=scope_files,
        t0=t0_cmds or [],
        evidence=[{"id": "EV1", "kind": "diff", "required": True,
                    "artifact_patterns": []}],
    )
    return _plan(pkt)


class TestSourceSplitDetection:

    def test_import_path_to_source_path(self):
        assert _import_path_to_source_path("app.services.llm_service") == \
            "apps/api/app/services/llm_service.py"
        assert _import_path_to_source_path("app.services.foo_bar") == \
            "apps/api/app/services/foo_bar.py"

    def test_detects_split_intent_from_description(self):
        env = _env()
        plan = _split_plan(["apps/api/app/services/llm/russian.py"])
        intents = detect_source_split_intents(
            "Split apps/api/app/services/llm_service.py into llm/ package",
            plan, env,
        )
        assert len(intents) >= 1
        assert any("llm_service.py" in i.source_path for i in intents)

    def test_detects_old_import_from_t0(self):
        env = _env()
        plan = _split_plan(
            ["apps/api/app/services/llm/russian.py"],
            t0_cmds=["grep -RIn 'app.services.llm_service' apps/api tests || true"],
        )
        intents = detect_source_split_intents(
            "Split llm_service.py into modules",
            plan, env,
        )
        assert any(i.old_import_path == "app.services.llm_service" for i in intents)

    def test_no_spread_detected_when_no_split_keywords(self):
        env = _env()
        plan = _plan(_pkt(title="Fix typo in docstring"))
        intents = detect_source_split_intents("Fix typo in docs", plan, env)
        assert len(intents) == 0

    def test_rejects_split_plan_missing_origin_source_file(self, tmp_path):
        (tmp_path / "apps/api/app/services").mkdir(parents=True)
        (tmp_path / "apps/api/app/services/llm_service.py").write_text("class LLMService: pass\n")
        compiler = PlanCompiler()
        env = _env()
        plan = _split_plan([
            "apps/api/app/services/llm/__init__.py",
            "apps/api/app/services/llm/russian.py",
        ])
        result = compiler.compile_plan(
            plan, env,
            feature_description="Split apps/api/app/services/llm_service.py into llm package",
            target_repo_root=tmp_path,
        )
        assert not result.ok
        assert any(e.code == "E_SOURCE_SPLIT_ORIGIN_MISSING" for e in result.errors)

    def test_accepts_split_plan_when_origin_source_file_in_scope(self):
        """Split plan with original source file in scope is OK."""
        compiler = PlanCompiler()
        env = _env()
        plan = _split_plan([
            "apps/api/app/services/llm/__init__.py",
            "apps/api/app/services/llm/russian.py",
            "apps/api/app/services/llm_service.py",
        ])
        result = compiler.compile_plan(
            plan, env,
            feature_description="Split apps/api/app/services/llm_service.py into llm package",
        )
        assert result.ok

    def test_rejects_import_migration_when_references_outside_scope(self, tmp_path):
        """Old import references outside scope are rejected."""
        compiler = PlanCompiler()
        env = _env()

        # Create files in tmp with source file + old import references
        (tmp_path / "apps/api/app/services").mkdir(parents=True)
        (tmp_path / "apps/api/app/services/llm_service.py").write_text("class LLMService: pass\n")
        (tmp_path / "apps" / "natal_report_service.py").write_text(
            "from app.services.llm_service import LLMService\n"
        )
        # Create source file and consumer with old import in separate temp dir
        repo = tmp_path / "repo_a"
        (repo / "apps/api/app/services").mkdir(parents=True)
        (repo / "apps/api/app/services/llm_service.py").write_text("class LLMService: pass\n")
        (repo / "apps/natal_report_service.py").write_text(
            "from app.services.llm_service import LLMService\n"
        )
        (repo / "apps/horary_service.py").write_text(
            "from app.services.llm_service import HoraryGenerationError\n"
        )

        plan = _split_plan(
            ["apps/api/app/services/llm/russian.py"],
            t0_cmds=["! grep -r app.services.llm_service apps/"],
        )
        result = compiler.compile_plan(
            plan, env,
            feature_description="Split apps/api/app/services/llm_service.py",
            target_repo_root=repo,
        )
        assert not result.ok
        assert any(e.code == "E_IMPORT_MIGRATION_SCOPE_INCOMPLETE" for e in result.errors)

    def test_accepts_import_migration_when_all_references_in_scope(self, tmp_path):
        """Old import references in scope are OK."""
        compiler = PlanCompiler()
        env = _env()

        repo = tmp_path / "repo_b"
        (repo / "apps/api/app/services").mkdir(parents=True)
        (repo / "apps/api/app/services/llm_service.py").write_text("class LLMService: pass\n")
        (repo / "apps/api/app/services/natal_report_service.py").write_text(
            "from app.services.llm_service import LLMService\n"
        )

        plan = _split_plan(
            ["apps/api/app/services/llm/russian.py",
             "apps/api/app/services/llm_service.py",
             "apps/api/app/services/natal_report_service.py"],
            t0_cmds=["! grep -r app.services.llm_service apps/"],
        )
        result = compiler.compile_plan(
            plan, env,
            feature_description="Split apps/api/app/services/llm_service.py",
            target_repo_root=repo,
        )
        assert result.ok

    def test_rejects_exact_failing_case(self, tmp_path):
        """Regression: feat_kmtisgXzb9 plan must be rejected by compiler."""
        (tmp_path / "apps/api/app/services").mkdir(parents=True)
        (tmp_path / "apps/api/app/services/llm_service.py").write_text("class LLMService: pass\n")
        compiler = PlanCompiler()
        env = _env()
        # This plan had scope missing llm_service.py
        plan = _plan(
            _pkt(
                title="Extract llm/ package and update all callers",
                scope=[
                    "apps/api/app/services/llm/__init__.py",
                    "apps/api/app/services/llm/russian.py",
                    "apps/api/app/services/llm/client.py",
                    "apps/api/app/services/llm/prompts.py",
                    "apps/api/app/services/llm/service.py",
                    "apps/api/app/services/llm/horary.py",
                    "apps/api/app/services/today_service.py",
                    "apps/api/app/services/horary_service.py",
                    "apps/api/app/services/natal_report_service.py",
                    "apps/api/tests/test_llm_service.py",
                    "apps/api/tests/test_horary_endpoints.py",
                    "apps/api/tests/test_horary_answer_quality.py",
                    "apps/api/tests/test_horary_failure_metadata.py",
                    "apps/api/tests/test_natal_full_report_api.py",
                    "apps/api/tests/test_natal_report_service.py",
                ],
                t0=["grep -r from app.services.llm_service apps/"],
            )
        )
        result = compiler.compile_plan(
            plan, env,
            feature_description="Split apps/api/app/services/llm_service.py into llm package. Update all callers and tests.",
            target_repo_root=tmp_path,
        )
        assert not result.ok
        assert any(e.code == "E_SOURCE_SPLIT_ORIGIN_MISSING" for e in result.errors)

    def test_detects_russian_split_intent_from_description(self):
        """Russian 'разбить' should trigger source-split detection."""
        env = _env()
        plan = _split_plan(["apps/api/app/services/llm/russian.py"])
        intents = detect_source_split_intents(
            "разбить apps/api/app/services/llm_service.py на мелкие файлы",
            plan, env,
        )
        assert len(intents) >= 1
        assert any("llm_service.py" in i.source_path for i in intents)

    def test_compile_plan_wrapper_supports_kwargs(self):
        """Module-level compile_plan wrapper must accept feature_description/target_repo_root."""
        env = _env()
        plan = _split_plan([
            "apps/api/app/services/llm/russian.py",
            "apps/api/app/services/llm_service.py",
        ])
        from pathlib import Path
        result = compile_plan(
            plan, env,
            feature_description="Split llm_service.py",
            target_repo_root=Path("/tmp"),
        )
        assert isinstance(result.ok, bool)

    def test_russian_split_rejected_when_origin_missing(self, tmp_path):
        """Russian feature description + missing source file → E_SOURCE_SPLIT_ORIGIN_MISSING."""
        (tmp_path / "apps/api/app/services").mkdir(parents=True)
        (tmp_path / "apps/api/app/services/llm_service.py").write_text("class LLMService: pass\n")
        compiler = PlanCompiler()
        env = _env()
        plan = _split_plan([
            "apps/api/app/services/llm/russian.py",
        ])
        result = compiler.compile_plan(
            plan, env,
            feature_description="разбить apps/api/app/services/llm_service.py на модули",
            target_repo_root=tmp_path,
        )
        assert not result.ok
        assert any(e.code == "E_SOURCE_SPLIT_ORIGIN_MISSING" for e in result.errors)


# ══════════════════════════════════════════════════════════════════════
# Evidence contradiction detection
# ══════════════════════════════════════════════════════════════════════


class TestEvidenceContradiction:
    """TZ: Typed evidence expectations — contradiction detection."""

    def test_delete_instruction_conflicts_with_exists_evidence(self):
        """Instructions say 'remove models.py' but evidence expects it exists → contradiction."""
        plan = _plan(_pkt(
            title="Remove models",
            scope=["src/models.py"],
            evidence=[{
                "id": "models-exists",
                "kind": "file",
                "artifact_patterns": ["src/models.py"],
                "expectation": "exists",
            }],
            instructions=["remove models.py and split into modules"],
        ))
        env = _env()
        compiler = PlanCompiler()
        result = compiler.compile_plan(plan, env)
        assert not result.ok
        assert any(e.code == "E_EVIDENCE_CONTRADICTS_INSTRUCTIONS" for e in result.errors)

    def test_delete_instruction_with_deleted_expectation_ok(self):
        """Instructions say 'delete models.py' and evidence says 'deleted' → no contradiction."""
        plan = _plan(_pkt(
            title="Delete models",
            scope=["src/models.py"],
            evidence=[{
                "id": "models-deleted",
                "kind": "file",
                "artifact_patterns": ["src/models.py"],
                "expectation": "deleted",
            }],
            instructions=["delete models.py during refactor"],
        ))
        env = _env()
        compiler = PlanCompiler()
        result = compiler.compile_plan(plan, env)
        assert result.ok
        assert not any(e.code == "E_EVIDENCE_CONTRADICTS_INSTRUCTIONS" for e in result.errors)

    def test_no_delete_instruction_no_contradiction(self):
        """No delete keywords in instructions → no contradiction even with exists evidence."""
        plan = _plan(_pkt(
            title="Add service",
            scope=["src/service.py"],
            evidence=[{
                "id": "service-exists",
                "kind": "file",
                "artifact_patterns": ["src/service.py"],
                "expectation": "exists",
            }],
            instructions=["implement the new service"],
        ))
        env = _env()
        compiler = PlanCompiler()
        result = compiler.compile_plan(plan, env)
        assert result.ok

    def test_remove_file_content_does_not_mean_delete_evidence_file(self):
        """Removing stale links from an XML document must preserve exists evidence."""
        plan = _plan(_pkt(
            title="Repair documentation",
            scope=["docs/development-plan.xml", "docs/verification-matrix.md"],
            evidence=[{
                "id": "plan-xml",
                "kind": "contract",
                "artifact_patterns": ["docs/development-plan.xml"],
                "expectation": "exists",
            }],
            instructions=[
                "Reconcile docs/development-plan.xml with W00-W07 history and remove stale log links from docs/verification-matrix.md",
            ],
        ))
        result = PlanCompiler().compile_plan(plan, _env())

        assert result.ok
        assert not any(
            error.code == "E_EVIDENCE_CONTRADICTS_INSTRUCTIONS"
            for error in result.errors
        )

    def test_consolidate_instruction_triggers_contradiction(self):
        """'consolidate' implies removing old file — contradiction with 'exists' evidence."""
        plan = _plan(_pkt(
            title="Consolidate models",
            scope=["src/old_models.py"],
            evidence=[{
                "id": "old-models",
                "kind": "file",
                "artifact_patterns": ["src/old_models.py"],
                "expectation": "exists",
            }],
            instructions=["consolidate old_models.py into the new structure"],
        ))
        env = _env()
        compiler = PlanCompiler()
        result = compiler.compile_plan(plan, env)
        assert not result.ok
        assert any(e.code == "E_EVIDENCE_CONTRADICTS_INSTRUCTIONS" for e in result.errors)

    def test_russian_remove_triggers_contradiction(self):
        """Russian 'удалить' keyword → contradiction with 'exists' evidence."""
        plan = _plan(_pkt(
            title="Удалить models",
            scope=["src/models.py"],
            evidence=[{
                "id": "models-exists",
                "kind": "file",
                "artifact_patterns": ["src/models.py"],
            }],
            instructions=["удалить src/models.py"],
        ))
        env = _env()
        compiler = PlanCompiler()
        result = compiler.compile_plan(plan, env)
        assert not result.ok
        assert any(e.code == "E_EVIDENCE_CONTRADICTS_INSTRUCTIONS" for e in result.errors)

    def test_evidence_contradiction_details_include_suggested_fix(self):
        """Error details contain suggested fix field."""
        plan = _plan(_pkt(
            title="Remove module",
            scope=["src/module.py"],
            evidence=[{
                "id": "module-ev",
                "kind": "file",
                "artifact_patterns": ["src/module.py"],
                "expectation": "exists",
            }],
            instructions=["delete src/module.py"],
        ))
        env = _env()
        compiler = PlanCompiler()
        result = compiler.compile_plan(plan, env)
        assert not result.ok
        ev_err = next(e for e in result.errors if e.code == "E_EVIDENCE_CONTRADICTS_INSTRUCTIONS")
        assert ev_err.details is not None
        assert ev_err.details.get("suggested_fix") == "deleted"
        assert ev_err.details.get("file") == "src/module.py"
        assert ev_err.details.get("remove_target_explicit") is True
        assert "delete" in ev_err.details.get("remove_keywords", [])

    def test_unknown_evidence_expectation_rejected_by_compiler(self):
        """expectation value not in valid set → E_EVIDENCE_EXPECTATION_UNKNOWN."""
        plan = _plan(_pkt(
            title="Bad evidence",
            scope=["src/models.py"],
            evidence=[{
                "id": "bad-ev",
                "kind": "file",
                "artifact_patterns": ["src/models.py"],
                "expectation": "deletd",
            }],
            instructions=["refactor"],
        ))
        env = _env()
        compiler = PlanCompiler()
        result = compiler.compile_plan(plan, env)
        assert not result.ok
        assert any(e.code == "E_EVIDENCE_EXPECTATION_UNKNOWN" for e in result.errors)

    def test_typod_expectation_does_not_fall_through_to_contradiction(self):
        """Typos in expectation should be caught by enum validation, not contradiction."""
        plan = _plan(_pkt(
            title="Typo evidence",
            scope=["src/models.py"],
            evidence=[{
                "id": "typo-ev",
                "kind": "file",
                "artifact_patterns": ["src/models.py"],
                "expectation": "deletd",
            }],
            instructions=["delete src/models.py"],
        ))
        env = _env()
        compiler = PlanCompiler()
        result = compiler.compile_plan(plan, env)
        assert not result.ok
        # Must see UNKNOWN, not CONTRADICTS
        assert any(e.code == "E_EVIDENCE_EXPECTATION_UNKNOWN" for e in result.errors)
        assert not any(e.code == "E_EVIDENCE_CONTRADICTS_INSTRUCTIONS" for e in result.errors)


def test_plan_compiler_rejects_missing_dependency_title():
    plan = _plan({
        **_pkt(title="Consumer"),
        "depends_on": ["Missing producer"],
        "conflict_keys": [],
    })

    result = PlanCompiler().compile_plan(plan, _env())

    assert not result.ok
    assert any(error.code == "E_DEPENDENCY_MISSING" for error in result.errors)


def test_plan_compiler_rejects_new_same_wave_dependency():
    plan = {
        "waves": [{"title": "Wave 1", "packets": [
            {**_pkt(title="Producer"), "depends_on": [], "conflict_keys": []},
            {**_pkt(title="Consumer"), "depends_on": ["Producer"], "conflict_keys": []},
        ]}],
    }

    result = PlanCompiler().compile_plan(plan, _env())

    assert not result.ok
    assert any(error.code == "E_DEPENDENCY_WAVE_ORDER" for error in result.errors)
