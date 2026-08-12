# ############################################################################
# AI_HEADER: test_no_opencode_legacy — durable guard for removed runtime legacy.
# ROLE: Architecture regression guard for the OpenCode removal packet. It checks
#       runtime files, settings, profiles, backend selection, and active imports.
# ############################################################################

# START_MODULE_CONTRACT
# purpose: Prove that removed runtime legacy does not re-enter active code.
# inputs: Repository files under the active source, test, script, and config roots.
# returns: Pytest assertions; no production values are returned.
# side_effects: Reads repository files and parses active settings/profile config.
# emitted_logs: None.
# error_behavior: Raises AssertionError when removed legacy is found.
# END_MODULE_CONTRACT

# START_MODULE_MAP
# mapping:
#   - function: test_removed_runtime_contract_is_absent
# END_MODULE_MAP

from __future__ import annotations

from pathlib import Path

import yaml

from grace_control.config.settings import GraceSettings
from grace_control.core.structured_logger import GraceLogger

_log = GraceLogger("architecture_guard")
_ROOT = Path(__file__).resolve().parents[3]


# START_BLOCK_ARCHITECTURE_GUARD
# START_FUNCTION_CONTRACT
# name: test_removed_runtime_contract_is_absent
# purpose: Verify the removed runtime, configuration, profiles, imports, and selection branch stay absent.
# inputs: None; reads the checked-out repository.
# returns: None after all architecture assertions pass.
# side_effects: Reads source, test, script, settings, and profile files.
# emitted_logs: None.
# error_behavior: Raises AssertionError when an active legacy reference exists.
# END_FUNCTION_CONTRACT
def test_removed_runtime_contract_is_absent() -> None:
    runtime_root = _ROOT / "src" / "grace_control" / "runtime"
    assert not list(runtime_root.glob("opencode_*.py"))

    field_names = GraceSettings.model_fields
    assert "agent_runtime_use_opencode_adapter" not in field_names
    assert not any(name.startswith("op" + "encode_") for name in field_names)

    profile_path = _ROOT / "src" / "grace_control" / "config" / "agent_profiles.yaml"
    profile_text = profile_path.read_text()
    profile_data = yaml.safe_load(profile_text) or {}
    assert "opencode" not in profile_text.lower()
    for profile in (profile_data.get("agents") or {}).values():
        assert "opencode" not in " ".join(str(value) for value in profile.values()).lower()

    packet_executor = (_ROOT / "src" / "grace_control" / "adapters" / "packet_executor.py").read_text()
    assert "opencode_runtime_adapter" not in packet_executor.lower()
    assert "agent_runtime_use_opencode_adapter" not in packet_executor

    active_roots = (
        _ROOT / "src",
        _ROOT / "tests",
        _ROOT / "scripts",
    )
    active_files = [path for root in active_roots for path in root.rglob("*.py")]
    active_files.extend([
        _ROOT / "src" / "grace_control" / "config" / "agent_profiles.yaml",
    ])
    active_files = [path for path in active_files if path != Path(__file__)]
    forbidden_imports = ("grace_control.runtime.opencode", "OpenCodeRuntimeAdapter")
    for path in active_files:
        text = path.read_text(errors="ignore").lower()
        assert not any(token.lower() in text for token in forbidden_imports), str(path)

    _log.info("architecture_guard_passed", checked_files=len(active_files))
# END_BLOCK_ARCHITECTURE_GUARD
