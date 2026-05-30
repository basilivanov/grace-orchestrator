# ############################################################################
# AI_HEADER: scenario_fixtures
# ROLE: Generate temporary test fixtures for synthetic scenarios.
# ############################################################################

# START_MODULE_CONTRACT
# purpose: Generate fake packet dirs, registry YAML, session indexes for testing.
# inputs: SyntheticScenario dimensions, tmp_path.
# returns: SyntheticFixture with paths to generated files.
# side_effects: Writes temporary files under tmp_path.
# emitted_logs: None.
# error_behavior: Raises exception on file write errors.
# END_MODULE_CONTRACT

# START_MODULE_MAP
# mapping:
#   - class: SyntheticFixture
#   - function: generate_fixture_for_scenario
# END_MODULE_MAP

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

#START_BLOCK_MODELS
@dataclass
class SyntheticFixture:
    """
    Generated test fixture for one scenario.
    """
    packet_dir: Path
    registry_file: Path
    session_index: Path
    state_root: Path
    packet_id: str
    feature_id: str
    dimensions: dict[str, str]

    # START_FUNCTION_CONTRACT
    # name: setup
    # purpose: Write fixture files to disk.
    # inputs: None (instance method).
    # returns: None.
    # side_effects: Creates directories and writes packet, registry, and session files.
    # emitted_logs: None.
    # error_behavior: Raises exception on file write errors.
    # END_FUNCTION_CONTRACT
    def setup(self) -> None:
        """
        Write fixture files to disk.
        """
        # Create directories
        self.packet_dir.mkdir(parents=True, exist_ok=True)
        self.state_root.mkdir(parents=True, exist_ok=True)

        # Write EXECUTION_PACKET.md
        packet_content = self._generate_packet_content()
        packet_file = self.packet_dir / "EXECUTION_PACKET.md"
        packet_file.write_text(packet_content, encoding="utf-8")

        # Write registry YAML
        registry_content = self._generate_registry_content()
        self.registry_file.parent.mkdir(parents=True, exist_ok=True)

        # Remove any existing registry file to prevent state leaks
        if self.registry_file.exists():
            self.registry_file.unlink()

        if self.dimensions.get("registry_error") == "corrupt_yaml":
            # Write invalid YAML
            self.registry_file.write_text("{ invalid: yaml: [", encoding="utf-8")
        elif self.dimensions.get("registry_error") == "none":
            with open(self.registry_file, "w", encoding="utf-8") as f:
                yaml.safe_dump(registry_content, f, default_flow_style=False, allow_unicode=True)
        elif self.dimensions.get("registry_error") == "load_failed":
            # Don't create the file (already removed above)
            pass
        else:
            # Default: write valid YAML
            with open(self.registry_file, "w", encoding="utf-8") as f:
                yaml.safe_dump(registry_content, f, default_flow_style=False, allow_unicode=True)

        # Write session index
        session_content = self._generate_session_content()
        self.session_index.parent.mkdir(parents=True, exist_ok=True)
        self.session_index.write_text(json.dumps(session_content, indent=2), encoding="utf-8")

    # START_FUNCTION_CONTRACT
    # name: teardown
    # purpose: Clean up fixture files (optional, pytest tmp_path handles this).
    # inputs: None (instance method).
    # returns: None.
    # side_effects: None (cleanup handled by pytest).
    # emitted_logs: None.
    # error_behavior: None.
    # END_FUNCTION_CONTRACT
    def teardown(self) -> None:
        """
        Clean up fixture files (optional, pytest tmp_path handles this).
        """
        pass

    def _generate_packet_content(self) -> str:
        """
        Generate EXECUTION_PACKET.md content.
        """
        return f"""# Execution Packet: {self.packet_id}

## Objective

Synthetic test packet for scenario testing.

## Slice

- packet_id: `{self.packet_id}`
- feature_id: `{self.feature_id}`
- wave_id: `W01`
- status: `ready`

## Allowed Write Scope

- `/tmp/synthetic/**`

## Frozen Scope

- `/opt/astro-project/backend/**`
- `/opt/astro-project/frontend/**`
"""

    def _generate_registry_content(self) -> dict[str, Any]:
        """
        Generate packet registry content based on dimensions.
        """
        source_hash_value = self._compute_source_hash()

        # Determine last_executed_source_hash
        if self.dimensions.get("source_hash") == "same":
            last_executed_hash = source_hash_value
        elif self.dimensions.get("source_hash") == "changed":
            last_executed_hash = "old_hash_12345678"
        elif self.dimensions.get("source_hash") == "missing":
            last_executed_hash = None
        elif self.dimensions.get("source_hash") == "malformed":
            last_executed_hash = "malformed!!!"
        else:
            last_executed_hash = None

        # Determine resume_allowed
        resume_allowed_dim = self.dimensions.get("resume_allowed", "missing")
        if resume_allowed_dim == "true":
            resume_allowed = True
        elif resume_allowed_dim == "false":
            resume_allowed = False
        else:
            resume_allowed = None

        # Determine resume_block_reason
        resume_block_reason_dim = self.dimensions.get("resume_block_reason", "none")
        resume_block_reason = None if resume_block_reason_dim == "none" else resume_block_reason_dim

        # Determine latest_coder_session_id
        session_dim = self.dimensions.get("session", "missing")
        if session_dim == "exists":
            latest_coder_session_id = "thread-synthetic-12345"
        elif session_dim == "stale":
            latest_coder_session_id = "thread-stale-old"
        elif session_dim == "wrong_packet":
            latest_coder_session_id = "thread-wrong-packet-99999"
        elif session_dim == "wrong_role":
            latest_coder_session_id = "thread-wrong-role-architect"
        elif session_dim == "killed_stalled":
            latest_coder_session_id = "thread-killed-stalled"
        else:
            latest_coder_session_id = None

        registry_data = {
            self.packet_id: {
                "packet_id": self.packet_id,
                "feature_id": self.feature_id,
                "source_hash": source_hash_value,
                "last_executed_source_hash": last_executed_hash,
                "resume_allowed": resume_allowed,
                "resume_block_reason": resume_block_reason,
                "latest_coder_session_id": latest_coder_session_id,
                "status": self.dimensions.get("registry_status", "ready"),
            }
        }

        return registry_data

    def _generate_session_content(self) -> dict[str, Any]:
        """
        Generate session index content.
        """
        session_dim = self.dimensions.get("session", "missing")

        if session_dim == "missing":
            return {}

        return {
            "feature_id": self.feature_id,
            "role_threads": {
                "coder": {
                    "thread_id": "thread-synthetic-12345",
                    "packet_id": self.packet_id,
                    "session_mode": "exec",
                    "updated_at": "2026-05-26T10:00:00Z",
                }
            },
        }

    def _compute_source_hash(self) -> str:
        """
        Compute a deterministic source hash for the packet.
        """
        content = f"{self.packet_id}-{self.feature_id}"
        return hashlib.sha256(content.encode("utf-8")).hexdigest()[:16]

#END_BLOCK_MODELS
#START_BLOCK_GENERATOR
# START_FUNCTION_CONTRACT
# name: generate_fixture_for_scenario
# purpose: Generate a SyntheticFixture for a given scenario.
# inputs:
#   scenario_id: str - Unique scenario identifier.
#   dimensions: dict[str, str] - Scenario dimension values.
#   tmp_path: Path - Temporary directory for fixture files.
# returns: SyntheticFixture - Fixture with paths to generated files.
# side_effects: None (files written by fixture.setup()).
# emitted_logs: None.
# error_behavior: None.
# END_FUNCTION_CONTRACT
def generate_fixture_for_scenario(
    scenario_id: str,
    dimensions: dict[str, str],
    tmp_path: Path,
) -> SyntheticFixture:
    """
    Generate a SyntheticFixture for a given scenario.

    Args:
        scenario_id: Unique scenario identifier.
        dimensions: Scenario dimension values.
        tmp_path: Temporary directory for fixture files.

    Returns:
        SyntheticFixture with paths to generated files.
    """
    packet_id = f"PKT-SYNTHETIC-{scenario_id}"
    feature_id = f"FEAT-SYNTHETIC-{scenario_id}"

    packet_dir = tmp_path / "packets" / feature_id / packet_id
    state_root = tmp_path / "state"
    registry_file = state_root / "packet_registry.yaml"
    session_index = state_root / "features.yaml"

    fixture = SyntheticFixture(
        packet_dir=packet_dir,
        registry_file=registry_file,
        session_index=session_index,
        state_root=state_root,
        packet_id=packet_id,
        feature_id=feature_id,
        dimensions=dimensions,
    )

    return fixture

#END_BLOCK_GENERATOR
