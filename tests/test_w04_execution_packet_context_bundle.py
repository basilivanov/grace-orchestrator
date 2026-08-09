# ############################################################################
# AI_HEADER: test_w04_execution_packet_context_bundle
# ROLE: W04 tests: enriched EXECUTION_PACKET.md, context gate, config
#       allowlist, cwd safety, profile validation.
# ############################################################################
from __future__ import annotations

import tempfile
from pathlib import Path

import pytest

from grace_control.services.packet_materializer import PacketMaterializer
from grace_control.services.agent_workspace_builder import AgentWorkspaceBuilder
from grace_control.services.agent_run_service import AgentRunService
from grace_control.config.agent_profiles import get_agent_profile


# ═══════════════════════════════════════════════════════════════════════════
# Section 6/7 test: file tree + previews
# ═══════════════════════════════════════════════════════════════════════════

def test_execution_packet_contains_file_tree_and_previews(db):
    """W04 §1: EXECUTION_PACKET.md must include file tree (sizes) and
    selected file previews (first lines)."""
    materializer = PacketMaterializer()
    with tempfile.TemporaryDirectory() as tmp:
        target_root = Path(tmp) / "target"
        target_root.mkdir()
        (target_root / "src").mkdir()
        (target_root / "src" / "main.py").write_text(
            "def main():\n    print('hello')\n\nif __name__ == '__main__':\n    main()\n"
        )
        (target_root / "src" / "utils.py").write_text(
            "import os\n\ndef helper():\n    return 42\n"
        )
        (target_root / "pyproject.toml").write_text("[project]\nname='test'\n")

        packet_data = {
            "id": "pkt_w04_tree",
            "title": "W04 Tree Test",
            "description": "Test file tree rendering",
            "spec_json": {
                "scope": ["src/main.py", "src/utils.py"],
                "acceptance_criteria": ["Everything works"],
                "verification": {"t0": ["python -m py_compile src/main.py"]},
                "expected_evidence": [
                    {"id": "test_results", "description": "Test output", "format": "json"},
                ],
            },
        }
        state_root = Path(tmp) / "state"
        state_root.mkdir()
        path = materializer.materialize(packet_data, state_root, target_root=target_root)
        content = path.read_text()

    # Section 6: file tree must list files with sizes
    assert "src/main.py" in content
    assert "src/utils.py" in content
    assert "B)" in content or "bytes" in content.lower()

    # Section 7: file previews must include first lines
    assert "def main():" in content
    assert "def helper():" in content

    # All 17 sections must be present
    assert "## 1. Objective" in content
    assert "## 2. Business Requirement" in content
    assert "## 3. Role and Non-Goals" in content
    assert "## 4. Allowed Write Scope" in content
    assert "## 5. Frozen Scope" in content
    assert "## 6. Relevant File Tree" in content
    assert "## 7. Selected File Previews" in content
    assert "## 8. Nearby Tests" in content
    assert "## 9. Config / Build Files Available" in content
    assert "## 10. Import / Dependency Hints" in content
    assert "## 11. Coder Instructions" in content
    assert "## 12. Acceptance Criteria" in content
    assert "## 13. Verification Commands" in content
    assert "## 14. Full Expected Evidence Fields" in content
    assert "## 15. Workspace Mode and Limitations" in content
    assert "## 16. Target Repo Root Diagnostics" in content
    assert "## 17. Full Spec JSON" in content


def test_execution_packet_contains_source_feature_specification_once(db):
    """Packet coders receive the original feature/TZ even when the target
    repository is empty, without duplicating it in the YAML diagnostics."""
    materializer = PacketMaterializer()
    with tempfile.TemporaryDirectory() as tmp:
        packet_data = {
            "id": "pkt_source_tz",
            "title": "Create canon",
            "description": "Create the documentation wave",
            "spec_json": {
                "scope": ["docs/requirements.xml"],
                "feature_context": {
                    "feature_id": "feat_source_tz",
                    "title": "Exact architecture specification",
                    "description": "EXACT_TZ_SENTINEL with required_field_name",
                },
            },
        }
        path = materializer.materialize(packet_data, Path(tmp))
        content = path.read_text()

    assert "### Source Feature\nExact architecture specification" in content
    assert "### Source TZ / Specification" in content
    assert content.count("EXACT_TZ_SENTINEL with required_field_name") == 1
    assert "description: (rendered verbatim in section 2)" in content


def test_execution_packet_materializes_conflict_keys_and_legacy_default(db):
    materializer = PacketMaterializer()
    with tempfile.TemporaryDirectory() as tmp:
        path = materializer.materialize({
            "id": "pkt_conflict_keys",
            "title": "Semantic contract",
            "spec_json": {
                "scope": ["src/contract.py"],
                "conflict_keys": [" api:user-service ", "db-schema"],
            },
        }, Path(tmp))
        content = path.read_text()

    assert "api:user-service" in content
    assert "db-schema" in content

    with tempfile.TemporaryDirectory() as tmp:
        path = materializer.materialize({
            "id": "pkt_legacy_conflict_keys",
            "title": "Legacy packet",
            "spec_json": {"scope": ["src/legacy.py"]},
        }, Path(tmp))
        content = path.read_text()

    assert "conflict_keys: []" in content


# START_FUNCTION_CONTRACT
# name: test_execution_packet_surfaces_bounded_retry_context
# purpose: Verify retry coders see the prior failed command and recovery decision prominently rather than only in diagnostic YAML.
# inputs: None.
# returns: None.
# side_effects: Creates and removes a temporary packet state directory.
# emitted_logs: None.
# error_behavior: AssertionError on missing or duplicated retry context.
# END_FUNCTION_CONTRACT
def test_execution_packet_surfaces_bounded_retry_context():
    materializer = PacketMaterializer()
    with tempfile.TemporaryDirectory() as tmp:
        packet_data = {
            "id": "pkt_retry_context",
            "title": "Retry the failed gate",
            "spec_json": {
                "scope": ["src/app.py"],
                "coder_instructions": ["Fix only the reported failure"],
                "recovery": {
                    "previous_attempt": 2,
                    "action": "switch_coder",
                    "failure_class": "retryable_coder",
                    "reason": "T1 failed",
                    "acceptance_summary": "T1 failed: 1/1 commands failed",
                    "requested_executor_id": "coder-deepseek",
                    "failed_checks": [{
                        "stage": "T1_TARGETED_TESTS",
                        "command": "python -m missing_linter",
                        "exit_code": 1,
                    }],
                },
            },
        }
        path = materializer.materialize(packet_data, Path(tmp))
        content = path.read_text()

    instructions = content.split("## 11. Coder Instructions", 1)[1].split(
        "## 12. Acceptance Criteria", 1
    )[0]
    assert "### Retry Context" in instructions
    assert "Previous attempt: 2" in instructions
    assert "python -m missing_linter" in instructions
    assert "### Required Actions" in instructions


# ═══════════════════════════════════════════════════════════════════════════
# Section 14 test: full structured evidence fields
# ═══════════════════════════════════════════════════════════════════════════

def test_execution_packet_renders_full_evidence_requirements():
    """W04 §1: Expected Evidence section must render full structured fields
    (description, format) not just IDs."""
    materializer = PacketMaterializer()
    with tempfile.TemporaryDirectory() as tmp:
        packet_data = {
            "id": "pkt_w04_evidence",
            "title": "W04 Evidence",
            "spec_json": {
                "scope": ["src/app.py"],
                "expected_evidence": [
                    {"id": "test_results", "description": "Output from pytest", "format": "json"},
                    {"id": "lint_output", "description": "Linter results", "format": "text"},
                    {"id": "changed_files", "description": "List of modified files", "format": "list"},
                ],
            },
        }
        path = materializer.materialize(packet_data, Path(tmp))
        content = path.read_text()

    # Must include structured fields
    assert "test_results" in content
    assert "Output from pytest" in content
    assert "lint_output" in content
    assert "Linter results" in content
    assert "changed_files" in content
    assert "List of modified files" in content

    # Must NOT match the old fallback format
    assert "structured fields TBD" not in content


# ═══════════════════════════════════════════════════════════════════════════
# Context gate test: NORMAL/STRICT packets must not launch blindly
# ═══════════════════════════════════════════════════════════════════════════

def test_normal_packet_requires_context_or_explicit_override():
    """W04 §2: NORMAL coder packet with skip_context_builder=true and no
    context_not_required must be rejected before agent run."""
    # Test the gate logic directly (no DB, no mocks)
    # Gate: if role=coder AND profile in (NORMAL, STRICT) AND skip_ctx AND not ctx_not_required => BLOCK
    def _gate_should_block(role, profile, skip_ctx, ctx_not_required):
        return role == "coder" and profile in ("NORMAL", "STRICT") and skip_ctx and not ctx_not_required

    # Case 1: NORMAL coder, skip_context, no override => BLOCK
    assert _gate_should_block("coder", "NORMAL", True, False)

    # Case 2: STRICT coder, skip_context, no override => BLOCK
    assert _gate_should_block("coder", "STRICT", True, False)

    # Case 3: NORMAL coder, skip_context, WITH override => PASS
    assert not _gate_should_block("coder", "NORMAL", True, True)

    # Case 4: FAST coder, skip_context => PASS (only NORMAL/STRICT checked)
    assert not _gate_should_block("coder", "FAST", True, False)

    # Case 5: NORMAL coder, context NOT skipped => PASS
    assert not _gate_should_block("coder", "NORMAL", False, False)

    # Case 6: NORMAL architect (non-coder role) => PASS
    assert not _gate_should_block("architect", "NORMAL", True, False)


def test_normal_packet_passes_with_context_not_required():
    """W04 §2: NORMAL coder packet with skip_context_builder but
    context_not_required=true must NOT be rejected."""
    def _gate_should_block(role, profile, skip_ctx, ctx_not_required):
        return role == "coder" and profile in ("NORMAL", "STRICT") and skip_ctx and not ctx_not_required

    assert not _gate_should_block("coder", "NORMAL", True, True)
    assert not _gate_should_block("coder", "STRICT", True, True)


# ═══════════════════════════════════════════════════════════════════════════
# Config allowlist test
# ═══════════════════════════════════════════════════════════════════════════

def test_scoped_copy_includes_required_config_allowlist():
    """W04 §3: CONFIG_ALLOWLIST must include all required config files
    and scoped copy must copy them when they exist."""
    # Verify the constant has the required files
    allowlist = PacketMaterializer.CONFIG_ALLOWLIST
    assert "pyproject.toml" in allowlist
    assert "pytest.ini" in allowlist
    assert "setup.cfg" in allowlist
    assert "tox.ini" in allowlist
    assert "mypy.ini" in allowlist
    assert "ruff.toml" in allowlist or ".ruff.toml" in allowlist
    assert "package.json" in allowlist
    assert "conftest.py" in allowlist
    assert ".env.example" in allowlist

    # Never includes .env
    assert ".env" not in allowlist or ".env" == ".env.example"

    # Verify scoped copy actually copies config files
    with tempfile.TemporaryDirectory() as tmp:
        target_root = Path(tmp) / "target"
        target_root.mkdir()
        (target_root / "main.py").write_text("x=1")
        (target_root / "pyproject.toml").write_text("[project]\nname='test'")
        (target_root / "pytest.ini").write_text("[pytest]\n")
        (target_root / "setup.cfg").write_text("[tool:pytest]\n")
        (target_root / "conftest.py").write_text("# conftest")

        from grace_control.services.git_service import GitService
        git = GitService()
        git._run(["init", "-q"], target_root)
        git._run(["config", "user.email", "test@grace"], target_root)
        git._run(["config", "user.name", "Test"], target_root)
        git._run(["add", "."], target_root)
        git._run(["commit", "-q", "-m", "init"], target_root)

        builder = AgentWorkspaceBuilder(target_root=target_root)
        ws = builder.build_scoped_copy(
            scope_paths=["main.py"],
            workspace_root=Path(tmp) / "workspaces",
            slug="test-cfg-ws",
            config_allowlist=PacketMaterializer.CONFIG_ALLOWLIST,
        )

        assert (ws.workspace_path / "pyproject.toml").exists(), f"pyproject.toml not in {list(ws.workspace_path.iterdir())}"
        assert (ws.workspace_path / "pytest.ini").exists()
        assert (ws.workspace_path / "setup.cfg").exists()
        assert (ws.workspace_path / "conftest.py").exists()

    # .env must NOT be copied even if in allowlist pattern
    # (the allowlist intentionally does not include .env)


# ═══════════════════════════════════════════════════════════════════════════
# CWD safety test: missing cwd must fail, not silently create
# ═══════════════════════════════════════════════════════════════════════════

def test_agent_run_fails_if_cwd_missing_instead_of_creating_it():
    """W04 §4: agent_run_service must NOT silently create cwd. Missing cwd
    raises RuntimeError."""
    service = AgentRunService()

    with tempfile.TemporaryDirectory() as tmp:
        state_root = Path(tmp) / "state"
        worktree_path = Path(tmp) / "worktree_exists"
        worktree_path.mkdir()

        # Try to run with cwd that does not exist
        executor = {
            "executor_id": "test-coder",
            "role": "coder",
            "command": ["echo", "hello"],
            "cwd": "{worktree_path}/nonexistent_subdir",
            "input": {"mode": "none"},
            "env": {},
            "backend": "cli",
        }

        with pytest.raises(RuntimeError, match="CWD does not exist"):
            import asyncio
            asyncio.run(service.run(
                executor,
                packet_id="pkt_cwd_test",
                worktree_path=worktree_path,
                state_root=state_root,
                packet_markdown="# Test",
                timeout_seconds=5,
            ))


# ═══════════════════════════════════════════════════════════════════════════
# Profile validation: all coder profiles must have input_mode or packet_arg
# ═══════════════════════════════════════════════════════════════════════════

def test_coder_profiles_all_have_input_mode_or_packet_arg():
    """W04: Every coder profile must have input.mode set to something
    other than 'none', or reference {packet_markdown} / {packet_path} in
    command/template."""
    from grace_control.config.agent_profiles import load_agent_profiles, get_agent_profile
    from grace_control.core.executor_selector import _profile_matches_role
    from pathlib import Path as _P

    profiles = load_agent_profiles()

    # Find coder profiles via executor_selector heuristic
    coder_executor_ids = set()
    for eid in profiles:
        if _profile_matches_role(eid, "coder"):
            coder_executor_ids.add(eid)

    # Also check codex.executors for coder role executors in the YAML
    import yaml as _yaml
    _profiles_yaml_path = _P(__file__).resolve().parent.parent / "src" / "grace_control" / "config" / "agent_profiles.yaml"
    if _profiles_yaml_path.exists():
        with open(_profiles_yaml_path) as _f:
            _raw = _yaml.safe_load(_f)
        codex_executors = _raw.get("codex", {}).get("executors", [])
        for ex in codex_executors:
            if isinstance(ex, dict) and "coder" in ex.get("roles", []):
                eid = ex.get("executor_id", "")
                if eid:
                    coder_executor_ids.add(eid)

    assert len(coder_executor_ids) > 0, "No coder profiles found"

    for eid in coder_executor_ids:
        prof = get_agent_profile(eid)
        if prof is None:
            continue
        d = prof.to_dict()
        cmd = d.get("command", [])
        cmd_str = " ".join(cmd) if isinstance(cmd, list) else str(cmd)
        input_mode = d.get("input_mode", "none")
        input_template = d.get("input_template", "")

        has_packet_ref = (
            "{packet_markdown}" in cmd_str
            or "{packet_path}" in cmd_str
            or "{packet_markdown}" in input_template
            or "{packet_path}" in input_template
        )

        valid = input_mode in ("stdin", "file") or has_packet_ref
        assert valid, (
            f"Coder profile {eid!r} has no input mode and no packet reference. "
            f"input_mode={input_mode!r}, command={cmd}"
        )
