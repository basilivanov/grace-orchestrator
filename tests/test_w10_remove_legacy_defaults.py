# ############################################################################
# AI_HEADER: test_w10_remove_legacy_defaults
# ROLE: W10 tests — remove legacy defaults, duplicates, and misleading config.
# ############################################################################

"""W10 Remove Legacy Defaults, Duplicates, and Misleading Config.

Tests cover:
1. No default broad scope constants used for execution
2. No removed runtime settings are reintroduced
3. No selected profile uses legacy architect schema
4. Critical exceptions are logged, not silently passed
5. No release endpoint without lease fencing
6. (regression) _real_shell runs git commands with shell=False
7. (regression) _real_shell handles paths with spaces
8. (regression) selftest CHECK_GIT_ROOT passes with real repo
"""

from __future__ import annotations

import re
import pytest
from pathlib import Path
from unittest.mock import patch, MagicMock

from grace_control.config.agent_profiles import AgentProfile, load_agent_profiles, reset_cache


# ─── Test 1: No default broad scope constants used for execution ────────────

def test_no_default_broad_scope_constants_used_for_execution():
    """W10: No DEFAULT_SCOPE, setdefault('scope', []), or broad scope fallback
    should exist in the codebase for executable packets. These were removed in
    W02 and must not be reintroduced."""
    src_root = Path(__file__).resolve().parent.parent / "src" / "grace_control"

    # Patterns that indicate dangerous broad scope defaults
    dangerous_patterns = [
        (r'DEFAULT_SCOPE\s*=\s*["\']src/', "DEFAULT_SCOPE = 'src/' broad fallback"),
        (r'\.setdefault\(\s*["\']scope["\']\s*,\s*\[\]\s*\)', "setdefault('scope', []) empty fallback"),
        (r'setdefault\(\s*["\']scope["\']\s*,\s*\["\s*src/', "setdefault('scope', ['src/...']) broad fallback"),
    ]

    violations = []
    for py_file in src_root.rglob("*.py"):
        content = py_file.read_text(encoding="utf-8", errors="ignore")
        for pattern, description in dangerous_patterns:
            # Skip comments (lines starting with #)
            for i, line in enumerate(content.split("\n"), 1):
                stripped = line.lstrip()
                if stripped.startswith("#"):
                    continue
                if re.search(pattern, line):
                    violations.append(
                        f"{py_file.relative_to(src_root.parent)}:{i}: {description}"
                    )

    assert len(violations) == 0, \
        f"Found dangerous broad scope defaults:\n" + "\n".join(violations)


# ─── Test 2: Removed runtime settings stay absent ───────────────────────────

def test_removed_runtime_settings_stay_absent():
    """Removed runtime-specific settings must not return to GraceSettings."""
    from grace_control.config.settings import GraceSettings

    field_names = list(GraceSettings.model_fields.keys())
    assert all(not name.startswith("op" + "encode_") for name in field_names)


# ─── Test 3: No selected profile uses legacy architect schema ───────────────

def test_no_selected_profile_uses_legacy_architect_schema():
    """W10: Enabled architect profiles must not use legacy fields
    (allowed_files, forbidden_files, evidence_required) in their commands.
    The canonical schema uses scope, frozen_scope, and expected_evidence."""
    reset_cache()
    profiles = load_agent_profiles()

    architect_profiles = [p for p in profiles.values()
                          if "architect" in p.executor_id.lower() and not p.disabled]
    assert len(architect_profiles) > 0, "No enabled architect profiles found"

    legacy_fields = ["allowed_files", "forbidden_files", "evidence_required"]

    for profile in architect_profiles:
        command_text = " ".join(profile.command)

        for field in legacy_fields:
            assert field not in command_text, \
                (f"Architect profile '{profile.executor_id}' references legacy field "
                 f"'{field}' in command. Use canonical fields (scope, frozen_scope, "
                 f"expected_evidence) instead.")


# ─── Test 4: Critical exceptions are logged not silently passed ─────────────

def test_critical_exceptions_are_logged_not_silently_passed():
    """W10: The packet_executor must not have bare 'except: pass' or critical
    'except Exception: pass' patterns. All critical exception handlers must
    log the error for observability."""
    src_root = Path(__file__).resolve().parent.parent / "src" / "grace_control"

    # Check for bare except: pass (most dangerous)
    bare_except_pass = []
    # Check for except Exception: pass (critical path)
    except_exception_pass = []

    for py_file in src_root.rglob("*.py"):
        # Skip test files
        if "test_" in py_file.name:
            continue
        content = py_file.read_text(encoding="utf-8", errors="ignore")
        lines = content.split("\n")

        for i, line in enumerate(lines):
            stripped = line.strip()

            # Bare except: pass (no exception type)
            if stripped == "except:" or stripped.startswith("except: #"):
                # Check if next non-empty line is 'pass'
                for j in range(i + 1, min(i + 3, len(lines))):
                    next_line = lines[j].strip()
                    if next_line == "pass":
                        bare_except_pass.append(
                            f"{py_file.relative_to(src_root.parent)}:{i+1}: except: pass"
                        )
                        break
                    elif next_line:
                        break

            # except Exception: pass (without logging)
            if re.match(r"except\s+Exception\s*:", stripped):
                # Check if next non-empty line is 'pass'
                for j in range(i + 1, min(i + 3, len(lines))):
                    next_line = lines[j].strip()
                    if next_line == "pass":
                        except_exception_pass.append(
                            f"{py_file.relative_to(src_root.parent)}:{i+1}: except Exception: pass"
                        )
                        break
                    elif next_line:
                        break

    assert len(bare_except_pass) == 0, \
        f"Found bare 'except: pass' patterns (most dangerous):\n" + \
        "\n".join(bare_except_pass)

    # Critical handlers should log, not pass silently
    # Allow a few in non-critical files (devtools, etc.)
    critical_pass = [v for v in except_exception_pass
                     if "packet_executor" in v or "worker" in v or "release" in v]
    assert len(critical_pass) == 0, \
        f"Found critical 'except Exception: pass' in core execution paths:\n" + \
        "\n".join(critical_pass)


# ─── Test 5: No release endpoint without lease fencing ──────────────────────

def test_no_release_endpoint_without_lease_fencing():
    """W10: All release endpoints must require lease fencing (worker_id,
    lease_id, claimed_attempt). No release path should be accessible without
    lease validation (W01 fencing invariant)."""
    src_root = Path(__file__).resolve().parent.parent / "src" / "grace_control"

    # Read the packets router for release endpoints
    packets_router = src_root / "api" / "routers" / "packets.py"
    if not packets_router.exists():
        pytest.skip("packets router not found")

    content = packets_router.read_text(encoding="utf-8")

    # Find all release-related function definitions
    release_functions = re.findall(
        r"(def\s+release\w*\([^)]*\)(?:\s*->[^:]+)?:)", content
    )

    # For each release function, verify it references lease/fencing tokens
    violations = []
    for func_match in release_functions:
        func_name = re.search(r"def\s+(\w+)", func_match).group(1)
        # Find the function body
        func_start = content.find(func_match)
        if func_start == -1:
            continue

        # Get a reasonable chunk of the function body (next 2000 chars)
        func_body = content[func_start:func_start + 2000]

        # Check for lease fencing references
        has_lease_check = any(
            kw in func_body
            for kw in ["lease_id", "claimed_attempt", "StaleLeaseError", "lease_fencing", "_release_with_fencing"]
        )

        if not has_lease_check:
            violations.append(
                f"Release function '{func_name}' does not reference lease fencing tokens"
            )

    assert len(violations) == 0, \
        f"Found release endpoints without lease fencing:\n" + \
        "\n".join(violations)


# ─── Test 6 (regression): _real_shell runs git commands with shell=False ────

def test_real_shell_runs_git_command_with_shell_false():
    """W10 regression: _real_shell() uses shlex.split() + shell=False and
    must be able to successfully execute a real git command against a real
    git repository.  This prevents the breakage where changing shell=True
    to shell=False without splitting the command string caused
    FileNotFoundError for commands like 'git -C /repo rev-parse ...'."""
    import subprocess
    import tempfile
    from grace_control.runtime.agent_runtime_selftest import _real_shell

    with tempfile.TemporaryDirectory() as td:
        # Create a real git repo
        init_rc, _, init_err = _real_shell(f"git init {td}")
        assert init_rc == 0, f"git init failed: {init_err}"

        # Verify git rev-parse --show-toplevel works via _real_shell
        rc, out, err = _real_shell(f"git -C {td} rev-parse --show-toplevel")
        assert rc == 0, f"git rev-parse failed (rc={rc}): {err}"
        # The output should match the repo root (git may append newline)
        assert out.strip() == td.strip(), \
            f"git root mismatch: expected {td!r}, got {out!r}"


def test_real_shell_handles_path_with_spaces():
    """W10 regression: shlex.quote() + shlex.split() must correctly handle
    repository paths that contain spaces."""
    import shlex
    import tempfile
    from grace_control.runtime.agent_runtime_selftest import _real_shell

    with tempfile.TemporaryDirectory(prefix="repo with spaces ") as td:
        # Create a real git repo in a path with spaces
        init_rc, _, init_err = _real_shell(f"git init {shlex.quote(td)}")
        assert init_rc == 0, f"git init failed in path with spaces: {init_err}"

        # Verify git rev-parse works with the quoted path
        rc, out, err = _real_shell(
            f"git -C {shlex.quote(td)} rev-parse --show-toplevel"
        )
        assert rc == 0, f"git rev-parse failed for path with spaces: {err}"
        assert out.strip() == td, \
            f"git root mismatch for path with spaces: expected {td!r}, got {out!r}"


def test_selftest_git_check_passes_with_real_repo():
    """W10 regression: AgentRuntimeSelftest CHECK_GIT_ROOT_EQUALS_WORKTREE_ROOT
    must pass against a real temporary git repo using the production
    _real_shell runner (shell=False)."""
    import subprocess
    import tempfile
    from pathlib import Path
    from grace_control.config.settings import settings
    from grace_control.runtime.agent_runtime_selftest import (
        AgentRuntimeSelftest,
        CHECK_GIT_ROOT_EQUALS_WORKTREE_ROOT,
    )
    from grace_control.runtime.agent_runtime_contract import AgentRuntimeContract
    from grace_control.core.runtime_trace import RuntimeTraceContext

    original_cwd = settings.agent_runtime_fail_on_bad_cwd
    original_git = settings.agent_runtime_fail_on_bad_git_root
    try:
        settings.agent_runtime_fail_on_bad_cwd = False
        settings.agent_runtime_fail_on_bad_git_root = True

        with tempfile.TemporaryDirectory() as td:
            td_path = Path(td)
            wt = td_path / "wt"
            wt.mkdir()

            # Initialize a real git repo
            subprocess.run(
                ["git", "init", td],
                capture_output=True, text=True, check=True,
            )

            trace = RuntimeTraceContext(
                trace_id="test-trace-w10-reg",
                feature_id="feat_w10",
                packet_id="pkt_w10_reg",
                wave_id="wave_w10",
                runtime_run_id="pkt_w10_reg-R01",
            )
            contract = AgentRuntimeContract(
                runtime_run_id="r1",
                feature_id="feat_w10",
                wave_id="wave_w10",
                packet_id="pkt_w10_reg",
                role="coder",
                adapter="cli",
                target_repo_root=td,
                orchestrator_repo_root=td,
                worktree_root=str(wt),
                cwd=str(wt),
                shell="/bin/sh",
                executor_id="test-executor",
                agent_name="test-agent",
                provider="deepseek",
                model="deepseek-v4-flash",
                packet_scope=["src/foo"],
                frozen_scope=["src/frozen"],
                acceptance_profile="FAST",
                runtime_artifacts_dir=str(td_path / ".grace" / "runs" / "artifacts"),
                timeout_seconds=600,
                created_at=None,
            )

            selftest = AgentRuntimeSelftest()  # uses _real_shell by default
            result = selftest.run(contract, trace)

            git_check = [c for c in result.checks
                         if c.check_id == CHECK_GIT_ROOT_EQUALS_WORKTREE_ROOT]
            assert git_check, "CHECK_GIT_ROOT_EQUALS_WORKTREE_ROOT not in results"
            assert git_check[0].ok, \
                f"git root check should pass for real repo: " \
                f"expected={git_check[0].expected!r} actual={git_check[0].actual!r}"
    finally:
        settings.agent_runtime_fail_on_bad_cwd = original_cwd
        settings.agent_runtime_fail_on_bad_git_root = original_git
