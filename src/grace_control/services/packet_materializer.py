# ############################################################################
# AI_HEADER: packet_materializer
# ROLE: Convert a packet's spec_json into an EXECUTION_PACKET.md the legacy
#       codex_launcher can consume.
# ############################################################################

# START_MODULE_CONTRACT
# purpose: Pure transformation packet_data + state_root → Path. No DB, no I/O
#          outside the target file. Safe to test in isolation.
# inputs: packet_data dict (id, spec_json, ...), state_root Path.
# returns: Path to EXECUTION_PACKET.md.
# side_effects: Creates state_root/packets/{id}/EXECUTION_PACKET.md.
# emitted_logs: None.
# error_behavior: Raises on filesystem error.
# END_MODULE_CONTRACT

# START_MODULE_MAP
# mapping:
#   - class: PacketMaterializer
# END_MODULE_MAP

from __future__ import annotations

from pathlib import Path

import yaml


# Legacy branch format for agent worktrees. The canonical home moved to
# `grace_control.agent.legacy_backend.LEGACY_BRANCH_FORMAT` (P2#8) and
# that module was deleted in W8. The constant lives here for tests that
# still check the format string.
BRANCH_FORMAT = "agent/default/{packet_id}/{attempt_slug}"


class PacketMaterializer:
    """Renders EXECUTION_PACKET.md from a packet DB row.

    W02: No DEFAULT_SCOPE — executable packets must have explicit scope.
    Missing scope raises ValueError instead of falling back to 'src/'.
    """

    # W02: DEFAULT_SCOPE removed — no silent fallback for executable packets.
    # The plan compiler enforces non-empty scope for coder packets.
    DEFAULT_FROZEN: list[str] = []  # No default frozen scope either
    DEFAULT_VERIFICATION = "pytest -v\npython3 scripts/grace_lint.py"

    def materialize(self, packet_data: dict, state_root: Path) -> Path:
        packet_id = packet_data["id"]
        packet_dir = state_root / "packets" / packet_id
        packet_dir.mkdir(parents=True, exist_ok=True)

        spec_json = packet_data["spec_json"] if isinstance(packet_data["spec_json"], dict) else {}
        spec_str = yaml.dump(spec_json, default_flow_style=False, allow_unicode=True)

        scope = spec_json.get("scope", [])
        if isinstance(scope, str):
            scope = [scope]

        # W02: Fail-closed — refuse to materialize executable packet without scope
        if not scope:
            raise ValueError(
                f"Packet {packet_id} has no write scope — "
                f"every executable packet must have explicit scope. "
                f"The plan compiler should have caught this."
            )

        scope_lines = "\n".join(f"- {s}" for s in scope)

        frozen = spec_json.get("frozen_scope", [])
        if isinstance(frozen, str):
            frozen = [frozen]
        frozen_lines = "\n".join(f"- {s}" for s in frozen) if frozen else "- (none)"

        verification_text = self._render_verification(spec_json.get("verification", {}))

        expected_raw = spec_json.get("expected_evidence", [])
        if expected_raw:
            expected_lines = "\n".join(
                f"- {e['id']}" if isinstance(e, dict) else f"- {e}"
                for e in expected_raw
            )
        else:
            expected_lines = "- test results\n- lint output"

        pd = packet_data
        content = f"""# Execution Packet: {pd['id']}

## Objective
{pd.get('objective') or pd.get('title') or pd['id']}

## GRACE Canon (MANDATORY)
Every new file must follow this EXACT template:

```
# ############################################################################
# AI_HEADER: module_name — one-line description
# ROLE: Detailed role. Who calls it, what it provides.
# ############################################################################

# START_MODULE_CONTRACT
# purpose: What this module does.
# inputs: Parameters, dependencies.
# returns: What it returns.
# side_effects: File writes, DB inserts, network, subprocess.
# emitted_logs: GraceLogger msg= names this module emits.
# error_behavior: Exceptions raised and when.
# END_MODULE_CONTRACT

# START_MODULE_MAP
# mapping:
#   - class: ClassName
#     methods:
#       - method_one
#   - function: standalone_func
# END_MODULE_MAP

from __future__ import annotations
from grace_control.core.structured_logger import GraceLogger

_log = GraceLogger("component_name")


# START_BLOCK_METHODS
# START_FUNCTION_CONTRACT
# name: my_func
# purpose: What it does.
# inputs: param — description.
# returns: return_type — meaning.
# side_effects: ...
# emitted_logs: my_func_start, my_func_done.
# error_behavior: ...
# END_FUNCTION_CONTRACT
def my_func(param: str) -> str:
    _log.info("my_func_start", param=param)
    ...
    _log.info("my_func_done", result=result)
    return result
# END_BLOCK_METHODS
```

RULES:
— # ############################################################################ above AND below AI_HEADER+ROLE.
— Every public function/method: START_FUNCTION_CONTRACT before it.
— Group related methods: START_BLOCK_name / END_BLOCK_name.
— GraceLogger only, NEVER print() or logging.getLogger().
— _log = GraceLogger("name") ONCE at module level.
— Log msgs: _log.info("msg_name", ctx_key=value).

## Scope
{scope_lines}

## Frozen (do not modify)
{frozen_lines}

## Verification
{verification_text}

## Expected Evidence
{expected_lines}

## Spec JSON
```yaml
{spec_str}
```
"""
        packet_file = packet_dir / "EXECUTION_PACKET.md"
        packet_file.write_text(content)
        return packet_file

    @staticmethod
    def _render_verification(verification_raw) -> str:
        if isinstance(verification_raw, list):
            return "\n".join(
                f"- {v}" if isinstance(v, str) else f"- {' '.join(v)}"
                for v in verification_raw
            )
        if isinstance(verification_raw, dict):
            parts = []
            for stage in ("t0", "t1", "t2"):
                cmds = verification_raw.get(stage, [])
                for c in cmds:
                    c_str = " ".join(c) if isinstance(c, list) else c
                    parts.append(f"- [{stage}] {c_str}")
            return "\n".join(parts) if parts else PacketMaterializer.DEFAULT_VERIFICATION
        return PacketMaterializer.DEFAULT_VERIFICATION
