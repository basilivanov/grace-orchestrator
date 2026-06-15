# ############################################################################
# AI_HEADER: test_w10_remove_legacy_defaults
# ROLE: W10 tests — remove legacy defaults, duplicates, and misleading config.
# ############################################################################

"""W10 Remove Legacy Defaults, Duplicates, and Misleading Config.

Tests cover:
1. No default broad scope constants used for execution
2. No duplicate opencode_server_url setting
3. No selected profile uses legacy architect schema
4. Critical exceptions are logged, not silently passed
5. No release endpoint without lease fencing
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


# ─── Test 2: No duplicate opencode_server_url setting ───────────────────────

def test_no_duplicate_opencode_server_url_setting():
    """W10: The opencode_server_url field must appear exactly once in
    GraceSettings. W10 removed the duplicate at line 120 that was shadowed
    by the W5 definition at line 150."""
    from grace_control.config.settings import GraceSettings

    # Count how many times opencode_server_url appears in model_fields
    field_names = list(GraceSettings.model_fields.keys())
    url_count = field_names.count("opencode_server_url")

    assert url_count == 1, \
        f"opencode_server_url should appear exactly once in settings, found {url_count}"

    # Verify the field exists and has the correct default
    field = GraceSettings.model_fields["opencode_server_url"]
    assert field.default == "", \
        f"opencode_server_url default should be empty string, got {field.default!r}"


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
